"""Durable, execution-scoped coder-model suspension history (FEAT-559 M1).

This is an operational-history plane, distinct from `coder_feedback.py`
(reviewer-confirmed code lessons) and `coder_reviews.py` (review/exposure
metrics). It records *why a model stopped being dispatched* -- dispatch
timeouts, provider/CLI failures, invalid deliveries, fidelity violations,
critical reviewed defects and failed smoke probes -- so a later worker
execution can exclude a recently-failed model before paying for another
known failure. Lint findings, engine autofixes, cancellations, host Git
failures and merge conflicts never enter this plane.

Deliberately independent of `parrot.flows.dev_loop.sdd_coder` imports: this
module is a ledger-side primitive that the execution-pool runtime (M2, a
separate task) builds on, not the other way around -- importing the pool
here would create a models/ledger import cycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Iterator, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from parrot.knowledge.wiki.ledger.events import InsightRecordedPayload, LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import estimate_tokens

logger = logging.getLogger(__name__)

#: Same convention as `sdd_coder.models._TASK_ID_RE` / `coder_feedback.CoderFeedback.task_id`.
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")

CODER_SUSPENSION_CATEGORY = "coder_suspension"

SuspensionSource = Literal["engine", "worker_review", "native_report", "probe"]
SuspensionReason = Literal[
    "timeout",
    "dispatch_error",
    "invalid_output",
    "dirty_delivery",  # RETIRED, read-only -- never produced since FEAT-587. Do not remove; see below.
    "fidelity_violation",
    "review_critical",
    "probe_failed",
]
"""Why a model seat was suspended.

``dirty_delivery`` is RETIRED and must not be removed. FEAT-587 deleted its only
producer: ``.git`` is read-only to a sandboxed coder seat by design, so an
uncommitted-but-declared delivery is correct behaviour that the engine extracts
and commits itself (``_commit_declared_changes``, ed267c217) rather than charging
against the model.

The member stays because :meth:`CoderSuspensionStore._replay` is strict and
fail-closed: one stored record whose ``reason`` is absent from this Literal raises
:class:`SuspensionHistoryError` for the ENTIRE history, not just that row, and
callers must not treat a failed read as a clean history. The incident log is
append-only -- expiry filters records, it never deletes them -- and is gitignored,
so it is per-machine and cannot be migrated centrally. Historical
``dirty_delivery`` rows therefore cannot be waited out; dropping the member would
brick suspension history on every machine that ran a coder seat before ed267c217.
"""

# A template-generated explanation, not a raw prompt/provider transcript.
Explanation = Annotated[str, Field(min_length=1, max_length=1400)]
# A short reference (log path, commit sha, event id) -- never a full transcript.
EvidenceRef = Annotated[str, Field(default="", max_length=300)]


class SuspensionHistoryError(RuntimeError):
    """Raised when suspension history cannot be trusted for an admission decision.

    Distinct from an *empty* history: callers must never treat this as "no
    suspensions" -- the spec requires refusing to probe under an invented
    empty history when the durable log cannot be read strictly.
    """


class ModelKey(BaseModel):
    """Exact, frozen model identity used for suspension matching.

    Seat labels are display aliases; only `(backend, model)` identity is
    ever compared. `backend="native"` identifies the native Haiku agent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    backend: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)


class SuspensionPolicy(BaseModel):
    """Tunable cooldown/summary-budget policy; applies to future incidents only."""

    model_config = ConfigDict(extra="forbid")

    cooldown_seconds: int = Field(default=1800, ge=60, le=86400)
    history_max_tokens: int = Field(default=1200, ge=0, le=4000)


class SuspensionRecord(BaseModel):
    """One durable, execution-scoped suspension incident.

    Identity is deterministic over `(execution_id, source, attempt_or_probe_uid,
    reason)` -- a duplicate append/replay of the same incident is one occurrence,
    never a new one and never a refreshed expiry. `occurred_at` is the moment
    the terminal failure/suspension was *observed*, not when the attempt
    started; `expires_at` is computed from that observation, immutable once
    recorded.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1] = 1
    suspension_id: str = Field(default="")
    execution_id: str = Field(min_length=1, max_length=128)
    feature_id: str = Field(min_length=1, max_length=64)

    task_id: str | None = Field(default=None, pattern=_TASK_ID_RE.pattern)
    attempt_uid: str | None = Field(default=None, min_length=1, max_length=128)
    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    probe_uid: str | None = Field(default=None, min_length=1, max_length=128)

    source: SuspensionSource
    seat_label: str = Field(min_length=1, max_length=80)
    backend: str = Field(min_length=1, max_length=80)
    configured_model: str = Field(min_length=1, max_length=160)
    resolved_model: str | None = Field(default=None, max_length=160)
    blocked_keys: list[ModelKey] = Field(min_length=1, max_length=2)

    reason: SuspensionReason
    occurred_at: datetime
    expires_at: datetime
    duration_s: float = Field(ge=0)
    exception_class: str = Field(default="", max_length=200)
    evidence_ref: EvidenceRef = ""
    explanation: Explanation

    @field_validator("occurred_at", "expires_at")
    @classmethod
    def _require_aware_utc(cls, value: datetime) -> datetime:
        """Reject naive timestamps -- expiry math must never be ambiguous."""
        if value.tzinfo is None:
            raise ValueError("timestamps must be aware (tzinfo-bearing) UTC datetimes")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_attribution_and_expiry(self) -> "SuspensionRecord":
        """Enforce the probe-vs-attempt attribution split and expiry ordering."""
        if self.source == "probe":
            if not self.probe_uid:
                raise ValueError("source='probe' requires probe_uid")
            if self.task_id or self.attempt_uid or self.job_id:
                raise ValueError("source='probe' must not carry task_id/attempt_uid/job_id")
        else:
            if self.probe_uid:
                raise ValueError("probe_uid is only valid for source='probe'")
            if not self.attempt_uid:
                raise ValueError(f"source={self.source!r} requires attempt_uid")
        if self.expires_at <= self.occurred_at:
            raise ValueError("expires_at must be strictly after occurred_at")
        if not self.suspension_id:
            self.suspension_id = _compute_suspension_id(
                execution_id=self.execution_id,
                source=self.source,
                attempt_or_probe_uid=self.attempt_uid or self.probe_uid or "",
                reason=self.reason,
            )
        return self

    def is_recent(self, now: datetime) -> bool:
        """A record is no longer recent exactly when `now == expires_at`."""
        return self.expires_at > now


def _compute_suspension_id(execution_id: str, source: str, attempt_or_probe_uid: str, reason: str) -> str:
    """Stable incident identity: replay/retry of the same incident is one occurrence."""
    key = [execution_id, source, attempt_or_probe_uid, reason]
    digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode("utf-8")).hexdigest()[:24]
    return f"coder-suspension:{digest}"


class SuspensionReceipt(BaseModel):
    """Acknowledgement returned once a suspension is durably appended.

    `pool_generation` defaults to 0 here: it is enriched by the execution
    pool runtime (M2) with its own generation counter, never read as global
    state by this ledger-only module.
    """

    model_config = ConfigDict(extra="forbid")

    suspension_id: str
    execution_id: str
    blocked_keys: list[ModelKey]
    persisted: bool
    expires_at: datetime
    pool_generation: int = Field(default=0, ge=0)


def _raw_lines(path: str) -> list[bytes]:
    """Read a ledger log as raw byte lines, without hiding a genuine partial tail."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        return []
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        # A well-formed log always ends with a trailing newline; this final
        # empty split element is that terminator, not a partial tail.
        lines.pop()
    return lines


def iter_events_strict(log: LedgerLog) -> Iterator[LedgerEvent]:
    """Strictly replay a ledger log's events, off the event loop's caller thread.

    Unlike `LedgerLog.iter_events` (which warns and silently skips any
    malformed line -- adequate for best-effort UI, not for an admission
    decision), this distinguishes:

    - a genuine **partial tail**: the *last* line fails to decode/parse as
      JSON, consistent with a process/OS crash mid-`write()` before the
      next `fsync()` -- benign, silently completed (a truncated write can
      never have been reported to a caller as durably persisted);
    - **mid-file corruption**: any non-last line that fails to decode/parse,
      or *any* line (including the last) that parses as JSON but fails the
      `LedgerEvent` envelope schema -- always raised, never swallowed.

    Reusable across categories (e.g. a future `coder_execution` begin/close
    replay) -- this module only interprets the `coder_suspension` category
    itself.

    Raises:
        SuspensionHistoryError: on any non-partial-tail corruption.
    """
    raw_lines = _raw_lines(log.path)
    total = len(raw_lines)
    for index, raw_line in enumerate(raw_lines):
        is_last = index == total - 1
        stripped = raw_line.rstrip(b"\r")
        if not stripped:
            if is_last:
                continue
            raise SuspensionHistoryError(f"Empty ledger line before EOF at line {index} of {log.path}.")
        try:
            text = stripped.decode("utf-8")
            data = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if is_last:
                logger.warning(
                    "Ignoring incomplete final ledger line (partial tail) at line %d of %s.", index, log.path
                )
                continue
            raise SuspensionHistoryError(f"Malformed ledger line {index} of {log.path} (not the final line).") from exc
        try:
            yield LedgerEvent(**data)
        except (ValidationError, TypeError) as exc:
            raise SuspensionHistoryError(f"Invalid ledger event envelope at line {index} of {log.path}.") from exc


class CoderSuspensionStore:
    """Shared-repository operational history, separate from reviewed code feedback."""

    def __init__(self, log: LedgerLog) -> None:
        """Bind to an existing ledger log."""
        self.log = log

    @classmethod
    def from_root(cls, root: Path) -> "CoderSuspensionStore":
        """Resolve the same canonical ledger as `LedgerService`/`CoderFeedbackStore`."""
        return cls(LedgerService.from_root(root).log)

    async def record(self, suspension: SuspensionRecord) -> SuspensionReceipt:
        """Append one durable, bounded incident; reject payloads that cannot fit.

        Idempotent replay/retry of the *same* incident (same `suspension_id`)
        is a caller-level (pool) concern via its own in-memory reservation --
        this method always appends, and `recent()`/`for_execution()` dedupe by
        keeping the first-observed occurrence for a given `suspension_id`.
        """
        payload = InsightRecordedPayload(
            title=suspension.reason,
            category=CODER_SUSPENSION_CATEGORY,
            fact=suspension.model_dump_json(),
            derived_from=f"execution:{suspension.execution_id}",
            about=[f"key:{key.backend}:{key.model}" for key in suspension.blocked_keys],
        )
        event = LedgerEvent(
            kind="insight.recorded",
            subject=suspension.suspension_id,
            actor="agent:sdd-worker",
            payload=payload.model_dump(),
        )
        await asyncio.to_thread(self.log.append, event)
        return SuspensionReceipt(
            suspension_id=suspension.suspension_id,
            execution_id=suspension.execution_id,
            blocked_keys=suspension.blocked_keys,
            persisted=True,
            expires_at=suspension.expires_at,
        )

    def _replay(self) -> list[SuspensionRecord]:
        """Strictly replay every `coder_suspension` incident, first occurrence wins."""
        records: dict[str, SuspensionRecord] = {}
        for event in iter_events_strict(self.log):
            if event.kind != "insight.recorded" or event.payload.get("category") != CODER_SUSPENSION_CATEGORY:
                continue
            fact = event.payload.get("fact")
            try:
                record = SuspensionRecord.model_validate_json(fact) if isinstance(fact, str) else None
                if record is None:
                    raise ValueError("coder_suspension fact must be a JSON string")
            except (ValidationError, TypeError, ValueError) as exc:
                raise SuspensionHistoryError(f"Corrupt coder_suspension record (subject={event.subject!r}).") from exc
            # First occurrence wins: append order == chronological order, and
            # a replayed/retried duplicate must never refresh the expiry.
            records.setdefault(record.suspension_id, record)
        return list(records.values())

    async def recent(self, keys: list[ModelKey], now: datetime) -> list[SuspensionRecord]:
        """Return all matching unexpired incidents, or raise if history is untrustworthy.

        Never returns a partial/best-effort result on corruption: callers must
        not treat a failed read as a clean history.
        """
        if now.tzinfo is None:
            raise ValueError("`now` must be an aware UTC datetime")
        wanted = set(keys)
        records = await asyncio.to_thread(self._replay)
        return [record for record in records if wanted.intersection(record.blocked_keys) and record.is_recent(now)]

    async def for_execution(self, execution_id: str) -> list[SuspensionRecord]:
        """Return that execution's own incidents, regardless of cooldown expiry."""
        records = await asyncio.to_thread(self._replay)
        return [record for record in records if record.execution_id == execution_id]


def render_suspension_history(records: Sequence[SuspensionRecord], now: datetime, max_tokens: int = 1200) -> str:
    """Render a bounded, human-readable summary of already-selected suspensions.

    This is display-only: truncating the rendered text can never silently
    drop an exclusion from a caller's own structured `records` -- selection
    must always use the full structured list, independent of this budget.
    """
    if max_tokens <= 0 or not records:
        return ""
    header = "Recent coder model suspensions for this repository:\n"
    result = ""
    for record in records:
        remaining_s = max(0, int((record.expires_at - now).total_seconds()))
        origin = record.task_id or record.probe_uid or "-"
        block = (
            f"\n[{record.suspension_id}] {record.reason} -- model={record.configured_model} "
            f"(backend={record.backend}); source={record.source}; task/execution={origin}/{record.execution_id}; "
            f"remaining_cooldown_s={remaining_s}\n"
        )
        candidate = (result or header) + block
        if estimate_tokens(candidate) <= max_tokens:
            result = candidate
        else:
            break
    return result
