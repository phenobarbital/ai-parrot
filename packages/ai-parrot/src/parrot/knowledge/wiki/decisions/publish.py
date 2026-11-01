"""All-or-nothing publication of an approved decision batch (FEAT-784 Module 8).

Write order (AC12): (1) batch marker ``pending``; (2) every record of the
batch through the per-record CAS; (3) one CAS flipping the marker to
``published``; (4) only then retire the predecessors the batch supersedes.
A crash before (3) leaves the marker ``pending``, so the eligibility predicate
hides every record of the batch; a retry converges.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import Field

from parrot.knowledge.wiki.decisions.approvals import ApprovalAdapter, ApprovalEntry, ApprovalManifest
from parrot.knowledge.wiki.decisions.codec import canonical_json
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService
from parrot.knowledge.wiki.decisions.inventory import BATCH_MARKER_CATEGORY, batch_marker_id
from parrot.knowledge.wiki.decisions.models import (
    ADR_REVISION_CONFLICT,
    APPROVAL_UNVERIFIED,
    BATCH_PARTIAL,
    DecisionConfig,
    DecisionDiagnostic,
    DecisionError,
    DecisionRecord,
    _Strict,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.spec_entries import (
    DECISIONS_HEADING,
    SEED_HEADING,
    canonical_block_bytes,
    entries_to_records,
    parse_spec_decisions,
)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens


class PublishResult(_Strict):
    """Outcome of one ``BatchPublisher.publish`` call."""

    batch_id: str
    written: int = 0
    retired: int = 0
    skipped: int = 0
    status: Literal["published", "already-published", "refused"]
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)


def _marker_body(batch_id: str, state: str, decision_ids: list[str]) -> str:
    """Return the canonical JSON body of a batch marker."""
    return json.dumps(
        {"batch_id": batch_id, "state": state, "decision_ids": sorted(decision_ids)},
        sort_keys=True,
        separators=(",", ":"),
    )


def _marker_page(batch_id: str, state: str, decision_ids: list[str]) -> WikiPageRecord:
    """Build the single visibility-marker page for ``batch_id`` in ``state``."""
    body = _marker_body(batch_id, state, decision_ids)
    return WikiPageRecord(
        concept_id=batch_marker_id(batch_id),
        node_id=batch_marker_id(batch_id),
        title=f"ADR batch {batch_id}",
        category=BATCH_MARKER_CATEGORY,
        summary=state,
        body=body,
        token_count=estimate_tokens(body),
        origin="authored",
        content_hash=hashlib.sha1(body.encode("utf-8")).hexdigest(),  # noqa: S324 — identity, not authenticity
    )


def _parse_marker(page: dict | None) -> dict | None:
    """Decode a marker page body; ``None`` for a malformed or foreign page."""
    if page is None or page.get("category") != BATCH_MARKER_CATEGORY:
        return None
    try:
        body = json.loads(page.get("body") or "")
    except (TypeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


class BatchPublisher:
    """Publish one approved batch; retries converge to the same result."""

    def __init__(
        self,
        store: BaseWikiStore,
        root: Path,
        config: DecisionConfig,
        service: ConsequenceService,
        approvals: ApprovalManifest,
        adapter: ApprovalAdapter,
    ) -> None:
        """Bind the plane, repository root and the trust/replay collaborators.

        Args:
            store: Wiki plane receiving records and the batch marker.
            root: Repository root; approved spec paths are confined to it.
            config: Decision configuration (inventory bound).
            service: Consequence evaluator used for the ``replay`` check.
            approvals: Parsed approval manifest.
            adapter: Trust check for approval entries.
        """
        self.store, self.root, self.config, self.service = store, root, config, service
        self.approvals, self.adapter = approvals, adapter
        self.repo = DecisionRepository(store, max_records=config.max_records)
        self.logger = logging.getLogger(__name__)

    async def publish(self, batch_id: str) -> PublishResult:
        """Refuse on stale approval, non-pass replay, or partial batch.

        Args:
            batch_id: The approved batch to publish.

        Returns:
            ``published`` after a full write, ``already-published`` with zero
            writes when the marker is already flipped, ``refused`` otherwise.
        """
        # Phase 0 — verify approval, block digest and replay.
        verified = await self._verify(batch_id)
        if isinstance(verified, PublishResult):
            return verified
        entry, records = verified
        decision_ids = [record.decision_id for record in records]

        # Phase 1 — marker pending (or already published).
        marker_hash = await self._ensure_pending(batch_id, decision_ids)
        if isinstance(marker_hash, PublishResult):
            return (
                marker_hash.model_copy(update={"skipped": len(records)})
                if (marker_hash.status == "already-published")
                else marker_hash
            )

        # Phase 2 — records, each through its own CAS.
        try:
            written, skipped = await self._write_records(records)
        except DecisionError as exc:
            self.logger.warning("publish %s: record write failed; marker stays pending: %s", batch_id, exc)
            return self._refused(batch_id, exc.code, exc.message, entry.spec_path, exc.decision_id)

        # Phase 3 — one CAS flips visibility for the whole batch.
        published = _marker_page(batch_id, "published", decision_ids)
        if not await self.store.compare_and_swap_page(published, marker_hash):
            return self._refused(batch_id, BATCH_PARTIAL, "batch marker changed during publication", entry.spec_path)
        self.logger.info("publish %s: %d written, %d unchanged; marker published", batch_id, written, skipped)

        # Phase 4 — retirement strictly after the successor is visible.
        diagnostics: list[DecisionDiagnostic] = []
        retired = await self._retire_predecessors(records, diagnostics)
        return PublishResult(
            batch_id=batch_id,
            written=written,
            retired=retired,
            skipped=skipped,
            status="published",
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------ phases

    @staticmethod
    def _refused(
        batch_id: str,
        code: str,
        message: str,
        path: str | None = None,
        decision_id: str | None = None,
        extra: list[DecisionDiagnostic] | None = None,
    ) -> PublishResult:
        """Build a ``refused`` result with one leading diagnostic."""
        diagnostics = [DecisionDiagnostic(code=code, message=message, path=path, decision_id=decision_id)]
        return PublishResult(batch_id=batch_id, status="refused", diagnostics=[*diagnostics, *(extra or [])])

    async def _verify(self, batch_id: str) -> PublishResult | tuple[ApprovalEntry, list[DecisionRecord]]:
        """Phase 0: approval trust, approved-digest match and ``replay == pass``."""
        entries = [e for e in self.approvals.entries if e.batch_id == batch_id and e.kind in ("spec", "seed")]
        if not entries:
            return self._refused(batch_id, APPROVAL_UNVERIFIED, f"no spec/seed approval for batch {batch_id!r}")
        entry = entries[0]
        resolved_root = self.root.resolve()
        spec_file = (self.root / entry.spec_path).resolve()
        if not spec_file.is_relative_to(resolved_root):
            return self._refused(batch_id, APPROVAL_UNVERIFIED, "approved spec path escapes the root", entry.spec_path)
        try:
            spec_text = await asyncio.to_thread(spec_file.read_text, encoding="utf-8")
        except OSError as exc:
            return self._refused(batch_id, APPROVAL_UNVERIFIED, f"cannot read approved spec: {exc}", entry.spec_path)

        ok, verify_diagnostics = await self.adapter.verify(entry, spec_text=spec_text)
        if not ok:
            return self._refused(
                batch_id, APPROVAL_UNVERIFIED, "approval did not verify", entry.spec_path, extra=verify_diagnostics
            )

        heading = SEED_HEADING if entry.kind == "seed" else DECISIONS_HEADING
        block, _, parse_diagnostics = parse_spec_decisions(spec_text, source_path=entry.spec_path, heading=heading)
        if block is None:
            return self._refused(
                batch_id,
                APPROVAL_UNVERIFIED,
                "decisions block does not parse",
                entry.spec_path,
                extra=parse_diagnostics,
            )
        if (
            block.document_id != entry.document_id
            or hashlib.sha256(canonical_block_bytes(block)).hexdigest() != entry.block_sha256
        ):
            return self._refused(
                batch_id, APPROVAL_UNVERIFIED, "decisions block no longer matches the approved digest", entry.spec_path
            )

        report = await self.service.evaluate(Path(entry.spec_path), mode="replay")
        if report.status != "pass":
            return self._refused(
                batch_id,
                APPROVAL_UNVERIFIED,
                f"replay evaluation is {report.status!r}, not 'pass'",
                entry.spec_path,
                extra=list(report.diagnostics),
            )
        return entry, entries_to_records(block, source_path=entry.spec_path, batch_id=batch_id)

    async def _ensure_pending(self, batch_id: str, decision_ids: list[str]) -> str | PublishResult:
        """Phase 1: insert or confirm the ``pending`` marker; return its content hash."""
        page = await self.store.get_page(batch_marker_id(batch_id), include_body=True)
        if page is None:
            pending = _marker_page(batch_id, "pending", decision_ids)
            if not await self.store.compare_and_swap_page(pending, None):
                return self._refused(batch_id, BATCH_PARTIAL, "batch marker appeared concurrently")
            return pending.content_hash
        body = _parse_marker(page)
        state = body.get("state") if body else None
        if state == "published":
            return PublishResult(batch_id=batch_id, status="already-published")
        if state == "pending" and sorted(body.get("decision_ids") or []) == sorted(decision_ids):
            return page.get("content_hash") or _marker_page(batch_id, "pending", decision_ids).content_hash
        return self._refused(batch_id, BATCH_PARTIAL, f"batch marker is in an unknown state: {state!r}")

    async def _write_records(self, records: list[DecisionRecord]) -> tuple[int, int]:
        """Phase 2: write each record via CAS, skipping ones already identical."""
        written = skipped = 0
        for record in records:
            existing = await self.repo.get(record.decision_id)
            if existing is not None and canonical_json(existing[0]) == canonical_json(record):
                skipped += 1
                continue
            await self.repo.save(record, None if existing is None else existing[1])
            written += 1
        return written, skipped

    async def _retire_predecessors(
        self, records: list[DecisionRecord], diagnostics: list[DecisionDiagnostic] | None = None
    ) -> int:
        """Set lifecycle='retired' AND source_status='superseded' on each exact supersedes_refs predecessor (AC12, AC17)."""
        sink = diagnostics if diagnostics is not None else []
        retired = 0
        for record in records:
            for ref in record.supersedes_refs:
                got = await self.repo.get(ref.decision_id)
                if got is None:
                    sink.append(
                        DecisionDiagnostic(
                            code=ADR_REVISION_CONFLICT,
                            message="superseded predecessor not found",
                            decision_id=ref.decision_id,
                        )
                    )
                    continue
                predecessor, content_hash = got
                if predecessor.lifecycle == "retired" and predecessor.source_status == "superseded":
                    continue
                if predecessor.revision != ref.revision:
                    sink.append(
                        DecisionDiagnostic(
                            code=ADR_REVISION_CONFLICT,
                            message=f"predecessor is at revision {predecessor.revision}, batch supersedes {ref.revision}",
                            decision_id=ref.decision_id,
                        )
                    )
                    continue
                update: dict[str, object] = {"source_status": "superseded"}
                if predecessor.schema_version == 2:
                    update["lifecycle"] = "retired"
                try:
                    await self.repo.save(predecessor.model_copy(update=update), content_hash)
                except DecisionError as exc:
                    sink.append(DecisionDiagnostic(code=exc.code, message=exc.message, decision_id=ref.decision_id))
                    continue
                retired += 1
        return retired
