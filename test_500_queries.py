#!/usr/bin/env python3
"""
Create a test CSV with first 500 queries for testing clustering.
"""

import pandas as pd

# Load the full CSV
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

# Take first 500
df_test = df_clean.head(500).copy()

# Save to test CSV
df_test.to_csv('Queries_test_500.csv', index=False)

print(f"Created test CSV with {len(df_test)} queries")
print(f"  Total clicks: {df_test['clicks'].sum():.0f}")
print(f"  Total impressions: {df_test['impressions'].sum():.0f}")
print(f"  Queries with clicks > 0: {len(df_test[df_test['clicks'] > 0])}")
print(f"\nSaved to: Queries_test_500.csv")

