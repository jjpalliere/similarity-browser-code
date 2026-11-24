#!/usr/bin/env python3
"""Publish clustering runs to Cloudflare R2 for the hosted frontend."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BUCKET = "similarity-runs"
DATA_DIR = Path(__file__).resolve().parent.parent / "backend" / "data" / "runs"


def wrangler_put(local_path: str, remote_key: str, cache_control: str = "max-age=86400"):
    """Upload a file to R2 via wrangler CLI."""
    cmd = [
        "npx", "wrangler", "r2", "object", "put",
        f"{BUCKET}/{remote_key}",
        "--file", local_path,
        "--content-type", "application/json",
        "--cache-control", cache_control,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR uploading {remote_key}: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def load_run_metadata(path: Path) -> dict | None:
    """Extract metadata (without events) from a run JSON file."""
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "run_id": data["run_id"],
            "name": data.get("name", data["run_id"]),
            "created_at": data.get("created_at", ""),
            "row_count": data.get("row_count", 0),
            "text_col": data.get("text_col", ""),
            "metric_col": data.get("metric_col", ""),
        }
    except Exception as e:
        print(f"  WARNING: could not read {path.name}: {e}", file=sys.stderr)
        return None


def publish_run(path: Path) -> dict | None:
    """Upload a single run JSON to R2. Returns metadata if successful."""
    meta = load_run_metadata(path)
    if not meta:
        return None

    rid = meta["run_id"]
    print(f"  Uploading runs/{rid}.json ({path.stat().st_size // 1024}KB)...")

    if wrangler_put(str(path), f"runs/{rid}.json"):
        return meta
    return None


def publish_index(all_meta: list[dict]):
    """Build and upload index.json from collected metadata."""
    all_meta.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    index = {"runs": all_meta}

    tmp = DATA_DIR / "_index_tmp.json"
    with open(tmp, "w") as f:
        json.dump(index, f)

    print(f"  Uploading index.json ({len(all_meta)} runs)...")
    ok = wrangler_put(str(tmp), "index.json", cache_control="max-age=60")
    tmp.unlink(missing_ok=True)
    return ok


def main():
    parser = argparse.ArgumentParser(description="Publish runs to Cloudflare R2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Publish all runs")
    group.add_argument("--run-id", type=str, help="Publish a single run by ID")
    args = parser.parse_args()

    if not DATA_DIR.exists():
        print(f"Data directory not found: {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(DATA_DIR.glob("*.json"))
    if not json_files:
        print("No run files found.")
        sys.exit(0)

    if args.run_id:
        # Single run mode
        target = DATA_DIR / f"{args.run_id}.json"
        if not target.exists():
            print(f"Run not found: {args.run_id}", file=sys.stderr)
            sys.exit(1)

        print(f"Publishing run {args.run_id}...")
        meta = publish_run(target)
        if not meta:
            sys.exit(1)

        # Rebuild full index (upload all metadata, not just this one)
        print("Rebuilding index...")
        all_meta = []
        for f in json_files:
            m = load_run_metadata(f)
            if m:
                all_meta.append(m)
        publish_index(all_meta)

    else:
        # All runs mode
        print(f"Publishing {len(json_files)} run(s)...")
        all_meta = []
        for f in json_files:
            meta = publish_run(f)
            if meta:
                all_meta.append(meta)

        if all_meta:
            print("Building index...")
            publish_index(all_meta)

    print("Done.")


if __name__ == "__main__":
    main()
