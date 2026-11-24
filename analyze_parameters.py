#!/usr/bin/env python3
"""
Analyze the query data to determine optimal clustering parameters.
"""

import pandas as pd
import numpy as np

# Load the CSV
df = pd.read_csv('Queries.csv', skiprows=9)
df.columns = [c.strip() for c in df.columns]

# Find columns
query_col = [c for c in df.columns if 'query' in c.lower()][0]
clicks_col = [c for c in df.columns if 'click' in c.lower() and 'rate' not in c.lower()][0]
impressions_col = [c for c in df.columns if 'impression' in c.lower()][0]

# Clean data
df_clean = df[[query_col, clicks_col, impressions_col]].copy()
df_clean.columns = ['query', 'clicks', 'impressions']
df_clean['clicks'] = pd.to_numeric(df_clean['clicks'], errors='coerce').fillna(0)
df_clean['impressions'] = pd.to_numeric(df_clean['impressions'], errors='coerce').fillna(0)
df_clean = df_clean[df_clean['query'].astype(str).str.strip() != '']
df_clean = df_clean[df_clean['query'].astype(str) != 'nan']

print("=" * 80)
print("DATA DISTRIBUTION ANALYSIS")
print("=" * 80)

print(f"\nTotal queries: {len(df_clean):,}")
print(f"Total clicks: {df_clean['clicks'].sum():,.0f}")
print(f"Total impressions: {df_clean['impressions'].sum():,.0f}")

print(f"\n📊 CLICKS DISTRIBUTION:")
print(f"  Queries with 0 clicks: {len(df_clean[df_clean['clicks'] == 0]):,} ({100*len(df_clean[df_clean['clicks'] == 0])/len(df_clean):.1f}%)")
print(f"  Queries with 1+ clicks: {len(df_clean[df_clean['clicks'] > 0]):,} ({100*len(df_clean[df_clean['clicks'] > 0])/len(df_clean):.1f}%)")
print(f"  Queries with 10+ clicks: {len(df_clean[df_clean['clicks'] >= 10]):,}")
print(f"  Queries with 50+ clicks: {len(df_clean[df_clean['clicks'] >= 50]):,}")

print(f"\n📈 CLICKS PERCENTILES:")
for p in [50, 75, 90, 95, 99, 99.9]:
    val = df_clean['clicks'].quantile(p/100)
    print(f"  {p:5.1f}th percentile: {val:6.1f} clicks")

print(f"\n🎯 TOP QUERIES BY CLICKS:")
top20 = df_clean.nlargest(20, 'clicks')
for idx, row in top20.iterrows():
    print(f"  {row['query']:40s} {row['clicks']:6.0f} clicks ({row['clicks']/df_clean['clicks'].sum()*100:5.2f}% of total)")

print("\n" + "=" * 80)
print("PARAMETER RECOMMENDATIONS")
print("=" * 80)

# Analyze different scenarios
scenarios = [
    ("All queries", df_clean),
    ("Queries with clicks > 0", df_clean[df_clean['clicks'] > 0]),
    ("Queries with clicks >= 1", df_clean[df_clean['clicks'] >= 1]),
    ("Queries with clicks >= 10", df_clean[df_clean['clicks'] >= 10]),
]

for scenario_name, scenario_df in scenarios:
    if len(scenario_df) == 0:
        continue
    
    print(f"\n📋 Scenario: {scenario_name}")
    print(f"   Queries: {len(scenario_df):,}")
    print(f"   Total clicks: {scenario_df['clicks'].sum():,.0f}")
    
    # Calculate reasonable min_cluster_size
    # Rule of thumb: min_cluster_size should be ~1-2% of total, but at least 10
    min_size_1pct = max(10, int(len(scenario_df) * 0.01))
    min_size_2pct = max(10, int(len(scenario_df) * 0.02))
    min_size_5pct = max(10, int(len(scenario_df) * 0.05))
    
    print(f"   Recommended min_cluster_size:")
    print(f"     - Conservative (1%): {min_size_1pct}")
    print(f"     - Moderate (2%): {min_size_2pct}")
    print(f"     - Aggressive (5%): {min_size_5pct}")
    
    # Calculate reasonable target_leaf_count
    # If min_cluster_size = X, max possible leaves = total / X
    max_leaves_1pct = len(scenario_df) // min_size_1pct if min_size_1pct > 0 else 0
    max_leaves_2pct = len(scenario_df) // min_size_2pct if min_size_2pct > 0 else 0
    
    print(f"   Max possible leaf clusters:")
    print(f"     - With min_size={min_size_1pct}: {max_leaves_1pct}")
    print(f"     - With min_size={min_size_2pct}: {max_leaves_2pct}")
    
    # Recommended target_leaf_count (aim for 50-70% of max)
    if max_leaves_1pct > 0:
        recommended_target = max(10, int(max_leaves_1pct * 0.6))
        print(f"   Recommended target_leaf_count: {recommended_target} (60% of max)")

print("\n" + "=" * 80)
print("KEY INSIGHTS")
print("=" * 80)

zero_clicks = len(df_clean[df_clean['clicks'] == 0])
with_clicks = len(df_clean[df_clean['clicks'] > 0])

print(f"""
⚠️  CRITICAL FINDINGS:

1. DATA SKEW: {zero_clicks:,} queries ({100*zero_clicks/len(df_clean):.1f}%) have ZERO clicks
   - Only {with_clicks:,} queries have any clicks
   - This means most queries won't contribute to metric-weighted clustering

2. RECOMMENDATION: Filter out zero-click queries before clustering
   - Focus on the {with_clicks:,} queries with clicks
   - These contain all the valuable signal

3. PARAMETER ADJUSTMENTS NEEDED:
   - min_cluster_size=50 is TOO HIGH for {with_clicks:,} queries
   - Suggested: min_cluster_size=10-20 for queries with clicks
   - target_leaf_count=50 might be achievable, but depends on min_cluster_size

4. METRIC WEIGHTING:
   - Top 2 queries account for {df_clean.nlargest(2, 'clicks')['clicks'].sum()/df_clean['clicks'].sum()*100:.1f}% of all clicks
   - Top 10 queries account for {df_clean.nlargest(10, 'clicks')['clicks'].sum()/df_clean['clicks'].sum()*100:.1f}% of all clicks
   - Metric-weighted approach will heavily prioritize these

5. MIN_GAIN_REL THRESHOLD:
   - Default 0.05 (5% inertia reduction) is reasonable
   - With sparse data, might want to lower to 0.02-0.03 for more splits
   - Or raise to 0.10 for stricter quality control
""")

