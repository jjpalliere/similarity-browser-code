#!/bin/bash
# Upload all local run JSON files to Cloudflare KV
# Usage: bash scripts/upload-to-kv.sh

KV_NAMESPACE_ID="942017366eb249cf99ab89efff1084e4"
DATA_DIR="backend/data/runs"

cd "$(dirname "$0")/.." || exit 1

if [ ! -d "$DATA_DIR" ]; then
  echo "No data directory found at $DATA_DIR"
  exit 1
fi

count=0
for file in "$DATA_DIR"/*.json; do
  [ -f "$file" ] || continue

  # Extract run_id from filename (without .json)
  run_id=$(basename "$file" .json)

  echo "Uploading $run_id..."
  npx wrangler kv key put "$run_id" --path "$file" \
    --namespace-id "$KV_NAMESPACE_ID" \
    --metadata "$(python3 -c "
import json, sys
with open('$file') as f:
    d = json.load(f)
print(json.dumps({
    'run_id': d.get('run_id',''),
    'name': d.get('name',''),
    'created_at': d.get('created_at',''),
    'row_count': d.get('row_count',0)
}))
")"

  count=$((count + 1))
done

echo "Done — uploaded $count run(s) to KV"
