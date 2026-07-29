"""GraphPublisher — the durable write path for agent graph memory.

Implements the "publish pattern" for knowledge graphs used as persistent
shared agent memory: workers submit a validated :class:`GraphUpdate`
(nodes + edges + attribution), the publisher stamps assertion metadata
onto every unattributed item, and the persistence backend applies the
whole batch in one audited, revertible transaction.

The publisher is duck-typed over its ``persistence`` dependency — any
backend exposing ``apply_update`` / ``get_commit`` / ``list_commits`` /
``revert_commit`` works (``SQLitePersistence`` today; the ArangoDB
``GraphIndexPersistence`` can implement the same protocol later).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    CommitReceipt,
    GraphUpdate,
    Provenance,
)
from parrot.knowledge.ontology.schema import TenantContext

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class GraphPublisher:
    """Validate, attribute, and durably commit agent graph writes.

    Args:
        persistence: Backend implementing the commit protocol
            (``apply_update``, ``get_commit``, ``list_commits``,
            ``revert_commit``). ``SQLitePersistence`` satisfies it.
        ctx: Tenant context identifying the target graph.
    """

    def __init__(self, persistence: Any, ctx: TenantContext) -> None:
        self.persistence = persistence
        self.ctx = ctx
        self.logger = logging.getLogger(__name__)

    def _stamp(self, update: GraphUpdate) -> None:
        """Stamp assertion metadata onto every unattributed node/edge.

        Items that already carry an ``assertion`` keep it (extraction
        pipelines may pre-attribute). Nodes/edges without one receive an
        :class:`AssertionMeta` built from the update's attribution.

        Provenance handling: agent-minted nodes (``agent://`` source
        URIs) and non-INFERRED edges are marked ``Provenance.ASSERTED``.
        Pipeline-extracted nodes an agent merely annotates keep their
        original provenance — the assertion metadata alone records who
        touched them. ``INFERRED`` items are never re-labeled (their
        ``confidence`` semantics depend on it).

        Args:
            update: The update to stamp (mutated in place).
        """
        meta = AssertionMeta(
            asserted_by=update.asserted_by,
            asserted_at=_now_iso(),
            agent_id=update.agent_id,
            run_id=update.run_id,
            source=update.source,
        )
        for node in update.nodes:
            if node.assertion is None:
                node.assertion = meta
                if (
                    node.provenance == Provenance.EXTRACTED
                    and node.source_uri.startswith("agent://")
                ):
                    node.provenance = Provenance.ASSERTED
        for edge in update.edges:
            if edge.assertion is None:
                edge.assertion = meta
                if edge.provenance == Provenance.EXTRACTED:
                    edge.provenance = Provenance.ASSERTED

    async def publish(self, update: GraphUpdate) -> CommitReceipt:
        """Stamp attribution onto the update and commit it durably.

        Args:
            update: The validated batch of graph writes.

        Returns:
            The :class:`CommitReceipt` recorded by the backend.
        """
        self._stamp(update)
        receipt = await self.persistence.apply_update(self.ctx, update)
        self.logger.info(
            "GraphPublisher.publish: commit %s (%s) by %s",
            receipt.commit_id,
            update.op,
            update.asserted_by,
        )
        return receipt

    async def get_commit(self, commit_id: str) -> Optional[dict[str, Any]]:
        """Fetch one recorded commit (payload + items) by id.

        Args:
            commit_id: The commit identifier.

        Returns:
            The commit dict, or ``None`` when unknown.
        """
        return await self.persistence.get_commit(self.ctx, commit_id)

    async def list_commits(
        self,
        run_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List recorded commits, newest first.

        Args:
            run_id: Optional filter on the producing run.
            agent_id: Optional filter on the producing agent.
            limit: Maximum rows returned.

        Returns:
            Commit summary dicts.
        """
        return await self.persistence.list_commits(
            self.ctx, run_id=run_id, agent_id=agent_id, limit=limit
        )

    async def revert_commit(self, commit_id: str) -> dict[str, Any]:
        """Revert a commit by restoring its captured pre-images.

        Args:
            commit_id: The commit to revert.

        Returns:
            ``{"status": "reverted", ...}`` or ``{"error": ...}``.
        """
        return await self.persistence.revert_commit(self.ctx, commit_id)
