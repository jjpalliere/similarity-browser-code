#!/usr/bin/env python3
"""
Cluster chatbot user questions using the existing SEO clustering engine.

This is a thin entry-point that:
1. Reads a 2-column CSV (question, count) — with or without a header
2. Remaps it to the 3-column format cluster_queries.py expects
3. Calls cluster_queries.py as a subprocess with chatbot-appropriate defaults
4. Post-processes output CSVs to use chatbot-friendly column names
"""

import argparse
import os
import sys
import subprocess
import tempfile
import pandas as pd

# Load .env file if present (keeps API key out of shell config)
def load_dotenv(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()


def detect_header(csv_path: str) -> bool:
    """Detect whether the CSV has a header row.

    Heuristic: if the second column of the first row is NOT numeric, it's a header.
    """
    with open(csv_path, 'r', encoding='utf-8') as f:
        first_line = f.readline().strip()

    if not first_line:
        return False

    # Split by comma (handle quoted fields)
    try:
        import csv as csv_mod
        reader = csv_mod.reader([first_line])
        fields = next(reader)
    except Exception:
        fields = first_line.split(',')

    if len(fields) < 2:
        return False

    # If the second field can be parsed as a number, it's probably data, not a header
    try:
        float(fields[-1].strip())
        return False
    except ValueError:
        return True


def relabel_output_csv(csv_path: str, add_percent: bool = False):
    """Rename SEO-specific columns to chatbot-friendly names in-place."""
    if not os.path.exists(csv_path):
        return

    df = pd.read_csv(csv_path)

    rename_map = {
        'total_clicks': 'total_count',
        'total_impressions': 'total_count_impressions',
        'clicks': 'count',
        'impressions': 'count_impressions',
        'query': 'question',
    }

    # Only rename columns that actually exist
    rename_map = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # Add percent_of_set column right after total_count (groups CSV only)
    if add_percent and 'total_count' in df.columns:
        sum_total = df['total_count'].sum()
        if sum_total > 0:
            col_idx = df.columns.get_loc('total_count') + 1
            df.insert(col_idx, 'percent_of_set', (df['total_count'] / sum_total * 100).round(1))

    # Drop the duplicated impressions columns (they're identical to count)
    for col in ['total_count_impressions', 'count_impressions']:
        if col in df.columns:
            df = df.drop(columns=[col])

    df.to_csv(csv_path, index=False)


def main():
    parser = argparse.ArgumentParser(
        description="Cluster chatbot user questions using semantic similarity"
    )
    parser.add_argument(
        'input_csv',
        help='Path to chatbot questions CSV (2 columns: question, count)'
    )
    parser.add_argument(
        '--target_leaf_count',
        type=int,
        default=30,
        help='Target number of clusters (default: 30)'
    )
    parser.add_argument(
        '--min_cluster_size',
        type=int,
        default=5,
        help='Minimum cluster size for splitting (default: 5, lower than SEO because chatbot datasets are smaller)'
    )
    parser.add_argument(
        '--min_child_size',
        type=int,
        default=3,
        help='Minimum size for child clusters after splitting (default: 3)'
    )
    parser.add_argument(
        '--min_gain_rel',
        type=float,
        default=0.03,
        help='Minimum relative inertia gain to accept a split (default: 0.03)'
    )
    parser.add_argument(
        '--min_filter_value',
        type=float,
        default=0.0,
        help='Minimum count to include a question (default: 0.0 = include all with count > 0)'
    )
    parser.add_argument(
        '--max_mean_distance',
        type=float,
        default=None,
        help='Stop splitting if cluster cohesion is below this threshold (default: None)'
    )
    parser.add_argument(
        '--output_dir',
        default=None,
        help='Output directory. If not specified, auto-creates outputs/chatbot_N/'
    )
    parser.add_argument(
        '--no_relabel',
        action='store_true',
        help='Skip renaming output columns to chatbot-friendly names'
    )

    args = parser.parse_args()

    # Validate input
    if not os.path.exists(args.input_csv):
        print(f"Error: Input file not found: {args.input_csv}")
        sys.exit(1)

    # Check for API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    # --- Step 1: Read and remap the chatbot CSV ---
    print("Reading chatbot questions CSV...")

    has_header = detect_header(args.input_csv)

    if has_header:
        df = pd.read_csv(args.input_csv)
        # Use first column as question, second as count
        question_col = df.columns[0]
        count_col = df.columns[1]
        print(f"  Detected header: question='{question_col}', count='{count_col}'")
    else:
        df = pd.read_csv(args.input_csv, header=None, names=['question', 'count'])
        question_col = 'question'
        count_col = 'count'
        print(f"  No header detected, using positional columns")

    print(f"  Loaded {len(df)} questions")

    # Build the 3-column format the engine expects
    remapped = pd.DataFrame({
        'query': df[question_col].astype(str),
        'clicks': pd.to_numeric(df[count_col], errors='coerce').fillna(0),
        'impressions': pd.to_numeric(df[count_col], errors='coerce').fillna(0),
    })

    # Drop empty/nan questions
    remapped = remapped[remapped['query'].str.strip() != '']
    remapped = remapped[remapped['query'] != 'nan']
    print(f"  {len(remapped)} valid questions after cleanup")

    # --- Step 2: Write temp CSV ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_csv = tempfile.NamedTemporaryFile(
        mode='w', suffix='.csv', prefix='chatbot_remapped_',
        dir=script_dir, delete=False
    )
    remapped.to_csv(tmp_csv.name, index=False)
    tmp_csv.close()
    print(f"  Wrote remapped CSV to temp file")

    # --- Step 3: Determine output directory ---
    if args.output_dir is None:
        output_base = os.path.join(script_dir, 'outputs')
        os.makedirs(output_base, exist_ok=True)
        # Use chatbot_ prefix to separate from SEO runs
        existing = []
        for d in os.listdir(output_base):
            if d.startswith('chatbot_') and os.path.isdir(os.path.join(output_base, d)):
                try:
                    existing.append(int(d.replace('chatbot_', '')))
                except ValueError:
                    pass
        next_num = max(existing) + 1 if existing else 1
        output_dir = os.path.join(output_base, f'chatbot_{next_num}')
    else:
        output_dir = args.output_dir

    os.makedirs(output_dir, exist_ok=True)
    print(f"  Output directory: {output_dir}")

    # --- Step 4: Call cluster_queries.py ---
    print("\n" + "=" * 70)
    print("CLUSTERING CHATBOT QUESTIONS")
    print("=" * 70 + "\n")

    cluster_script = os.path.join(script_dir, 'cluster_queries.py')

    cmd = [
        sys.executable, cluster_script,
        '--input_csv', tmp_csv.name,
        '--output_dir', output_dir,
        '--output_row_csv', os.path.join(output_dir, 'clustered_rows_by_count.csv'),
        '--output_group_csv', os.path.join(output_dir, 'clustered_groups_by_count.csv'),
        '--filter_by', 'clicks',  # "clicks" is remapped count — filters out count=0
        '--min_filter_value', str(args.min_filter_value),
        '--rank_by', 'clicks',  # rank by count (mapped to clicks)
        '--target_leaf_count', str(args.target_leaf_count),
        '--min_cluster_size', str(args.min_cluster_size),
        '--min_child_size', str(args.min_child_size),
        '--min_gain_rel', str(args.min_gain_rel),
        '--split_log_csv', os.path.join(output_dir, 'split_progression.csv'),
        '--embedding_cache_path', os.path.join(output_dir, 'embeddings.parquet'),
    ]

    if args.max_mean_distance is not None:
        cmd.extend(['--max_mean_distance', str(args.max_mean_distance)])

    result = subprocess.run(cmd, capture_output=False)

    # Clean up temp file
    try:
        os.unlink(tmp_csv.name)
    except OSError:
        pass

    if result.returncode != 0:
        print(f"\nError: Clustering failed with exit code {result.returncode}")
        sys.exit(1)

    # --- Step 5: Relabel output columns ---
    if not args.no_relabel:
        print("\nRelabeling output columns to chatbot-friendly names...")
        relabel_output_csv(os.path.join(output_dir, 'clustered_rows_by_count.csv'))
        relabel_output_csv(os.path.join(output_dir, 'clustered_groups_by_count.csv'), add_percent=True)
        print("  Done.")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("CHATBOT QUESTION CLUSTERING COMPLETE")
    print("=" * 70)
    print(f"Output directory: {output_dir}")
    print(f"\nGenerated files:")
    print(f"  - clustered_groups_by_count.csv   (one row per theme)")
    print(f"  - clustered_rows_by_count.csv     (5 representative questions per theme)")
    print(f"  - split_progression.csv           (clustering history)")
    print(f"  - embeddings.parquet              (cached embeddings)")


if __name__ == '__main__':
    main()
