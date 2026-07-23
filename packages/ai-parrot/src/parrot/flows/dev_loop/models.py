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
See ``sdd/specs/feat-129-upgrades.spec.md`` §3 Module 1 for the FEAT-132
``WorkBrief`` rename and ``kind`` field.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

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
    blocking: bool = Field(
        default=False,
        description=(
            "FEAT-322: when True, QANode opens a blocking manual_criterion "
            "HITL gate and awaits its resolution before returning — the run "
            "pauses (phase='awaiting_gate') until a human approves/rejects "
            "or the gate's TTL expires. Default False preserves today's "
            "behavior exactly: the criterion is synthesized as "
            "passed=True without blocking (see QANode._merge_manual_results)."
        ),
    )


AcceptanceCriterion = Annotated[
    Union[FlowtaskCriterion, ShellCriterion, ManualCriterion],
    Field(discriminator="kind"),
]


# ─────────────────────────────────────────────────────────────────────
# Work brief (IntentClassifierNode / BugIntakeNode input → flow context)
# ─────────────────────────────────────────────────────────────────────

# Internal type alias for the kind discriminator field. Not exported
# publicly from parrot.flows.dev_loop — internal use only. FEAT-132.
WorkKind = Literal["bug", "enhancement", "new_feature"]


class LogSource(BaseModel):
    """A pointer to a log location that ``ResearchNode`` will fetch."""

    kind: Literal["cloudwatch", "elasticsearch", "attached_file"]
    locator: str = Field(
        ...,
        description="Log-group name, ES index, or file path depending on `kind`.",
    )
    time_window_minutes: int = Field(default=60, ge=1, le=1440)


class WorkBrief(BaseModel):
    """User-facing input contract for the dev-loop flow.

    Renamed from ``BugBrief`` in FEAT-132. The legacy name is preserved as
    a module-level alias (``BugBrief = WorkBrief``) so existing
    ``from parrot.flows.dev_loop import BugBrief`` callers keep working
    without edits.

    Field declaration order is intentional: ``kind`` is first so the JSON
    schema rendered by the dispatcher's ``_build_prompt`` surfaces it at
    the top of the field list.
    """

    kind: WorkKind = Field(
        default="bug",
        description=(
            "Intake classification: 'bug' for defect triage, "
            "'enhancement' for changes to existing behaviour, "
            "'new_feature' for net-new capability. Picked up by "
            "IntentClassifierNode for routing and by ResearchNode for "
            "Jira issuetype selection."
        ),
    )
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
    existing_issue_key: Optional[str] = Field(
        default=None,
        description=(
            "Optional Jira issue key (e.g. 'NAV-8241') the caller knows "
            "tracks this incident already. When set, ResearchNode skips "
            "the create-issue step and posts a re-triggered comment on "
            "the named ticket instead. When unset, ResearchNode searches "
            "the project for an open ticket with a matching summary "
            "before falling back to creating a new one."
        ),
    )
    dev_agents: Optional[List["DevAgentSpec"]] = Field(
        default=None,
        description=(
            "Optional per-run dev-agent pool declaration (FEAT-323). When "
            "set, ``DevelopmentNode`` dispatches this pool of sub-agents "
            "instead of the single-agent path. Falls back to the "
            "``DEV_LOOP_DEV_AGENTS`` env var, then to the single-agent "
            "behaviour, when unset."
        ),
    )
    dev_isolation: Optional[Literal["shared", "isolated"]] = Field(
        default=None,
        description=(
            "Optional per-run isolation mode override for the dev-agent "
            "pool (FEAT-323). Falls back to ``DEV_LOOP_DEV_ISOLATION``, "
            "then to ``DevAgentPoolConfig.isolation_mode`` (default "
            "'shared'), when unset."
        ),
    )


# Back-compat alias: existing `from parrot.flows.dev_loop import BugBrief`
# callers keep working unchanged. FEAT-132.
BugBrief = WorkBrief


# ─────────────────────────────────────────────────────────────────────
# Repository provisioning & revision-mode contracts (FEAT-250)
# ─────────────────────────────────────────────────────────────────────


class RepoSpec(BaseModel):
    """A git repository the dev-loop run operates on.

    Declared on the flow config (``DEV_LOOP_REPOS``); the repo-provisioning
    step clones/pulls each spec under ``DEV_LOOP_REPO_BASE_PATH`` before the
    Development node runs.
    """

    alias: str = Field(
        ...,
        description="Short name; also the clone directory name under the base path.",
    )
    url: str = Field(
        ...,
        description="HTTPS URL or 'owner/name' slug to clone.",
    )
    branch: str = Field(
        default="main",
        description="Base branch to clone and branch from.",
    )
    private: bool = Field(
        default=False,
        description="When True, use the toolkit's token / `gh` auth for the clone.",
    )

    @field_validator("alias")
    @classmethod
    def alias_is_safe_dirname(cls, v: str) -> str:
        """Reject alias values that could escape the clone base directory.

        Guards against path-traversal attacks when the JSON form of
        ``DEV_LOOP_REPOS`` is used (e.g. ``{"alias": "../../etc", ...}``).

        Args:
            v: Raw alias value.

        Returns:
            The alias unchanged if it is safe.

        Raises:
            ValueError: If the alias contains path separators, starts with
                a dot, or is one of the reserved names ``.`` / ``..``.
        """
        if not v or v in (".", ".."):
            raise ValueError("alias must not be empty, '.', or '..'")
        if "/" in v or "\\" in v:
            raise ValueError(f"alias must not contain path separators, got {v!r}")
        if v.startswith("."):
            raise ValueError(f"alias must not start with '.', got {v!r}")
        return v


class RevisionBrief(BaseModel):
    """Input to a revision-mode run (no new PR; update an existing one).

    Built by the PR-comment / PR-review webhook handler and passed to
    ``DevLoopRunner.run_revision(...)``. The revision flow enters at the
    Development node with ``cwd=repo_path`` (the existing clone + branch),
    re-runs QA, then pushes to the same branch and comments on the same PR.
    """

    repo_path: str = Field(
        ...,
        description="Existing clone on disk (the Development node's cwd).",
    )
    branch: str = Field(..., description="Existing feature branch already checked out.")
    pr_number: int = Field(..., description="The open draft PR to update.")
    repository: str = Field(..., description="'owner/name' of the repository.")
    jira_issue_key: str = Field(..., description="Linked Jira issue key.")
    feedback: str = Field(..., description="The reviewer comment text to act on.")
    head_sha: str = Field(
        ...,
        description="Head SHA at trigger time; used for dedup (mirrors GitHubReviewer).",
    )


# ─────────────────────────────────────────────────────────────────────
# Per-node dispatch outputs
# ─────────────────────────────────────────────────────────────────────


class ResearchOutput(BaseModel):
    """Structured output from the ``sdd-research`` dispatch.

    The research subagent creates the Jira ticket, the spec, the worktree
    and (optionally) initial task artifacts, then emits this payload.

    The model accepts a small set of common aliases under
    ``populate_by_name=True`` so subagent outputs that drift on field
    names (``jira_key``, ``feature_id``, ``branch``, ``worktree``) still
    validate. Pydantic's serialiser keeps the canonical names on
    output.
    """

    model_config = ConfigDict(populate_by_name=True)

    jira_issue_key: str = Field(
        ...,
        description="e.g. 'OPS-4321'",
        validation_alias=AliasChoices("jira_issue_key", "jira_key", "issue_key", "ticket_key"),
    )
    spec_path: str = Field(
        ...,
        description="Path to the spec, inside the worktree.",
        validation_alias=AliasChoices("spec_path", "spec"),
    )
    feat_id: str = Field(
        ...,
        description="e.g. 'FEAT-130'",
        validation_alias=AliasChoices("feat_id", "feature_id", "feat", "feature"),
    )
    branch_name: str = Field(
        ...,
        description="e.g. 'feat-130-fix-customer-sync'",
        validation_alias=AliasChoices("branch_name", "branch"),
    )
    worktree_path: str = Field(
        ...,
        description="Absolute on-disk worktree path.",
        validation_alias=AliasChoices("worktree_path", "worktree"),
    )
    repo_path: str = Field(
        default="",
        description=(
            "Absolute path of the primary cloned repository the Development "
            "node will `cd` into. Set by the repo-provisioning step (FEAT-250). "
            "Defaults to '' for back-compat; when empty, callers fall back to "
            "``worktree_path``."
        ),
        validation_alias=AliasChoices("repo_path", "repo", "clone_path"),
    )
    log_excerpts: List[str] = Field(
        default_factory=list,
        description="Short, redacted log excerpts gathered during research.",
    )


# ─────────────────────────────────────────────────────────────────────
# Dev-agent pool configuration & task-scoped dispatch (FEAT-323)
# ─────────────────────────────────────────────────────────────────────

DevAgentBackend = Literal[
    "claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot"
]


class DevAgentSpec(BaseModel):
    """A single dev-agent declaration inside a ``DevAgentPoolConfig``.

    Materialized by the pool builder into an existing
    ``DevLoopCodeDispatcher`` instance; ``count`` replicas of the same
    backend/model share the same dispatcher (and its semaphore).
    """

    agent: DevAgentBackend = Field(
        ..., description="Backend → existing dispatcher (claude-code, codex, ...)."
    )
    model: str = Field(
        default="", description="'' ⇒ use the backend's default model."
    )
    count: int = Field(
        default=1, ge=1, description="Number of replicas of this spec in the pool."
    )


class DevAgentPoolConfig(BaseModel):
    """Declares the pool of dev sub-agents for a dev-loop run (FEAT-323).

    Travels on ``WorkBrief.dev_agents`` / ``dev_isolation``, or is parsed
    from the ``DEV_LOOP_DEV_AGENTS`` / ``DEV_LOOP_DEV_ISOLATION`` env
    vars. When absent entirely, ``DevelopmentNode`` runs the single-agent
    path unchanged.
    """

    agents: List[DevAgentSpec] = Field(
        ..., min_length=1, description="Dev-agent specs that make up the pool."
    )
    isolation_mode: Literal["shared", "isolated"] = Field(
        default="shared",
        description=(
            "'shared': all dispatches share the single worktree (precondition: "
            "disjoint task files). 'isolated': one sub-worktree per worker, "
            "merged sequentially back to the feature branch."
        ),
    )


class TaskScopedBrief(BaseModel):
    """Per-dispatch brief for a single task, used by the ``DevAgentPool``.

    Wraps the (single, shared) ``ResearchOutput`` with the ``task_id`` the
    dispatched sub-agent must implement in isolation, per the
    ``sdd-worker.md`` conditional instruction (FEAT-323 Module 7).
    """

    research: ResearchOutput
    task_id: str = Field(..., description="TASK-NNN id this dispatch must implement.")


class WorkerSummary(BaseModel):
    """Per-worker summary emitted by a ``DevAgentPool`` dispatch wave.

    One instance per sub-agent in the pool (FEAT-323), aggregated onto
    ``DevelopmentOutput.worker_summaries`` by ``DevelopmentNode`` when it
    runs in pool mode.
    """

    worker_id: str = Field(
        ..., description="Synthetic node id, e.g. 'development.w1'."
    )
    agent: str = Field(..., description="Backend used for this worker, e.g. 'codex'.")
    model: str = Field(..., description="Model name/id used by this worker.")
    tasks_completed: List[str] = Field(
        default_factory=list, description="TASK-NNN ids completed by this worker."
    )
    tasks_failed: List[str] = Field(
        default_factory=list, description="TASK-NNN ids that failed on this worker."
    )
    summary: str = Field(default="", description="Free-text summary from the worker.")


class DevelopmentOutput(BaseModel):
    """Structured output from the ``sdd-worker`` dispatch."""

    files_changed: List[str]
    commit_shas: List[str]
    summary: str
    incomplete_tasks: List[str] = Field(
        default_factory=list,
        description=(
            "TASK-NNN ids that could not be completed after a retry "
            "(FEAT-323 pool mode). Empty for the single-agent path and for "
            "back-compat with pre-FEAT-323 payloads."
        ),
    )
    worker_summaries: List[WorkerSummary] = Field(
        default_factory=list,
        description=(
            "Per-worker summaries when dispatched via a ``DevAgentPool`` "
            "(FEAT-323). Empty for the single-agent path."
        ),
    )


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
    code_review_passed: bool = Field(
        default=True,
        description=(
            "Result of the additive `sdd-codereview` gate (FEAT-250). Defaults "
            "to True so legacy QA paths that do not run code-review are "
            "unaffected. The final `passed` is "
            "``deterministic_passed and code_review_passed``."
        ),
    )
    code_review_findings: List[str] = Field(
        default_factory=list,
        description="Qualitative findings emitted by the code-review gate.",
    )


# ─────────────────────────────────────────────────────────────────────
# Dispatcher contracts
# ─────────────────────────────────────────────────────────────────────


class ClaudeCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.

    ``subagent`` selects a programmatic subagent from the ``agents=`` dict
    passed to the SDK; when ``None``, ``system_prompt_override`` is used
    and the dispatcher falls back to a generic session.
    """

    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"]] = "sdd-worker"
    system_prompt_override: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"
    setting_sources: List[Literal["user", "project", "local"]] = Field(default_factory=lambda: ["project"])
    strict_mcp_config: bool = Field(
        default=True,
        description=(
            "When True (the default), the dispatched headless CLI ignores "
            "claude.ai account connectors and filesystem .mcp.json, using "
            "only MCP servers explicitly provided. This isolates server-side "
            "dispatches from the operator's interactive Claude Code "
            "environment, whose connector/OAuth setup (e.g. the claude.ai "
            "Design MCP connector) otherwise makes the non-interactive run "
            "exit with an empty error result. Set False only when a dispatch "
            "genuinely needs the inherited MCP surface."
        ),
    )
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    model: str = "claude-sonnet-4-6"


class CodexCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``CodexCodeDispatcher.dispatch()``.

    The v1 Codex integration is intentionally scoped to Development. The
    profile still keeps ``subagent`` explicit so the dispatcher can load the
    same SDD subagent prompt body used by the Claude Code path.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "gpt-5.5"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    approval_policy: Literal["untrusted", "on-request", "never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    ignore_user_config: bool = Field(
        default=True,
        description=(
            "When True, pass --ignore-user-config so server-side dispatches do "
            "not inherit an operator's interactive Codex settings."
        ),
    )
    ignore_rules: bool = Field(
        default=False,
        description=(
            "When True, pass --ignore-rules. Defaults to False so repository "
            "AGENTS.md / rules still guide the coding agent."
        ),
    )


class GeminiCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``GeminiCodeDispatcher.dispatch()``.

    The Gemini integration is designed to run the Google Gemini Agent
    supporting tool calling and structured output extraction.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "auto"
    sandbox: bool = Field(
        default=True,
        description="Whether to run the gemini session in a sandbox.",
    )
    approval_mode: Literal["default", "auto_edit", "yolo", "plan"] = "auto_edit"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class LLMCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``LLMCodeDispatcher.dispatch()``.

    This profile targets OpenAI-compatible ``AbstractClient`` implementations
    via ``LLMFactory``. The dispatcher supplies the coding-agent loop locally,
    so the model only needs standard chat/tool-calling support.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    llm: str = "nvidia:moonshotai/kimi-k2-instruct-0905"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    max_turns: int = Field(default=24, ge=1, le=100)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    command_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    allowed_commands: List[str] = Field(
        default_factory=lambda: [
            "git",
            "uv",
            "pytest",
            "python",
            "python3",
            "rg",
            "ls",
            "pwd",
            "cat",
            "sed",
            "find",
        ],
        description="Executable names allowed through the run_command tool.",
    )
    enable_thinking: bool = Field(
        default=False,
        description="Forward Nvidia reasoning flags for models such as z-ai/glm-5.1.",
    )
    clear_thinking: bool = False


class GrokCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``GrokCodeDispatcher.dispatch()``.

    This profile targets Grok models. The dispatcher supplies the coding-agent
    loop locally, so the model only needs standard chat/tool-calling support.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "grok-build-0.1"
    sandbox: Literal["workspace-write"] = "workspace-write"
    approval_policy: Literal["never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    max_turns: int = Field(default=24, ge=1, le=100)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    command_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    allowed_commands: List[str] = Field(
        default_factory=lambda: [
            "git",
            "uv",
            "pytest",
            "python",
            "python3",
            "rg",
            "ls",
            "pwd",
            "cat",
            "sed",
            "find",
        ],
        description="Executable names allowed through the run_command tool.",
    )


class ZaiCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.

    Subclasses ``LLMCodeDispatchProfile`` so it flows through the inherited
    dispatch loop unchanged; Z.ai-native fields (``enable_thinking``,
    ``reasoning_effort``) are consumed by
    ``ZaiCodeDispatcher._completion_args`` instead of the Nvidia-style
    ``extra_body.chat_template_kwargs`` block used by the base class.
    """

    model: str = Field(
        default="glm-5.2",
        description="Convenience field; kept in sync with ``llm`` (zai:<model>).",
    )
    llm: str = "zai:glm-5.2"
    enable_thinking: bool = Field(
        default=True,
        description="Z.ai native thinking mode (thinking={'type': 'enabled'|'disabled'}).",
    )
    reasoning_effort: Literal[
        "max", "xhigh", "high", "medium", "low", "minimal", "none"
    ] = Field(
        default="max",
        description=(
            "Z.ai reasoning_effort. GLM-5.2-only, effective only when "
            "thinking is enabled."
        ),
    )
    max_tokens: int = Field(default=8192, ge=256, le=131072)

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "ZaiCodeDispatchProfile":
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly."""
        if "llm" not in self.model_fields_set:
            self.llm = f"zai:{self.model}"
        return self


class MoonshotCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``MoonshotCodeDispatcher.dispatch()``.

    Subclasses ``LLMCodeDispatchProfile`` so it flows through the inherited
    dispatch loop unchanged; Moonshot-native fields (``enable_thinking``,
    ``reasoning_effort``) are consumed by
    ``MoonshotCodeDispatcher._completion_args`` / ``_chat_completion``
    instead of the Nvidia-style ``extra_body.chat_template_kwargs`` block
    used by the base class.
    """

    model: str = Field(
        default="kimi-k3",
        description="Convenience field; kept in sync with ``llm`` (moonshot:<model>).",
    )
    llm: str = "moonshot:kimi-k3"
    enable_thinking: bool = Field(
        default=True,
        description=(
            "Moonshot thinking mode. Only kimi-k2.6 accepts an explicit "
            "thinking dict; kimi-k3 and the kimi-k2.7-code variants always "
            "reason server-side."
        ),
    )
    reasoning_effort: str = Field(
        default="max",
        description=(
            "Moonshot reasoning_effort (kimi-k3 only, injected via "
            "extra_body). Kimi-k3 always reasons; this tunes how hard."
        ),
    )
    max_tokens: int = Field(default=8192, ge=256, le=131072)

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "MoonshotCodeDispatchProfile":
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly."""
        if "llm" not in self.model_fields_set:
            self.llm = f"moonshot:{self.model}"
        return self


class CodeReviewFinding(BaseModel):
    """A single finding from the code review (FEAT-270)."""

    message: str
    severity: Literal["critical", "major", "minor", "nit"]
    file: str = ""
    line: int = 0


class CodeReviewVerdict(BaseModel):
    """Extended verdict emitted by all code review dispatchers (FEAT-270).

    Public replacement for the previous ``_CodeReviewVerdict`` private model
    in ``nodes/qa.py``. A verdict with no findings and no modified files is a
    pass, matching the old model's backward-compatible defaults.

    The ``findings`` validator coerces plain strings (the format the old model
    accepted) into ``CodeReviewFinding(message=s, severity="minor")`` so an LLM
    that returns the legacy format doesn't fail Pydantic validation.
    """

    passed: bool = True
    findings: List[CodeReviewFinding] = Field(default_factory=list)
    summary: str = ""
    files_modified: List[str] = Field(default_factory=list)

    @field_validator("findings", mode="before")
    @classmethod
    def _coerce_plain_strings(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [
                CodeReviewFinding(message=item, severity="minor")
                if isinstance(item, str)
                else item
                for item in v
            ]
        return v


class ClaudeCodeReviewProfile(ClaudeCodeDispatchProfile):
    """Review profile for the Claude Code review dispatcher (FEAT-270).

    Inherits ``ClaudeCodeDispatchProfile`` so it carries the ``setting_sources``
    and ``strict_mcp_config`` fields that ``ClaudeCodeDispatcher._resolve_run_options()``
    accesses. Overrides defaults for the write-enabled review use case: the
    ``sdd-codereview`` subagent is allowed to fix issues it finds and commit
    the fixes to the worktree branch.
    """

    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"]] = "sdd-codereview"
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"
    allowed_tools: List[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
    )
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class CodexCodeReviewProfile(CodexCodeDispatchProfile):
    """Review profile for the Codex code review dispatcher (FEAT-270).

    Inherits ``CodexCodeDispatchProfile`` so it carries the ``ignore_user_config``
    and ``ignore_rules`` fields that ``CodexCodeDispatcher._build_command()`` accesses.
    Overrides defaults for the write-enabled review use case.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "gpt-5.5"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    approval_policy: Literal["untrusted", "on-request", "never"] = "on-request"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class GeminiCodeReviewProfile(GeminiCodeDispatchProfile):
    """Review profile for the Gemini code review dispatcher (FEAT-270).

    Inherits ``GeminiCodeDispatchProfile`` so it carries the fields that
    ``GeminiCodeDispatcher._build_command()`` accesses. Overrides defaults
    for the write-enabled review use case.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "auto"
    sandbox: bool = False
    approval_mode: Literal["default", "auto_edit", "yolo", "plan"] = "auto_edit"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


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
