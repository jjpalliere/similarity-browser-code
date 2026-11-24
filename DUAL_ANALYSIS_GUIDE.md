# Dual Analysis Guide: Clicks vs Impressions

## Overview

The script now supports running two separate clustering analyses:
1. **Clicks-based**: Focus on queries that received clicks
2. **Impressions-based**: Focus on queries with high visibility/impressions

## New Parameters

### `--filter_by` (choices: 'none', 'clicks', 'impressions')
- Filters queries before clustering based on the specified metric
- `'clicks'`: Only include queries with clicks > min_filter_value
- `'impressions'`: Only include queries with impressions > min_filter_value
- `'none'`: Include all queries (default)

### `--min_filter_value` (default: 0.0)
- Minimum value for the filter metric to keep a query
- Default 0.0 means "> 0" (excludes zeros)

### `--rank_by` (choices: 'clicks', 'impressions')
- Which metric to use for ranking clusters and selecting split candidates
- Determines which clusters get prioritized for splitting
- Default: 'clicks'

## Recommended Commands

### Analysis 1: Clicks-Based Clustering

```bash
python3 cluster_queries.py \
    --input_csv Queries.csv \
    --output_row_csv clustered_rows_by_clicks.csv \
    --output_group_csv clustered_groups_by_clicks.csv \
    --filter_by clicks \
    --rank_by clicks \
    --target_leaf_count 30 \
    --min_cluster_size 10 \
    --min_gain_rel 0.03 \
    --top_group_count 20 \
    --split_log_csv split_progression_clicks.csv
```

**What this does:**
- Filters to queries with clicks > 0
- Ranks and splits clusters by total clicks
- Focuses on queries that actually converted

### Analysis 2: Impressions-Based Clustering

```bash
python3 cluster_queries.py \
    --input_csv Queries.csv \
    --output_row_csv clustered_rows_by_impressions.csv \
    --output_group_csv clustered_groups_by_impressions.csv \
    --filter_by impressions \
    --rank_by impressions \
    --target_leaf_count 50 \
    --min_cluster_size 100 \
    --min_gain_rel 0.05 \
    --top_group_count 20 \
    --split_log_csv split_progression_impressions.csv
```

**What this does:**
- Includes every query (all have impressions > 0)
- Ranks and splits clusters by total impressions
- Captures queries with high visibility even if they didn't click

## Quick Run: Both Analyses

Use the provided script:

```bash
./run_both_analyses.sh
```

This will run both analyses sequentially with optimized parameters for each.

## Parameter Differences

| Parameter | Clicks Analysis | Impressions Analysis | Reasoning |
|-----------|----------------|---------------------|-----------|
| `--filter_by` | `clicks` | `impressions` | Different filtering criteria |
| `--rank_by` | `clicks` | `impressions` | Different ranking metric |
| `--target_leaf_count` | 30 | 50 | More queries in impressions = more clusters possible |
| `--min_cluster_size` | 10 | 100 | Larger dataset needs larger clusters |
| `--min_gain_rel` | 0.03 | 0.05 | Stricter threshold for larger dataset |

## Output Files

Each analysis produces:
- **Row-level CSV**: Each original query with cluster assignment
- **Group-level CSV**: Each cluster with aggregated metrics
- **Split log CSV**: Progression of how clusters were split

Files are prefixed with `_by_clicks` or `_by_impressions` to distinguish them.

## Use Cases

### Use Clicks Analysis When:
- You want to understand what converts
- Focus on high-intent queries
- Optimize for queries that drive actions

### Use Impressions Analysis When:
- You want to understand search visibility
- Identify content gaps (high impressions, low clicks)
- Optimize for brand awareness

### Use Both When:
- You want a complete picture
- Compare conversion vs visibility patterns
- Identify opportunities in both dimensions

