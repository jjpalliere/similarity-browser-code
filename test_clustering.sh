#!/bin/bash
# Test clustering with recommended parameters for this dataset

echo "Testing clustering with recommended parameters..."
echo ""

python3 cluster_queries.py \
    --input_csv Queries.csv \
    --output_row_csv test_clustered_rows.csv \
    --output_group_csv test_clustered_groups.csv \
    --target_leaf_count 30 \
    --min_cluster_size 10 \
    --min_gain_rel 0.03 \
    --top_group_count 20 \
    --split_log_csv test_split_progression.csv \
    --filter_zero_clicks \
    --embedding_cache_path test_embeddings.parquet

echo ""
echo "Test complete! Check the output files:"
echo "  - test_clustered_rows.csv"
echo "  - test_clustered_groups.csv"
echo "  - test_split_progression.csv"

