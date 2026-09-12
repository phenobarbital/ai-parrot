"""Durable per-attempt token telemetry for sdd-coder (FEAT-554).

Two append-only JSONL line kinds per attempt, joined on `attempt_uid`:
an `attempt` row written when the attempt returns, and one or more `outcome`
rows written as the attempt's fate is decided. Rows carry counters, ids and
timings ONLY — never prompt text, tool arguments or exception messages
(spec §10 R5).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord

logger = logging.getLogger(__name__)

MAX_LINE_BYTES: int = 8192
"""Upper bound for one serialized row, checked at write time.

Measured worst case with every string field at `max_length` and a full
101-turn series: ~3.6 KB (probe, 2026-09-12 —
artifacts/logs/feat554-row-size-probe-20260912.md). NOT a PIPE_BUF
requirement: 4096 governs pipes, not regular files, and POSIX makes an
`O_APPEND` write to a regular file atomic against other appenders at any
size. The budget keeps each row one bounded syscall and fails loudly if a
row ever grows unexpectedly.
"""

_SAFE_FEATURE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class AttemptUsageRow(BaseModel):
    """The `attempt` JSONL line. See spec §2 Data Models for the field list."""

    kind: Literal["attempt"] = "attempt"
    ts: str
    attempt_uid: str = Field(..., min_length=8, max_length=64)
    job_id: str = Field("", max_length=64)
    feature_id: str = Field(..., max_length=64)
    task_id: str = Field(..., max_length=64)
    attempt: int = Field(..., ge=1, le=3)
    seat_label: str = Field("", max_length=32)
    backend: str = Field("", max_length=32)
    configured_model: str = Field("", max_length=200)
    resolved_model: str = Field("", max_length=200)
    duration_s: float = 0.0
    turns: int = 0
    terminal: str = Field("completed", max_length=16)
    error_class: str = Field("", max_length=120)
    declared_files: Optional[int] = None
    declared_files_known: bool = False
    provider_input_tokens: Optional[int] = None
    provider_output_tokens: Optional[int] = None
    ledger_input_tokens: Optional[int] = None
    ledger_output_tokens: Optional[int] = None
    ledger_settled_estimate_input_tokens: Optional[int] = None
    ledger_released_estimate_tokens: Optional[int] = None
    ledger_uncertain_tokens: Optional[int] = None
    ledger_overrun_tokens: Optional[int] = None
    ledger_counting_methods: List[str] = Field(default_factory=list)
    ledger_accounting_complete: Optional[bool] = None
    enforcement: str = Field("observe", max_length=16)
    turns_with_unknown_usage: int = 0
    calibration_eligible: bool = False
    turn_series: List[Tuple[int, Optional[int], Optional[int]]] = Field(default_factory=list)


class OutcomeRow(BaseModel):
    """The `outcome` JSONL line. Several per `attempt_uid` are expected."""

    kind: Literal["outcome"] = "outcome"
    ts: str
    attempt_uid: str = Field(..., min_length=8, max_length=64)
    job_id: str = Field("", max_length=64)
    feature_id: str = Field(..., max_length=64)
    task_id: str = Field(..., max_length=64)
    attempt: int = Field(..., ge=1, le=3)
    event_seq: int = Field(..., ge=1)
    outcome: str = Field(..., max_length=32)
    conflict_file_count: int = 0
    unexpected_file_count: int = 0


def feature_file_name(feature_id: str) -> str:
    """Return `<feature_id>.jsonl`, or raise ValueError on an unsafe id.

    `feature_id` comes from a per-spec index header with no filename validator,
    so it is untrusted input to a path join (design research S6).
    """
    if not _SAFE_FEATURE_ID.match(feature_id or ""):
        raise ValueError(f"unsafe feature_id for a filename: {feature_id!r}")
    return f"{feature_id}.jsonl"


def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path:
    """Resolve and validate the telemetry root, or raise ValueError.

    An explicit absolute *configured* path wins. Otherwise the main checkout is
    derived from `git rev-parse --path-format=absolute --git-common-dir`, which
    points at the MAIN repository's `.git` even when called inside a linked
    worktree. A root that resolves under *worktree_base_path* is REFUSED: the
    dataset must outlive `git worktree remove`, and `conf.BASE_DIR` cannot be
    trusted to avoid it (spec §10 R7).
    """
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            raise ValueError(f"Configured telemetry path must be absolute: {configured!r}")
        resolved = path.resolve()
    else:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True,
                text=True,
                check=True,
            )
            git_common_dir = Path(res.stdout.strip()).resolve()
            # git_common_dir is usually /path/to/main/.git or similar.
            # Its parent is the main checkout root.
            main_checkout = git_common_dir.parent
            resolved = (main_checkout / "artifacts" / "logs" / "sdd-coder-usage").resolve()
        except Exception as e:
            raise ValueError(f"Failed to resolve main checkout via git: {e}") from e

    wt_base = Path(worktree_base_path).resolve()
    # Reject when the resolved path == worktree_base_path or is under it
    if resolved == wt_base or wt_base in resolved.parents:
        raise ValueError(f"Telemetry root {resolved} cannot be inside or equal to worktree base path {wt_base}")

    return resolved


def build_attempt_row(
    record: AttemptRecord, *, feature_id: str, job_id: str, task_id: str, declared_files: Optional[int]
) -> AttemptUsageRow:
    """Project an AttemptRecord onto a row by EXPLICIT ALLOWLIST.

    `task_id` is a required parameter, not sourced from `record` — unlike
    `feature_id`/`job_id`, `AttemptRecord` has no `task_id` field, and
    `AttemptUsageRow.task_id` is a required (non-defaulted) key field used
    for per-task correlation in the analysis. The caller (the engine, which
    always has the owning `PlannedTask` in scope) must supply it explicitly.

    Never a `model_dump()`: `AttemptRecord.error` holds the full exception
    string (verified: engine.py:583) and a field added to that model later must
    not leak into the dataset by default (spec §10 R5, AC-7). Only
    `error_class` crosses over.

    Sets `calibration_eligible` = ledger accounting complete AND no turn
    reported unknown usage — the one place that rule lives.
    """
    # Safely extract fields from record, handling potential missing attributes
    # (e.g. if record is from an un-migrated AttemptRecord or has new fields)
    attempt_uid = getattr(record, "attempt_uid", "")

    # `budget_report` is `BudgetReport.model_dump()` (set in llm.py's dispatch
    # `finally` block from `(await scope.ledger.report()).model_dump()`), whose
    # field names are UNPREFIXED (verified: parrot/models/token_budget.py:
    # 122-158 — `input_tokens`, `output_tokens`, `settled_estimate_input_tokens`,
    # `released_estimate_tokens`, `uncertain_tokens`, `overrun_tokens`,
    # `counting_methods`, `accounting_complete`). There is no "ledger_"-prefixed
    # key anywhere in that model — only this row's OWN fields carry the
    # `ledger_` prefix, to distinguish them from the row's `provider_*` fields
    # (spec §2 Data Models).
    budget_report = getattr(record, "budget_report", {}) or {}

    ledger_input_tokens = budget_report.get("input_tokens")
    ledger_output_tokens = budget_report.get("output_tokens")
    ledger_settled_estimate_input_tokens = budget_report.get("settled_estimate_input_tokens")
    ledger_released_estimate_tokens = budget_report.get("released_estimate_tokens")
    ledger_uncertain_tokens = budget_report.get("uncertain_tokens")
    ledger_overrun_tokens = budget_report.get("overrun_tokens")
    ledger_counting_methods = list(budget_report.get("counting_methods") or [])
    ledger_accounting_complete = budget_report.get("accounting_complete")
    # `enforcement` lives on the nested policy, not on the report itself
    # (verified: BudgetReport.policy: TokenBudgetPolicy; TokenBudgetPolicy.
    # enforcement — token_budget.py:31,128-158). Default "observe": every
    # scope this feature binds is observational by construction.
    _policy = budget_report.get("policy") or {}
    ledger_enforcement = _policy.get("enforcement", "observe") if isinstance(_policy, dict) else "observe"

    # Extract other fields
    turns_with_unknown_usage = getattr(record, "turns_with_unknown_usage", 0)

    # Compute calibration_eligible
    calibration_eligible = bool(ledger_accounting_complete and turns_with_unknown_usage == 0)

    # Build the row
    return AttemptUsageRow(
        ts=record.started_at,
        attempt_uid=attempt_uid,
        job_id=job_id,
        feature_id=feature_id,
        task_id=task_id,
        attempt=record.attempt,
        seat_label=record.seat_label,
        backend=record.backend,
        configured_model=record.model,  # configured_model maps to record.model
        resolved_model=getattr(record, "resolved_model", record.model),
        duration_s=record.duration_s,
        turns=getattr(record, "turns", 0),
        terminal=getattr(record, "terminal", "completed"),
        error_class=getattr(record, "error_class", ""),
        declared_files=declared_files,
        declared_files_known=getattr(record, "declared_files_known", False),
        provider_input_tokens=record.usage.get("input_tokens") if isinstance(record.usage, dict) else None,
        provider_output_tokens=record.usage.get("output_tokens") if isinstance(record.usage, dict) else None,
        ledger_input_tokens=ledger_input_tokens,
        ledger_output_tokens=ledger_output_tokens,
        ledger_settled_estimate_input_tokens=ledger_settled_estimate_input_tokens,
        ledger_released_estimate_tokens=ledger_released_estimate_tokens,
        ledger_uncertain_tokens=ledger_uncertain_tokens,
        ledger_overrun_tokens=ledger_overrun_tokens,
        ledger_counting_methods=ledger_counting_methods,
        ledger_accounting_complete=ledger_accounting_complete,
        enforcement=ledger_enforcement,
        turns_with_unknown_usage=turns_with_unknown_usage,
        calibration_eligible=calibration_eligible,
        turn_series=getattr(record, "turn_series", []),
    )


class CoderTelemetrySink:
    """One append-only JSONL file per feature under a validated root."""

    def __init__(self, root: str | Path, *, enabled: bool = True) -> None:
        self.logger = logging.getLogger(__name__)
        self._root = Path(root)
        self._enabled = enabled
        self._warned = False

    async def write_attempt(self, row: AttemptUsageRow) -> None:
        """Append one `attempt` row. Never raises."""
        await self._append(row.feature_id, row.model_dump_json())

    async def write_outcome(self, row: OutcomeRow) -> None:
        """Append one `outcome` row. Never raises."""
        await self._append(row.feature_id, row.model_dump_json())

    async def _append(self, feature_id: str, line: str) -> None:
        """Serialize-check then ONE os.write to an O_APPEND fd, off the loop.

        Runs the blocking write through `asyncio.to_thread`, the pattern
        `_journal` follows (verified: engine.py:472-488). Every failure is
        logged once at WARNING and dropped: a telemetry problem must never
        change a dispatch or a merge outcome (AC-11).
        """
        if not self._enabled:
            return

        try:
            # Check size bound
            payload = (line + "\n").encode("utf-8")
            if len(payload) > MAX_LINE_BYTES:
                self.logger.warning(
                    "Oversized telemetry row dropped: %d bytes (max %d)",
                    len(payload),
                    MAX_LINE_BYTES,
                )
                return

            # Resolve filename safely
            filename = feature_file_name(feature_id)
            file_path = self._root / filename

            def _write() -> None:
                # Ensure directory exists
                self._root.mkdir(parents=True, exist_ok=True)
                # Open with O_WRONLY | O_CREAT | O_APPEND
                fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    os.write(fd, payload)
                finally:
                    os.close(fd)

            import asyncio

            await asyncio.to_thread(_write)

        except Exception as e:
            if not self._warned:
                self.logger.warning("Telemetry write failed (suppressing future warnings): %s", e)
                self._warned = True
