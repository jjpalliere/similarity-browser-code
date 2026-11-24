#!/bin/bash
# Run clustering analysis twice: once for clicks, once for impressions

echo "=========================================="
echo "ANALYSIS 1: Clustering by CLICKS"
echo "=========================================="
echo ""

python3 cluster_queries.py \
    --input_csv Queries.csv \
    --output_row_csv clustered_rows_by_clicks.csv \
    --output_group_csv clustered_groups_by_clicks.csv \
    --filter_by clicks \
    --min_filter_value 0.0 \
    --rank_by clicks \
    --target_leaf_count 30 \
    --min_cluster_size 10 \
    --min_gain_rel 0.03 \
    --top_group_count 20 \
    --split_log_csv split_progression_clicks.csv \
    --embedding_cache_path embeddings_clicks.parquet

echo ""
echo "=========================================="
echo "ANALYSIS 2: Clustering by IMPRESSIONS"
echo "=========================================="
echo ""

python3 cluster_queries.py \
    --input_csv Queries.csv \
    --output_row_csv clustered_rows_by_impressions.csv \
    --output_group_csv clustered_groups_by_impressions.csv \
    --filter_by impressions \
    --min_filter_value 0.0 \
    --rank_by impressions \
    --target_leaf_count 50 \
    --min_cluster_size 100 \
    --min_gain_rel 0.05 \
    --top_group_count 20 \
    --split_log_csv split_progression_impressions.csv \
    --embedding_cache_path embeddings_impressions.parquet

echo ""
echo "=========================================="
echo "BOTH ANALYSES COMPLETE!"
echo "=========================================="
echo ""
echo "Clicks analysis outputs:"
echo "  - clustered_rows_by_clicks.csv"
echo "  - clustered_groups_by_clicks.csv"
echo "  - split_progression_clicks.csv"
echo ""
echo "Impressions analysis outputs:"
echo "  - clustered_rows_by_impressions.csv"
echo "  - clustered_groups_by_impressions.csv"
echo "  - split_progression_impressions.csv"

