"""Reviewed-delivery measurements for evaluating coder feedback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackReceipt
from parrot.knowledge.wiki.ledger.events import InsightRecordedPayload, LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog

logger = logging.getLogger(__name__)
CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class CoderReview(BaseModel):
    """Review outcome including zero-fix deliveries, supplied by the worker.

    fix_commits includes only reviewer-confirmed corrections, never engine lint
    commits. The engine checks commit subjects and attempt attribution.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task_id: str = Field(pattern=r"^TASK-\d{1,5}$")
    attempt_uid: str = Field(min_length=1, max_length=128)
    backend: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    fix_commits: list[CommitSha] = Field(max_length=30)
    review_evidence: str = Field(min_length=1, max_length=600)
    execution_id: str = Field("", max_length=64)
    """FEAT-559: the execution this review was recorded under. Empty for historical records."""


class CoderReviewMeasurement(CoderReview):
    """Exposure information added by the engine, never asserted by the worker."""

    exposure: Literal["with_feedback", "without_feedback", "unavailable"]
    feedback_tokens: int = Field(ge=0)


class CoderReviewMetrics(BaseModel):
    """Descriptive rates by backend/model and feedback exposure."""

    backend: str
    model: str
    exposure: str
    reviewed_tasks: int
    reviewed_attempts: int
    correction_commits: int
    correction_commits_per_task: float
    task_correction_commits: dict[str, int]
    mean_feedback_tokens: float


class CoderReviewReport(BaseModel):
    """Measured review cohorts; missing historical data is never treated as zero."""

    rows: list[CoderReviewMetrics]
    limitation: str = (
        "Only recorded completed reviews are counted. without_feedback is an observed baseline, not inferred "
        "historical data. Cohorts can differ in task difficulty; these rates do not establish causality."
    )


class CoderReviewStore:
    """Persist/replay review outcomes on the same immutable SDD ledger."""

    def __init__(self, log: LedgerLog) -> None:
        """Bind to the shared ledger log."""
        self.log = log

    async def record(self, review: CoderReviewMeasurement) -> CoderFeedbackReceipt:
        """Record the completed review; subsequent records update its measurement."""
        key = json.dumps([review.backend, review.model, review.task_id, review.attempt_uid])
        subject = "coder-review:" + hashlib.sha256(key.encode()).hexdigest()[:24]
        payload = InsightRecordedPayload(
            title=f"Review {review.task_id}",
            category="coder_review",
            fact=review.model_dump_json(),
            derived_from=f"task:{review.task_id}",
        )
        event = LedgerEvent(
            kind="insight.recorded", subject=subject, actor="agent:sdd-worker", payload=payload.model_dump()
        )
        await asyncio.to_thread(self.log.append, event)
        return CoderFeedbackReceipt(feedback_id=subject)

    def _report(self) -> CoderReviewReport:
        """Aggregate complete reviews, deduplicating attempts and fix SHAs."""
        records: dict[tuple[str, str, str, str], CoderReviewMeasurement] = {}
        for event, _offset in self.log.iter_events():
            if event.kind != "insight.recorded" or event.payload.get("category") != "coder_review":
                continue
            try:
                review = CoderReviewMeasurement.model_validate_json(event.payload.get("fact", ""))
            except (ValidationError, TypeError):
                logger.warning("Ignoring invalid coder review %s", event.subject)
                continue
            records[(review.backend, review.model, review.task_id, review.attempt_uid)] = review
        groups: dict[tuple[str, str, str], list[CoderReviewMeasurement]] = {}
        for review in records.values():
            groups.setdefault((review.backend, review.model, review.exposure), []).append(review)
        rows = []
        for (backend, model, exposure), reviews in sorted(groups.items()):
            tasks = len({review.task_id for review in reviews})
            commits = len({sha for review in reviews for sha in review.fix_commits})
            rows.append(
                CoderReviewMetrics(
                    backend=backend,
                    model=model,
                    exposure=exposure,
                    reviewed_tasks=tasks,
                    reviewed_attempts=len(reviews),
                    correction_commits=commits,
                    correction_commits_per_task=commits / tasks,
                    task_correction_commits={
                        task_id: len(
                            {sha for review in reviews if review.task_id == task_id for sha in review.fix_commits}
                        )
                        for task_id in sorted({review.task_id for review in reviews})
                    },
                    mean_feedback_tokens=sum(review.feedback_tokens for review in reviews) / len(reviews),
                )
            )
        return CoderReviewReport(rows=rows)

    async def report(self) -> CoderReviewReport:
        """Render rates off the event loop; retain history after lessons expire."""
        return await asyncio.to_thread(self._report)
