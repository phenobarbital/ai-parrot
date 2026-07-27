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
    SerializeAsAny,
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
    """A pointer to a log location that ``ResearchNode`` will fetch.

    The ``inline`` kind carries the log content itself: use it when the
    reporter pastes a stack trace, log excerpt, or error message directly
    instead of pointing at a CloudWatch group, ES index, or file on disk.
    """

    kind: Literal["cloudwatch", "elasticsearch", "attached_file", "inline"]
    locator: str = Field(
        ...,
        description=(
            "Log-group name, ES index, or file path depending on `kind`. "
            "For `inline`, the raw pasted log/stack-trace/error text itself."
        ),
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
    acceptance_criteria: Optional[List[AcceptanceCriterion]] = Field(
        default=None,
        description=(
            "The original feature's acceptance criteria (FEAT-377 TASK-1908). "
            "When present and non-empty, `run_revision` re-verifies them "
            "alongside the lint gate instead of running lint-only. `None` "
            "(the default) preserves legacy lint-only revision QA exactly — "
            "no caller populates this yet; graph memory write-back "
            "(TASK-1915) is the intended future source."
        ),
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
    escalation_model: str = Field(
        default="",
        description=(
            "FEAT-377 TASK-1912 (G3): model used on retry/redispatch instead "
            "of `model` — same backend, stronger tier (e.g. 'claude-code' "
            "sonnet -> opus). Consulted by DevAgentPool.run_wave's single "
            "retry AND the QA repair-loop's development redispatch "
            "(attempt >= 2). '' (default) disables escalation — the retry "
            "uses `model`, byte-identical to pre-TASK-1912 behavior. No "
            "built-in per-backend ladder in v1 (decided 2026-07-26, spec §8) "
            "— explicit only."
        ),
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
    kind: Literal["flowtask", "shell", "manual"] = "shell"
    exit_code: int = 0
    duration_seconds: float = 0.0
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

    @field_validator("code_review_findings", mode="before")
    @classmethod
    def _coerce_finding_dicts(cls, v: Any) -> Any:
        """Coerce structured finding dicts to plain strings.

        The sdd-qa agent sees the full QAReport schema and may return
        CodeReviewFinding-shaped dicts instead of strings.
        """
        if isinstance(v, list):
            return [
                item.get("message", "") or str(item)
                if isinstance(item, dict)
                else item
                for item in v
            ]
        return v

    attempt: int = Field(
        default=1,
        ge=1,
        description=(
            "FEAT-377 TASK-1910: which QA attempt produced this report "
            "(1-based). Lives ON the report — not merely in shared state — "
            "because the engine's `cel_evaluator` coerces the node result "
            "via `model_dump()`, so the qa→development retry / "
            "qa→failure_handler exhaustion CEL predicates can only "
            "reference fields on `QAReport` itself."
        ),
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

    subagent: Optional[
        Literal[
            "sdd-research",
            "sdd-worker",
            "sdd-qa",
            "sdd-codereview",
            "sdd-planner",
            "sdd-feedback",
        ]
    ] = "sdd-worker"
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

    subagent: Literal["sdd-worker", "sdd-secondopinion"] = "sdd-worker"
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

    ``findings`` is ``SerializeAsAny``-wrapped (FEAT-375 code-review fix) so
    that subclass instances — e.g. ``AdversarialFinding``, tagged with
    ``source``/``disposition``/``triage_reason`` by the advisory reviewers —
    keep those extra fields when this verdict is ``.model_dump()``'d, instead
    of being silently truncated down to the base ``CodeReviewFinding`` shape.
    """

    passed: bool = True
    findings: List[SerializeAsAny[CodeReviewFinding]] = Field(default_factory=list)
    summary: str = ""
    files_modified: List[str] = Field(default_factory=list)

    @field_validator("findings", mode="before")
    @classmethod
    def _coerce_findings(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        out = []
        for item in v:
            if isinstance(item, str):
                out.append(CodeReviewFinding(message=item, severity="minor"))
            elif isinstance(item, dict):
                if "message" not in item:
                    item = {**item, "message": item.get("summary", item.get("description", "(no message)"))}
                if "severity" not in item:
                    item = {**item, "severity": "minor"}
                out.append(item)
            else:
                out.append(item)
        return out


class AdversarialFinding(CodeReviewFinding):
    """A finding from an advisory reviewer, awaiting or carrying a triage disposition (FEAT-375)."""

    source: str = "codex-adversarial"
    disposition: Optional[Literal["confirm", "reject", "escalate"]] = None
    triage_reason: str = ""
    finding_id: str = Field(
        default="",
        description=(
            "Stable identifier assigned before a triage round (e.g. "
            "'finding-0'), so the triage worker's disposition can be matched "
            "back to the originating finding without relying on exact "
            "file/message text equality (which an LLM may paraphrase)."
        ),
    )


class TriageBrief(BaseModel):
    """Brief for the primary worker's triage dispatch (FEAT-375).

    Neutral by construction: carries only the advisory findings, the
    acceptance criteria, and the worktree path — no field for the caller's
    reasoning, so ratification of the adversarial reviewer is structurally
    impossible.
    """

    findings: List[AdversarialFinding]
    acceptance_criteria: List[AcceptanceCriterion]
    worktree_path: str
    summary: str = ""


class TriageReport(BaseModel):
    """Every input finding MUST appear with a disposition — none dropped (FEAT-375)."""

    findings: List[AdversarialFinding]
    files_modified: List[str] = Field(default_factory=list)
    summary: str = ""


class PerspectiveSynthesis(BaseModel):
    """Deterministic merge of primary + adversarial verdicts (FEAT-375 G7)."""

    agreements: List[AdversarialFinding]
    disagreements: List[AdversarialFinding]
    judge_summary: str = ""


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


class CodexAdversarialReviewProfile(CodexCodeDispatchProfile):
    """Advisory review profile for the Codex adversarial second-opinion (FEAT-375).

    Read-only, neutral-brief, no-writes profile: the dispatcher runs
    ``codex exec review`` (or ``codex exec resume --last``) in a read-only
    sandbox with the ``sdd-secondopinion`` subagent brief, which by
    construction never receives the primary agent's reasoning.
    """

    subagent: Literal["sdd-secondopinion"] = "sdd-secondopinion"
    sandbox: Literal["read-only"] = "read-only"
    approval_policy: Literal["never"] = "never"
    review_scope: Literal["uncommitted", "base", "commit"] = "uncommitted"
    review_base: str = ""
    review_commit: str = ""
    resume_last: bool = Field(
        default=False,
        description="G6: use `codex exec resume --last` to continue the existing review session.",
    )
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


# ─────────────────────────────────────────────────────────────────────
# Feature-mode contracts (FEAT-378) — document-driven planning, judge
# panel, synthesis and feedback-router outputs, feature handoff.
# ─────────────────────────────────────────────────────────────────────


class FeatureBrief(BaseModel):
    """Document-based intake for the feature-mode dev-loop topology.

    Unlike :class:`WorkBrief` (log-driven bug/enhancement/new_feature
    triage), a ``FeatureBrief`` points at an existing SDD document
    (brainstorm, proposal, or already-resolved spec) and lets
    ``PlannerNode`` generate whatever SDD artifacts are still missing
    (spec via ``/sdd-spec``, task index via ``/sdd-task``) plus the
    feature worktree. Jira is optional end-to-end in feature-mode: only
    linked when ``jira_issue_key`` is populated.
    """

    kind: Literal["feature"] = "feature"
    document_path: str = Field(
        ...,
        description=(
            "Path to the brainstorm/proposal/spec markdown driving this "
            "run. Must exist and be a readable file — validated eagerly "
            "at model construction so an invalid brief fails before any "
            "dispatch."
        ),
    )
    document_kind: Literal["brainstorm", "proposal", "spec"] = Field(
        ...,
        description=(
            "Which SDD phase the document represents. 'spec' skips "
            "PlannerNode's /sdd-spec step and goes straight to /sdd-task "
            "(or validates an existing task index)."
        ),
    )
    jira_issue_key: Optional[str] = Field(
        default=None,
        description=(
            "Optional Jira issue key. Feature-mode never creates a Jira "
            "issue; when set, downstream nodes only link/transition/"
            "comment on the existing ticket."
        ),
    )
    dev_agents: Optional[List[DevAgentSpec]] = Field(
        default=None,
        description=(
            "Optional explicit dev-agent pool. When unset, PlannerNode "
            "derives the pool from the width of the first "
            "``TaskScheduler`` wave, capped at ``development_pool_max``."
        ),
    )
    judge_panel: Optional["JudgePanelConfig"] = Field(
        default=None,
        description=(
            "Optional QA judge-panel override. When unset, "
            "``JudgePanelReviewDispatcher`` uses ``default_judge_panel()`` "
            "or the ``DEV_LOOP_JUDGE_PANEL`` conf key."
        ),
    )

    @field_validator("document_path")
    @classmethod
    def _document_path_must_be_readable(cls, v: str) -> str:
        """Fail fast when the intake document does not exist or is unreadable.

        Args:
            v: Raw ``document_path`` value.

        Returns:
            The path unchanged if it resolves to a readable file.

        Raises:
            ValueError: If the path does not exist, is not a file, or
                cannot be opened for reading.
        """
        from pathlib import Path

        path = Path(v)
        if not path.is_file():
            raise ValueError(f"document_path does not exist or is not a file: {v!r}")
        try:
            with path.open("r", encoding="utf-8"):
                pass
        except OSError as exc:
            raise ValueError(f"document_path is not readable: {v!r} ({exc})") from exc
        return v

    @model_validator(mode="after")
    def _warn_on_doc_kind_suffix_mismatch(self) -> "FeatureBrief":
        """Warn (not fail) when ``document_kind`` disagrees with the filename suffix."""
        import logging

        suffix_map = {
            ".brainstorm.md": "brainstorm",
            ".proposal.md": "proposal",
            ".spec.md": "spec",
        }
        name = self.document_path
        for suffix, expected_kind in suffix_map.items():
            if name.endswith(suffix) and expected_kind != self.document_kind:
                logging.getLogger(__name__).warning(
                    "FeatureBrief.document_kind=%r does not match the "
                    "filename convention for %r (expected %r)",
                    self.document_kind,
                    name,
                    expected_kind,
                )
        return self


class JudgeSpec(BaseModel):
    """A single judge declaration inside a :class:`JudgePanelConfig`.

    Reuses the 7-backend :data:`DevAgentBackend` Literal for the field's
    type — a judge is materialized into a dispatcher via
    ``build_dispatcher()`` exactly like a dev-agent, just used for review
    instead of development — but only 3 backends actually have a review
    profile (see :class:`JudgePanelReviewDispatcher._build_judge` in
    ``code_review.py``): ``agent`` is validated eagerly against that same
    supported set so a misconfigured ``DEV_LOOP_JUDGE_PANEL`` (or
    programmatic ``JudgePanelConfig``) fails at config-load time with a
    clear message, instead of surfacing as a swallowed
    ``asyncio.gather(..., return_exceptions=True)`` failure deep inside
    ``JudgePanelReviewDispatcher.review()`` at dispatch time (code-review
    finding).
    """

    agent: DevAgentBackend = Field(
        ..., description="Backend → existing dispatcher (claude-code, codex, ...)."
    )
    model: str = Field(
        default="", description="'' ⇒ use the backend's default model."
    )

    @field_validator("agent")
    @classmethod
    def _agent_must_have_review_profile(cls, v: str) -> str:
        supported = ("claude-code", "codex", "gemini")
        if v not in supported:
            raise ValueError(
                f"JudgeSpec.agent={v!r} has no review profile — "
                f"JudgePanelReviewDispatcher only supports {supported}."
            )
        return v


class JudgePanelConfig(BaseModel):
    """N-judge QA panel configuration for :class:`JudgePanelReviewDispatcher`.

    Simple majority decision; a tie or an abstention that breaks
    majority escalates (fail-closed) rather than passing by default.
    """

    judges: List[JudgeSpec] = Field(..., min_length=1)
    decision: Literal["majority"] = "majority"


def default_judge_panel() -> JudgePanelConfig:
    """Return the resolved default 3-judge panel (spec §2).

    claude-code/claude-sonnet-4-6 + codex/gpt-5.5 (the adversarial judge,
    dispatched via the ``sdd-secondopinion`` profile) + gemini/auto.

    Returns:
        The default :class:`JudgePanelConfig`.
    """
    return JudgePanelConfig(
        judges=[
            JudgeSpec(agent="claude-code", model="claude-sonnet-4-6"),
            JudgeSpec(agent="codex", model="gpt-5.5"),
            JudgeSpec(agent="gemini", model=""),
        ],
        decision="majority",
    )


class PlannerOutput(BaseModel):
    """Structured output from the ``sdd-planner`` dispatch.

    Mirrors :class:`ResearchOutput`'s field shape (minus the
    always-present Jira key, since feature-mode Jira is optional and
    never created by the planner).
    """

    spec_path: str = Field(..., description="Path to the spec, inside the worktree.")
    task_index_path: str = Field(
        ..., description="Path to the per-spec task index JSON."
    )
    feat_id: str = Field(..., description="e.g. 'FEAT-378'")
    branch_name: str = Field(..., description="e.g. 'feat-378-devloop-enhancement'")
    worktree_path: str = Field(..., description="Absolute on-disk worktree path.")
    repo_path: str = Field(
        default="",
        description=(
            "Absolute path of the primary repository the Development node "
            "will `cd` into. Defaults to '' — callers fall back to "
            "``worktree_path``."
        ),
    )
    jira_issue_key: Optional[str] = Field(
        default=None,
        description=(
            "Passed through from ``FeatureBrief.jira_issue_key`` when "
            "present. The planner NEVER creates a Jira issue."
        ),
    )
    suggested_pool: Optional[DevAgentPoolConfig] = Field(
        default=None,
        description="Pool sized from the first ``TaskScheduler`` wave width.",
    )


class SynthesisReport(BaseModel):
    """Structured output from the ``SynthesisNode`` reconciliation dispatch."""

    consistent: bool = Field(
        ...,
        description=(
            "False when the synthesis agent found unresolved inter-worker "
            "inconsistencies or the integration pytest run failed."
        ),
    )
    adjustments: List[str] = Field(
        default_factory=list,
        description="Reconciliation adjustments the agent made/committed.",
    )
    summary: str = ""


class FeedbackDecision(BaseModel):
    """Structured output from the ``sdd-feedback`` dispatch.

    The LLM only *proposes* a decision — :class:`FeedbackRouterNode`
    re-checks the deterministic ``accept_with_notes`` envelope and the
    ``DEV_LOOP_QA_MAX_RETRIES`` stop rule in Python, post-parse, and
    downgrades the decision when the proposal violates either.
    """

    decision: Literal["retry", "escalate", "accept_with_notes"]
    dev_brief: str = Field(
        default="",
        description="Actionable brief injected into the retry dispatch.",
    )
    notes: str = Field(
        default="",
        description="Appended to the PR body when decision='accept_with_notes'.",
    )


# ─────────────────────────────────────────────────────────────────────
# Discriminated brief union (FEAT-378)
# ─────────────────────────────────────────────────────────────────────

# NOTE: ``WorkBrief.kind`` defaults to "bug" and is a 3-value Literal, not
# a single tag. A plain ``Annotated[Union[WorkBrief, FeatureBrief],
# Field(discriminator="kind")]`` works fine for dicts that *carry* a
# ``kind`` key (pydantic's discriminated-union machinery reads the value
# and dispatches to the matching member), but callers that omit ``kind``
# entirely rely on ``WorkBrief``'s own default — which the discriminator
# fast-path does not apply for missing keys the same way plain
# ``TypeAdapter`` validation does for a non-discriminated union. To keep
# "existing briefs with no `kind` key still parse as WorkBrief" byte-
# identical, ``parse_brief`` is a thin loader shim used everywhere instead
# of validating ``Brief`` directly against a bare dict.
Brief = Annotated[Union[WorkBrief, FeatureBrief], Field(discriminator="kind")]


def parse_brief(data: Dict[str, Any]) -> Union[WorkBrief, FeatureBrief]:
    """Parse a raw brief dict into a :class:`WorkBrief` or :class:`FeatureBrief`.

    Loader shim around the ``Brief`` discriminated union: routes on the
    ``kind`` field when present (``"feature"`` → ``FeatureBrief``,
    anything else → ``WorkBrief``), and falls back to ``WorkBrief`` when
    ``kind`` is absent entirely — preserving ``WorkBrief.kind``'s own
    ``"bug"`` default for pre-FEAT-378 callers (zero behavior change).

    Args:
        data: Raw brief mapping, e.g. loaded from YAML.

    Returns:
        A validated ``WorkBrief`` or ``FeatureBrief`` instance.

    Raises:
        pydantic.ValidationError: If the dict fails validation against
            the resolved model.
    """
    if data.get("kind") == "feature":
        return FeatureBrief(**data)
    return WorkBrief(**data)
