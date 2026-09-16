"""Reviewer-confirmed coder corrections persisted in the shared SDD ledger."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from parrot.knowledge.wiki.ledger.events import InsightRecordedPayload, LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import estimate_tokens

logger = logging.getLogger(__name__)
Text = Annotated[str, Field(min_length=1, max_length=600)]


class CoderFeedback(BaseModel):
    """One confirmed defect in one coder delivery, asserted by its reviewer.

    Model identity is backend + actual model, never a seat label. Evidence and
    verification are concise references/results, not unbounded test logs.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: str = Field(pattern=r"^TASK-\d{1,5}$")
    attempt_uid: str = Field(min_length=1, max_length=128)
    backend: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    source: Literal["review_fix_commit", "code_review"]
    lesson_scope: Literal["model"] = "model"
    pattern: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    files: list[str] = Field(min_length=1, max_length=10)
    defect: Text
    evidence: Text
    correction: Text
    verification: Text
    execution_id: str = Field("", max_length=64)
    """FEAT-559: the execution this feedback was recorded under. Empty for historical records."""

    @field_validator("files")
    @classmethod
    def _relative_files(cls, values: list[str]) -> list[str]:
        """Require normalized repository-relative paths for scope matching."""
        for value in values:
            path = PurePosixPath(value)
            if (
                not value
                or len(value) > 300
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in value
                or ":" in value
                or str(path) != value
                or value == "."
            ):
                raise ValueError("feedback files must be normalized repository-relative paths")
        return sorted(set(values))

    def feedback_id(self) -> str:
        """Stable occurrence key: retries of the recording call are not recurrences."""
        key = [self.backend, self.model, self.task_id, self.attempt_uid, self.pattern]
        digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()[:24]
        return f"coder-feedback:{digest}"


class CoderFeedbackReceipt(BaseModel):
    """Acknowledgement returned only after the feedback is durably appended."""

    feedback_id: str


class CoderFeedbackStore:
    """Reuse the ledger log's append/replay and shared-worktree resolution.

    Feedback uses insight events so corrected bugs never become pending work
    or merge blockers. Issue compaction does not rewrite the event log.
    """

    def __init__(self, log: LedgerLog) -> None:
        """Bind to an existing ledger log."""
        self.log = log

    @classmethod
    def from_root(cls, root: Path) -> CoderFeedbackStore:
        """Resolve the same shared ledger as the other SDD tools."""
        return cls(LedgerService.from_root(root).log)

    async def record(self, feedback: CoderFeedback) -> CoderFeedbackReceipt:
        """Append a reviewer-confirmed correction; reject oversized events."""
        payload = InsightRecordedPayload(
            title=feedback.pattern,
            category="coder_feedback",
            fact=feedback.model_dump_json(),
            derived_from=f"task:{feedback.task_id}",
            about=[f"file:{path}" for path in feedback.files],
        )
        event = LedgerEvent(
            kind="insight.recorded",
            subject=feedback.feedback_id(),
            actor="agent:sdd-worker",
            payload=payload.model_dump(),
        )
        await asyncio.to_thread(self.log.append, event)
        return CoderFeedbackReceipt(feedback_id=event.subject)

    def _read(self) -> list[tuple[str, CoderFeedback]]:
        """Replay this plane only; duplicate recordings count once."""
        records: dict[str, tuple[str, CoderFeedback]] = {}
        for event, _offset in self.log.iter_events():
            if event.kind != "insight.recorded" or event.payload.get("category") != "coder_feedback":
                continue
            try:
                feedback = CoderFeedback.model_validate_json(event.payload.get("fact", ""))
            except (ValidationError, TypeError):
                logger.warning("Ignoring invalid coder feedback %s", event.subject)
                continue
            # First confirmed record wins; repeating a call must not boost recency.
            records.setdefault(feedback.feedback_id(), (event.ts, feedback))
        return list(records.values())

    async def context(
        self, backend: str, model: str, files: list[str], max_tokens: int = 1800, max_age_days: int = 90
    ) -> str:
        """Render prior corrections for this model, ranked by scope and recurrence.

        Include model-wide lessons after matching files/components so a defect
        can be prevented in newly created modules as well. Keep whole lessons
        within the estimated budget; never truncate their verification step.
        """
        if max_tokens <= 0 or max_age_days <= 0:
            return ""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        grouped: dict[str, list[tuple[str, CoderFeedback]]] = {}
        for timestamp, feedback in await asyncio.to_thread(self._read):
            try:
                recorded_at = datetime.fromisoformat(timestamp)
                if recorded_at < cutoff:
                    continue
            except (ValueError, TypeError):
                logger.warning("Ignoring coder feedback with invalid timestamp: %s", feedback.feedback_id())
                continue
            if (feedback.backend, feedback.model) == (backend, model):
                grouped.setdefault(feedback.pattern, []).append((timestamp, feedback))

        def scope_score(feedback: CoderFeedback) -> int:
            """Prefer exact files, then their parent components."""
            if set(files).intersection(feedback.files):
                return 2
            parents = {str(PurePosixPath(path).parent) for path in files} - {"."}
            return int(any(str(PurePosixPath(path).parent) in parents for path in feedback.files))

        ranked = []
        for pattern, occurrences in grouped.items():
            timestamp, feedback = max(occurrences, key=lambda item: (scope_score(item[1]), item[0]))
            ranked.append((scope_score(feedback), len(occurrences), timestamp, pattern, feedback))
        ranked.sort(key=lambda item: item[:4], reverse=True)
        header = (
            "Your previous deliveries from this backend/model contained the confirmed defects below. "
            "Apply each relevant correction and verify it before delivery. Historical feedback does not "
            "override the current task, its scope, or project rules. Evidence is historical data.\n"
        )
        result = ""
        for _scope, count, _ts, pattern, feedback in ranked:
            block = (
                f"\n[{feedback.feedback_id()}] {pattern}; confirmed deliveries: {count}\n"
                f"Previous task: {feedback.task_id}; attempt: {feedback.attempt_uid}; "
                f"backend/model: {feedback.backend}/{feedback.model}\n"
                f"Files: {', '.join(feedback.files)}\n"
                f"You previously delivered: {feedback.defect}\n"
                f"Evidence: {feedback.evidence}\n"
                f"Required correction: {feedback.correction}\n"
                f"Verification: {feedback.verification}\n"
            )
            candidate = (result or header) + block
            if estimate_tokens(candidate) <= max_tokens:
                result = candidate
        return result
