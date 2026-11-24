"""
Projection module.

Uses PCA -> t-SNE for dimensionality reduction of embeddings.
Supports 2D and 3D output.
"""

import numpy as np
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE


def _project(embeddings: np.ndarray, n_dims: int, random_state: int = 42) -> np.ndarray:
    """
    Project high-dimensional embeddings to n_dims dimensions,
    then normalize to [-1, 1] range.

    Pipeline: PCA(50) -> t-SNE(n_dims)
    """
    n_samples = len(embeddings)

    # Step 1: PCA to reduce dimensionality first (faster t-SNE)
    n_components_pca = min(50, n_samples - 1, embeddings.shape[1])
    if n_components_pca > n_dims:
        pca = PCA(n_components=n_components_pca, random_state=random_state)
        reduced = pca.fit_transform(embeddings)
    else:
        reduced = embeddings

    # Step 2: t-SNE
    if n_samples > 5:
        perplexity = min(30, n_samples - 1)
        tsne = TSNE(
            n_components=n_dims,
            random_state=random_state,
            perplexity=perplexity,
            n_iter=1000,
            metric="cosine",
            init="pca" if n_dims <= min(n_components_pca, reduced.shape[1]) else "random",
        )
        coords = tsne.fit_transform(reduced)
    else:
        pca2 = PCA(n_components=n_dims, random_state=random_state)
        coords = pca2.fit_transform(reduced)

    # Normalize to [-1, 1]
    for dim in range(n_dims):
        col = coords[:, dim]
        mn, mx = col.min(), col.max()
        if mx - mn > 0:
            coords[:, dim] = 2 * (col - mn) / (mx - mn) - 1
        else:
            coords[:, dim] = 0.0

    return coords


def project_2d(embeddings: np.ndarray, random_state: int = 42) -> np.ndarray:
    """Project to 2D. Returns (N, 2) array."""
    return _project(embeddings, 2, random_state)


def project_3d(embeddings: np.ndarray, random_state: int = 42) -> np.ndarray:
    """Project to 3D. Returns (N, 3) array."""
    return _project(embeddings, 3, random_state)
