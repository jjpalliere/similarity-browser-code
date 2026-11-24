#!/usr/bin/env python3
"""Upload local run JSON files to Cloudflare KV with interactive selection."""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

KV_NAMESPACE_ID = "942017366eb249cf99ab89efff1084e4"
DATA_DIR = Path(__file__).resolve().parent.parent / "backend" / "data" / "runs"


def parse_selection(raw: str, max_n: int) -> Optional[List[int]]:
    """Parse input like '1,3,5' or '1-5' or 'all' into list of indices. None = invalid."""
    raw = raw.strip().lower()
    if raw in ("a", "all", "*"):
        return list(range(max_n))

    indices = []
    for part in raw.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a.strip()), int(b.strip())
                if 1 <= lo <= hi <= max_n:
                    indices.extend(range(lo - 1, hi))
                else:
                    return None
            except ValueError:
                return None
        else:
            try:
                i = int(part)
                if 1 <= i <= max_n:
                    indices.append(i - 1)
                else:
                    return None
            except ValueError:
                return None

    return sorted(set(indices)) if indices else None


def upload_run(path: Path) -> bool:
    """Upload a single run to KV. Returns True on success."""
    run_id = path.stem
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ERROR reading {path.name}: {e}")
        return False

    metadata = json.dumps({
        "run_id": data.get("run_id", ""),
        "name": data.get("name", ""),
        "created_at": data.get("created_at", ""),
        "row_count": data.get("row_count", 0),
        "text_col": data.get("text_col", ""),
        "metric_col": data.get("metric_col", ""),
    })

    result = subprocess.run(
        [
            "npx", "wrangler", "kv", "key", "put",
            run_id,
            "--path", str(path),
            "--namespace-id", KV_NAMESPACE_ID,
            "--metadata", metadata,
            "--remote",
        ],
        text=True,
    )

    if result.returncode != 0:
        return False
    return True


def main():
    if not DATA_DIR.exists():
        print(f"No data directory found at {DATA_DIR}")
        sys.exit(1)

    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        print("No JSON files found")
        sys.exit(0)

    # Build run list with metadata
    runs = []
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
            runs.append({
                "path": f,
                "run_id": d.get("run_id", f.stem),
                "name": d.get("name", f.stem),
                "created_at": d.get("created_at", ""),
                "row_count": d.get("row_count", 0),
            })
        except Exception as e:
            print(f"Warning: could not read {f.name}: {e}")

    if not runs:
        print("No valid run files found")
        sys.exit(1)

    # Display selection menu
    print("\n  Local runs to upload to KV:\n")
    for i, r in enumerate(runs, 1):
        name = (r["name"][:40] + "…") if len(r["name"]) > 40 else r["name"]
        print(f"    {i:2}. {r['run_id']}  {name}  ({r['row_count']} rows)")

    print("\n  Enter selection:")
    print("    • Numbers: 1,3,5  or  1-5  or  2-4,7")
    print("    • All: a  or  all")
    print("    • Cancel: q  or  Enter (empty)\n")

    raw = input("  Selection: ").strip()
    if not raw or raw.lower() in ("q", "quit"):
        print("  Cancelled.")
        sys.exit(0)

    indices = parse_selection(raw, len(runs))
    if indices is None:
        print("  Invalid selection.")
        sys.exit(1)

    to_upload = [runs[i] for i in indices]
    print(f"\n  Uploading {len(to_upload)} run(s)...\n")

    ok = 0
    for r in to_upload:
        print(f"  {r['run_id']}...", end=" ")
        if upload_run(r["path"]):
            print("OK")
            ok += 1
        else:
            print("FAILED")

    print(f"\n  Done — {ok}/{len(to_upload)} uploaded.\n")


if __name__ == "__main__":
    main()
