"""The four-stage retrieval policy protocol (spec §5).

Every concrete policy (`DirectSymbolPolicy`, `VectorSeedPolicy`, and later
`PersonalizedPageRankPolicy`/`SteinerTreePolicy`/`AncestrySummaryPolicy`/
`RationalePolicy`) implements the same four stages. Stages are
individually skippable (a policy may no-op a stage that does not apply to
it) but are **never reordered** — a future refactor changing that shape
would force edits across every policy.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.models import (
    ContextBundle,
    EdgeRef,
    NodeRef,
    RetrievalBudget,
    RetrievalRequest,
)

logger = logging.getLogger(__name__)


class Seed(BaseModel):
    """One seed anchor a policy starts expansion from (spec §5).

    Attributes:
        node: The seed `NodeRef`.
        score: Policy-local seed relevance. Not comparable across policies
            (same caveat as `Evidence.score`, spec §3.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: NodeRef
    score: float


class Subgraph(BaseModel):
    """Nodes gathered by `expand`/`prune`, ready for `assemble` (spec §5).

    `nodes` and `edge_paths` are parallel tuples (same length, same
    order) rather than a mapping, so the model stays frozen/hashable —
    ``edge_paths[i]`` is how ``nodes[i]`` was reached from the seed set
    (empty for the seeds themselves).

    Attributes:
        nodes: Candidate `NodeRef`s for the eventual `ContextBundle`.
        edge_paths: Per-node reach path, parallel to `nodes`.
        truncated: INV-5 — ``True`` iff the budget was exhausted before
            expansion/pruning completed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[NodeRef, ...]
    edge_paths: tuple[tuple[EdgeRef, ...], ...] = ()
    truncated: bool = False

    def model_post_init(self, context: Any, /) -> None:
        """Pad `edge_paths` with empty tuples if the caller omitted it."""
        if not self.edge_paths:
            object.__setattr__(self, "edge_paths", tuple(() for _ in self.nodes))
        elif len(self.edge_paths) != len(self.nodes):
            raise ValueError(
                f"Subgraph.edge_paths length ({len(self.edge_paths)}) must match "
                f"nodes length ({len(self.nodes)})"
            )


class RetrievalPolicyProtocol(Protocol):
    """The four-stage protocol every retrieval policy implements.

    Args:
        req: The `RetrievalRequest` (query + pinned workspace + budget).
        graph: Policy-specific graph/reader access — intentionally
            loosely typed here since each policy's graph dependency
            differs (`SQLiteGraphReader`, an in-memory `rustworkx`
            subgraph, etc.).
        seeds: Seed anchors produced by `seed`.
        subgraph: Intermediate `Subgraph` state.
        budget: The request's `RetrievalBudget` — every stage after
            `seed` must respect it (INV-5).
    """

    async def seed(self, req: RetrievalRequest, graph: Any) -> tuple[Seed, ...]:
        """Produce seed anchors for `req.query`."""
        ...

    async def expand(
        self, seeds: tuple[Seed, ...], graph: Any, budget: RetrievalBudget
    ) -> Subgraph:
        """Expand from `seeds` into a candidate `Subgraph`."""
        ...

    async def prune(self, subgraph: Subgraph, budget: RetrievalBudget) -> Subgraph:
        """Trim `subgraph` down to fit `budget`."""
        ...

    async def assemble(self, subgraph: Subgraph, budget: RetrievalBudget) -> ContextBundle:
        """Read content and build the final `ContextBundle`."""
        ...
