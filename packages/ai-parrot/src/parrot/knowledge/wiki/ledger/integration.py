"""Canonical integration of sealed ledger batches into origin/dev (FEAT-758 Module 2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
from parrot.knowledge.wiki.ledger.outbox import LedgerDeliveryConflict, StrictLedgerReadError, read_strict_events
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import shared_log_files

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"closed", "superseded"})


class MergePlan(BaseModel):
    """Events to append to the destination log, in captured order."""

    new_lines: list[bytes] = Field(default_factory=list)
    new_events: list[LedgerEvent] = Field(default_factory=list)
    duplicates: int = 0


def _canonical(event: LedgerEvent) -> str:
    """Return the canonical serialized representation of an event."""
    return canonical_json_dumps(event.model_dump())


def read_logical_log(repo_root: Path) -> list[tuple[bytes, LedgerEvent]]:
    """Strictly read archives and current log in ``shared_log_files`` order."""
    result: list[tuple[bytes, LedgerEvent]] = []
    known: dict[str, str] = {}
    for path in shared_log_files(repo_root):
        strict_read = read_strict_events(path)
        if strict_read.truncated_tail:
            raise StrictLedgerReadError(f"{path}: committed log has a truncated tail")
        for raw_line, event in zip(strict_read.raw_lines, strict_read.events, strict=True):
            canonical = _canonical(event)
            previous = known.get(event.event_id)
            if previous is None:
                known[event.event_id] = canonical
                result.append((raw_line, event))
            elif previous != canonical:
                raise StrictLedgerReadError(f"event {event.event_id!r} has conflicting canonical content")
    return result


def merge_batch(remote: Sequence[tuple[bytes, LedgerEvent]], batch: Sequence[tuple[bytes, LedgerEvent]]) -> MergePlan:
    """Return batch events absent from ``remote``; reject equal ids with different content."""
    remote_by_id = {event.event_id: _canonical(event) for _, event in remote}
    plan = MergePlan()
    for raw_line, event in batch:
        remote_content = remote_by_id.get(event.event_id)
        if remote_content is None:
            plan.new_lines.append(raw_line)
            plan.new_events.append(event)
        elif remote_content == _canonical(event):
            plan.duplicates += 1
        else:
            raise StrictLedgerReadError(f"event {event.event_id!r} has conflicting canonical content")
    return plan


def find_transition_conflicts(
    remote: Sequence[LedgerEvent], new: Sequence[LedgerEvent]
) -> list[LedgerDeliveryConflict]:
    """Replay ``remote`` then check each ``new`` issue event against its preceding state."""
    state: dict[str, dict[str, Any]] = {}
    conflicts: list[LedgerDeliveryConflict] = []
    for event in remote:
        _apply(state, event)

    for event in new:
        if event.kind.startswith("issue."):
            current = state.get(event.subject)
            reason: str | None = None
            if event.kind != "issue.opened" and current is None:
                reason = "missing-predecessor"
            elif event.kind == "issue.claimed" and current["status"] == "claimed":
                if current["claimed_by"] != event.payload.get("claimed_by"):
                    reason = "competing-claim"
            elif event.kind == "issue.closed" and current["status"] in TERMINAL:
                evidence = (
                    event.payload.get("closed_by"),
                    event.payload.get("reason"),
                    event.payload.get("resolved_by"),
                )
                if current["close"] != evidence:
                    reason = "conflicting-close"
            elif event.kind == "issue.unclaimed" and current["status"] in TERMINAL:
                reason = "unclaim-terminal"

            if reason is not None:
                conflicts.append(LedgerDeliveryConflict(event_id=event.event_id, subject=event.subject, reason=reason))
        _apply(state, event)
    return conflicts


def _apply(state: dict[str, dict[str, Any]], event: LedgerEvent) -> None:
    """Mirror the live reducer for status, claim owner, and close evidence."""
    if not event.kind.startswith("issue."):
        return
    current = state.get(event.subject)
    if event.kind == "issue.opened":
        if current is None:
            state[event.subject] = {"status": "open", "claimed_by": None, "close": None}
    elif event.kind == "issue.claimed" and current is not None and current["status"] == "open":
        current["status"] = "claimed"
        current["claimed_by"] = event.payload.get("claimed_by")
    elif event.kind == "issue.unclaimed" and current is not None and current["status"] == "claimed":
        current["status"] = "open"
        current["claimed_by"] = None
    elif event.kind == "issue.closed" and current is not None:
        current["status"] = "closed"
        current["close"] = (
            event.payload.get("closed_by"),
            event.payload.get("reason"),
            event.payload.get("resolved_by"),
        )
    elif event.kind == "issue.superseded" and current is not None:
        current["status"] = "superseded"


async def build_scratch_snapshot(merged: Sequence[bytes], *, scratch_dir: Path, dest: Path) -> bool:
    """Replay ``merged`` raw lines in an isolated ledger and export ``dest``."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    data = b"".join(line + b"\n" for line in merged)
    await asyncio.to_thread((scratch_dir / "events.jsonl").write_bytes, data)
    service = LedgerService.from_dir(scratch_dir)
    await service.index.sync()
    changed = await service.export_snapshot(dest, reconcile=True)
    logger.debug("Scratch ledger snapshot %s (changed=%s) from %d events", dest, changed, len(merged))
    return changed
