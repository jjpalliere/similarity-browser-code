"""
Step-by-step clustering wrapper.

Refactored from cluster_queries.py to yield after each split,
producing events for the WebSocket stream.
Supports pause/resume: runs to target_leaf_count, then can split_more().
"""

import logging
import numpy as np

log = logging.getLogger(__name__)
import pandas as pd
from sklearn.cluster import KMeans
from openai import OpenAI
from typing import List, Dict, Optional, Tuple, Generator, Any
from dataclasses import dataclass


@dataclass
class Cluster:
    cluster_id: str
    member_indices: List[int]
    total_metric: float
    parent_id: Optional[str] = None
    depth: int = 0
    canonical: Optional[str] = None

    @property
    def size(self) -> int:
        return len(self.member_indices)


class StepClusterer:
    """
    Resumable recursive clusterer.
    - run() yields init + steps up to target_leaf_count, then paused.
    - split_more(n) yields n additional steps.
    - Both yield events: init, step, log, paused, complete.
    """

    def __init__(
        self,
        embeddings: np.ndarray,
        texts: List[str],
        metrics: List[float],
        coords: np.ndarray,
        openai_client: OpenAI,
        min_cluster_size: int = 10,
        target_leaf_count: int = 30,
        min_gain_rel: float = 0.01,
        min_child_size: int = 8,
        # Legacy alias
        coords_2d: Optional[np.ndarray] = None,
    ):
        self.embeddings = embeddings
        self.texts = texts
        self.metrics = metrics
        self.coords = coords if coords is not None else coords_2d
        self.n_dims = self.coords.shape[1]  # 2 or 3
        self.client = openai_client
        self.min_cluster_size = min_cluster_size
        self.target_leaf_count = target_leaf_count
        self.min_gain_rel = min_gain_rel
        self.min_child_size = min_child_size

        self.clusters: Dict[str, Cluster] = {}
        self.next_id = 0
        self.leaf_ids: List[str] = []
        self.terminal: set = set()
        self.step = 0
        self.exhausted = False  # True when no more candidates exist

    def _new_id(self) -> str:
        cid = f"c-{self.next_id}"
        self.next_id += 1
        return cid

    def _log(self, message: str) -> Dict[str, Any]:
        """Create a log event dict."""
        return {"type": "log", "message": message}

    def run(self) -> Generator[Dict[str, Any], None, None]:
        """Initial run: yields init event, splits to target, then pauses."""

        yield self._log(f"Starting clustering: {len(self.texts)} texts, {self.n_dims}D coords")
        yield self._log(f"Parameters: min_cluster={self.min_cluster_size}, target_leaves={self.target_leaf_count}, min_gain={self.min_gain_rel}, min_child={self.min_child_size}")

        total_metric = sum(self.metrics)
        top_metrics = sorted(enumerate(self.metrics), key=lambda x: x[1], reverse=True)[:5]
        yield self._log(f"Total metric: {total_metric:.0f}")
        for rank, (idx, val) in enumerate(top_metrics):
            yield self._log(f"  Top {rank+1}: \"{self.texts[idx][:60]}\" = {val:.0f}")

        # Build init event with all points
        points = []
        for i in range(len(self.texts)):
            pt = {
                "id": i,
                "text": self.texts[i],
                "metric": self.metrics[i],
                "x": float(self.coords[i, 0]),
                "y": float(self.coords[i, 1]),
            }
            if self.n_dims >= 3:
                pt["z"] = float(self.coords[i, 2])
            points.append(pt)

        # Estimate total steps
        estimated_steps = min(self.target_leaf_count - 1, len(self.texts) // self.min_cluster_size)
        yield self._log(f"Estimated {estimated_steps} split steps to reach {self.target_leaf_count} leaves")

        # Create root cluster
        root_id = self._new_id()
        root = Cluster(
            cluster_id=root_id,
            member_indices=list(range(len(self.texts))),
            total_metric=sum(self.metrics),
            depth=0,
        )
        self.clusters[root_id] = root
        self.leaf_ids = [root_id]

        yield self._log(f"Root cluster {root_id}: {root.size} members, metric={root.total_metric:.0f}")

        yield {
            "type": "init",
            "points": points,
            "total_steps_estimate": max(estimated_steps, 1),
            "root_cluster": {
                "id": root_id,
                "canonical": "all queries",
                "size": root.size,
                "total_metric": root.total_metric,
            },
        }

        # Split to target
        yield from self._run_splits(self.target_leaf_count)

        # Pause — client can request more
        if not self.exhausted:
            yield self._log(f"Paused at {len(self.leaf_ids)} leaves. Send 'split_more' to continue.")
            yield {"type": "paused", "total_steps": self.step, "leaf_count": len(self.leaf_ids), "can_split": True}
        else:
            yield self._log(f"No more splittable clusters. Final: {self.step} steps, {len(self.leaf_ids)} leaves.")
            yield {"type": "complete", "total_steps": self.step}

    def split_more(self, n: int = 5) -> Generator[Dict[str, Any], None, None]:
        """Run n additional split steps beyond current state."""
        target = len(self.leaf_ids) + n
        yield self._log(f"Splitting {n} more (current={len(self.leaf_ids)} leaves, new target={target})")

        yield from self._run_splits(target)

        if not self.exhausted:
            yield self._log(f"Paused at {len(self.leaf_ids)} leaves.")
            yield {"type": "paused", "total_steps": self.step, "leaf_count": len(self.leaf_ids), "can_split": True}
        else:
            yield self._log(f"No more splittable clusters. Final: {self.step} steps, {len(self.leaf_ids)} leaves.")
            yield {"type": "complete", "total_steps": self.step}

    def _run_splits(self, target_leaves: int) -> Generator[Dict[str, Any], None, None]:
        """Internal: run splits until we reach target_leaves or exhaust candidates."""
        while len(self.leaf_ids) < target_leaves:
            yield self._log(f"--- Round {self.step+1} | {len(self.leaf_ids)} leaves, target={target_leaves} ---")

            # Show current leaf state
            leaf_summary = []
            for lid in sorted(self.leaf_ids, key=lambda x: self.clusters[x].total_metric, reverse=True)[:5]:
                c = self.clusters[lid]
                label = c.canonical or "unlabeled"
                leaf_summary.append(f"  {lid} \"{label[:40]}\" size={c.size} metric={c.total_metric:.0f}")
            for line in leaf_summary:
                yield self._log(line)
            if len(self.leaf_ids) > 5:
                yield self._log(f"  ... and {len(self.leaf_ids) - 5} more leaves")

            candidate_id = self._find_best_candidate()
            if candidate_id is None:
                yield self._log("No valid candidates remain — all leaves are terminal or too small")
                self.exhausted = True
                break

            candidate = self.clusters[candidate_id]
            yield self._log(f"Selected candidate: {candidate_id} \"{candidate.canonical or 'root'}\" (size={candidate.size}, metric={candidate.total_metric:.0f}, depth={candidate.depth})")

            # Show top queries in candidate
            top_in_candidate = sorted(
                [(self.metrics[i], self.texts[i]) for i in candidate.member_indices],
                reverse=True
            )[:3]
            for m, t in top_in_candidate:
                yield self._log(f"  Top query: \"{t[:60]}\" = {m:.0f}")

            result = self._try_split(candidate_id)
            if result is None:
                self.terminal.add(candidate_id)
                yield self._log(f"Split FAILED for {candidate_id} — marked terminal")
                continue

            children, gain_rel, split_logs = result
            # Yield deferred split logs
            for log_msg in split_logs:
                yield self._log(log_msg)

            self.leaf_ids.remove(candidate_id)

            yield self._log(f"Split produced {len(children)} children (gain={gain_rel:.3f})")

            # Generate canonical labels for children
            for child in children:
                yield self._log(f"Labeling {child.cluster_id} (size={child.size}, metric={child.total_metric:.0f})...")
                child.canonical = self._generate_canonical(child)
                yield self._log(f"  → \"{child.canonical}\"")
                self.leaf_ids.append(child.cluster_id)

            self.step += 1

            # Build step event
            cluster_events = []
            for child in children:
                queries = []
                for idx in child.member_indices:
                    q = {
                        "id": idx,
                        "text": self.texts[idx],
                        "metric": self.metrics[idx],
                        "x": float(self.coords[idx, 0]),
                        "y": float(self.coords[idx, 1]),
                    }
                    if self.n_dims >= 3:
                        q["z"] = float(self.coords[idx, 2])
                    queries.append(q)
                cluster_events.append({
                    "id": child.cluster_id,
                    "parent_id": child.parent_id,
                    "canonical": child.canonical or "",
                    "size": child.size,
                    "total_metric": child.total_metric,
                    "depth": child.depth,
                    "queries": queries,
                })

            yield {
                "type": "step",
                "step": self.step,
                "depth": children[0].depth,
                "parent_id": candidate_id,
                "parent_canonical": self.clusters[candidate_id].canonical or "all queries",
                "clusters": cluster_events,
            }

        # Summary
        final_leaves = sorted(self.leaf_ids, key=lambda x: self.clusters[x].total_metric, reverse=True)
        yield self._log("Current clusters by metric:")
        for i, lid in enumerate(final_leaves):
            c = self.clusters[lid]
            yield self._log(f"  {i+1}. \"{c.canonical or '?'}\" — size={c.size}, metric={c.total_metric:.0f}, depth={c.depth}")

    def _find_best_candidate(self) -> Optional[str]:
        candidates = [
            cid for cid in self.leaf_ids
            if self.clusters[cid].size >= self.min_cluster_size
            and cid not in self.terminal
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda cid: self.clusters[cid].total_metric, reverse=True)
        return candidates[0]

    def _try_split(self, cluster_id: str) -> Optional[Tuple[List["Cluster"], float, List[str]]]:
        """Split a cluster, returning (children, gain_rel, log_messages) or None."""
        logs: List[str] = []
        cluster = self.clusters[cluster_id]

        if cluster.size < self.min_cluster_size or cluster.size <= self.min_child_size * 2:
            logs.append(f"Cluster too small: size={cluster.size} < min={self.min_cluster_size} or <= 2*min_child={self.min_child_size*2}")
            return None

        embs = self.embeddings[cluster.member_indices]
        weights = np.array([self.metrics[i] for i in cluster.member_indices])
        parent_metric = cluster.total_metric
        min_child_metric = parent_metric * 0.05

        logs.append(f"Parent metric={parent_metric:.0f}, min_child_metric={min_child_metric:.1f} (5%)")

        # Pure geometric KMeans — metric only decides WHICH cluster to split,
        # not HOW to split it. Semantic geometry separates the actual groups.
        parent_center = embs.mean(axis=0)
        parent_inertia = np.sum((embs - parent_center) ** 2)
        logs.append(f"Parent inertia={parent_inertia:.2f}")

        best_inertia = float("inf")
        best_labels = None
        best_k = 2

        for k in [2, 3]:
            if cluster.size < k:
                continue
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = km.fit_predict(embs)
            _, counts = np.unique(labels, return_counts=True)

            logs.append(f"  k={k}: inertia={km.inertia_:.2f}, sizes={counts.tolist()}")

            # Validate children: each must have enough members OR enough metric
            valid = True
            for label_idx in range(k):
                mask = labels == label_idx
                child_count = mask.sum()
                child_metric = weights[mask].sum()
                if child_count < self.min_child_size and child_metric < min_child_metric:
                    logs.append(f"    child {label_idx} INVALID: count={child_count} < {self.min_child_size} AND metric={child_metric:.0f} < {min_child_metric:.1f}")
                    valid = False
                    break
                else:
                    logs.append(f"    child {label_idx}: count={child_count}, metric={child_metric:.0f} ✓")
            if not valid:
                continue

            if km.inertia_ < best_inertia:
                best_inertia = km.inertia_
                best_labels = labels
                best_k = k
                logs.append(f"  → k={k} is current best")

        if best_labels is None:
            logs.append("No valid k found — split rejected")
            return None

        gain_rel = (parent_inertia - best_inertia) / parent_inertia if parent_inertia > 0 else 0
        logs.append(f"Best k={best_k}, gain_rel={gain_rel:.4f} (threshold={self.min_gain_rel})")

        if gain_rel < self.min_gain_rel:
            logs.append(f"Gain too low: {gain_rel:.4f} < {self.min_gain_rel} — split rejected")
            return None

        children = []
        for label in range(best_k):
            child_indices = [cluster.member_indices[i] for i in range(len(cluster.member_indices)) if best_labels[i] == label]
            child_metric = sum(self.metrics[i] for i in child_indices)
            # Dual check: accept if enough members OR enough metric share
            if len(child_indices) < self.min_child_size and child_metric < min_child_metric:
                logs.append(f"  Skipping child {label}: count={len(child_indices)}, metric={child_metric:.0f}")
                continue

            child = Cluster(
                cluster_id=self._new_id(),
                member_indices=child_indices,
                total_metric=child_metric,
                parent_id=cluster_id,
                depth=cluster.depth + 1,
            )
            children.append(child)
            self.clusters[child.cluster_id] = child
            # Show top query in each child
            top_q = sorted([(self.metrics[i], self.texts[i]) for i in child_indices], reverse=True)
            if top_q:
                logs.append(f"  Child {child.cluster_id}: size={child.size}, metric={child_metric:.0f}, top=\"{top_q[0][1][:50]}\"")

        if len(children) <= 1:
            logs.append("Only 0-1 valid children — split rejected")
            return None

        return (children, gain_rel, logs)

    def _generate_canonical(self, cluster: Cluster) -> str:
        """Generate a short canonical label for a cluster via LLM."""
        # Get top queries by metric, filter out low-signal noise
        indexed = [(self.metrics[i], self.texts[i]) for i in cluster.member_indices]
        indexed.sort(reverse=True)

        max_metric = indexed[0][0] if indexed else 1
        threshold = max_metric * 0.05
        significant = [(m, t) for m, t in indexed if m >= threshold][:50]

        # If only 1 significant query, skip LLM — just return it
        if len(significant) == 1:
            return significant[0][1][:80]

        prompt = (
            "You are analyzing a cluster of similar search queries. "
            "Generate a single canonical query that best represents the cluster.\n\n"
            "Queries ranked by importance weight (number in brackets is the weight, NOT part of the query text):\n"
            + "\n".join(f"- [{int(m)}] {t}" for m, t in significant)
            + "\n\nRules:\n"
            "1. The canonical query should closely match the HIGHEST-WEIGHTED query's exact phrasing\n"
            "2. Only deviate if lower queries reveal a meaningfully different shared theme\n"
            "3. Do NOT add qualifiers (industry, region, etc.) from low-weight variants\n"
            "4. At most 8 words\n"
            "5. Output ONLY the query, nothing else"
        )

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a search query analyst. Output only the canonical query."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=50,
            )
            return resp.choices[0].message.content.strip().strip('"').strip("'")
        except Exception as e:
            log.warning("Canonical generation failed for %s: %s", cluster.cluster_id, e)
            # Fallback: use top query
            return (indexed[0][1][:80] if indexed else "unknown")
