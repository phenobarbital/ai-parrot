"""Scheduler-free contracts watcher jobs (FEAT-539 M11).

Three plain async callables. They import **no scheduler** and send
**nothing**: the deploying agent decides when to run them (``@schedule``)
and what to do with the result (``send_result``). Every dependency —
library, delta tool, publishers, clock, service principal and recipient
scope — is injected.

``ingest_delta`` is the one with teeth. Its cursor rule is the whole point:
the committed delta link only advances once **every** item in the batch is
durably processed or explicitly recorded as skipped, so an interrupted run
replays idempotently instead of losing changes.

A 410 means the cursor is dead, never that everything was deleted. The job
recovers by re-enumerating the drive in full — retaining the dead cursor
would stall the source forever, since every later run would hit the same
410. Because a deletion that happened while the cursor was expired appears
in no page, a recovered rescan is then reconciled against local state.

That reconciliation is the one destructive path here, so it is deliberately
timid. It withdraws a contract only when absence really is evidence: a
complete whole-drive rescan of the same drive, with its final cursor, no
item errors, and no other live file still backing the card. A folder-scoped
rescan cannot prove absence at all — it only ever sees part of the drive —
so its missing items are reported in ``suspected_deletions`` for an
operator rather than acted on.
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

from .retrieval import READ_ROLES, ContractRetrieval, RequestContext

__all__ = (
    "RENEWAL_BUCKETS",
    "RECOGNISED_RECURRENCE",
    "SourceConfig",
    "DeltaIngestResult",
    "DeltaEnumerationError",
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
        folder_id: Optional stable item id of that folder. Graph's delta feed
            omits ``parentReference.path`` but reports ``parentReference.id``,
            so an id is the exact filter; a path has to be resolved to one.
            Supply it when it is known, to save the tool a lookup.
        download: Whether the job may download changed items.
    """

    source: str
    drive_id: str
    folder_path: Optional[str] = None
    folder_id: Optional[str] = None
    download: bool = True


class DeltaIngestResult(BaseModel):
    """What one ``ingest_delta`` run did.

    ``rescan_required`` means the committed cursor is dead **and** could not
    be recovered — nothing was processed and the cursor is retained.
    ``rescan_performed`` means a cursor expiry *was* recovered by
    re-enumerating the drive in full, so the batch is a complete listing and
    was reconciled against local state; ``reconciled`` lists the contracts
    retracted because they were absent from that listing.

    ``suspected_deletions`` lists source items missing from a rescan that
    were **not** retracted because absence did not prove deletion — a
    folder-scoped rescan only ever sees part of the drive. Those need an
    operator's eye, not an automatic withdrawal.
    """

    source: str
    report: IngestReport = Field(default_factory=IngestReport)
    cursor_committed: Optional[str] = None
    cursor_retained: Optional[str] = None
    rescan_required: bool = False
    rescan_performed: bool = False
    reconciled: list[str] = Field(default_factory=list)
    suspected_deletions: list[str] = Field(default_factory=list)
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
    """Cards inside the configured recipient scope.

    A principal with a read role covers the whole catalog; one with only an
    authenticated employee identity is narrowed exactly like
    ``my_contracts``, so a scoped digest never reports someone else's
    contracts.
    """
    pattern = None if principal.has_any_role(READ_ROLES) else "my_contracts"
    retrieval.authorize(principal, pattern=pattern)
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
        retrieval: Retrieval supplying the authorization gate. When it is
            omitted the gate is built from ``library.catalog`` — the
            principal is **always** authorized, never implicitly trusted.
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
    # Authorization is not optional on a path that carries retractions.
    # An omitted `retrieval` means "build the gate from this catalog", not
    # "skip the gate" — a missing argument must never widen access.
    gate = retrieval if retrieval is not None else ContractRetrieval(catalog=library.catalog)
    gate.authorize(principal, pattern="ingest_delta")

    catalog = library.catalog
    result = DeltaIngestResult(source=source.source)
    committed = await catalog.get_delta_token(source.source)
    enumeration_started = clock()

    try:
        page = await _enumerate(delta_tool, source, token=committed)
        if page.get("rescan_required"):
            # A 410 means "re-enumerate", never "everything was deleted".
            # Recover here rather than returning: a tool that only *signals*
            # the expiry would otherwise stall this source forever, because
            # the same dead cursor is retained and replayed on every run.
            logger.info(
                "Delta token expired for %s; re-enumerating the drive in full",
                source.source,
            )
            page = await _enumerate(delta_tool, source, token=None, full=True)
            result.rescan_performed = True
    except DeltaEnumerationError as exc:
        # A failed enumeration is not an empty one: keep the cursor so the
        # next run replays instead of advancing over unseen changes.
        result.errors.append(f"delta enumeration failed: {exc}")
        result.cursor_retained = committed
        logger.warning("Delta enumeration failed for %s: %s", source.source, exc)
        return result

    if page.get("rescan_required"):
        # Still unusable after a full re-enumeration. Touch nothing.
        result.rescan_required = True
        result.rescan_performed = False
        result.cursor_retained = committed
        logger.warning(
            "Delta enumeration for %s still reports a required rescan; "
            "cursor retained and nothing processed",
            source.source,
        )
        return result

    # The tool may have recovered the expiry internally and handed us the
    # full rescan already; that is equally a rescan for reconciliation.
    if page.get("reset_performed"):
        result.rescan_performed = True

    items: list[dict[str, Any]] = list(page.get("items") or [])
    tombstones = set(page.get("tombstones") or [])
    rows: list[IngestItemReport] = []

    async def _still_referenced(contract_id: str, drive_id: str, item_id: str) -> bool:
        """Whether another live source item still backs this contract.

        Identical files deduplicate onto one card, so the disappearance of
        one source file does not mean the contract is gone.
        """
        for other in await catalog.list_source_items(source.source):
            if other.deleted or other.contract_id != contract_id:
                continue
            if (other.drive_id, other.item_id) != (drive_id, item_id):
                return True
        return False

    async def retract(
        *,
        drive_id: str,
        item_id: str,
        current_uri: str,
        contract_id: Optional[str],
        reason: str,
    ) -> None:
        """Record a source item as gone and retract its projection.

        The catalog history, the archived evidence and the original document
        all survive; only the indexed projection is withdrawn.

        The projection is withdrawn **before** the source item is marked
        deleted. A failure part-way therefore leaves the item un-deleted and
        so eligible for the next run, instead of stranding a contract that
        is flagged gone but still indexed.
        """
        retracted = False
        if contract_id:
            if await _still_referenced(contract_id, drive_id, item_id):
                rows.append(
                    IngestItemReport(
                        source_uri=current_uri,
                        outcome="skipped",
                        contract_id=contract_id,
                        reason="source item gone, but another live file still backs this contract",
                    )
                )
            else:
                try:
                    await catalog.remove(contract_id)
                    if graph_loader is not None:
                        await graph_loader.retract(contract_id)
                except Exception as exc:  # noqa: BLE001 - retryable next run
                    # Leave the source item un-deleted below so the next run
                    # retries, and make the run non-durable so the cursor is
                    # retained rather than advancing past an unfinished
                    # retraction.
                    result.errors.append(f"{item_id}: retraction failed: {exc}")
                    rows.append(
                        IngestItemReport(
                            source_uri=current_uri,
                            outcome="error",
                            contract_id=contract_id,
                            reason=f"retraction failed: {exc}",
                        )
                    )
                    return False
                result.tombstoned.append(contract_id)
                retracted = True
                rows.append(
                    IngestItemReport(
                        source_uri=current_uri,
                        outcome="skipped",
                        contract_id=contract_id,
                        reason=reason,
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
        return retracted

    for item in items:
        item_id = item.get("item_id")
        drive_id = item.get("drive_id") or source.drive_id
        known = await catalog.get_source_item(drive_id, item_id)
        current_uri = item.get("web_url") or item.get("path") or item_id

        if item_id in tombstones or item.get("deleted"):
            await retract(
                drive_id=drive_id,
                item_id=item_id,
                current_uri=current_uri,
                contract_id=known.contract_id if known else None,
                reason="source item was deleted; contract retracted",
            )
            continue

        if item.get("is_folder"):
            rows.append(IngestItemReport(source_uri=current_uri, outcome="skipped", reason="folder"))
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
                contract_id=ingest.card.contract_id if ingest.card else (known.contract_id if known else None),
                sha256=item.get("sha256"),
                last_seen_at=clock(),
            )
        )

    # ----------------------------------------------------------------
    # Post-reset reconciliation
    #
    # Microsoft's resynchronisation guidance says to compare a rescan
    # against local state. The danger is the inverse error: treating a
    # listing that is merely *narrower* than local state as proof of
    # deletion, and silently withdrawing real contracts. Absence is only
    # evidence when the listing genuinely covers everything we hold.
    # ----------------------------------------------------------------
    reconcilable = (
        result.rescan_performed
        # A first run has no local state to reconcile against.
        and committed
        # No item errored, so a gap is not just a failure.
        and result.durable
        # The walk actually reached the end...
        and page.get("complete")
        # ...and produced the cursor that proves it.
        and page.get("delta_link")
        # The tool reported an explicit item list rather than omitting it.
        and isinstance(page.get("items"), list)
    )
    if result.rescan_performed and not reconcilable:
        logger.info(
            "Rescan of %s not reconciled (durable=%s complete=%s cursor=%s)",
            source.source,
            result.durable,
            bool(page.get("complete")),
            bool(page.get("delta_link")),
        )

    if reconcilable:
        # A folder-scoped rescan only ever sees part of the drive, so an
        # item outside the folder — or one the filter could not place — is
        # absent for reasons that have nothing to do with deletion. Report
        # those instead of acting on them.
        scoped = bool(source.folder_path or source.folder_id)
        seen = {(item.get("drive_id") or source.drive_id, item.get("item_id")) for item in items}

        for known_item in await catalog.list_source_items(source.source):
            if known_item.deleted:
                continue
            # Reconcile only the drive we actually enumerated: one source
            # name may span drives, and a rescan of one says nothing about
            # the others.
            if known_item.drive_id != source.drive_id:
                continue
            if (known_item.drive_id, known_item.item_id) in seen:
                continue
            # Mitigation against a concurrent run having just written this
            # item: anything touched after our enumeration began was not in
            # the snapshot we are reasoning about. (Serialising runs per
            # source is the real fix; this only narrows the window.)
            if known_item.last_seen_at is not None and known_item.last_seen_at > enumeration_started:
                continue

            if scoped:
                result.suspected_deletions.append(known_item.item_id)
                continue

            if await retract(
                drive_id=known_item.drive_id,
                item_id=known_item.item_id,
                current_uri=known_item.current_uri or known_item.item_id,
                contract_id=known_item.contract_id,
                reason="absent from a complete rescan; contract retracted",
            ):
                result.reconciled.append(known_item.contract_id)

        if result.reconciled:
            logger.info(
                "Rescan of %s retracted %d contract(s) missed while the cursor was expired",
                source.source,
                len(result.reconciled),
            )
        if result.suspected_deletions:
            logger.warning(
                "Rescan of %s is folder-scoped, so %d missing item(s) were "
                "reported rather than retracted: %s",
                source.source,
                len(result.suspected_deletions),
                ", ".join(sorted(result.suspected_deletions)),
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


class DeltaEnumerationError(RuntimeError):
    """The delta tool could not be driven, or reported a failure."""


def _delta_payload(outcome: Any) -> dict[str, Any]:
    """Normalise a delta call's return value into a plain payload dict.

    An ``O365Tool`` answers with a ``ToolResult``; a plain helper or a test
    double answers with the payload directly. Both are accepted, but an
    error result is raised rather than being mistaken for an empty page —
    treating a failed enumeration as "no changes" would let the cursor
    advance over unseen work.

    Args:
        outcome: Whatever the delta surface returned.

    Returns:
        The payload dict.

    Raises:
        DeltaEnumerationError: If the tool reported an error, or returned
            something that is not a payload.
    """
    if isinstance(outcome, dict):
        status = outcome.get("status")
        if outcome.get("error") or (status is not None and status != "success"):
            raise DeltaEnumerationError(outcome.get("error") or f"delta tool returned status={status!r}")
        return outcome
    status = getattr(outcome, "status", None)
    if status is not None:
        if status != "success" or getattr(outcome, "error", None):
            raise DeltaEnumerationError(getattr(outcome, "error", None) or f"delta tool returned status={status!r}")
        payload = getattr(outcome, "result", None)
        if isinstance(payload, dict):
            return payload
        raise DeltaEnumerationError(f"delta tool returned a non-dict result: {type(payload).__name__}")
    raise DeltaEnumerationError(f"delta tool returned an unusable value: {type(outcome).__name__}")


async def _enumerate(
    delta_tool: Any,
    source: SourceConfig,
    *,
    token: Optional[str],
    full: bool = False,
) -> dict[str, Any]:
    """Call whichever delta surface the injected tool exposes.

    Args:
        delta_tool: Either an ``O365Tool``-shaped delta tool or a plain
            helper exposing ``enumerate(**kwargs)``.
        source: The configured source scope.
        token: The committed cursor to resume from.
        full: Ignore ``token`` and enumerate the drive from scratch.

    Returns:
        The delta payload dict.

    Raises:
        DeltaEnumerationError: If the tool exposes no usable surface, or
            reported a failure.
    """
    kwargs: dict[str, Any] = {
        "drive_id": source.drive_id,
        "delta_token": None if full else token,
        "folder_path": source.folder_path,
    }
    if source.folder_id:
        # The exact filter, when the deployment knows it. Only sent when set,
        # so a tool without that argument is unaffected.
        kwargs["folder_id"] = source.folder_id

    enumerate_surface = getattr(delta_tool, "enumerate", None)
    if callable(enumerate_surface):
        return _delta_payload(await enumerate_surface(**kwargs))

    # An O365Tool must be driven through its public `run()`, which acquires
    # the authenticated Graph client via `_get_client()` and wraps failures.
    # Calling `_execute_graph_operation` directly skips authentication and
    # has no client to pass — `O365Tool` exposes `_client`, never `.client`.
    run_surface = getattr(delta_tool, "run", None)
    if callable(run_surface):
        return _delta_payload(await run_surface(**kwargs))

    raise DeltaEnumerationError(
        f"{type(delta_tool).__name__} exposes neither enumerate() nor run(); "
        f"it cannot be used as a delta tool"
    )


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
                contracts=[card.brief() for card in cards if card.contract_id in allowed],
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
