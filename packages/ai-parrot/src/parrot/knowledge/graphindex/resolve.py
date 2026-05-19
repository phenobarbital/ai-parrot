"""Cross-domain resolution stage for GraphIndex.

Level 1 embedding-threshold pass: for each pair of nodes from DIFFERENT
extractors (identified by different source domains), computes cosine
similarity from the FAISS index.  If ``sim > threshold``, emits a
``mentions`` edge with ``provenance=Provenance.INFERRED`` and
``confidence=sim``.

Level 2 LLM verification is deferred to v2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)


@dataclass
class ResolutionConfig:
    """Configuration for cross-domain resolution.

    Args:
        threshold: Global cosine similarity threshold.  Pairs with similarity
            above this value will produce ``mentions`` edges.
        max_edges_per_node: Maximum number of inferred edges per source node
            to prevent combinatorial explosion.
    """

    threshold: float = 0.75
    max_edges_per_node: int = 10


def _get_extractor_domain(node: UniversalNode) -> str:
    """Return a string identifying the extractor domain for a node.

    Used to determine whether two nodes come from different extractors.
    The domain is derived from the node ``kind``:
    - ``SYMBOL`` / ``RATIONALE`` → "code"
    - ``DOCUMENT`` / ``SECTION`` → "document"
    - ``SKILL``    → "skill"
    - ``CONCEPT``  → "concept"

    Nodes of the same domain are considered same-extractor and are skipped
    by the cross-domain resolution pass.

    Args:
        node: The node to classify.

    Returns:
        A domain string.
    """
    _KIND_TO_DOMAIN = {
        NodeKind.SYMBOL: "code",
        NodeKind.RATIONALE: "code",
        NodeKind.DOCUMENT: "document",
        NodeKind.SECTION: "document",
        NodeKind.SKILL: "skill",
        NodeKind.CONCEPT: "concept",
    }
    return _KIND_TO_DOMAIN.get(node.kind, "unknown")


async def resolve_cross_domain(
    nodes: list[UniversalNode],
    embedder: object,
    config: Optional[ResolutionConfig] = None,
) -> list[UniversalEdge]:
    """Discover implicit cross-domain edges via embedding similarity.

    For each pair of nodes from different extractors (different domain
    strings), checks cosine similarity via the FAISS index.  Emits
    ``mentions`` edges where similarity exceeds the configured threshold.

    Args:
        nodes: All nodes from all extractors.
        embedder: A ``GraphIndexEmbedder`` instance with the FAISS index
            already populated (i.e., after the embed stage).
        config: Resolution configuration.  Uses ``ResolutionConfig()``
            defaults if not provided.

    Returns:
        List of new ``UniversalEdge`` objects with
        ``provenance=Provenance.INFERRED``.
    """
    if config is None:
        config = ResolutionConfig()

    if len(nodes) < 2:
        return []

    # Index nodes with embeddings, grouped by domain
    embedded_nodes: list[UniversalNode] = [
        n for n in nodes if n.embedding_ref is not None
    ]

    if len(embedded_nodes) < 2:
        return []

    # Group by domain for cross-domain filtering
    domain_groups: dict[str, list[UniversalNode]] = {}
    for node in embedded_nodes:
        domain = _get_extractor_domain(node)
        domain_groups.setdefault(domain, []).append(node)

    domains = list(domain_groups.keys())
    if len(domains) < 2:
        # All nodes from same domain — nothing to resolve
        return []

    new_edges: list[UniversalEdge] = []

    # For each pair of different domains, check cross-domain similarity
    for i, domain_a in enumerate(domains):
        for domain_b in domains[i + 1:]:
            nodes_a = domain_groups[domain_a]
            nodes_b = domain_groups[domain_b]

            for node_a in nodes_a:
                edges_for_node: list[UniversalEdge] = []

                for node_b in nodes_b:
                    sim = await _compute_similarity(node_a.node_id, node_b.node_id, embedder)
                    if sim is None:
                        continue

                    if sim > config.threshold:
                        edges_for_node.append(
                            UniversalEdge(
                                source_id=node_a.node_id,
                                target_id=node_b.node_id,
                                kind=EdgeKind.MENTIONS,
                                provenance=Provenance.INFERRED,
                                confidence=float(sim),
                            )
                        )

                # Sort by confidence and cap
                edges_for_node.sort(key=lambda e: e.confidence or 0.0, reverse=True)
                new_edges.extend(edges_for_node[: config.max_edges_per_node])

    return new_edges


async def _compute_similarity(
    node_id_a: str,
    node_id_b: str,
    embedder: object,
) -> Optional[float]:
    """Compute cosine similarity between two nodes via the FAISS embedder.

    Args:
        node_id_a: First node ID.
        node_id_b: Second node ID.
        embedder: A ``GraphIndexEmbedder`` instance.

    Returns:
        Cosine similarity in [0, 1], or ``None`` if embeddings are missing.
    """
    vec_a = embedder.get_embedding(node_id_a)
    vec_b = embedder.get_embedding(node_id_b)

    if vec_a is None or vec_b is None:
        return None

    vec_a = vec_a.astype(np.float32)
    vec_b = vec_b.astype(np.float32)

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    sim = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
    # Clamp to [0, 1] (negative similarity → no inferred edge)
    return max(0.0, sim)
