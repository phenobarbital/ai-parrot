---
type: Wiki Overview
title: 'Feature Specification: Dev-Loop Orchestration with Claude Code Subagent Mirror'
id: doc:sdd-specs-dev-loop-orchestration-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The development feedback loop for "small operational fixes" today is entirely
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.autonomous.webhooks
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.claude_agent
  rel: mentions
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.flows
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.bug_intake
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.deployment_handoff
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.development
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.failure_handler
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.qa
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.research
  rel: mentions
- concept: mod:parrot.flows.dev_loop.streaming
  rel: mentions
- concept: mod:parrot.flows.dev_loop.webhook
  rel: mentions
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.aws.cloudwatch
  rel: mentions
- concept: mod:parrot_tools.elasticsearch
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# Feature Specification: Dev-Loop Orchestration with Claude Code Subagent Mirror

**Feature ID**: FEAT-129
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.6.x (`ai-parrot`, post-FEAT-124)

> **Note (FEAT-196, 2026-05-28)**: Import paths in code examples below reference
> `parrot.bots.flow` (singular, deleted). Use `parrot.bots.flows` (plural) instead:
> - `from parrot.bots.flow import AgentsFlow` → `from parrot.bots.flows import AgentsFlow`
> - `from parrot.bots.flow import FlowTransition` → `from parrot.bots.flows import FlowTransition`
> - `from parrot.bots.flow.node import Node` → `from parrot.bots.flows.core.node import Node`
> - `from parrot.bots.flow import InteractiveDecisionNode` → `from parrot.bots.flows import InteractiveDecisionNode`

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

…(truncated)…
