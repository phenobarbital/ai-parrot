"""Pydantic v2 contracts for the dev-loop orchestration flow (FEAT-129).

This module is the foundation for ``parrot.flows.dev_loop``. Every other
sub-module (dispatcher, nodes, flow factory, streaming multiplexer)
imports its data structures from here.

The module intentionally has **zero internal dependencies** beyond the
Pydantic v2 runtime. In particular, it MUST NOT import anything from
``claude_agent_sdk`` at top level so that ``import parrot.flows.dev_loop``
succeeds even when the optional ``[claude-agent]`` extra is not installed.

See ``sdd/specs/dev-loop-orchestration.spec.md`` §2 "Data Models" for the
authoritative contracts.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────
# Acceptance criteria (discriminated union)
# ─────────────────────────────────────────────────────────────────────


class _AcceptanceCriterionBase(BaseModel):
    """Common fields shared by every acceptance criterion variant."""

    name: str = Field(..., description="Human-readable criterion identifier.")
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    expected_exit_code: int = Field(default=0)


class FlowtaskCriterion(_AcceptanceCriterionBase):
    """Run a Flowtask YAML/JSON pipeline and assert its exit code."""

    kind: Literal["flowtask"] = "flowtask"
    task_path: str = Field(
        ...,
        description="Relative path to the flowtask, e.g. 'etl/customers/sync.yaml'.",
    )
    args: List[str] = Field(default_factory=list)


class ShellCriterion(_AcceptanceCriterionBase):
    """Run an allow-listed shell command and assert its exit code.

    The command head (first whitespace-separated token) is validated by
    ``BugIntakeNode`` against the ``ACCEPTANCE_CRITERION_ALLOWLIST``
    setting at intake time.
    """

    kind: Literal["shell"] = "shell"
    command: str = Field(
        ...,
        description="Full shell command. The head is checked against an allow-list.",
    )


class ManualCriterion(BaseModel):
    """Human-readable acceptance statement that the QA subagent must NOT run.

    Used for criteria that are inherently subjective or require human
    judgement ("the dashboard renders without flicker", "the migration
    note in the PR mentions both downtime and rollback"). The
    :class:`QANode` filters these out before dispatch, then re-appends a
    synthesized :class:`CriterionResult` with ``kind="manual"`` and
    ``passed=True`` so the deterministic gate does not block the flow.
    The text is also embedded in the Jira ticket description and in
    ``QAReport.notes`` so the human reviewer can sign off explicitly.
    """

    kind: Literal["manual"] = "manual"
    name: str = Field(..., description="Short identifier for the criterion.")
    text: str = Field(
        ...,
        min_length=1,
        description="Human-readable statement the reviewer must verify.",
    )


AcceptanceCriterion = Annotated[
    Union[FlowtaskCriterion, ShellCriterion, ManualCriterion],
    Field(discriminator="kind"),
]


# ─────────────────────────────────────────────────────────────────────
# Bug brief (BugIntakeNode input → flow context)
# ─────────────────────────────────────────────────────────────────────


class LogSource(BaseModel):
    """A pointer to a log location that ``ResearchNode`` will fetch."""

    kind: Literal["cloudwatch", "elasticsearch", "attached_file"]
    locator: str = Field(
        ...,
        description="Log-group name, ES index, or file path depending on `kind`.",
    )
    time_window_minutes: int = Field(default=60, ge=1, le=1440)


class BugBrief(BaseModel):
    """User-facing input contract for the dev-loop flow.

    Produced by the nav-admin form (or another caller) and validated by
    ``BugIntakeNode`` before any dispatch happens.
    """

    summary: str = Field(
        ...,
        min_length=10,
        max_length=255,
        description=(
            "Short human-readable headline. Becomes the Jira ticket "
            "`summary` field, which Atlassian caps at 255 characters."
        ),
    )
    description: str = Field(
        default="",
        description=(
            "Long-form incident details (steps to reproduce, hypotheses, "
            "links). Embedded in the Jira ticket description; never "
            "forwarded to the `summary` field."
        ),
    )
    affected_component: str
    log_sources: List[LogSource] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = Field(..., min_length=1)
    escalation_assignee: str = Field(
        ...,
        description="Jira accountId or email of the failure escalation assignee.",
    )
    reporter: str = Field(
        ...,
        description="Jira accountId or email of the original human reporter.",
    )


# ─────────────────────────────────────────────────────────────────────
# Per-node dispatch outputs
# ─────────────────────────────────────────────────────────────────────


class ResearchOutput(BaseModel):
    """Structured output from the ``sdd-research`` dispatch.

    The research subagent creates the Jira ticket, the spec, the worktree
    and (optionally) initial task artifacts, then emits this payload.
    """

    jira_issue_key: str = Field(..., description="e.g. 'OPS-4321'")
    spec_path: str = Field(..., description="Path to the spec, inside the worktree.")
    feat_id: str = Field(..., description="e.g. 'FEAT-130'")
    branch_name: str = Field(..., description="e.g. 'feat-130-fix-customer-sync'")
    worktree_path: str = Field(..., description="Absolute on-disk worktree path.")
    log_excerpts: List[str] = Field(
        default_factory=list,
        description="Short, redacted log excerpts gathered during research.",
    )


class DevelopmentOutput(BaseModel):
    """Structured output from the ``sdd-worker`` dispatch."""

    files_changed: List[str]
    commit_shas: List[str]
    summary: str


class CriterionResult(BaseModel):
    """Result of running a single acceptance criterion in QA."""

    name: str
    kind: Literal["flowtask", "shell", "manual"]
    exit_code: int
    duration_seconds: float
    stdout_tail: str = Field("", max_length=4000)
    stderr_tail: str = Field("", max_length=4000)
    passed: bool


class QAReport(BaseModel):
    """Structured output from the ``sdd-qa`` dispatch.

    The QA node returns this payload regardless of pass/fail; the *flow*
    decides routing based on ``passed``.
    """

    passed: bool
    criterion_results: List[CriterionResult]
    lint_passed: bool
    lint_output: str = ""
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────
# Dispatcher contracts
# ─────────────────────────────────────────────────────────────────────


class ClaudeCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.

    ``subagent`` selects a programmatic subagent from the ``agents=`` dict
    passed to the SDK; when ``None``, ``system_prompt_override`` is used
    and the dispatcher falls back to a generic session.
    """

    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa"]] = "sdd-worker"
    system_prompt_override: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    permission_mode: Literal[
        "default", "acceptEdits", "plan", "bypassPermissions"
    ] = "default"
    setting_sources: List[Literal["user", "project", "local"]] = Field(
        default_factory=lambda: ["project"]
    )
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    model: str = "claude-sonnet-4-6"


class DispatchEvent(BaseModel):
    """Envelope for stream-json events published to Redis.

    The dispatcher wraps every SDK message and every lifecycle transition
    in a ``DispatchEvent`` and ``XADD``s it to
    ``flow:{run_id}:dispatch:{node_id}``. The streaming multiplexer
    consumes the same envelope on the way out to the UI.
    """

    kind: Literal[
        "dispatch.queued",
        "dispatch.started",
        "dispatch.message",
        "dispatch.tool_use",
        "dispatch.tool_result",
        "dispatch.output_invalid",
        "dispatch.failed",
        "dispatch.completed",
    ]
    ts: float = Field(..., description="POSIX timestamp seconds.")
    run_id: str
    node_id: str
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw SDK event dict, or error context.",
    )
