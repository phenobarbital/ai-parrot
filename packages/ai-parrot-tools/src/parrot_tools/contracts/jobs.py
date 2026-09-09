"""Scheduler-free contracts watcher jobs (FEAT-539 M11).

Three plain async callables. They import **no scheduler** and send
**nothing**: the deploying agent decides when to run them (``@schedule``)
and what to do with the result (``send_result``). Every dependency —
library, delta tool, publishers, clock, service principal and recipient
scope — is injected.

``ingest_delta`` is the one with teeth. Its cursor rule is the whole point:
the committed delta link only advances once **every** item in the batch is
durably processed or explicitly recorded as skipped, so an interrupted run
replays idempotently instead of losing changes. A 410 triggers a full
rescan; a partial listing is never interpreted as mass deletion.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.contracts.models import (
    IngestItemReport,
    IngestReport,
    SourceItem,
)

from .retrieval import RequestContext

__all__ = (
    "RENEWAL_BUCKETS",
    "RECOGNISED_RECURRENCE",
    "SourceConfig",
    "DeltaIngestResult",
    "RenewalBucket",
    "RenewalsReport",
    "ObligationsDigest",
    "ingest_delta",
    "renewals_report",
    "obligations_digest",
)

logger = logging.getLogger(__name__)

#: Deterministic, non-overlapping renewal buckets (inclusive day windows).
RENEWAL_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
)

#: Recurrence rules the digest recognises. Anything else is surfaced for
#: review rather than interpreted.
RECOGNISED_RECURRENCE: dict[str, int] = {
    "annually": 365,
    "annual": 365,
    "yearly": 365,
    "semiannually": 182,
    "semi-annually": 182,
    "quarterly": 91,
    "monthly": 30,
    "weekly": 7,
}


class SourceConfig(BaseModel):
    """One configured document source to enumerate.

    Args:
        source: Stable source name (also the cursor key).
        drive_id: Graph drive id to enumerate.
        folder_path: Optional folder filter within the drive.
        download: Whether the job may download changed items.
    """

    source: str
    drive_id: str
    folder_path: Optional[str] = None
    download: bool = True


class DeltaIngestResult(BaseModel):
    """What one ``ingest_delta`` run did."""

    source: str
    report: IngestReport = Field(default_factory=IngestReport)
    cursor_committed: Optional[str] = None
    cursor_retained: Optional[str] = None
    rescan_required: bool = False
    tombstoned: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def durable(self) -> bool:
        """Whether every item was durably processed or explicitly skipped."""
        return not self.errors


class RenewalBucket(BaseModel):
    """One non-overlapping renewal window."""

    label: str
    start: date
    end: date
    contracts: list[dict[str, Any]] = Field(default_factory=list)


class RenewalsReport(BaseModel):
    """Deterministic renewals radar output."""

    today: date
    key: str = "notice_deadline"
    buckets: list[RenewalBucket] = Field(default_factory=list)
    prose: Optional[dict[str, Any]] = None

    @property
    def total(self) -> int:
        """How many contracts the report covers."""
        return sum(len(bucket.contracts) for bucket in self.buckets)


class ObligationsDigest(BaseModel):
    """Deterministic obligations digest output."""

    today: date
    until: date
    due: list[dict[str, Any]] = Field(default_factory=list)
    recurring: list[dict[str, Any]] = Field(default_factory=list)
    needs_review: list[dict[str, Any]] = Field(default_factory=list)
    prose: Optional[dict[str, Any]] = None


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _authorized_cards(retrieval: Any, principal: RequestContext) -> list[Any]:
    """Cards the configured service principal may see."""
    retrieval.authorize(principal)
    return await retrieval._authorized_cards(principal)


# --------------------------------------------------------------------------
# ingest_delta
# --------------------------------------------------------------------------


async def ingest_delta(
    *,
    library: Any,
    delta_tool: Any,
    source: SourceConfig,
    principal: RequestContext,
    retrieval: Any = None,
    graph_loader: Any = None,
    temporal: Any = None,
    tenant_context: Any = None,
    downloader: Any = None,
    now: Any = None,
) -> DeltaIngestResult:
    """Ingest changes from one configured source.

    Args:
        library: The :class:`ContractLibrary` doing the carding.
        delta_tool: A delta tool exposing
            ``_execute_graph_operation(client, **kwargs)`` or an
            ``enumerate``-shaped helper.
        source: The configured source scope (drive/folder/cursor key).
        principal: The trusted service principal this job runs as.
        retrieval: Optional retrieval used to authorize the principal.
        graph_loader: Optional loader used to retract tombstoned contracts.
        temporal: Optional temporal publisher to drain afterwards.
        tenant_context: Tenant context for the temporal drain.
        downloader: ``async (item) -> Path | None`` supplying local bytes.
        now: Injectable clock.

    Returns:
        A :class:`DeltaIngestResult`. The cursor is committed **only** when
        every item was durably processed or explicitly skipped.
    """
    clock = now or _utcnow
    if retrieval is not None:
        retrieval.authorize(principal)

    catalog = library.catalog
    result = DeltaIngestResult(source=source.source)
    committed = await catalog.get_delta_token(source.source)

    page = await _enumerate(delta_tool, source, token=committed)
    if page.get("rescan_required"):
        # A 410 means "re-enumerate", never "everything was deleted".
        result.rescan_required = True
        result.cursor_retained = committed
        logger.info("Delta token expired for %s; a full rescan is required", source.source)
        return result

    items: list[dict[str, Any]] = list(page.get("items") or [])
    tombstones = set(page.get("tombstones") or [])
    rows: list[IngestItemReport] = []

    for item in items:
        item_id = item.get("item_id")
        drive_id = item.get("drive_id") or source.drive_id
        known = await catalog.get_source_item(drive_id, item_id)
        current_uri = item.get("web_url") or item.get("path") or item_id

        if item_id in tombstones or item.get("deleted"):
            # A tombstone retracts the projection; catalog history, the
            # archived evidence and the original document all survive.
            contract_id = known.contract_id if known else None
            await catalog.upsert_source_item(
                SourceItem(
                    source=source.source,
                    drive_id=drive_id,
                    item_id=item_id,
                    current_uri=current_uri,
                    contract_id=contract_id,
                    deleted=True,
                    last_seen_at=clock(),
                )
            )
            if contract_id:
                await catalog.remove(contract_id)
                if graph_loader is not None:
                    await graph_loader.retract(contract_id)
                result.tombstoned.append(contract_id)
                rows.append(
                    IngestItemReport(
                        source_uri=current_uri,
                        outcome="skipped",
                        contract_id=contract_id,
                        reason="source item was deleted; contract retracted",
                    )
                )
            else:
                rows.append(
                    IngestItemReport(
                        source_uri=current_uri,
                        outcome="skipped",
                        reason="tombstone for an item that was never carded",
                    )
                )
            continue

        if item.get("is_folder"):
            rows.append(
                IngestItemReport(
                    source_uri=current_uri, outcome="skipped", reason="folder"
                )
            )
            continue

        path = None
        if downloader is not None:
            try:
                path = await downloader(item)
            except Exception as exc:  # noqa: BLE001 - a failed download is retryable
                result.errors.append(f"{item_id}: download failed: {exc}")
                rows.append(
                    IngestItemReport(
                        source_uri=current_uri,
                        outcome="error",
                        reason=f"download failed: {exc}",
                    )
                )
                continue
        if path is None:
            rows.append(
                IngestItemReport(
                    source_uri=current_uri,
                    outcome="skipped",
                    reason="no local copy available for this item",
                )
            )
            await catalog.upsert_source_item(
                SourceItem(
                    source=source.source,
                    drive_id=drive_id,
                    item_id=item_id,
                    current_uri=current_uri,
                    contract_id=known.contract_id if known else None,
                    sha256=item.get("sha256"),
                    last_seen_at=clock(),
                )
            )
            continue

        ingest = await library.add_contract(
            path,
            source_uri=known.current_uri if known else current_uri,
        )
        rows.append(IngestItemReport.from_result(ingest))
        if ingest.outcome == "error":
            result.errors.append(f"{item_id}: {ingest.reason}")
        await catalog.upsert_source_item(
            SourceItem(
                source=source.source,
                drive_id=drive_id,
                item_id=item_id,
                current_uri=current_uri,
                name=item.get("name"),
                contract_id=ingest.card.contract_id
                if ingest.card
                else (known.contract_id if known else None),
                sha256=item.get("sha256"),
                last_seen_at=clock(),
            )
        )

    result.report = IngestReport(items=rows)

    delta_link = page.get("delta_link")
    if result.durable and page.get("complete") and delta_link:
        await catalog.set_delta_token(source.source, delta_link)
        result.cursor_committed = delta_link
        result.report.cursor_advanced = True
        result.report.cursor = delta_link
    else:
        # Retain the old cursor so the next run replays this batch.
        result.cursor_retained = committed
        logger.info(
            "Cursor for %s retained (durable=%s complete=%s)",
            source.source,
            result.durable,
            page.get("complete"),
        )

    if temporal is not None:
        drain = await temporal.drain(tenant_context)
        result.errors.extend(drain.errors)

    return result


async def _enumerate(delta_tool: Any, source: SourceConfig, *, token: Optional[str]) -> dict[str, Any]:
    """Call whichever delta surface the injected tool exposes."""
    kwargs = {
        "drive_id": source.drive_id,
        "delta_token": token,
        "folder_path": source.folder_path,
    }
    if hasattr(delta_tool, "_execute_graph_operation"):
        client = getattr(delta_tool, "client", None)
        return await delta_tool._execute_graph_operation(client, **kwargs)
    return await delta_tool.enumerate(**kwargs)


# --------------------------------------------------------------------------
# renewals_report
# --------------------------------------------------------------------------


async def renewals_report(
    *,
    retrieval: Any,
    principal: RequestContext,
    today: Optional[date] = None,
    key: str = "notice_deadline",
    flow: Any = None,
    prose_question: Optional[str] = None,
) -> RenewalsReport:
    """Bucket upcoming renewals into 30/60/90-day windows.

    Buckets are inclusive and non-overlapping (0-30, 31-60, 61-90), the
    driving date is the notice deadline with an expiration fallback, and
    contracts with no date at all are omitted. Deterministic and SQL-only:
    no ArangoDB, no LLM.

    Args:
        retrieval: The authorized retrieval layer.
        principal: The trusted service principal.
        today: Injected current date.
        key: ``notice_deadline`` (default) or ``expiration_date``.
        flow: Optional fixed answer flow for the prose paragraph.
        prose_question: The question that prose would answer.

    Returns:
        A :class:`RenewalsReport`; ``prose`` is present only when a flow
        was supplied. Nothing is ever sent.
    """
    reference = today or _utcnow().date()
    allowed = {card.contract_id for card in await _authorized_cards(retrieval, principal)}

    buckets: list[RenewalBucket] = []
    for label, start_offset, end_offset in RENEWAL_BUCKETS:
        start = reference + timedelta(days=start_offset)
        end = reference + timedelta(days=end_offset)
        cards = await retrieval.catalog.expiring(until=end, key=key, since=start)
        buckets.append(
            RenewalBucket(
                label=label,
                start=start,
                end=end,
                contracts=[
                    card.brief() for card in cards if card.contract_id in allowed
                ],
            )
        )

    report = RenewalsReport(today=reference, key=key, buckets=buckets)
    if flow is not None and prose_question:
        outcome = await flow.answer(prose_question, request_context=principal)
        report.prose = _prose_payload(outcome)
    return report


# --------------------------------------------------------------------------
# obligations_digest
# --------------------------------------------------------------------------


async def obligations_digest(
    *,
    retrieval: Any,
    principal: RequestContext,
    today: Optional[date] = None,
    days: int = 7,
    kinds: Optional[Sequence[str]] = None,
    flow: Any = None,
    prose_question: Optional[str] = None,
) -> ObligationsDigest:
    """Digest obligations coming due in a window.

    Fixed due dates inside the window are reported as ``due``; recognised
    anchored recurrences are reported as ``recurring``; anything with an
    unrecognised or unanchored recurrence is surfaced under
    ``needs_review`` rather than interpreted by a model.

    Args:
        retrieval: The authorized retrieval layer.
        principal: The trusted service principal.
        today: Injected current date.
        days: Window length (defaults to the weekly cadence).
        kinds: Restrict to these obligation kinds.
        flow: Optional fixed answer flow for the prose paragraph.
        prose_question: The question that prose would answer.

    Returns:
        An :class:`ObligationsDigest`. Nothing is ever sent.
    """
    from parrot.knowledge.contracts.catalog import ObligationWindow  # noqa: PLC0415

    reference = today or _utcnow().date()
    until = reference + timedelta(days=max(1, int(days)))
    allowed = {card.contract_id for card in await _authorized_cards(retrieval, principal)}

    window = ObligationWindow(
        since=reference,
        until=until,
        kinds=list(kinds) if kinds else None,
        include_recurring=True,
        limit=500,
    )
    digest = ObligationsDigest(today=reference, until=until)
    for obligation in await retrieval.catalog.obligations_due(window):
        if obligation.contract_id not in allowed:
            continue
        payload = obligation.model_dump(mode="json")
        if obligation.due_date is not None:
            digest.due.append(payload)
            continue
        recurrence = (obligation.recurrence or "").strip().lower()
        if recurrence in RECOGNISED_RECURRENCE:
            anchor = _recurrence_anchor(obligation)
            if anchor is None:
                payload["review_reason"] = "recurrence has no anchor date"
                digest.needs_review.append(payload)
            else:
                payload["next_due"] = anchor.isoformat()
                digest.recurring.append(payload)
        elif recurrence:
            payload["review_reason"] = f"unrecognised recurrence {obligation.recurrence!r}"
            digest.needs_review.append(payload)

    if flow is not None and prose_question:
        outcome = await flow.answer(prose_question, request_context=principal)
        digest.prose = _prose_payload(outcome)
    return digest


def _recurrence_anchor(obligation: Any) -> Optional[date]:
    """Return the anchor a recurrence is measured from, if there is one.

    A recurrence with no anchor is ambiguous by definition, so it goes to
    review instead of being guessed at.
    """
    provenance = getattr(obligation, "provenance", None)
    verified_at = getattr(provenance, "verified_at", None) if provenance else None
    if verified_at is not None:
        return verified_at.date()
    return None


def _prose_payload(outcome: Any) -> dict[str, Any]:
    """Render an optional prose paragraph produced by the shared gate."""
    answer = getattr(outcome, "answer", None)
    if answer is None:
        return {"reason": getattr(outcome, "reason", "no answer produced")}
    return {
        "answer_kind": answer.answer_kind,
        "answer": answer.answer,
        "citations": [citation.model_dump(mode="json") for citation in answer.citations],
        "answer_id": getattr(outcome, "answer_id", None),
    }
