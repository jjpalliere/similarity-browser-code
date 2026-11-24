#!/usr/bin/env python3
"""
Run both clicks and impressions analyses in sequence.
This script automatically creates a new output directory and runs both analyses.
"""

import os
import sys
import subprocess

def main():
    # Check for API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)
    
    # Find the highest numbered output directory
    output_base = 'outputs'
    if os.path.exists(output_base):
        existing = [int(d) for d in os.listdir(output_base) 
                   if os.path.isdir(os.path.join(output_base, d)) and d.isdigit()]
        next_num = max(existing) + 1 if existing else 1
    else:
        os.makedirs(output_base, exist_ok=True)
        next_num = 1
    output_dir = os.path.join(output_base, str(next_num))
    os.makedirs(output_dir, exist_ok=True)
    print(f"Created output directory: {output_dir}\n")
    
    # Get input CSV path (default to Queries.csv)
    input_csv = sys.argv[1] if len(sys.argv) > 1 else 'Queries.csv'
    if not os.path.exists(input_csv):
        print(f"Error: Input CSV file not found: {input_csv}")
        sys.exit(1)
    
    print("=" * 70)
    print("ANALYSIS 1: Clustering by CLICKS")
    print("=" * 70)
    
    # Run clicks analysis
    clicks_cmd = [
        sys.executable, 'cluster_queries.py',
        '--input_csv', input_csv,
        '--output_dir', output_dir,
        '--output_row_csv', os.path.join(output_dir, 'clustered_rows_by_clicks.csv'),
        '--output_group_csv', os.path.join(output_dir, 'clustered_groups_by_clicks.csv'),
        '--filter_by', 'clicks',
        '--rank_by', 'clicks',
        '--target_leaf_count', '30',
        '--min_cluster_size', '10',
        '--min_child_size', '8',
        '--min_gain_rel', '0.03',
        '--top_group_count', '20',
        '--split_log_csv', os.path.join(output_dir, 'split_progression_clicks.csv'),
        '--embedding_cache_path', os.path.join(output_dir, 'embeddings_clicks.parquet')
    ]
    
    result1 = subprocess.run(clicks_cmd, capture_output=False)
    if result1.returncode != 0:
        print(f"\nError: Clicks analysis failed with exit code {result1.returncode}")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("ANALYSIS 2: Clustering by IMPRESSIONS")
    print("=" * 70)
    
    # Run impressions analysis
    impressions_cmd = [
        sys.executable, 'cluster_queries.py',
        '--input_csv', input_csv,
        '--output_dir', output_dir,
        '--output_row_csv', os.path.join(output_dir, 'clustered_rows_by_impressions.csv'),
        '--output_group_csv', os.path.join(output_dir, 'clustered_groups_by_impressions.csv'),
        '--filter_by', 'impressions',
        '--rank_by', 'impressions',
        '--target_leaf_count', '50',
        '--min_cluster_size', '100',
        '--min_child_size', '8',
        '--min_gain_rel', '0.05',
        '--top_group_count', '20',
        '--split_log_csv', os.path.join(output_dir, 'split_progression_impressions.csv'),
        '--embedding_cache_path', os.path.join(output_dir, 'embeddings_impressions.parquet')
    ]
    
    result2 = subprocess.run(impressions_cmd, capture_output=False)
    if result2.returncode != 0:
        print(f"\nError: Impressions analysis failed with exit code {result2.returncode}")
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("BOTH ANALYSES COMPLETE!")
    print("=" * 70)
    print(f"Output directory: {output_dir}")
    print("\nGenerated files:")
    print(f"  - clustered_rows_by_clicks.csv")
    print(f"  - clustered_groups_by_clicks.csv")
    print(f"  - clustered_rows_by_impressions.csv")
    print(f"  - clustered_groups_by_impressions.csv")
    print(f"  - split_progression_clicks.csv")
    print(f"  - split_progression_impressions.csv")
    print(f"  - embeddings_clicks.parquet")
    print(f"  - embeddings_impressions.parquet")


if __name__ == '__main__':
    main()

