"""Recoverable GraphIndex temporal publication (FEAT-539 M6).

Every card revision is published to the GraphIndex Postgres plane as one
``GraphUpdate`` commit, so the graph keeps a **recorded-time** history of
what the catalog said and when. That is a different question from
contractual **effective time** (``contract_in_force`` over the embedded
``versions[]``), and both are exposed separately on purpose: an amendment
recorded in September can be effective since July.

``PostgresPersistence.apply_update`` owns its own transaction and generates
its own commit id, so it is *never* atomic with the catalog write. The
durable outbox is therefore the recovery mechanism: publication is
serialized per tenant, each revision keeps a stable ``run_id``, and a crash
between commit and receipt is recovered by looking the run up with
``list_commits`` and **validating** the commit payload before reusing it —
never by publishing a second logical version.

No global revert is exposed here: ``revert_commit`` would rewrite shared
graph history far beyond one contract.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..graphindex.schema import GraphUpdate, NodeKind, UniversalNode
from .catalog import ContractCatalogStore, PublicationUnavailableError
from .models import ContractCard, ContractVersion, PublicationRecord

__all__ = (
    "TEMPORAL_AGENT_ID",
    "NODE_ID_PREFIX",
    "contract_node_id",
    "revision_run_id",
    "build_graph_update",
    "TemporalDrainReport",
    "ContractTemporalPublisher",
)

logger = logging.getLogger(__name__)

#: Agent id stamped on every contracts temporal commit.
TEMPORAL_AGENT_ID = "contracts.temporal"

#: Stable node identity prefix (spec §2 "Temporal publication").
NODE_ID_PREFIX = "contracts:contract:"


def contract_node_id(contract_id: str) -> str:
    """Return the stable GraphIndex node id of a contract."""
    return f"{NODE_ID_PREFIX}{contract_id}"


def revision_run_id(contract_id: str, version_n: int, revision: int) -> str:
    """Return the stable run id of one card revision.

    Stability is what makes crash recovery possible: the same revision
    always looks itself up under the same ``run_id``.
    """
    return f"contracts:{contract_id}:{version_n}:{revision}"


def build_graph_update(
    card: ContractCard,
    version: Optional[ContractVersion] = None,
    *,
    tenant_id: str,
    revision: Optional[int] = None,
    tombstone: bool = False,
    agent_id: str = TEMPORAL_AGENT_ID,
) -> GraphUpdate:
    """Map one immutable card revision to a :class:`GraphUpdate`.

    Uses the existing ``NodeKind.DOCUMENT`` — no new enum member — and
    embeds the historical values (version number, revision, effective
    interval, source hash, card snapshot) in the node's ``domain_tags`` so
    they live in *versioned node content* rather than only in a mutable
    external reference.

    Args:
        card: The card revision being published.
        version: The contractual version row it belongs to.
        tenant_id: Tenant this commit belongs to.
        revision: Recorded revision; defaults to the card's.
        tombstone: True when publishing a retraction.
        agent_id: Agent id stamped on the commit.

    Returns:
        The ``GraphUpdate`` to apply.
    """
    if version is not None and version.card_snapshot:
        card = ContractCard.model_validate(version.card_snapshot)
    recorded_revision = revision if revision is not None else card.revision
    version_n = version.n if version is not None else (card.versions[-1].n if card.versions else 1)
    valid_from = version.valid_from if version is not None else card.term.effective_date
    valid_to = version.valid_to if version is not None else None
    snapshot = version.card_snapshot if version is not None else {}

    domain_tags: dict[str, Any] = {
        "tenant_id": tenant_id,
        "contract_id": card.contract_id,
        "contract_type": card.contract_type,
        "status": card.status,
        "verification": card.verification,
        "version_n": version_n,
        "revision": recorded_revision,
        "effective_from": valid_from.isoformat() if valid_from else None,
        "effective_to": valid_to.isoformat() if valid_to else None,
        "source_sha256": (version.source_sha256 if version else "") or card.source_sha256,
        "card_snapshot": snapshot,
        "active": not tombstone,
        "tombstone": tombstone,
    }
    node = UniversalNode(
        node_id=contract_node_id(card.contract_id),
        kind=NodeKind.DOCUMENT,
        title=card.title,
        source_uri=card.source_uri,
        summary=(card.summary or "")[:2000],
        domain_tags=domain_tags,
    )
    return GraphUpdate(
        nodes=[node],
        agent_id=agent_id,
        run_id=revision_run_id(card.contract_id, version_n, recorded_revision),
        asserted_by=agent_id,
        source=card.source_uri,
        reason=(
            f"contract {card.contract_id} retracted"
            if tombstone
            else f"contract {card.contract_id} v{version_n} r{recorded_revision}"
        ),
        op="publish",
    )


class TemporalDrainReport(BaseModel):
    """Outcome of one temporal outbox drain."""

    claimed: int = 0
    published: list[str] = Field(default_factory=list)
    recovered: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    receipts: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    unavailable: bool = False


class ContractTemporalPublisher:
    """Drain the temporal outbox into the GraphIndex Postgres plane.

    Args:
        catalog: The tenant-bound catalog owning the outbox.
        persistence: A ``PostgresPersistence`` bound to **this tenant's**
            schema. Passing a ``TenantContext`` alone does not isolate
            temporal reads, so each tenant gets its own configured schema.
        agent_id: Agent id stamped on commits.
        now: Injectable clock.
    """

    def __init__(
        self,
        *,
        catalog: ContractCatalogStore,
        persistence: Any,
        agent_id: str = TEMPORAL_AGENT_ID,
        now: Any = None,
    ) -> None:
        self.catalog = catalog
        self.persistence = persistence
        self.agent_id = agent_id
        self._now = now or (lambda: datetime.now(tz=timezone.utc))
        self._lock = asyncio.Lock()

    # -- publication -------------------------------------------------------

    async def drain(self, ctx: Any, *, limit: int = 10) -> TemporalDrainReport:
        """Publish queued revisions, serialized per tenant.

        Args:
            ctx: The ``TenantContext`` handed to the persistence layer.
            limit: Maximum outbox rows to claim.

        Returns:
            A :class:`TemporalDrainReport`; failures stay queued and
            observable rather than being swallowed.
        """
        report = TemporalDrainReport()
        guard = getattr(self.catalog, "publication_guard", None)
        async with self._lock, guard(target="temporal") if guard else nullcontext(True) as acquired:
            if not acquired:
                return report
            try:
                claimed = await self.catalog.claim_publication(target="temporal", limit=limit)
            except PublicationUnavailableError as exc:
                report.unavailable = True
                report.errors.append(str(exc))
                return report

            report.claimed = len(claimed)
            for record in claimed:
                try:
                    receipt, recovered = await self._publish_record(ctx, record)
                except Exception as exc:  # noqa: BLE001 - failures must stay retryable
                    logger.warning("Temporal publication failed for %s: %s", record.run_id, exc)
                    await self.catalog.fail_publication(record, error=str(exc))
                    report.failed.append(record.contract_id)
                    report.errors.append(f"{record.contract_id}: {exc}")
                    continue
                await self.catalog.complete_publication(record, receipt=receipt)
                report.receipts[record.contract_id] = receipt
                (report.recovered if recovered else report.published).append(record.contract_id)
        return report

    async def _publish_record(
        self,
        ctx: Any,
        record: PublicationRecord,
    ) -> tuple[str, bool]:
        """Publish one outbox row, recovering an acknowledged commit first.

        Returns:
            ``(commit_id, recovered)``.

        Raises:
            RuntimeError: When the card/version is missing, or an existing
                commit for this run does not match the intended payload.
        """
        card = await self.catalog.get(record.contract_id)
        if card is None:
            raise RuntimeError(f"unknown contract {record.contract_id!r}")
        versions = await self.catalog.versions(record.contract_id)
        version = next(
            (item for item in versions if item.n == record.version_n and item.revision == record.revision),
            None,
        )
        if version is None or not version.card_snapshot:
            raise RuntimeError(f"missing immutable snapshot for {record.run_id}")
        tombstone = bool(record.payload.get("tombstone"))
        update = build_graph_update(
            card,
            version,
            tenant_id=self.catalog.tenant_id,
            revision=record.revision,
            tombstone=tombstone,
            agent_id=self.agent_id,
        )

        recovered = await self.recover(ctx, update)
        if recovered is not None:
            return recovered, True

        receipt = await self.persistence.apply_update(ctx, update)
        return getattr(receipt, "commit_id", str(receipt)), False

    async def recover(self, ctx: Any, update: GraphUpdate) -> Optional[str]:
        """Return the commit id of an already-applied revision, if any.

        A crash between ``apply_update`` and the receipt write leaves a
        real commit behind. Re-publishing would emit a duplicate logical
        version, so the run is looked up by its stable ``run_id`` and the
        stored payload is **validated** against the intended one before it
        is accepted.

        Args:
            ctx: Tenant context.
            update: The update that was about to be applied.

        Returns:
            The recovered ``commit_id``, or ``None`` when this revision was
            never committed.

        Raises:
            RuntimeError: When a commit exists for this run but its payload
                does not match — never silently accepted.
        """
        commits = await self.persistence.list_commits(ctx, run_id=update.run_id, limit=10)
        if not commits:
            return None
        node = update.nodes[0]
        for summary in commits:
            commit_id = summary.get("commit_id")
            if not commit_id:
                continue
            commit = await self.persistence.get_commit(ctx, commit_id)
            if commit is None:
                continue
            if self._payload_matches(commit.get("payload") or {}, node):
                logger.info(
                    "Recovered acknowledged temporal commit %s for run %s",
                    commit_id,
                    update.run_id,
                )
                return commit_id
            raise RuntimeError(
                f"commit {commit_id} exists for run {update.run_id!r} but its payload does "
                "not match this revision; refusing to accept it"
            )
        return None

    @staticmethod
    def _payload_matches(payload: dict[str, Any], node: UniversalNode) -> bool:
        """Whether a recorded commit payload is this revision's node."""
        nodes = payload.get("nodes") or []
        for candidate in nodes:
            tags = (candidate.get("domain_tags") or {}) if isinstance(candidate, dict) else {}
            if candidate.get("node_id") != node.node_id:
                continue
            return (
                tags == node.domain_tags
                and candidate.get("title") == node.title
                and candidate.get("source_uri") == node.source_uri
                and candidate.get("summary") == node.summary
            )
        return False

    async def publish_retraction(self, ctx: Any, contract_id: str) -> str:
        """Record a retraction tombstone as a new recorded version.

        The node is *not* removed: recorded history must keep showing what
        the graph said before the retraction.

        Args:
            ctx: Tenant context.
            contract_id: The retracted contract.

        Returns:
            The commit id of the tombstone.

        Raises:
            RuntimeError: When the contract is unknown.
        """
        card = await self.catalog.get(contract_id)
        if card is None:
            raise RuntimeError(f"unknown contract {contract_id!r}")
        update = build_graph_update(
            card,
            None,
            tenant_id=self.catalog.tenant_id,
            revision=card.revision,
            tombstone=True,
            agent_id=self.agent_id,
        )
        receipt = await self.persistence.apply_update(ctx, update)
        return getattr(receipt, "commit_id", str(receipt))

    # -- recorded-time reads (distinct from contractual validity) ----------

    async def graph_as_of(self, ctx: Any, when: datetime) -> Any:
        """Recorded-time snapshot: what the graph said at ``when``.

        This is **not** ``contract_in_force``: it answers "what had we
        recorded by then", not "which wording was contractually in force".
        """
        return await self.persistence.as_of(ctx, when)

    async def contract_history(self, ctx: Any, contract_id: str) -> Any:
        """Recorded-time version rows of one contract node."""
        return await self.persistence.history(ctx, contract_node_id(contract_id))

    async def contract_diff(
        self,
        ctx: Any,
        contract_id: str,
        t1: datetime,
        t2: datetime,
    ) -> Any:
        """Recorded-time diff of one contract node between two instants."""
        return await self.persistence.diff(ctx, contract_node_id(contract_id), t1, t2)

    @staticmethod
    def contract_in_force(card: ContractCard, as_of: Any) -> Optional[ContractVersion]:
        """Contractual (effective-time) version in force on ``as_of``.

        Selected from the card's embedded ``versions[]`` — deliberately
        independent of when the graph recorded anything.

        Args:
            card: The card to inspect.
            as_of: The contractual date to test.

        Returns:
            The version in force, or ``None`` (an unknown effective date
            never claims to be in force).
        """
        for version in sorted(card.versions, key=lambda item: (item.n, item.revision)):
            if version.in_force(as_of):
                return version
        return None
