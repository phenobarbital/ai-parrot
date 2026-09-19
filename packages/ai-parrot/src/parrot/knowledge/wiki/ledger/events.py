import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Final, Literal
from pydantic import BaseModel, Field

LedgerEventKind = Literal[
    "issue.opened",
    "issue.claimed",
    "issue.acknowledged",
    "issue.closed",
    "issue.superseded",
    "issue.unclaimed",
    "issue.linked",
    "task.started",
    "task.closed",
    "spec.registered",
    "insight.recorded",
    "insight.superseded",
]

IssueKind = Literal["bug", "tech_debt", "feature_gap", "vulnerability"]
IssueSeverity = Literal["critical", "major", "minor", "low"]
IssueStatus = Literal["open", "claimed", "closed", "superseded"]

SEVERITY_ORDER: Final[dict[IssueSeverity, int]] = {"critical": 0, "major": 1, "minor": 2, "low": 3}
"""Canonical severity order, most urgent first (FEAT-572, design research S6).

Defined HERE, beside the Literal it orders, so ``LedgerService.ready_work()``,
the fix planner, ``wikitoolkit ledger ready`` and the MCP ``ledger_ready`` tool
all share one key. Never redefine it in a consumer — import it.
"""


class IssueOpenedPayload(BaseModel):
    title: str
    body: str
    kind: IssueKind = "bug"
    severity: IssueSeverity = "minor"
    discovered_from: str = Field(description="Source task/spec/review, e.g. task:TASK-3200, review:TASK-3200")
    about: list[str] = Field(default_factory=list, description="Target code symbols/files, e.g. sym:pkg/mod.py#Func")


class IssueClaimedPayload(BaseModel):
    claimed_by: str = Field(description="Agent or task claiming work, e.g. task:TASK-3205")


class IssueUnclaimedPayload(BaseModel):
    """Release a claim so the issue returns to the ready pool (FEAT-572).

    Reduces ``claimed -> open`` and clears ``claimed_by``; a no-op on any
    other status. Mirrors :class:`IssueClaimedPayload`.
    """

    unclaimed_by: str = Field(description="Actor releasing the claim, e.g. agent:sdd-fix")
    reason: str


class IssueAcknowledgedPayload(BaseModel):
    """Explicit acceptance that an open critical issue must not block a merge.

    Does NOT change `status`; the index sets `acknowledged=True` on the issue page.
    """

    acknowledged_by: str = Field(description="Must be a human actor, e.g. human:jesus")
    reason: str


class IssueClosedPayload(BaseModel):
    reason: str
    closed_by: str
    resolved_by: str | None = None  # e.g. task:TASK-3205


class InsightRecordedPayload(BaseModel):
    fact: str
    title: str
    category: str = "note"
    derived_from: str = Field(description="Originating task, review, or spec id")
    about: list[str] = Field(default_factory=list, description="Related symbol or file ids")


def canonical_json_dumps(obj: Any) -> str:
    """Serialize an object to a canonical JSON string with sorted keys and no extra whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_event_id(kind: str, subject: str, actor: str, ts: str, payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-1 hash hex digest (first 12 chars) for an event."""
    canonical_payload = canonical_json_dumps(payload)
    raw_str = f"{kind}|{subject}|{actor}|{ts}|{canonical_payload}"
    sha1 = hashlib.sha1(raw_str.encode("utf-8")).hexdigest()
    return sha1[:12]


def compute_issue_id(kind: str, title: str, discovered_from: str) -> str:
    """Compute a deterministic issue ID (first 12 chars of SHA-1) based on kind, title, and discovery source."""
    raw_str = f"{kind}|{title}|{discovered_from}"
    sha1 = hashlib.sha1(raw_str.encode("utf-8")).hexdigest()
    return f"issue:{sha1[:12]}"


class LedgerEvent(BaseModel):
    """Immutable single-line event serialized into events.jsonl."""

    event_id: str = Field(default="", description="SHA-1 hash hex digest (first 12 chars)")
    kind: LedgerEventKind
    subject: str = Field(description="Target identifier, e.g. issue:3f8a1c9e, task:TASK-1234, spec:FEAT-566")
    actor: str = Field(description="Author identifier, e.g. agent:codex, human:jesus")
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Compute event_id if not provided."""
        if not self.event_id:
            self.event_id = compute_event_id(
                kind=self.kind,
                subject=self.subject,
                actor=self.actor,
                ts=self.ts,
                payload=self.payload,
            )
