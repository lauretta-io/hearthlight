"""K-reciprocal reranking for a bounded set of normalized embeddings."""

import numpy as np


def reciprocal_distances(embeddings, query_count):
    """Blend cosine distance and weighted Jaccard distance over reciprocal neighbors."""
    distance = np.clip(1 - embeddings @ embeddings.T, 0, 2)
    size = len(embeddings)
    # Keep neighborhoods local when the window holds only a few observations.
    k1 = min(20, max(1, size // 3), size - 1)
    k2 = min(6, max(1, k1 // 3))
    np.fill_diagonal(distance, -1)
    rank = np.argsort(distance, axis=1, kind="stable")
    np.fill_diagonal(distance, 0)

    def reciprocal(index, count):
        neighbors = rank[index, :count + 1]
        return neighbors[(rank[neighbors, :count + 1] == index).any(axis=1)]

    weights = np.zeros_like(distance)
    for index in range(size):
        neighbors = reciprocal(index, k1)
        expanded = set(neighbors)
        for neighbor in neighbors:
            nearby = reciprocal(neighbor, max(1, round(k1 / 2)))
            if len(set(nearby).intersection(neighbors)) > 2 * len(nearby) / 3:
                expanded.update(nearby)
        columns = list(expanded)
        affinity = np.exp(-distance[index, columns])
        weights[index, columns] = affinity / affinity.sum()
    if k2 > 1:
        weights = weights[rank[:, :k2]].mean(axis=1)

    result = np.empty((query_count, size - query_count), dtype=np.float32)
    for index in range(query_count):
        shared = np.minimum(weights[index], weights[query_count:]).sum(axis=1)
        jaccard = 1 - shared / (2 - shared)
        result[index] = 0.7 * jaccard + 0.3 * distance[index, query_count:]
    return result
