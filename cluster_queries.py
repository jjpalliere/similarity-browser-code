#!/usr/bin/env python3
"""
Cluster Google search queries using embeddings into a metric-weighted recursive tree.

This script:
1. Loads queries from CSV with clicks/impressions
2. Generates/caches embeddings using OpenAI
3. Builds a recursive tree by splitting highest-click clusters
4. Ranks clusters by total clicks and selects top N
5. Generates canonical queries for top clusters using LLM
6. Outputs row-level and group-level CSVs
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from openai import OpenAI
try:
    from openai import RateLimitError
except ImportError:
    # Fallback for older versions - use generic Exception
    RateLimitError = type('RateLimitError', (Exception,), {})
import warnings

warnings.filterwarnings('ignore')

# Set random seeds for reproducibility
np.random.seed(42)


@dataclass
class Cluster:
    """Represents a cluster with member rows and aggregated metrics."""
    cluster_id: int
    member_indices: List[int]
    total_clicks: float
    total_impressions: float
    parent_id: Optional[int] = None
    depth: int = 0  # Depth in tree (0 = root, increases with each split)
    canonical_query: Optional[str] = None

    @property
    def size(self) -> int:
        return len(self.member_indices)


class EmbeddingCache:
    """Handles embedding generation and caching."""
    
    def __init__(self, api_key: str, cache_path: str):
        self.client = OpenAI(api_key=api_key)
        self.cache_path = cache_path
        self.model = "text-embedding-3-small"
        self.batch_size = 100  # OpenAI allows up to 2048, but 100 is safe
    
    def load_cache(self) -> Optional[pd.DataFrame]:
        """Load embeddings from cache if it exists."""
        if os.path.exists(self.cache_path):
            try:
                return pd.read_parquet(self.cache_path)
            except Exception as e:
                print(f"Warning: Could not load cache: {e}")
                return None
        return None
    
    def save_cache(self, df: pd.DataFrame):
        """Save embeddings to cache."""
        try:
            df.to_parquet(self.cache_path, index=False)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")
    
    def get_embeddings(self, queries: List[str]) -> np.ndarray:
        """Get embeddings for queries, using cache when possible."""
        # Try to load from cache
        cache_df = self.load_cache()
        
        # Create a DataFrame for current queries
        query_df = pd.DataFrame({'query': queries})
        
        if cache_df is not None:
            # Merge with cache
            merged = query_df.merge(cache_df, on='query', how='left', suffixes=('', '_cached'))
            missing_mask = merged['embedding'].isna()
            missing_queries = merged[missing_mask]['query'].tolist()
            
            if len(missing_queries) == 0:
                # All queries are cached
                print(f"Loaded all {len(queries)} embeddings from cache")
                # Extract embeddings in the correct order
                embeddings_list = []
                for q in queries:
                    cached_row = cache_df[cache_df['query'] == q]
                    if not cached_row.empty:
                        embeddings_list.append(cached_row.iloc[0]['embedding'])
                return np.array(embeddings_list)
            else:
                print(f"Found {len(queries) - len(missing_queries)} cached, generating {len(missing_queries)} new embeddings")
        else:
            missing_queries = queries
            print(f"Cache not found, generating {len(queries)} embeddings")
        
        # Generate embeddings for missing queries
        new_embeddings = self._generate_embeddings(missing_queries)
        
        # Update cache
        if cache_df is not None:
            # Add new embeddings to cache
            new_cache_df = pd.DataFrame({
                'query': missing_queries,
                'embedding': [emb.tolist() for emb in new_embeddings]
            })
            updated_cache = pd.concat([cache_df, new_cache_df], ignore_index=True)
        else:
            updated_cache = pd.DataFrame({
                'query': queries,
                'embedding': [emb.tolist() for emb in new_embeddings]
            })
        
        self.save_cache(updated_cache)
        
        # Combine cached and new embeddings in correct order
        if cache_df is not None and len(missing_queries) < len(queries):
            final_embeddings = []
            for q in queries:
                if q in missing_queries:
                    idx = missing_queries.index(q)
                    final_embeddings.append(new_embeddings[idx])
                else:
                    cached_row = cache_df[cache_df['query'] == q]
                    final_embeddings.append(cached_row.iloc[0]['embedding'])
            return np.array(final_embeddings)
        else:
            return new_embeddings
    
    def _generate_embeddings(self, queries: List[str]) -> np.ndarray:
        """Generate embeddings via OpenAI API in batches."""
        all_embeddings = []
        
        for i in range(0, len(queries), self.batch_size):
            batch = queries[i:i + self.batch_size]
            print(f"Generating embeddings for batch {i//self.batch_size + 1}/{(len(queries)-1)//self.batch_size + 1}")
            
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"Error generating embeddings: {e}")
                raise
        
        return np.array(all_embeddings)


class RecursiveClusterer:
    """Builds a recursive tree of clusters using metric-weighted splitting."""
    
    def __init__(self, embeddings: np.ndarray, df: pd.DataFrame, 
                 min_cluster_size: int = 50, target_leaf_count: int = 50,
                 min_silhouette_improvement: float = 0.0,
                 min_gain_rel: float = 0.05, split_log_path: Optional[str] = None,
                 rank_by: str = 'clicks', min_child_size: int = 8,
                 max_mean_distance: Optional[float] = None):
        self.embeddings = embeddings
        self.df = df
        self.min_cluster_size = min_cluster_size
        self.target_leaf_count = target_leaf_count
        self.min_silhouette_improvement = min_silhouette_improvement
        self.min_gain_rel = min_gain_rel
        self.split_log_path = split_log_path
        self.rank_by = rank_by  # 'clicks' or 'impressions'
        self.min_child_size = min_child_size  # Minimum size for child clusters
        self.max_mean_distance = max_mean_distance  # Stop splitting if mean distance is below this (cohesion threshold)
        self.clusters: Dict[int, Cluster] = {}
        self.next_cluster_id = 0
        self.leaf_cluster_ids: List[int] = []
        self.split_log: List[Dict] = []  # Store accepted splits
        self.terminal_clusters = set()  # Clusters that failed to split (marked as terminal)
    
    def build_tree(self) -> Dict[int, Cluster]:
        """Build the recursive clustering tree."""
        # Initialize root cluster with all rows (depth = 0)
        root = Cluster(
            cluster_id=self.next_cluster_id,
            member_indices=list(range(len(self.df))),
            total_clicks=float(self.df['clicks'].sum()),
            total_impressions=float(self.df['impressions'].sum()),
            depth=0
        )
        self.clusters[root.cluster_id] = root
        self.leaf_cluster_ids = [root.cluster_id]
        self.next_cluster_id += 1
        
        print(f"Starting recursive clustering: {len(self.df)} queries, target {self.target_leaf_count} leaves")
        
        iteration = 0
        while len(self.leaf_cluster_ids) < self.target_leaf_count:
            iteration += 1
            
            # Find the best leaf cluster to split
            candidate = self._find_best_split_candidate()
            if candidate is None:
                print(f"No more splittable clusters (min_size={self.min_cluster_size})")
                break
            
            # Attempt to split
            split_result = self._split_cluster(candidate)
            if split_result is None:
                # Split failed (quality check or other reason)
                # Mark as terminal so it won't be selected again
                self.terminal_clusters.add(candidate)
                print(f"Cluster {candidate} failed quality check or cannot be split (marked as terminal)")
                continue
            
            children, gain_rel = split_result
            
            # Log the accepted split
            child_ids = [c.cluster_id for c in children]
            self.split_log.append({
                'parent_id': candidate,
                'child_ids': ','.join(map(str, child_ids)),
                'size': self.clusters[candidate].size,
                'clicks': self.clusters[candidate].total_clicks,
                'impressions': self.clusters[candidate].total_impressions,
                'gain_rel': gain_rel
            })
            
            # Replace parent with children in leaf set
            self.leaf_cluster_ids.remove(candidate)
            for child in children:
                self.leaf_cluster_ids.append(child.cluster_id)
            
            if iteration % 5 == 0:
                print(f"Iteration {iteration}: {len(self.leaf_cluster_ids)} leaf clusters")
        
        print(f"Clustering complete: {len(self.leaf_cluster_ids)} leaf clusters")
        
        # Save split log if path provided
        if self.split_log_path and self.split_log:
            self._save_split_log()
        
        return self.clusters
    
    def _save_split_log(self):
        """Save split log to CSV."""
        log_df = pd.DataFrame(self.split_log)
        log_df.to_csv(self.split_log_path, index=False)
        print(f"Saved split log with {len(self.split_log)} accepted splits to {self.split_log_path}")
    
    def _find_best_split_candidate(self) -> Optional[int]:
        """Find the leaf cluster with highest metric (clicks or impressions) that can be split.
        
        NOTE: Splitting ALWAYS uses clicks/impressions (metric-based), NOT depth.
        The rank_by parameter only affects final ranking/selection, not the splitting process.
        """
        candidates = [
            cid for cid in self.leaf_cluster_ids
            if self.clusters[cid].size >= self.min_cluster_size
            and cid not in self.terminal_clusters  # Exclude terminal clusters
        ]
        
        if not candidates:
            return None
        
        # Splitting always uses metric-based approach (clicks or impressions)
        # If rank_by is 'depth', we still use clicks for splitting decisions
        split_metric = 'impressions' if self.rank_by == 'impressions' else 'clicks'
        
        if split_metric == 'impressions':
            candidates.sort(key=lambda cid: self.clusters[cid].total_impressions, reverse=True)
        else:  # clicks
            candidates.sort(key=lambda cid: self.clusters[cid].total_clicks, reverse=True)
        return candidates[0]
    
    def _split_cluster(self, cluster_id: int) -> Optional[Tuple[List[Cluster], float]]:
        """Split a cluster into 2-3 subclusters using KMeans.
        
        Returns:
            Tuple of (children, gain_rel) if split is accepted, None otherwise.
            gain_rel is the relative inertia reduction: (inertia_parent - inertia_children) / inertia_parent
        """
        cluster = self.clusters[cluster_id]
        
        if cluster.size < self.min_cluster_size:
            return None
        
        # Don't split if cluster is too small - splitting would create children smaller than min_child_size
        # If splitting into 2, we need at least min_child_size * 2 items
        # If splitting into 3, we need at least min_child_size * 3 items
        # Use the more conservative check: min_child_size * 2
        if cluster.size <= self.min_child_size * 2:
            return None
        
        # Get embeddings for this cluster's members
        cluster_embeddings = self.embeddings[cluster.member_indices]
        
        # Calculate parent inertia (single cluster inertia)
        parent_center = cluster_embeddings.mean(axis=0)
        parent_inertia = np.sum((cluster_embeddings - parent_center) ** 2)
        
        # Calculate mean distance (cohesion measure)
        # Mean distance = sqrt(inertia / size) - average distance from center
        mean_distance = np.sqrt(parent_inertia / cluster.size) if cluster.size > 0 else 0
        
        # Cohesion-based stopping: if cluster is already very cohesive, don't split
        if self.max_mean_distance is not None and mean_distance < self.max_mean_distance:
            return None
        
        # Try different K values and pick the best
        best_k = 2
        best_inertia = float('inf')
        best_labels = None
        best_kmeans = None
        
        for k in [2, 3]:
            if cluster.size < k:
                continue
            
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(cluster_embeddings)
            
            # Check if split is valid (each child has at least min_child_size items)
            unique_labels, counts = np.unique(labels, return_counts=True)
            if np.any(counts < self.min_child_size):
                continue
            
            # Use inertia as the metric (lower is better)
            if kmeans.inertia_ < best_inertia:
                best_inertia = kmeans.inertia_
                best_k = k
                best_labels = labels
                best_kmeans = kmeans
        
        if best_labels is None:
            return None
        
        # Calculate total children inertia (sum of inertia for each child cluster)
        children_inertia = best_inertia
        
        # Calculate relative gain: (parent_inertia - children_inertia) / parent_inertia
        if parent_inertia == 0:
            gain_rel = 0.0
        else:
            gain_rel = (parent_inertia - children_inertia) / parent_inertia
        
        # Quality check: only split if gain exceeds threshold
        if gain_rel < self.min_gain_rel:
            return None
        
        # Additional quality check: silhouette score if enabled
        if self.min_silhouette_improvement > 0:
            if cluster.size >= best_k + 1:
                try:
                    score = silhouette_score(cluster_embeddings, best_labels)
                    if score < self.min_silhouette_improvement:
                        return None
                except:
                    pass  # If silhouette fails, proceed with inertia-based check
        
        # Create child clusters
        children = []
        for label in range(best_k):
            child_indices = [cluster.member_indices[i] for i in range(len(cluster.member_indices)) 
                           if best_labels[i] == label]
            
            if len(child_indices) == 0:
                continue
            
            # Final check: ensure child meets minimum size requirement
            if len(child_indices) < self.min_child_size:
                continue
            
            child_clicks = float(self.df.loc[child_indices, 'clicks'].sum())
            child_impressions = float(self.df.loc[child_indices, 'impressions'].sum())
            
            # Calculate depth: parent's depth + 1
            parent_depth = self.clusters[cluster_id].depth
            child = Cluster(
                cluster_id=self.next_cluster_id,
                member_indices=child_indices,
                total_clicks=child_clicks,
                total_impressions=child_impressions,
                parent_id=cluster_id,
                depth=parent_depth + 1
            )
            children.append(child)
            self.clusters[child.cluster_id] = child
            self.next_cluster_id += 1
        
        if len(children) <= 1:
            return None
        
        return (children, gain_rel)


class CanonicalQueryGenerator:
    """Generates canonical queries for clusters using LLM."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_example_queries = 50
    
    def select_representative_queries(self, cluster: Cluster, df: pd.DataFrame, num_queries: int = 5) -> List[int]:
        """Select N representative queries from a cluster that best represent the range.
        
        Returns list of indices (from df) of selected queries.
        Falls back to first N queries if LLM call fails (rate limit, etc.).
        """
        cluster_df = df.loc[cluster.member_indices].copy()
        cluster_df = cluster_df.sort_values('clicks', ascending=False)
        all_queries = cluster_df['query'].tolist()
        
        if len(all_queries) <= num_queries:
            # Not enough queries, return all
            return cluster.member_indices[:len(all_queries)]
        
        # Try to use LLM to select diverse representatives
        try:
            prompt = f"""You are analyzing a cluster of similar Google search queries. Your task is to select exactly {num_queries} queries that best represent the RANGE and DIVERSITY of this cluster.

All queries in this cluster (ranked by clicks):
{chr(10).join(f"- {q}" for q in all_queries[:50])}

Select exactly {num_queries} queries that:
1. Represent different aspects/variations within the cluster
2. Show the range of how users phrase similar intents
3. Include both high-click and diverse phrasings

Output ONLY the {num_queries} selected queries, one per line, in the exact format:
query1
query2
query3
query4
query5

No explanations, no numbering, just the queries."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a search query analyst. Output only the selected queries, one per line."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
            )
            
            selected_text = response.choices[0].message.content.strip()
            selected_queries = [q.strip() for q in selected_text.split('\n') if q.strip()]
            
            # Map selected queries back to indices
            selected_indices = []
            for query in selected_queries:
                # Find this query in the cluster
                matching = cluster_df[cluster_df['query'] == query]
                if not matching.empty:
                    selected_indices.append(matching.index[0])
            
            # If we got enough, return them
            if len(selected_indices) >= num_queries:
                return selected_indices[:num_queries]
            else:
                # Fallback: add top queries by clicks to reach num_queries
                for idx in cluster.member_indices:
                    if idx not in selected_indices and len(selected_indices) < num_queries:
                        selected_indices.append(idx)
                return selected_indices[:num_queries]
                
        except RateLimitError:
            # Rate limit - fall back to first N queries by clicks
            return cluster.member_indices[:num_queries]
        except Exception as e:
            # Other error - fall back to first N queries by clicks
            return cluster.member_indices[:num_queries]
    
    def generate_canonical_query(self, cluster: Cluster, df: pd.DataFrame) -> str:
        """Generate a canonical query for a cluster."""
        # Get top queries by clicks from this cluster
        cluster_df = df.loc[cluster.member_indices].copy()
        cluster_df = cluster_df.sort_values('clicks', ascending=False)
        top_queries = cluster_df.head(self.max_example_queries)['query'].tolist()
        
        prompt = f"""You are analyzing a cluster of similar Google search queries. Your task is to generate a single canonical query that best represents the intent of all these queries.

Queries in this cluster (ranked by clicks):
{chr(10).join(f"- {q}" for q in top_queries)}

Generate ONE canonical Google search query that:
1. Captures the common intent/theme of these queries
2. Is natural and typical of how users search on Google
3. Is at most 8 words long
4. Is a single query string, nothing else

Output ONLY the canonical query, no explanations, no quotes, no additional text."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a search query analyst. Output only the canonical query."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=50
            )
            
            canonical = response.choices[0].message.content.strip()
            # Remove quotes if present
            canonical = canonical.strip('"').strip("'")
            return canonical
        except RateLimitError:
            print(f"  Rate limit hit for cluster {cluster.cluster_id}, using fallback")
            return ""
        except Exception as e:
            print(f"  Error generating canonical query for cluster {cluster.cluster_id}: {e}")
            return ""


def load_and_validate_csv(csv_path: str) -> pd.DataFrame:
    """Load CSV and validate required columns."""
    try:
        # Try to find where the header row is (skip comment rows starting with #)
        with open(csv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            header_line_idx = None
            for i, line in enumerate(lines):
                if not line.strip().startswith('#') and ',' in line:
                    header_line_idx = i
                    break
            
            if header_line_idx is None:
                # No header found, try reading normally
                df = pd.read_csv(csv_path)
            else:
                # Read CSV starting from the header row
                df = pd.read_csv(csv_path, skiprows=header_line_idx)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        sys.exit(1)
    
    # Try to find query column (handle various names)
    query_col = None
    for col in df.columns:
        if 'query' in col.lower():
            query_col = col
            break
    
    if query_col is None:
        print("Error: Could not find 'query' column")
        sys.exit(1)
    
    # Try to find clicks and impressions columns
    clicks_col = None
    impressions_col = None
    
    for col in df.columns:
        col_lower = col.lower()
        if 'click' in col_lower and clicks_col is None:
            clicks_col = col
        if 'impression' in col_lower and impressions_col is None:
            impressions_col = col
    
    if clicks_col is None or impressions_col is None:
        print("Error: Could not find 'clicks' and 'impressions' columns")
        sys.exit(1)
    
    # Create standardized dataframe
    result_df = pd.DataFrame({
        'query': df[query_col].astype(str),
        'clicks': pd.to_numeric(df[clicks_col], errors='coerce').fillna(0),
        'impressions': pd.to_numeric(df[impressions_col], errors='coerce').fillna(0)
    })
    
    # Remove empty queries
    result_df = result_df[result_df['query'].str.strip() != '']
    result_df = result_df[result_df['query'] != 'nan']
    
    if len(result_df) == 0:
        print("Error: No valid queries found")
        sys.exit(1)
    
    print(f"Loaded {len(result_df)} queries")
    return result_df.reset_index(drop=True)


def filter_queries(df: pd.DataFrame, filter_by: str = 'none', min_value: float = 0.0) -> pd.DataFrame:
    """Filter queries based on clicks or impressions.
    
    Args:
        df: DataFrame with queries
        filter_by: 'clicks', 'impressions', or 'none'
        min_value: Minimum value to keep (default: 0.0, meaning > 0)
    """
    original_count = len(df)
    
    if filter_by == 'none':
        return df.reset_index(drop=True)
    elif filter_by == 'clicks':
        filtered_df = df[df['clicks'] > min_value].copy()
        metric_name = 'clicks'
        total_metric = filtered_df['clicks'].sum()
    elif filter_by == 'impressions':
        filtered_df = df[df['impressions'] > min_value].copy()
        metric_name = 'impressions'
        total_metric = filtered_df['impressions'].sum()
    else:
        raise ValueError(f"filter_by must be 'clicks', 'impressions', or 'none', got '{filter_by}'")
    
    removed_count = original_count - len(filtered_df)
    
    if removed_count > 0:
        print(f"Filtered out {removed_count} queries with {metric_name} <= {min_value} ({100*removed_count/original_count:.1f}%)")
        print(f"Remaining: {len(filtered_df)} queries with {total_metric:,.0f} total {metric_name}")
    
    return filtered_df.reset_index(drop=True)


def get_cluster_hierarchy_path(cluster: Cluster, all_clusters: Dict[int, Cluster], max_depth: int = 5) -> List[Optional[int]]:
    """
    Build the hierarchy path for a cluster, showing cluster IDs at each depth level.
    Returns a list of cluster IDs, where index 0 = depth 0 (root), index 1 = depth 1, etc.
    If a cluster is at depth 3, it will have IDs for depths 0, 1, 2, 3, and None for depth 4.
    The path traces from root (depth 0) to the cluster itself.
    """
    path = [None] * max_depth
    
    # Build path by walking up from cluster to root, then reverse
    path_from_leaf = []
    current = cluster
    visited = set()
    
    # Walk up the tree from the cluster to the root
    while current is not None and current.cluster_id not in visited:
        visited.add(current.cluster_id)
        path_from_leaf.append((current.depth, current.cluster_id))
        if current.parent_id is not None:
            current = all_clusters.get(current.parent_id)
        else:
            break
    
    # Fill in the path array (depth 0 = root, depth 1 = first split, etc.)
    for depth, cluster_id in path_from_leaf:
        if depth < max_depth:
            path[depth] = cluster_id
    
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Cluster Google search queries using embeddings"
    )
    parser.add_argument(
        '--input_csv',
        required=True,
        help='Path to input CSV with queries, clicks, impressions'
    )
    parser.add_argument(
        '--output_row_csv',
        default=None,
        help='Output CSV path for row-level data. If not specified, automatically named based on --rank_by (e.g., clustered_rows_by_clicks.csv)'
    )
    parser.add_argument(
        '--output_group_csv',
        default=None,
        help='Output CSV path for group-level data. If not specified, automatically named based on --rank_by (e.g., clustered_groups_by_clicks.csv)'
    )
    parser.add_argument(
        '--target_leaf_count',
        type=int,
        default=30,
        help='Target number of leaf clusters (default: 30, may not be achievable with small datasets)'
    )
    parser.add_argument(
        '--min_cluster_size',
        type=int,
        default=10,
        help='Minimum cluster size for splitting (default: 10)'
    )
    parser.add_argument(
        '--min_child_size',
        type=int,
        default=8,
        help='Minimum size for child clusters after splitting. Clusters with size <= min_child_size * 2 will not be split (default: 8)'
    )
    parser.add_argument(
        '--max_mean_distance',
        type=float,
        default=None,
        help='Stop splitting clusters if their mean distance (cohesion) is below this threshold. Lower values = tighter clusters required before stopping. If None, only uses target_leaf_count and min_cluster_size to stop (default: None)'
    )
    parser.add_argument(
        '--filter_by',
        choices=['none', 'clicks', 'impressions'],
        default='none',
        help='Filter queries by metric before clustering: none, clicks, or impressions (default: none)'
    )
    parser.add_argument(
        '--min_filter_value',
        type=float,
        default=0.0,
        help='Minimum value for filter_by metric to keep query (default: 0.0, meaning > 0)'
    )
    parser.add_argument(
        '--rank_by',
        choices=['clicks', 'impressions', 'depth'],
        default='clicks',
        help='Metric to use for ranking clusters: clicks, impressions, or depth (default: clicks). Depth prioritizes clusters with more semantic refinement.'
    )
    parser.add_argument(
        '--embedding_cache_path',
        default='embeddings.parquet',
        help='Path to embedding cache file (default: embeddings.parquet)'
    )
    parser.add_argument(
        '--top_group_count',
        type=int,
        default=20,
        help='Number of top clusters to generate canonical queries for (default: 20)'
    )
    parser.add_argument(
        '--min_silhouette_improvement',
        type=float,
        default=0.0,
        help='Minimum silhouette score improvement to allow split (default: 0.0, disabled)'
    )
    parser.add_argument(
        '--min_gain_rel',
        type=float,
        default=0.05,
        help='Minimum relative inertia gain to accept split: (inertia_parent - inertia_children) / inertia_parent (default: 0.05)'
    )
    parser.add_argument(
        '--split_log_csv',
        default=None,
        help='Path to save split log CSV (default: None, no log saved)'
    )
    parser.add_argument(
        '--output_dir',
        default=None,
        help='Output directory for all files. If not specified, automatically creates outputs/N/ (default: None)'
    )
    
    args = parser.parse_args()
    
    # Auto-generate output directory if not specified
    if args.output_dir is None:
        # Find the highest numbered output directory
        output_base = 'outputs'
        if os.path.exists(output_base):
            existing = [int(d) for d in os.listdir(output_base) 
                       if os.path.isdir(os.path.join(output_base, d)) and d.isdigit()]
            next_num = max(existing) + 1 if existing else 1
        else:
            os.makedirs(output_base, exist_ok=True)
            next_num = 1
        args.output_dir = os.path.join(output_base, str(next_num))
        os.makedirs(args.output_dir, exist_ok=True)
        print(f"Created output directory: {args.output_dir}")
    else:
        # Use specified output directory
        os.makedirs(args.output_dir, exist_ok=True)
    
    # Auto-generate output file names based on rank_by if not specified
    if args.output_row_csv is None:
        args.output_row_csv = os.path.join(args.output_dir, f'clustered_rows_by_{args.rank_by}.csv')
    if args.output_group_csv is None:
        args.output_group_csv = os.path.join(args.output_dir, f'clustered_groups_by_{args.rank_by}.csv')
    if args.split_log_csv is None:
        args.split_log_csv = os.path.join(args.output_dir, f'split_progression_{args.rank_by}.csv')
    if args.embedding_cache_path is None:
        args.embedding_cache_path = os.path.join(args.output_dir, f'embeddings_{args.rank_by}.parquet')
    
    # Check for API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)
    
    # Load and validate CSV
    print("Loading CSV...")
    df = load_and_validate_csv(args.input_csv)
    
    # Filter queries if requested (for clustering only)
    if args.filter_by != 'none':
        df = filter_queries(df, filter_by=args.filter_by, min_value=args.min_filter_value)
        if len(df) == 0:
            print(f"Error: No queries found after filtering by {args.filter_by}")
            sys.exit(1)
    
    # Generate/cache embeddings
    print("Processing embeddings...")
    cache = EmbeddingCache(api_key, args.embedding_cache_path)
    queries = df['query'].tolist()
    embeddings = cache.get_embeddings(queries)
    
    if len(embeddings) != len(df):
        print(f"Error: Embedding count mismatch ({len(embeddings)} vs {len(df)})")
        sys.exit(1)
    
    # Build recursive clustering tree
    print("Building clustering tree...")
    clusterer = RecursiveClusterer(
        embeddings=embeddings,
        df=df,
        min_cluster_size=args.min_cluster_size,
        target_leaf_count=args.target_leaf_count,
        min_silhouette_improvement=args.min_silhouette_improvement,
        min_gain_rel=args.min_gain_rel,
        split_log_path=args.split_log_csv,
        rank_by=args.rank_by,
        min_child_size=args.min_child_size,
        max_mean_distance=args.max_mean_distance
    )
    clusters = clusterer.build_tree()
    leaf_clusters = [clusters[cid] for cid in clusterer.leaf_cluster_ids]
    
    # Rank clusters by the specified metric
    if args.rank_by == 'clicks':
        leaf_clusters.sort(key=lambda c: c.total_clicks, reverse=True)
    elif args.rank_by == 'impressions':
        leaf_clusters.sort(key=lambda c: c.total_impressions, reverse=True)
    else:  # depth
        # Sort by depth descending, then by clicks descending as tie-breaker
        # This ensures clusters with same depth are ranked by traffic, not creation order
        leaf_clusters.sort(key=lambda c: (c.depth, c.total_clicks), reverse=True)
    
    # Generate canonical queries for ALL clusters (not just top N)
    print(f"Generating canonical queries for all {len(leaf_clusters)} clusters...")
    
    generator = CanonicalQueryGenerator(api_key)
    for i, cluster in enumerate(leaf_clusters):
        rank_info = f"depth={cluster.depth}" if args.rank_by == 'depth' else f"{cluster.total_clicks:.0f} clicks"
        print(f"  [{i+1}/{len(leaf_clusters)}] Cluster {cluster.cluster_id} ({cluster.size} queries, {rank_info})")
        cluster.canonical_query = generator.generate_canonical_query(cluster, df)
    
    # Create row-level output - select 5 representative queries per cluster
    print("Generating row-level output...")
    print("Selecting 5 representative queries per cluster using LLM...")
    
    row_data = []
    # Reuse the same generator instance
    
    for i, cluster in enumerate(leaf_clusters):
        if (i + 1) % 10 == 0:
            print(f"  Processing cluster {i+1}/{len(leaf_clusters)}...")
        
        # Select 5 representative queries for this cluster
        # Add small delay to avoid rate limits
        if i > 0:
            time.sleep(0.1)  # 100ms delay between calls
        
        selected_indices = generator.select_representative_queries(cluster, df, num_queries=5)
        
        # Get hierarchy path for this cluster
        hierarchy_path = get_cluster_hierarchy_path(cluster, clusters, max_depth=5)
        
        # Add selected queries to output
        for idx in selected_indices:
            if idx < len(df):
                row = df.iloc[idx]
                row_data.append({
                    'canonical_query': cluster.canonical_query if cluster.canonical_query else '',
                    'total_clicks': cluster.total_clicks,
                    'total_impressions': cluster.total_impressions,
                    'clicks': row['clicks'],
                    'impressions': row['impressions'],
                    'group size (# of internal queries)': cluster.size,
                    'cluster_id_depth_1': hierarchy_path[0],
                    'cluster_id_depth_2': hierarchy_path[1],
                    'cluster_id_depth_3': hierarchy_path[2],
                    'cluster_id_depth_4': hierarchy_path[3],
                    'cluster_id_depth_5': hierarchy_path[4],
                    'query': row['query']
                })
    
    row_df = pd.DataFrame(row_data)
    row_df.to_csv(args.output_row_csv, index=False)
    print(f"Saved row-level output to {args.output_row_csv} ({len(row_df)} representative query rows from {len(leaf_clusters)} clusters)")
    
    # Create group-level output
    print("Generating group-level output...")
    group_data = []
    for cluster in leaf_clusters:
        # Get hierarchy path for this cluster
        hierarchy_path = get_cluster_hierarchy_path(cluster, clusters, max_depth=5)
        
        group_data.append({
            'canonical_query': cluster.canonical_query if cluster.canonical_query else '',
            'total_clicks': cluster.total_clicks,
            'total_impressions': cluster.total_impressions,
            'group size (# of internal queries)': cluster.size,
            'cluster_id_depth_1': hierarchy_path[0],
            'cluster_id_depth_2': hierarchy_path[1],
            'cluster_id_depth_3': hierarchy_path[2],
            'cluster_id_depth_4': hierarchy_path[3],
            'cluster_id_depth_5': hierarchy_path[4]
        })
    
    group_df = pd.DataFrame(group_data)
    # Sort by the ranking metric used (with tie-breaker for depth)
    if args.rank_by == 'clicks':
        group_df = group_df.sort_values('total_clicks', ascending=False)
    elif args.rank_by == 'impressions':
        group_df = group_df.sort_values('total_impressions', ascending=False)
    else:  # depth
        # Sort by depth descending, then clicks descending as tie-breaker
        # Find max depth from hierarchy paths
        group_df['max_depth'] = group_df.apply(
            lambda row: max([i for i in range(5) if pd.notna(row[f'cluster_id_depth_{i+1}'])]) + 1 if any(pd.notna(row[f'cluster_id_depth_{i+1}']) for i in range(5)) else 0,
            axis=1
        )
        group_df = group_df.sort_values(['max_depth', 'total_clicks'], ascending=[False, False])
        group_df = group_df.drop('max_depth', axis=1)
    group_df.to_csv(args.output_group_csv, index=False)
    print(f"Saved group-level output to {args.output_group_csv}")
    
    print("\nDone!")


if __name__ == '__main__':
    main()

