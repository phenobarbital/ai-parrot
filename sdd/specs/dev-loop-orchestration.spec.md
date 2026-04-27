# Feature Specification: Dev-Loop Orchestration with Claude Code Subagent Mirror

**Feature ID**: FEAT-129
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.6.x (`ai-parrot`, post-FEAT-124)

---

## 1. Motivation & Business Requirements

### Problem Statement

The development feedback loop for "small operational fixes" today is entirely
manual:

1. A bug is detected (typically a Flowtask YAML/JSON producing an incorrect
   result, an integration that drifted, or a regression introduced by a schema
   change).
2. A human pulls logs from CloudWatch / Elasticsearch, identifies the cause,
   and writes a Jira ticket with reproduction steps and acceptance criteria.
3. A human writes (or stitches together from past PRs) the spec for the fix.
4. A human creates a worktree, implements the fix, runs `flowtask <task>`
   locally to verify, and runs lint.
5. A human pushes the branch, opens a PR, and waits for review.

For "tonta-but-time-consuming" fixes (single-file YAML/JSON tweaks, missing
field mappings, off-by-one in a transformation), this workflow consumes hours
per ticket and gates more interesting work behind a triage queue.

This feature builds the **orchestration layer** that mirrors each AI-Parrot
flow node onto a Claude Code subagent dispatch:

- The AI-Parrot side owns SaaS integrations, credentials, and the flow state
  machine.
- The Claude Code side owns the codebase (read, grep, edit, run tests, commit)
  inside a controlled worktree.
- A thin dispatcher between them carries a Pydantic-validated brief, runs the
  right subagent under the right permission profile, pumps the stream-json
  output to Redis for observability, and returns a Pydantic-validated result.

### Goals

- **G1** — Build a 5-node `AgentsFlow` (`BugIntake`, `Research`, `Development`,
  `QA`, `DeploymentHandoff`) that takes a bug brief and produces a PR plus a
  Jira ticket transitioned to *Ready to Deploy*.
- **G2** — Introduce `ClaudeCodeDispatcher`, a thin orchestration class over
  `ClaudeAgentClient` (FEAT-124) that resolves a dispatch profile, acquires a
  global semaphore slot, pumps stream-json events to Redis, and returns a
  Pydantic-validated output.
- **G3** — Use SDD subagents (`sdd-research`, `sdd-worker`, `sdd-qa`) by
  default, with a generic-session escape hatch via an explicit
  `system_prompt_override` on the profile.
- **G4** — Two-stream observability with a WebSocket multiplexer: a flow
  event stream + one stream per dispatch, multiplexed by an aiohttp WebSocket
  handler that the UI consumes (UI never speaks Redis directly).
- **G5** — Two-level concurrency control: a global semaphore on the dispatcher
  (`CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`, default 3) and a flow-level
  semaphore on the orchestrator (`FLOW_MAX_CONCURRENT_RUNS`, default 5).
- **G6** — Acceptance criteria are a list of `AcceptanceCriterion` objects
  with a discriminated `kind`. v1 implements `flowtask` and `shell`; the QA
  node executes them deterministically (subprocess + exit code), not via LLM
  judgment.
- **G7** — Service-account Jira credentials (`flow-bot@company`) via
  `StaticCredentialResolver`. The ticket reporter and assignee remain the
  original human; only comments, attachments, and transitions are written by
  the bot.
- **G8** — Worktree lifecycle is external to the flow: `ResearchNode` creates
  the worktree (via `/sdd-task` inside the dispatch); cleanup happens either
  when a human runs `/sdd-done` after merge, or via an `AutonomousOrchestrator`
  GitHub webhook handler on `pull_request.closed`.

### Non-Goals (explicitly out of scope for v1)

- Retry semantics on QA failure — failure path hands off to a human.
- Automatic PR merge or voting bypass — the flow stops at PR creation.
- Telegram HITL escalation — tracked separately.
- Knative microservice deployment of the dispatcher — local in-process for v1.
- In-process MCP server migration (already declared out of scope by FEAT-124).
- Multi-repo support — single-repo only for v1.
- Subclass `ClaudeCodeDispatchClient(ClaudeAgentClient)` (Option B in
  brainstorm) — rejected because clients are transports, not orchestrators.
  See `sdd/proposals/dev-loop-orchestration.brainstorm.md` Option A.
- Subprocess CLI dispatch bypassing FEAT-124 (Option C) — rejected because
  it duplicates the SDK integration FEAT-124 already builds.
- Dispatch as MCP toolkit (Option D) — rejected because dispatch is a
  structural component of a flow node, not a runtime LLM-callable tool.

---

## 2. Architectural Design

### Overview

A new package `parrot/flows/dev_loop/` contains:

- **`models.py`** — Pydantic v2 contracts: `BugBrief`, `ResearchOutput`,
  `DevelopmentOutput`, `QAReport`, `AcceptanceCriterion` (discriminated union),
  `ClaudeCodeDispatchProfile`, `DispatchEvent`.
- **`dispatcher.py`** — `ClaudeCodeDispatcher`, the thin orchestration class.
- **`nodes/`** — Five `FlowNode` subclasses: `BugIntakeNode`, `ResearchNode`,
  `DevelopmentNode`, `QANode`, `DeploymentHandoffNode`.
- **`flow.py`** — `build_dev_loop_flow()` factory producing an `AgentsFlow`
  wired with the five nodes and `FlowTransition`s.
- **`streaming.py`** — `FlowStreamMultiplexer`, an aiohttp WebSocket handler
  that subscribes to both Redis streams and merges them by timestamp.
- **`webhook.py`** — `register_pull_request_webhook(orchestrator)` adds a
  `pull_request.closed` handler to the existing `AutonomousOrchestrator`
  webhook listener for worktree cleanup.

The dispatcher uses `LLMFactory.create("claude-agent:<model>")` from FEAT-124
to resolve a `ClaudeAgentClient`. SDK options (`cwd`, `agents`,
`setting_sources`, `allowed_tools`, `permission_mode`) are derived from a
declarative `ClaudeCodeDispatchProfile`. Stream-json events are wrapped in
`DispatchEvent` envelopes and `XADD`-published to a per-dispatch Redis stream.

The Claude Code session uses programmatic subagents (the SDK exposes
`ClaudeAgentOptions.agents: dict[str, AgentDefinition]` at
`claude_agent_sdk/types.py:1389`) to bind one of `sdd-research`, `sdd-worker`,
or `sdd-qa` per dispatch. Filesystem subagents from `.claude/agents/` are also
loaded via `setting_sources=["project"]` as a fallback.

### Component Diagram

```
                                            ┌───────────────────────────┐
                                            │ nav-admin (Svelte 5 UI)   │
                                            │  ─ form: start a run      │
                                            │  ─ live SvelteFlow canvas │
                                            └─────────────┬─────────────┘
                                                          │ WebSocket
                                                          │ /api/flow/{run_id}/ws
                                                          ▼
┌────────────────────────────┐               ┌──────────────────────────────┐
│ AutonomousOrchestrator     │               │ FlowStreamMultiplexer        │
│ - run_flow(bug_brief)      │◄──events──────│ - merges 2 streams by ts     │
│ - flow-level semaphore (5) │  XADD Redis   │ - replays from Redis on conn │
└─────────────┬──────────────┘               └──────────────────────────────┘
              │
              │ instantiates AgentsFlow
              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ AgentsFlow (parrot/bots/flow/fsm.py)                                     │
│                                                                          │
│  BugIntakeNode ─► ResearchNode ─► DevelopmentNode ─► QANode ─► PR Handoff│
│   (pure parrot)    │ dispatch     │ dispatch         │ dispatch          │
│                    ▼              ▼                  ▼                   │
│              ClaudeCodeDispatcher (parrot/flows/dev_loop/dispatcher.py)  │
│              - global semaphore (3)                                      │
│              - resolve profile → ClaudeAgentRunOptions                   │
│              - acquire client via LLMFactory.create("claude-agent:...")  │
│              - iterate ask_stream → publish DispatchEvent → XADD Redis   │
│              - validate ResultMessage payload against output_model       │
└──────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────┐
│ ClaudeAgentClient (FEAT-124) │
│  ─ ask_stream(prompt, opts)  │
│  ─ subprocess(claude CLI)    │
└──────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Claude Code session inside .claude/worktrees/feat-<id>-<slug>/           │
│  bound to subagent: sdd-research | sdd-worker | sdd-qa                   │
│  permission_mode + allowed_tools enforced by profile                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.clients.ClaudeAgentClient` (FEAT-124) | depends on + may extend | Hard dependency. Used via `LLMFactory.create("claude-agent:<model>")`. Run options need at minimum `cwd`, `agents`, `allowed_tools`, `permission_mode`, `setting_sources` exposed on `ClaudeAgentRunOptions`. |
| `parrot.clients.LLMFactory` | depends on | `create("claude-agent:claude-sonnet-4-6")` returns the client. |
| `parrot.bots.flow.AgentsFlow` (`fsm.py:277`) | depends on | New flow built via `add_agent`, `task_flow`, `add_start_node`, `add_end_node`. |
| `parrot.bots.flow.FlowTransition` (`fsm.py:116`) | depends on | Wires nodes together, including the QA pass/fail branch. |
| `parrot.bots.flow.node.Node` (`node.py:14`) | extends | All five nodes subclass `Node` or `FlowNode`. |
| `parrot_tools.jiratoolkit.JiraToolkit` (`packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:609`) | depends on | Used by `BugIntakeNode`, `ResearchNode`, `DeploymentHandoffNode`, failure handler. Service-account credentials via `StaticCredentialResolver`. |
| `parrot_tools.elasticsearch.ElasticsearchTool` (`packages/ai-parrot-tools/src/parrot_tools/elasticsearch.py:167`) | depends on | Used by `ResearchNode` for log fetching. |
| `parrot_tools.aws.cloudwatch` (`packages/ai-parrot-tools/src/parrot_tools/aws/cloudwatch.py`) | depends on | Used by `ResearchNode` for log fetching. |
| `parrot.autonomous.AutonomousOrchestrator` (`orchestrator.py:112`) | depends on + extends | Hosts the flow runs (flow-level semaphore + history) and registers the `pull_request.closed` webhook handler. NB: the class is `AutonomousOrchestrator`, not `AutonomyOrchestrator`. |
| `parrot.autonomous.webhooks.WebhookListener` | depends on | HMAC-validated webhook endpoint for GitHub. Registered via `orchestrator.register_webhook(...)` (`orchestrator.py:646`). |
| `parrot.auth.credentials.StaticCredentialResolver` (`credentials.py:81`) | depends on | Wraps `flow-bot@company` Jira credentials. NB: in `parrot.auth`, not `parrot.security`. |
| `parrot.auth.permission.PermissionContext` (`permission.py:80`) | depends on | Per-flow user/tenant context for the JiraToolkit hooks. |
| `parrot.tools.toolkit.AbstractToolkit._pre_execute` / `_post_execute` (`toolkit.py:131,156,164,261`) | depends on | JiraToolkit lifecycle hooks for credential resolution. Confirmed merged. |
| `parrot.conf` (`conf.py`, navconfig) | extends | New settings: `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`, `FLOW_MAX_CONCURRENT_RUNS`, `FLOW_BOT_JIRA_ACCOUNT_ID`, `WORKTREE_BASE_PATH`, `FLOW_STREAM_TTL_SECONDS`, `ACCEPTANCE_CRITERION_ALLOWLIST`. |
| `nav-admin` (Svelte 5/SvelteKit plugin system) | extends | New `dev-loop` plugin: form page + live flow page + WebSocket consumer. |
| `pyproject.toml` (top-level + `packages/ai-parrot/pyproject.toml`) | extends | The `dev-loop-orchestration` capability requires `[claude-agent]` extra (transitive via FEAT-124). |
| GitHub repo settings | depends on | Webhook configured to send `pull_request.closed` events. |

### Data Models

```python
# parrot/flows/dev_loop/models.py
from typing import Annotated, Any, Dict, List, Literal, Optional, Type, Union
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────
# Acceptance criteria (discriminated union)
# ─────────────────────────────────────────────────────────────────────

class _AcceptanceCriterionBase(BaseModel):
    name: str = Field(..., description="Human-readable criterion identifier.")
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    expected_exit_code: int = Field(default=0)


class FlowtaskCriterion(_AcceptanceCriterionBase):
    kind: Literal["flowtask"] = "flowtask"
    task_path: str  # e.g. "etl/customers/sync.yaml"
    args: List[str] = Field(default_factory=list)


class ShellCriterion(_AcceptanceCriterionBase):
    kind: Literal["shell"] = "shell"
    command: str  # validated against ACCEPTANCE_CRITERION_ALLOWLIST


AcceptanceCriterion = Annotated[
    Union[FlowtaskCriterion, ShellCriterion],
    Field(discriminator="kind"),
]

# ─────────────────────────────────────────────────────────────────────
# Bug brief (BugIntakeNode input → flow context)
# ─────────────────────────────────────────────────────────────────────

class LogSource(BaseModel):
    kind: Literal["cloudwatch", "elasticsearch", "attached_file"]
    locator: str  # log-group name, ES index, or file path
    time_window_minutes: int = Field(default=60, ge=1, le=1440)


class BugBrief(BaseModel):
    summary: str = Field(..., min_length=10)
    affected_component: str
    log_sources: List[LogSource] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = Field(..., min_length=1)
    escalation_assignee: str  # Jira accountId
    reporter: str             # Jira accountId of the original human

# ─────────────────────────────────────────────────────────────────────
# Per-node dispatch outputs
# ─────────────────────────────────────────────────────────────────────

class ResearchOutput(BaseModel):
    jira_issue_key: str          # e.g. "OPS-4321"
    spec_path: str               # path inside the worktree
    feat_id: str                 # e.g. "FEAT-130"
    branch_name: str             # e.g. "feat-130-fix-customer-sync"
    worktree_path: str           # absolute, on disk
    log_excerpts: List[str]      # short, redacted


class DevelopmentOutput(BaseModel):
    files_changed: List[str]
    commit_shas: List[str]
    summary: str


class QAReport(BaseModel):
    passed: bool
    criterion_results: List["CriterionResult"]
    lint_passed: bool
    lint_output: str = ""
    notes: str = ""


class CriterionResult(BaseModel):
    name: str
    kind: Literal["flowtask", "shell"]
    exit_code: int
    duration_seconds: float
    stdout_tail: str = Field("", max_length=4000)
    stderr_tail: str = Field("", max_length=4000)
    passed: bool

# ─────────────────────────────────────────────────────────────────────
# Dispatcher contracts
# ─────────────────────────────────────────────────────────────────────

class ClaudeCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ClaudeCodeDispatcher.dispatch().

    `subagent` selects a programmatic subagent from the `agents=` dict
    passed to the SDK; when None, `system_prompt_override` is used and
    the dispatcher falls back to a generic session.
    """
    subagent: Optional[Literal["sdd-research", "sdd-worker", "sdd-qa"]] = "sdd-worker"
    system_prompt_override: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"
    setting_sources: List[Literal["user", "project", "local"]] = Field(default_factory=lambda: ["project"])
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    model: str = "claude-sonnet-4-6"


class DispatchEvent(BaseModel):
    """Envelope for stream-json events published to Redis."""
    kind: Literal[
        "dispatch.queued", "dispatch.started",
        "dispatch.message", "dispatch.tool_use", "dispatch.tool_result",
        "dispatch.output_invalid", "dispatch.failed", "dispatch.completed",
    ]
    ts: float                # POSIX timestamp seconds
    run_id: str
    node_id: str
    payload: Dict[str, Any]  # raw SDK event dict, or error context
```

### New Public Interfaces

```python
# parrot/flows/dev_loop/dispatcher.py
from typing import Type, TypeVar
from pydantic import BaseModel
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, DispatchEvent

T = TypeVar("T", bound=BaseModel)


class DispatchExecutionError(Exception):
    """Raised when the Claude Code session fails before producing a result."""

class DispatchOutputValidationError(Exception):
    """Raised when the final ResultMessage payload does not validate against
    the requested output_model. Carries `raw_payload: str` for the journal."""


class ClaudeCodeDispatcher:
    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None: ...

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: ClaudeCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
    ) -> T: ...


# parrot/flows/dev_loop/flow.py
from parrot.bots.flow import AgentsFlow

def build_dev_loop_flow(
    *,
    dispatcher: ClaudeCodeDispatcher,
    jira_toolkit,                # JiraToolkit instance, service-account
    log_toolkits: dict,          # {"cloudwatch": ..., "elasticsearch": ...}
) -> AgentsFlow: ...


# parrot/flows/dev_loop/streaming.py
from aiohttp import web

async def flow_stream_ws(request: web.Request) -> web.WebSocketResponse: ...
"""aiohttp handler bound to GET /api/flow/{run_id}/ws.

Query params:
  view: "flow" | "dispatch" | "both"  (default: "both")
  replay: bool                        (default: true)

Emits a stream of:
  {"source": "flow"|"dispatch", "node_id": str|null, "event_kind": str,
   "ts": float, "payload": dict}
"""

# parrot/flows/dev_loop/webhook.py
def register_pull_request_webhook(
    orchestrator: "AutonomousOrchestrator",
    *,
    secret: str,
) -> None:
    """Registers POST /webhooks/github/dev-loop on the orchestrator's
    WebhookListener. On `pull_request.closed`, runs `git worktree remove`
    on the matching worktree path and prunes."""
```

---

## 3. Module Breakdown

### Module 1: `parrot.flows.dev_loop.models`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` (new)
- **Responsibility**: All Pydantic v2 contracts (`BugBrief`,
  `AcceptanceCriterion` discriminated union, `ResearchOutput`,
  `DevelopmentOutput`, `QAReport`, `CriterionResult`,
  `ClaudeCodeDispatchProfile`, `DispatchEvent`, `LogSource`).
- **Depends on**: nothing internal. Imports `pydantic`.

### Module 2: `parrot.flows.dev_loop.dispatcher`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` (new)
- **Responsibility**: `ClaudeCodeDispatcher` class. Resolves profile →
  `ClaudeAgentRunOptions`, acquires global `asyncio.Semaphore`, calls
  `LLMFactory.create("claude-agent:<model>")`, iterates
  `client.ask_stream(...)`, wraps each event in `DispatchEvent`, `XADD`s to
  `flow:{run_id}:dispatch:{node_id}` (Redis Streams via `redis.asyncio`).
  On final `ResultMessage`, parses JSON-ish payload and validates against
  `output_model` (best-effort parsing — see §7 R2). Raises
  `DispatchExecutionError` / `DispatchOutputValidationError` on failure.
  Sets the stream's `MAXLEN`/`MINID` based on `FLOW_STREAM_TTL_SECONDS`.
- **Depends on**: Module 1 + FEAT-124 `ClaudeAgentClient`.

### Module 3: `parrot.flows.dev_loop.streaming`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` (new)
- **Responsibility**: aiohttp WebSocket handler that subscribes to
  `flow:{run_id}:flow` and (per active node) `flow:{run_id}:dispatch:{node_id}`
  via `XREAD BLOCK`. Optionally replays history via `XRANGE 0 +` on connect.
  Merges by timestamp and forwards as JSON envelopes
  `{source, node_id, event_kind, ts, payload}`. Honors `view` and `replay`
  query params.
- **Depends on**: Module 1, `aiohttp`, `redis.asyncio`.

### Module 4: `parrot.flows.dev_loop.nodes.bug_intake`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py` (new)
- **Responsibility**: `BugIntakeNode(Node)`. Pure AI-Parrot. Validates the
  incoming `BugBrief`: non-empty `acceptance_criteria`, every `ShellCriterion`
  command head matches `ACCEPTANCE_CRITERION_ALLOWLIST`, every
  `FlowtaskCriterion.task_path` looks like a relative path. Emits
  `flow.bug_brief_validated`. Does NOT dispatch.
- **Depends on**: Module 1.

### Module 5: `parrot.flows.dev_loop.nodes.research`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` (new)
- **Responsibility**: `ResearchNode(Node)`. Sequence:
  1. Fetch logs via `cloudwatch_tool` / `elasticsearch_tool` for each
     `LogSource`.
  2. Create the Jira ticket via `jira_toolkit.jira_create_issue(...)` with
     the service-account credentials. Reporter = original human, assignee =
     `flow-bot`.
  3. Build a `BugBrief` + log excerpts prompt and dispatch to the
     `sdd-research` subagent. The subagent is instructed to run `/sdd-spec`
     and `/sdd-task` inside the worktree path
     `.claude/worktrees/<branch_name>` (created by the subagent).
  4. Validate the dispatch output against `ResearchOutput`.
- **Depends on**: Modules 1, 2, JiraToolkit, log toolkits.

### Module 6: `parrot.flows.dev_loop.nodes.development`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` (new)
- **Responsibility**: `DevelopmentNode(Node)`. Dispatches to the
  `sdd-worker` subagent, prompt = "implement the spec at <spec_path>". Uses
  `cwd=worktree_path` from `ResearchOutput`. Validates output against
  `DevelopmentOutput`.
- **Depends on**: Modules 1, 2, 5 (consumes `ResearchOutput`).

### Module 7: `parrot.flows.dev_loop.nodes.qa`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (new)
- **Responsibility**: `QANode(Node)`. Dispatches to `sdd-qa` with a brief
  containing the list of `AcceptanceCriterion`. The subagent runs each
  criterion as a subprocess (`flowtask <task_path>` or `<command>`),
  collects exit code + tail of stdout/stderr, and runs lint
  (`ruff check . && mypy --no-incremental` by default — configurable). The
  output is a `QAReport`. The QA dispatch is `permission_mode="plan"` plus
  `allowed_tools=["Read", "Bash(...)"]` (no edits). Returns successfully even
  on test failure — the flow takes the failure transition based on
  `QAReport.passed`.
- **Depends on**: Modules 1, 2, 6.

### Module 8: `parrot.flows.dev_loop.nodes.deployment_handoff`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` (new)
- **Responsibility**: `DeploymentHandoffNode(Node)`. Pure AI-Parrot.
  Pushes the branch (via subprocess `git push -u origin <branch_name>`),
  opens a PR via the GitHub API (constructs the title/body from the spec +
  QA evidence), transitions the Jira ticket to "Ready to Deploy" via
  `jira_toolkit.jira_transition_issue(...)`, attaches the PR link as a
  comment. Retries the PR creation step ONCE on transient GitHub errors
  with backoff before falling back to a "Deployment Blocked" status.
- **Depends on**: Modules 1, 7. No Claude Code dispatch (PR creation is
  pure HTTP).

### Module 9: `parrot.flows.dev_loop.nodes.failure_handler`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` (new)
- **Responsibility**: Pure AI-Parrot helper invoked when any node hard-errors
  OR `QAReport.passed is False`. Posts a Jira comment with a structured
  failure report (the dispatched node, the error class, raw `ResultMessage`
  excerpt or QA criterion results), transitions to "Needs Human Review",
  reassigns the ticket to `BugBrief.escalation_assignee`. Ends the flow.
- **Depends on**: Modules 1, JiraToolkit.

### Module 10: `parrot.flows.dev_loop.flow`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` (new)
- **Responsibility**: `build_dev_loop_flow(dispatcher, jira_toolkit,
  log_toolkits) -> AgentsFlow`. Wires the five nodes via
  `flow.task_flow(...)` declarations, plus a `FlowTransition` from `QANode`
  that branches on `result.passed`:
  - `passed=True` → `DeploymentHandoffNode`
  - `passed=False` → `FailureHandlerNode`
  And a global error transition that routes any node hard-error to the
  failure handler.
- **Depends on**: Modules 4–9.

### Module 11: `parrot.flows.dev_loop.webhook`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/webhook.py` (new)
- **Responsibility**: `register_pull_request_webhook(orchestrator, secret)`
  uses `orchestrator.register_webhook(path="/github/dev-loop",
  target_type="agent", target_id="dev-loop-cleanup", secret=secret,
  transform_fn=...)` (`orchestrator.py:646`). The handler runs
  `git worktree remove .claude/worktrees/<branch>` and `git worktree prune`
  when GitHub delivers a `pull_request.closed` event whose head-branch
  matches `feat-<id>-*`.
- **Depends on**: `AutonomousOrchestrator` + `WebhookListener`.

### Module 12: Settings & registry wiring
- **Path**: `packages/ai-parrot/src/parrot/conf.py` + a tiny additions
  module if needed.
- **Responsibility**: Add the six new navconfig settings listed in §2
  Integration Points. Defaults:
  - `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES = 3`
  - `FLOW_MAX_CONCURRENT_RUNS = 5`
  - `FLOW_BOT_JIRA_ACCOUNT_ID = ""` (must be set per env)
  - `WORKTREE_BASE_PATH = ".claude/worktrees"`
  - `FLOW_STREAM_TTL_SECONDS = 604800` (7 days)
  - `ACCEPTANCE_CRITERION_ALLOWLIST = ["flowtask", "pytest", "ruff", "mypy", "pylint"]`
- **Depends on**: nothing.

### Module 13: SDD subagent definitions
- **Path**: `.claude/agents/sdd-research.md`, `.claude/agents/sdd-qa.md`
  (new). `.claude/agents/sdd-worker.md` already exists and is reused.
- **Responsibility**: Filesystem subagent definitions loaded by Claude Code
  via `setting_sources=["project"]`. The same definitions are also passed
  programmatically as `ClaudeAgentOptions.agents={...}` so they work
  regardless of whether the worktree's `.claude/agents/` directory has
  been refreshed.
- **Depends on**: nothing internal.

### Module 14: nav-admin Svelte plugin
- **Path**: navigator nav-admin plugin tree (separate repo / package).
- **Responsibility**: One form page (`/dev-loop/new`) and one live page
  (`/dev-loop/run/<run_id>`). The live page opens a WebSocket to the
  multiplexer, renders a SvelteFlow canvas for the five nodes, and per-node
  panels showing the merged event stream. UI never imports a Redis client.
- **Depends on**: Module 3 (the WebSocket envelope schema).

### Module 15: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/` (new directory).
- **Responsibility**: Unit + integration tests as detailed in §4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_bug_brief_rejects_empty_criteria` | M1 | `BugBrief(acceptance_criteria=[], …)` raises `ValidationError`. |
| `test_acceptance_criterion_discriminated_union_round_trip` | M1 | `BugBrief.model_validate({"...","acceptance_criteria":[{"kind":"flowtask",...}]})` produces a `FlowtaskCriterion`. |
| `test_shell_criterion_command_must_be_in_allowlist` | M4 | `BugIntakeNode` rejects a `ShellCriterion(command="rm -rf /")` against the default allowlist. |
| `test_dispatcher_acquires_and_releases_semaphore` | M2 | Mocked `ClaudeAgentClient.ask_stream` → semaphore goes from N=3 to N=2 during dispatch and back to N=3 after. Concurrent 4th call blocks. |
| `test_dispatcher_publishes_dispatch_events` | M2 | Mocked stream yields one `AssistantMessage` and one `ResultMessage`; dispatcher publishes 3 `DispatchEvent`s (`started`, `message`, `completed`). |
| `test_dispatcher_validates_output_model` | M2 | Mocked `ResultMessage` payload `{"foo":"bar"}` against `output_model=ResearchOutput` raises `DispatchOutputValidationError`. |
| `test_dispatcher_propagates_session_failure` | M2 | `ClaudeAgentClient.ask_stream` raises mid-stream → dispatcher publishes `dispatch.failed` event and re-raises `DispatchExecutionError`. |
| `test_dispatch_profile_to_run_options` | M2 | A `ClaudeCodeDispatchProfile(subagent="sdd-worker", allowed_tools=["Read","Edit","Bash"])` produces `ClaudeAgentRunOptions(cwd=..., agents={"sdd-worker": …}, allowed_tools=["Read","Edit","Bash"], permission_mode="default", setting_sources=["project"])`. |
| `test_dispatch_profile_generic_session_fallback` | M2 | `subagent=None, system_prompt_override="..."` produces options with `agents=None` and `system_prompt="..."`. |
| `test_research_node_creates_jira_then_dispatches` | M5 | Mocked `JiraToolkit.jira_create_issue` returns `OPS-1`; mocked dispatcher returns a valid `ResearchOutput`. The node calls Jira BEFORE dispatch (verified via call order on the mock). |
| `test_qa_node_returns_failure_without_raising` | M7 | Dispatch returns `QAReport(passed=False, …)`. The node returns the report; the *flow* takes the failure path, but the node itself does not raise. |
| `test_qa_node_dispatch_uses_plan_permission` | M7 | The dispatch profile passed to the dispatcher has `permission_mode="plan"` and no `Edit`/`Write` in `allowed_tools`. |
| `test_deployment_handoff_retries_pr_once` | M8 | First `gh api` call raises 502; second succeeds; node returns success and posts the PR link to Jira. |
| `test_failure_handler_reassigns_to_escalation` | M9 | The Jira `assignee` set on the failure path equals `BugBrief.escalation_assignee`. |
| `test_flow_qa_pass_routes_to_handoff` | M10 | A `QAReport(passed=True)` triggers the transition to `DeploymentHandoffNode`. |
| `test_flow_qa_fail_routes_to_failure_handler` | M10 | A `QAReport(passed=False)` triggers the transition to `FailureHandlerNode`. |
| `test_flow_node_hard_error_routes_to_failure_handler` | M10 | A `DispatchExecutionError` raised by `DevelopmentNode` triggers the failure handler. |
| `test_stream_multiplexer_replay_then_subscribe` | M3 | Two pre-seeded streams: replays history ordered by `ts`, then forwards new events from `XREAD BLOCK`. |
| `test_stream_multiplexer_view_filter` | M3 | `?view=flow` only forwards events whose `source=="flow"`. |
| `test_pr_webhook_removes_worktree` | M11 | Mocked GitHub `pull_request.closed` payload triggers a subprocess `git worktree remove .claude/worktrees/<branch>` + `prune`. |
| `test_pr_webhook_ignores_non_dev_loop_branches` | M11 | Branch `dependabot/...` is ignored (no subprocess call). |
| `test_settings_defaults` | M12 | `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`, `FLOW_MAX_CONCURRENT_RUNS`, `FLOW_STREAM_TTL_SECONDS`, `ACCEPTANCE_CRITERION_ALLOWLIST` resolve to documented defaults when no env override is set. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_happy_path` (`@pytest.mark.live`) | Real `claude-agent-sdk` + a fixture worktree containing a deliberately-broken Flowtask YAML. Runs the full flow: `BugIntake → Research → Development → QA → DeploymentHandoff`. Skipped if `claude` CLI / `ANTHROPIC_API_KEY` is unavailable. |
| `test_end_to_end_qa_failure_path` (`@pytest.mark.live`) | Same setup, but the dev node deliberately fails to fix the bug. Asserts the ticket ends in "Needs Human Review" and the PR is NOT created. |
| `test_concurrent_flows_respect_dispatcher_cap` | Spawn 4 flow runs in parallel with `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES=2`. Assert that at most 2 dispatches are in flight at any time (verified via Redis stream timestamps). |
| `test_websocket_replay_after_disconnect` | Start a flow run, let it produce 5 events, disconnect the WebSocket, reconnect with `replay=true`. Assert all 5 historical events are received in order before live events. |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/flows/dev_loop/conftest.py
import pytest
from parrot.flows.dev_loop.models import (
    BugBrief, FlowtaskCriterion, ShellCriterion, LogSource,
)


@pytest.fixture
def sample_bug_brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync flowtask drops the last row when the input has >1000 records",
        affected_component="etl/customers/sync.yaml",
        log_sources=[LogSource(kind="cloudwatch", locator="/etl/prod/customers", time_window_minutes=120)],
        acceptance_criteria=[
            FlowtaskCriterion(name="customers-sync-passes",
                              task_path="etl/customers/sync.yaml",
                              expected_exit_code=0),
            ShellCriterion(name="lint-clean", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def fake_dispatch_messages():
    """Mimics the message stream that ClaudeAgentClient.ask_stream() yields."""
    from claude_agent_sdk.types import (
        AssistantMessage, TextBlock, ResultMessage,
    )
    return [
        AssistantMessage(content=[TextBlock(text='{"jira_issue_key":"OPS-1","spec_path":"sdd/specs/x.spec.md",')]),
        AssistantMessage(content=[TextBlock(text='"feat_id":"FEAT-130","branch_name":"feat-130-fix",')]),
        AssistantMessage(content=[TextBlock(text='"worktree_path":"/abs/.claude/worktrees/feat-130-fix","log_excerpts":[]}')]),
        ResultMessage(subtype="success", num_turns=1, total_cost_usd=0.01),
    ]
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `parrot/flows/dev_loop/` exists with `models.py`, `dispatcher.py`,
  `streaming.py`, `flow.py`, `webhook.py`, and `nodes/` (six node files).
- [ ] All Pydantic v2 contracts in `models.py` validate per §4 unit tests.
- [ ] `ClaudeCodeDispatcher.dispatch(...)` resolves the profile to
  `ClaudeAgentRunOptions` with `cwd`, `agents`, `allowed_tools`,
  `permission_mode`, `setting_sources` set as documented in §2.
- [ ] `ClaudeCodeDispatcher` enforces `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`
  via an `asyncio.Semaphore`. Concurrent calls beyond the cap block until a
  slot is free.
- [ ] Every event emitted by `ClaudeAgentClient.ask_stream(...)` is wrapped
  in a `DispatchEvent` and `XADD`-published to
  `flow:{run_id}:dispatch:{node_id}` with `MAXLEN ~ floor(ttl_seconds / 60)`.
- [ ] On a final `ResultMessage`, the dispatcher validates the payload
  against `output_model` and returns a typed instance, OR raises
  `DispatchOutputValidationError` with the raw payload available for the
  audit log.
- [ ] `BugIntakeNode` rejects a brief whose `ShellCriterion.command` head
  is not in `ACCEPTANCE_CRITERION_ALLOWLIST`.
- [ ] `ResearchNode` creates the Jira ticket BEFORE dispatching (verified
  by mock call ordering).
- [ ] `DevelopmentNode` dispatches with `subagent="sdd-worker"`,
  `permission_mode="acceptEdits"`, and `cwd` from the upstream
  `ResearchOutput`.
- [ ] `QANode` dispatches with `permission_mode="plan"` and no `Edit`/`Write`
  in `allowed_tools`. The node returns successfully even when
  `QAReport.passed is False`.
- [ ] The flow built by `build_dev_loop_flow(...)` routes
  `QAReport.passed=True` to `DeploymentHandoffNode` and `False` to
  `FailureHandlerNode`. Any `DispatchExecutionError` /
  `DispatchOutputValidationError` raised by a middle node also routes to
  `FailureHandlerNode`.
- [ ] `DeploymentHandoffNode` pushes the branch, opens a PR, transitions
  the Jira ticket to "Ready to Deploy", and posts the PR URL as a comment
  signed by `flow-bot`.
- [ ] `FlowStreamMultiplexer` (aiohttp WebSocket handler) replays history
  on connect when `replay=true` and forwards new events live; honors
  `view=flow|dispatch|both`.
- [ ] `register_pull_request_webhook(orchestrator, secret)` registers a
  `/github/dev-loop` endpoint on the existing `WebhookListener`. A
  `pull_request.closed` payload whose head branch matches `feat-*` triggers
  `git worktree remove`.
- [ ] All new settings exist in `parrot.conf` with documented defaults.
- [ ] All unit tests in §4 pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`.
- [ ] At least one of the live integration tests passes against a real
  worktree on a developer machine.
- [ ] Documentation: a short section in the package README under "Optional
  capabilities" describes how to enable the dev-loop flow and what it does.
- [ ] No breaking changes to `AgentsFlow`, `JiraToolkit`,
  `AutonomousOrchestrator`, or `ClaudeAgentClient` public APIs.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below is verified by `grep`/`read` against the current
> working tree (`dev` branch, after FEAT-128).

### Verified Imports

```python
# Existing — keep using these verbatim.
from parrot.bots.flow import AgentsFlow, FlowTransition, InteractiveDecisionNode
# verified: parrot/bots/flow/__init__.py:22 (InteractiveDecisionNode export)
# verified: parrot/bots/flow/fsm.py:277 (AgentsFlow), :116 (FlowTransition)
from parrot.bots.flow.node import Node                    # node.py:14
from parrot.bots.flow.fsm import FlowNode                  # fsm.py:198

from parrot.tools.toolkit import AbstractToolkit           # toolkit.py:168
# AbstractToolkit._pre_execute / _post_execute confirmed at toolkit.py:131,156,164,261

from parrot_tools.jiratoolkit import JiraToolkit           # ai-parrot-tools pkg, jiratoolkit.py:609
from parrot_tools.elasticsearch import ElasticsearchTool   # ai-parrot-tools pkg, elasticsearch.py:167
# Verify on /sdd-task: parrot_tools.aws.cloudwatch CloudWatch tool class name and exports
# (file confirmed at packages/ai-parrot-tools/src/parrot_tools/aws/cloudwatch.py)

from parrot.autonomous.orchestrator import AutonomousOrchestrator  # orchestrator.py:112
# NB: class is `AutonomousOrchestrator`, NOT `AutonomyOrchestrator` (brainstorm typo).
# orchestrator.register_webhook(path, target_type, target_id, *, secret, transform_fn, ...)
# verified: orchestrator.py:646

from parrot.auth.credentials import StaticCredentialResolver, StaticCredentials
# verified: auth/credentials.py:81 (StaticCredentialResolver), :71 (StaticCredentials)
# NB: `parrot.auth`, NOT `parrot.security`.
from parrot.auth.permission import PermissionContext       # auth/permission.py:80

from parrot.clients import AbstractClient                  # clients/__init__.py:6
from parrot.clients.factory import LLMFactory              # factory.py:38
# Once FEAT-124 merges:
# from parrot.clients.claude_agent import ClaudeAgentClient, ClaudeAgentRunOptions
# (deliberately NOT re-exported from parrot.clients.__init__ per FEAT-124)

from parrot.conf import config                              # conf.py:5 (navconfig.config)

# claude-agent-sdk — already in [claude-agent] extra via FEAT-124
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AgentDefinition
# verified: claude_agent_sdk/types.py:82 (AgentDefinition), :1296+ (ClaudeAgentOptions)
from claude_agent_sdk.types import (
    AssistantMessage, UserMessage, SystemMessage, ResultMessage,
    TextBlock, ToolUseBlock, ToolResultBlock,
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/flow/fsm.py
class FlowTransition:                                      # line 116
    async def should_activate(self, result: Any,
                              error: Optional[Exception] = None) -> bool: ...   # line 136
    async def build_prompt(self, ...) -> str: ...                               # line 164

class FlowNode(Node):                                      # line 198
    def __post_init__(self) -> None: ...                                        # line 226
    @property
    def name(self) -> str: ...                                                  # line 230
    def is_terminal(self) -> bool: ...                                          # line 235
    def can_retry(self) -> bool: ...                                            # line 240
    def add_transition(self, transition: FlowTransition) -> None: ...           # line 244
    async def get_active_transitions(self, ...) -> List[FlowTransition]: ...    # line 250
    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> Any: ...       # line 266

class AgentsFlow(PersistenceMixin, SynthesisMixin):        # line 277
    def __init__(self, ...): ...                                                # line 316
    def add_agent(self, ref: AgentRef, ...): ...                                # line 397
    def add_start_node(self, name: str, ...): ...                               # line 456
    def add_end_node(self, name: str, ...): ...                                 # line 483
    def task_flow(self, ...): ...                                               # line 505
    def on_success(self, ...): ...                                              # line 631
    def on_error(self, ...): ...                                                # line 645
    def on_condition(self, ...): ...                                            # line 659
    async def run_flow(self, ...): ...                                          # line 675

# packages/ai-parrot/src/parrot/bots/flow/node.py
class Node(ABC):                                           # line 14
    def _init_node(self, name: str) -> None: ...                                # line 48
    @property
    def name(self) -> str: ...                                                  # line 61
    def add_pre_action(self, action: ActionCallback) -> None: ...               # line 66
    def add_post_action(self, action: ActionCallback) -> None: ...              # line 70
    async def run_pre_actions(self, ...) -> None: ...                           # line 76
    async def run_post_actions(self, ...) -> None: ...                          # line 92

# packages/ai-parrot/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:                              # line 112
    def __init__(self, ...): ...                                                # line 148
    async def start(self): ...                                                  # line 202
    async def stop(self): ...                                                   # line 239
    def setup_routes(self, app): ...                                            # line 253
    def add_hook(self, hook: BaseHook) -> str: ...                              # line 289
    async def execute_agent(self, ...): ...                                     # line 358
    async def execute_crew(self, ...): ...                                      # line 393
    async def inject_job(self, ...): ...                                        # line 585
    def register_webhook(
        self, path: str, target_type: Literal["agent", "crew"],
        target_id: str, *, secret: Optional[str] = None,
        transform_fn: Optional[Callable[[Dict], str]] = None,
        execution_mode: Optional[str] = None, **kwargs,
    ): ...                                                                      # line 646
    def on_event(self, pattern: str, ...): ...                                  # line 690
    async def emit_event(self, ...): ...                                        # line 749
    def _generate_session_id(self) -> str: ...                                  # line 1119
    def get_stats(self) -> Dict[str, Any]: ...                                  # line 1147

# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC): ...                         # line 27
class StaticCredentials: ...                               # line 71
class StaticCredentialResolver(CredentialResolver):        # line 81
    def __init__(self, credentials: StaticCredentials, ...): ...                # line 89
    async def resolve(self, channel: str, user_id: str) -> StaticCredentials: ...  # line 105

# packages/ai-parrot/src/parrot/auth/permission.py
class PermissionContext:                                   # line 80
    @property
    def user_id(self) -> str: ...                                               # line 123
    @property
    def tenant_id(self) -> str: ...                                             # line 128
    @property
    def roles(self) -> frozenset[str]: ...                                      # line 133
    def has_role(self, role: str) -> bool: ...                                  # line 137
    def has_any_role(self, roles: set[str] | frozenset[str]) -> bool: ...       # line 148

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                # line 168
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...         # line 261
    # Lifecycle wrap-around at line 156: `_pre_execute(...)` → bound method →
    # `_post_execute(...)`. JiraToolkit uses `_pre_execute` for credential
    # resolution (see comment at line 163).

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                        # line 609
    def __init__(self, *, server_url: str = ..., auth_type: Optional[str] = None,
                 user_id: Optional[str] = None, ...): ...                       # line 667
    async def jira_create_issue(self, ...): ...                                 # line 1366
    # (other methods: jira_transition_issue, jira_add_comment, jira_attach_file
    #  are referenced by parrot/bots/jira_specialist.py:1639+ — to verify
    #  exact signatures during /sdd-task)

# packages/ai-parrot-tools/src/parrot_tools/elasticsearch.py
class ElasticsearchTool(AbstractTool):                     # line 167

# claude_agent_sdk/types.py — relevant fields on ClaudeAgentOptions:
class ClaudeAgentOptions:
    allowed_tools: list[str]                               # line 1346
    permission_mode: PermissionMode | None                 # line 1349
    disallowed_tools: list[str]                            # line 1355
    cwd: str | Path | None                                 # line 1361 ✓ (resolves brainstorm Q)
    cli_path: str | Path | None
    settings: str | None
    add_dirs: list[str | Path]
    env: dict[str, str]
    extra_args: dict[str, str | None]                      # for --json-schema flag etc.
    can_use_tool: CanUseTool | None
    hooks: dict[HookEvent, list[HookMatcher]] | None
    user: str | None
    include_partial_messages: bool
    fork_session: bool
    agents: dict[str, AgentDefinition] | None              # line 1389 ✓ programmatic subagents
    setting_sources: list[SettingSource] | None            # line 1391
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ClaudeCodeDispatcher.dispatch` | `ClaudeAgentClient.ask_stream` | iterator + DispatchEvent wrap | FEAT-124 spec §2 (to be merged) |
| `ClaudeCodeDispatcher` | `LLMFactory.create("claude-agent:<model>")` | factory call | FEAT-124 + `factory.py:38` |
| `BugIntakeNode` / `ResearchNode` / etc. | `Node` ABC | inheritance | `parrot/bots/flow/node.py:14` |
| `build_dev_loop_flow` | `AgentsFlow.task_flow`, `add_start_node`, `add_end_node` | method calls | `fsm.py:456,483,505` |
| `ResearchNode` / handoff / failure | `JiraToolkit.jira_create_issue`, `jira_transition_issue`, `jira_add_comment` | method calls | `jiratoolkit.py:1366` (others to verify) |
| `register_pull_request_webhook` | `AutonomousOrchestrator.register_webhook` | call | `orchestrator.py:646` |
| `JiraToolkit` | `StaticCredentialResolver` | `_pre_execute` hook resolves creds | `toolkit.py:131,156,164` |
| `FlowStreamMultiplexer` | aiohttp `WebSocketResponse` | router registration on the same aiohttp app that hosts `nav-admin` | `aiohttp` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.flows`~~ as a package — does not exist; we create
  `parrot.flows.dev_loop` as a brand-new sibling under `parrot/`. **Note
  the divergence from convention**: existing flow code lives at
  `parrot.bots.flow`. The new package is named `parrot.flows.dev_loop`
  because it is *application-level* orchestration (a specific feature
  flow), not the FSM primitive. If the maintainer prefers
  `parrot.bots.flow.dev_loop`, the spec accepts that placement —
  see §8 Open Questions.
- ~~`parrot.toolkits`~~ — there is no `parrot.toolkits` package. Toolkits
  live in `parrot.tools` (single-package) or `parrot_tools.*` (sibling
  package `ai-parrot-tools`). Use the latter import path.
- ~~`parrot.security.PermissionContext`~~,
  ~~`parrot.security.StaticCredentialResolver`~~ — both are in
  `parrot.auth.permission` and `parrot.auth.credentials` respectively.
- ~~`parrot.orchestrator.AutonomyOrchestrator`~~ — the actual class is
  `AutonomousOrchestrator` and lives at `parrot.autonomous.orchestrator`.
- ~~`parrot.memory.JournalWriter`~~ — does not exist. Replace audit calls
  with `self.logger.info(...)` and (optionally) Redis-stream entries on
  `flow:{run_id}:flow`. A dedicated `JournalWriter` is out of scope for
  v1.
- ~~`parrot.tools.cloudwatch`~~ — the CloudWatch tool lives in the
  sibling package: `parrot_tools.aws.cloudwatch`.
- ~~`AcceptanceCriterion.kind == "regex_match"` / `"output_match"` /
  `"http_check"` / `"pytest"`~~ — v1 implements only `flowtask` and
  `shell`. Other kinds are extensible without flow changes but are NOT
  in v1.
- ~~`ClaudeCodeDispatcher.retry()`~~ — explicitly out of scope.
- ~~`ClaudeAgentClient.dispatch_subagent(...)`~~ — the dispatcher does
  not extend the client. Subagent selection happens via
  `ClaudeAgentRunOptions.agents={...}`.
- ~~`AbstractClient` `complete_async`~~ — base method is `complete()`
  (`base.py:627` per FEAT-124).
- ~~Auto-PR-merge / voting bypass~~ — flow stops at PR open.
- ~~Telegram HITL escalation~~ — out of scope for v1.
- ~~Knative microservice deployment~~ — out of scope for v1.
- ~~In-process MCP server migration~~ — out of scope (per FEAT-124).
- ~~Multi-repo support~~ — single-repo only for v1.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first**: every node's `execute(...)` is `async def`. The
  dispatcher and the multiplexer are async throughout. No blocking I/O.
- **Pydantic v2 for all contracts**: dispatcher inputs/outputs and the
  `AcceptanceCriterion` discriminated union all use Pydantic v2
  (`Annotated`, `Field(discriminator=...)`).
- **Lazy SDK access**: never import `claude_agent_sdk` at module top
  level inside `parrot/flows/dev_loop/`. Always go through
  `LLMFactory.create("claude-agent:<model>")` (FEAT-124's lazy loader),
  so a `pip install ai-parrot` without `[claude-agent]` does not break
  `import parrot.flows.dev_loop.models`.
- **Per-loop client cache**: rely on `AbstractClient._ensure_client`
  (per FEAT-124) — do NOT instantiate `ClaudeSDKClient` directly.
- **Logger over print**: every node and the dispatcher use `self.logger`
  (configured by their parent class).
- **navconfig**: read settings via `from parrot.conf import config` and
  `config.get("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", default=3)`.
- **JiraToolkit credential context**: `_pre_execute` resolves credentials
  from a `StaticCredentialResolver` injected at toolkit construction
  time. Pass `user_id="flow-bot"` so the resolver returns the
  service-account token.
- **Worktree path**: derived as
  `{config.WORKTREE_BASE_PATH}/{branch_name}` where `branch_name` is the
  `feat-<id>-<slug>` string emitted by the `sdd-research` subagent.
- **PR construction**: `DeploymentHandoffNode` uses `gh pr create` via
  subprocess for parity with the human workflow described in CLAUDE.md.
  An HTTP-based fallback (`PyGithub`) is acceptable but not preferred.
- **Subagent definitions are dual-sourced**: keep `.claude/agents/sdd-*.md`
  files committed AND embed the same definitions inline as
  `ClaudeAgentOptions.agents={...}` so dispatches do not depend on the
  worktree containing fresh `.claude/agents/` content.

### Known Risks / Gotchas

- **R1 — Hard dependency on FEAT-124**. This feature cannot ship until
  FEAT-124 is merged. If FEAT-124 slips, scheduling slips.
  **Mitigation**: track FEAT-124's status; coordinate any extension
  needed (e.g., `cwd`, `agents`, `setting_sources` exposure on
  `ClaudeAgentRunOptions`) as small additions to FEAT-124 rather than
  forking.
- **R2 — JSON-schema structured output is not directly exposed by
  `claude-agent-sdk` v0.1.68**. The SDK has `extra_args` for arbitrary
  CLI flags, so passing `extra_args={"output-format": "json",
  "json-schema": "<path>"}` may work, but this is not validated.
  **v1 falls back to best-effort parsing** of the final `ResultMessage`:
  the dispatcher reads the concatenated `TextBlock` text from the last
  `AssistantMessage`, attempts `output_model.model_validate_json(text)`,
  and on failure raises `DispatchOutputValidationError`. The subagent
  prompts must include explicit "respond with JSON matching <schema>"
  instructions. Track structured-output as a v2 enhancement.
- **R3 — Programmatic subagents require `claude-agent-sdk>=0.1.5x`**.
  FEAT-124 already pins `>=0.1.68`, so this is satisfied. Verify on the
  CI matrix before merge.
- **R4 — `permission_mode="acceptEdits"` for `DevelopmentNode` is
  high-power** (it can edit any file under `cwd`). Mitigation: enforce
  `cwd=worktree_path`, refuse dispatch if `worktree_path` is not under
  `WORKTREE_BASE_PATH`. Surface this check in `ClaudeCodeDispatcher`
  itself, not the node — defense in depth.
- **R5 — Worktree already exists** (e.g., a previous run left a stale
  one for the same FEAT-id): `ResearchNode` detects this and fails
  fast with a clear message instructing the human to run cleanup. v1
  does no automatic recovery.
- **R6 — `AcceptanceCriterion.command` shell injection**. v1
  ALLOWLIST is `{flowtask, pytest, ruff, mypy, pylint}` — only the
  command head is checked. Implementers MUST pass commands as a list
  to `subprocess.exec` (not `shell=True`) inside the QA dispatch.
  Operators can extend the allowlist via the navconfig setting.
- **R7 — Stream consumer (UI) disconnect mid-flow**. Both Redis streams
  retain events for `FLOW_STREAM_TTL_SECONDS` (default 7 days). The user
  reloads the page; the multiplexer replays history before forwarding
  live events. Done via `XRANGE 0 +` then `XREAD BLOCK $`.
- **R8 — Process-level abandonment**. If the flow process crashes
  mid-dispatch, there is no resume in v1. The orchestrator marks the
  run as "abandoned"; the worktree remains; a human takes over. v2 may
  add resume on top of `claude-agent-sdk`'s session resume.
- **R9 — PR creation race**. Two flows accidentally targeting the same
  ticket / branch: CLAUDE.md's `feat-<id>-<slug>` convention makes this
  vanishingly unlikely, but a flow-level lock keyed on FEAT-id is added
  by the orchestrator to prevent concurrent runs against the same
  feature ID.
- **R10 — `parrot.flows` package name divergence**. The existing FSM
  primitive lives at `parrot.bots.flow`. We introduce `parrot.flows`
  as a higher-level "application flows" namespace. Reviewers may
  prefer `parrot.bots.flow.dev_loop` for consistency. This decision is
  open in §8 — if changed, all import paths in this spec must be
  updated.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `claude-agent-sdk` | `>=0.1.68` | Programmatic subagents (`agents=` field) and `cwd` exposure on `ClaudeAgentOptions`. Already pinned via FEAT-124's `[claude-agent]` extra. |
| `pydantic` | `>=2.0` | All contracts use v2-only features (`Annotated`, `discriminator`). Already pinned by parent. |
| `aiohttp` | (existing) | Multiplexer + UI server. Already in core deps. |
| `redis[asyncio]` | (existing) | Two streams + `XREAD BLOCK`. Already in core deps. |
| `gh` CLI | runtime | `DeploymentHandoffNode.create_pr` uses `gh pr create`. Document as a runtime requirement. |

---

## Worktree Strategy

- **Default isolation unit**: **mixed**.
- **Core code worktree** (`per-spec` group): `parrot/flows/dev_loop/`
  including `models.py`, `dispatcher.py`, `streaming.py`, all five `nodes/*.py`,
  `flow.py`, `webhook.py`, the navconfig additions, and the unit/integration
  tests. The five nodes share imports and tight contracts; splitting them
  across worktrees would create constant rebase pain.
- **UI worktree** (separate, can start after multiplexer schema is locked):
  the nav-admin Svelte plugin (`Module 14`).
- **Subagent definitions** (`Module 13`, `.claude/agents/sdd-*.md`): these
  are project config, not in the AI-Parrot codebase. They commit on the
  same branch as the core code so the worktree-aware integration test can
  load them.
- **Cross-feature dependencies**: hard dependency on **FEAT-124**
  (`ClaudeAgentClient`, `ClaudeAgentRunOptions`, `LLMFactory` registration).
  Soft dependency on **FEAT-107/108** (`JiraToolkit` OAuth + auth_type
  unification). This feature uses `StaticCredentialResolver` directly so
  it does not block on FEAT-107's OAuth flow being live, but uses the
  resolver abstraction shipped by FEAT-107.
- **Recommended worktree creation** (after `/sdd-task`):
  ```bash
  git checkout dev && git pull origin dev
  git worktree add -b feat-129-dev-loop-orchestration \
    .claude/worktrees/feat-129-dev-loop-orchestration HEAD
  ```

---

## 8. Open Questions

### Resolved (carried forward from brainstorm)

- [x] Dispatcher = class, subclass, or MCP toolkit? — *Resolved in
  brainstorm*: Option A (class). Rationale: clients are transports;
  orchestration lives elsewhere. Keeps `ClaudeAgentClient` reusable for
  non-flow agents.
- [x] Convention vs explicit subagent prompts? — *Resolved in brainstorm*:
  Convention over configuration — `sdd-*` subagents by default; profile
  flag `subagent: str | None = None` permits a generic-session fallback
  with explicit `system_prompt_override`.
- [x] One Redis stream per run, or two? — *Resolved in brainstorm*: Two
  streams (flow + per-dispatch). aiohttp WebSocket multiplexer reconciles
  them for the UI; frontend never speaks Redis.
- [x] Worktree cleanup — flow's job or external? — *Resolved in
  brainstorm*: External. Two paths: human runs `/sdd-done`; or
  `AutonomousOrchestrator` listens for GitHub `pull_request.closed` and
  runs cleanup automatically.
- [x] Concurrency control — global, two-level? — *Resolved in
  brainstorm*: Two-level. `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES=3` on
  the dispatcher + `FLOW_MAX_CONCURRENT_RUNS=5` on the orchestrator.
- [x] Jira identity? — *Resolved in brainstorm*: Service account
  (`flow-bot@company`) via `StaticCredentialResolver`. Reporter and
  assignee remain the original human; only comments, attachments, and
  transitions written by the bot.
- [x] Failure path — retry or escalate? — *Resolved in brainstorm*:
  Hand off to human. No retry semantics in v1.
- [x] Acceptance criteria — single command or list? — *Resolved in
  brainstorm*: List of `AcceptanceCriterion` with discriminated `kind`.
  v1: `flowtask`, `shell`. Others extensible without flow changes.
- [x] PR creation — flow auto-merges or stops at PR open? — *Resolved
  in brainstorm*: Stops at PR open. Repo has voting rules requiring
  human approvals.
- [x] Subagent invocation mechanism — *Resolved by codebase research*:
  `ClaudeAgentOptions.agents: dict[str, AgentDefinition]` is exposed
  upstream (`claude_agent_sdk/types.py:1389`). FEAT-124's
  `ClaudeAgentRunOptions` must surface this field; it is the primary
  mechanism (filesystem subagents via `setting_sources=["project"]`
  are a redundant safety net).
- [x] `ClaudeAgentRunOptions.cwd` exposure — *Resolved by codebase
  research*: `ClaudeAgentOptions.cwd: str | Path | None` exists upstream
  (`claude_agent_sdk/types.py:1361`). FEAT-124 already lists `cwd` on
  the options model.
- [x] `AbstractToolkit._pre_execute` / `_post_execute` merged? —
  *Resolved by codebase research*: yes, both exist
  (`parrot/tools/toolkit.py:131,156,164,261`). JiraToolkit relies on
  `_pre_execute` for credential resolution.
- [x] `AgentsFlow` async support and structured payload passing? —
  *Resolved by codebase research*: yes, `async def run_flow(...)`
  (`fsm.py:675`) and `FlowNode.execute(prompt, ctx) -> Any`
  (`fsm.py:266`) carry typed payloads via `ctx`. Spec adopts this
  pattern as-is.
- [x] `AutonomousOrchestrator` GitHub webhook pattern? — *Resolved by
  codebase research*: `register_webhook(path, target_type, target_id, *,
  secret, transform_fn, …)` at `orchestrator.py:646`. HMAC validation is
  delegated to the `WebhookListener` (`autonomous/webhooks.py`).
- [x] Stream TTL default — *Resolved (brainstorm proposal accepted)*:
  7 days, configurable via `FLOW_STREAM_TTL_SECONDS`.
- [x] AcceptanceCriterion v1 allowlist — *Resolved (brainstorm proposal
  accepted)*: `{flowtask, pytest, ruff, mypy, pylint}`, configurable
  via `ACCEPTANCE_CRITERION_ALLOWLIST` navconfig setting.
- [x] Flow run identifier scheme — *Resolved by codebase research*:
  `AutonomousOrchestrator._generate_session_id()` at `orchestrator.py:1119`
  is the source for `run_id`. The flow consumes it, does not mint its
  own.

### Still Open Questions

- [x] **Package placement**: should the new code live at
  `parrot/flows/dev_loop/` (proposed) or `parrot/bots/flow/dev_loop/`
  (more consistent with the existing FSM location)? — *Owner: Jesus,
  before /sdd-task.* Proposed default if no objection: keep
  `parrot/flows/dev_loop/`, since this is application-level
  orchestration distinct from the FSM primitive: `parrot/flows/dev_loop/` allowing creating more kind of flows.
- [x] **JSON-schema structured output**: try `extra_args={"output-format":
  "json", "json-schema": "..."}` in v1 (alongside best-effort parsing as
  fallback), or defer entirely to v2? — *Owner: agent doing /sdd-task
  for Module 2*: add json-schema outputs in v1 (current scope)
- [x] **Worktree base path collision**: confirm during /sdd-task that no
  two concurrent flow runs can produce the same `feat-<id>-<slug>`
  branch (the orchestrator-level lock on FEAT-id is the proposed
  defense). — *Owner: agent doing /sdd-task for Module 5*: yes,. there is no collision.
- [x] **PR creation transport**: `gh` CLI subprocess (proposed) or
  `PyGithub` HTTP? — *Owner: agent doing /sdd-task for Module 8*.
  Decidable during implementation; not blocking: check first if `gh` exists or rely on pygithub (there is a Github toolkit too using pygithub as well).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-27 | Jesus Lara | Initial draft from `sdd/proposals/dev-loop-orchestration.brainstorm.md`. Carries forward 9 brainstorm-resolved questions plus 7 codebase-research-resolved questions. Corrects brainstorm's `parrot.security.*` / `AutonomyOrchestrator` / `JournalWriter` / `parrot.toolkits.*` references against the actual codebase: classes live in `parrot.auth`, `parrot.autonomous` (`AutonomousOrchestrator`), and `parrot_tools.*` (sibling package). `JournalWriter` does not exist and is dropped from v1. |
