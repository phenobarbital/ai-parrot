---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: `parrot devloop` — Interactive CLI Console for Dev-Loop Flows

**Feature ID**: FEAT-374
**Date**: 2026-07-24
**Author**: Jesus Lara (research + Q&A via /sdd-proposal, sdd/proposals/devloop-cli-console.proposal.md)
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop flow (FEAT-129/132/250/322/323) can currently only be driven
interactively through a WebSocket UI: `FlowStreamMultiplexer` fans Redis
streams into a WS the nav-admin Svelte plugin (or
`examples/dev_loop/static/index.html`) consumes, and HITL gates are resolved
via REST routes. There is no way to dispatch a dev-loop run, watch it, and
answer its gates from a terminal. `examples/dev_loop/quickstart.py` is a
one-shot script with a hard-coded brief — not interactive, not installable.

Build `parrot devloop`: a Claude-Code-like interactive console (Rich +
prompt_toolkit, both already core deps) that collects a `WorkBrief` through
pydantic-driven prompts (including the Jira ticket key and a
proposal/brainstorm path), dispatches the flow **embedded in-process** via
`DevLoopRunner`, renders the live run, and resolves HITL gates interactively.

### Goals

- G1 — `parrot devloop` is an installable subcommand of the existing `parrot`
  CLI (one `_lazy_commands` entry; no new console_script).
- G2 — A **generic, reusable** pydantic-model→interactive-wizard engine
  generates the brief prompts from `model_fields` metadata (descriptions,
  defaults, `Literal` choices, required-ness); instantiated for `WorkBrief`
  and `RevisionBrief`. *(resolved U2)*
- G3 — Embedded execution only: the console builds the real flow in-process
  (`build_dev_loop_flow` + `DevLoopRunner`) after a preflight check of
  real-mode prerequisites. No server/remote client. *(resolved U1)*
- G4 — Claude-Code-like scrolling console: Rich Live rendering of the run's
  `ActionEnvelope` stream (nodes, dispatch deltas, tool use, Jira/PR links),
  interactive gate panels, Ctrl-C → confirm → cancel. No `textual`
  dependency. *(resolved U4)*
- G5 — Full run scope in v1: new runs (`WorkBrief`), revision-mode runs
  (`RevisionBrief` via `run_revision`), and in-session run listing/attach
  (`/runs`, `/attach`) across the multiple runs one console session may
  dispatch. *(resolved U3)*
- G6 — List-typed fields (`acceptance_criteria`, `log_sources`) are collected
  both via an interactive "add another?" loop of typed sub-forms AND via a
  YAML/JSON file path (`@path` syntax). *(resolved follow-up Q)*
- G7 — The console binds ONLY to stable dev-loop surfaces (`DevLoopRunner`
  methods + `SessionHost` public read side) — never dispatcher internals.

### Non-Goals (explicitly out of scope)

- Remote/server attach mode (WS client + REST commands) — rejected for v1 in
  proposal Q&A (U1: "Embedded only"). The WS multiplexer and REST command
  routes remain UI-only; **no run-start REST endpoint is added to core**.
- Cross-process attach (rebuilding another process's run from the Redis
  `flow:{run_id}:actions` stream / persisted snapshot) — deferred to a
  follow-up FEAT; v1 lists/attaches only runs started in the current console
  process. *(resolved in spec Q&A)*
- Any change to `parrot/flows/dev_loop/` (runner, models, session_state,
  nodes, gates) — consumed as-is.
- Full-screen TUI / `textual` dependency (rejected U4).
- Changes to the agent REPL (`parrot agent`).

---

## 2. Architectural Design

### Overview

`parrot devloop` opens an interactive console session. On first entry (or
`/new`), the **PydanticWizard** walks the user through a `WorkBrief`:
`kind` (Literal choice), `summary`, `description` (free text **or** `@path`
to a proposal/brainstorm file whose contents are inlined),
`existing_issue_key` (the "Jira ticket, if any"), `affected_component`,
reporter/escalation identities (defaulted from navconfig), and the list
fields per G6. The validated brief is dispatched as an asyncio task via
`DevLoopRunner.run()`; the console renders the run by polling the run's
`SessionHost` public read side (`replay_since(last_seq)`) and painting
envelopes into a Rich Live region. When a `GateOpened` action produces a
pending `ApprovalGate`, the renderer pauses the stream view and prompts
approve/reject (+ comment), calling `DevLoopRunner.resolve_gate(...)`.
Slash commands (`/runs`, `/attach <run-id>`, `/cancel [run-id]`, `/revise`,
`/help`, `/quit`) manage the session; multiple concurrent runs are allowed up
to the runner's own cap. `parrot devloop revise` (or `/revise`) runs the
same wizard over `RevisionBrief` and dispatches `run_revision()`.

Key design decision — **envelope consumption without core changes**:
`SessionHost.on_envelope` is a single constructor-injected sink owned by the
runner (`_make_envelope_sink` XADDs to Redis). There is no public
subscribe API. The console therefore polls
`host.replay_since(last_rendered_seq)` (public, cheap, in-memory) on a
~100–200 ms ticker inside the Rich Live refresh loop. Gate state is read
from `host.state.gates`. This keeps G7 intact; a runner-level envelope
fan-out is noted in §8 as a possible future core enhancement.

### Component Diagram

```
parrot (click LazyGroup)
  └── devloop (click group, parrot/cli/devloop/__init__.py)
        ├── run / (default)  ──→ DevLoopConsole (console.py)
        ├── revise           ──→ DevLoopConsole (revision entry)
        │
DevLoopConsole (console.py)
  ├── PydanticWizard (parrot/cli/wizard.py)      # generic, reusable
  │       └── WorkBrief / RevisionBrief (flows/dev_loop/models.py)
  ├── EmbeddedRuntime (bootstrap.py)             # preflight + wiring
  │       ├── ClaudeCodeDispatcher ── build_dev_loop_flow ── DevLoopRunner
  │       └── JiraToolkit / log toolkits / Redis URL (navconfig)
  ├── RunView (renderer.py)                      # Rich Live painter
  │       └── SessionHost.replay_since / .state  (poll, read-only)
  └── slash commands (/runs /attach /cancel /revise /help /quit)
          └── DevLoopRunner.{registry_state, active_runs,
                             resolve_gate, cancel_run}
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.cli:cli` (`LazyGroup`) | registers into | add `"devloop": "parrot.cli.devloop"` to `cli._lazy_commands` |
| `DevLoopRunner` | uses | `run()`, `run_revision()`, `resolve_gate()`, `cancel_run()`, `get_host()`, `registry_state()`, `active_runs()` |
| `SessionHost` | reads (poll) | `state`, `snapshot()`, `replay_since(seq)` — public read side only |
| `build_dev_loop_flow` | uses | embedded flow construction (mirrors `examples/dev_loop/quickstart.py`) |
| `WorkBrief` / `RevisionBrief` / criterion models | instantiates | wizard output; validated with normal pydantic `ValidationError` loops |
| agent REPL stack (`repl.py`, `renderer.py`, `commands.py`) | follows pattern of | slash-command dispatcher shape, Rich console conventions, async input handling |
| `HITLCompanion` (`parrot/human/cli_companion.py`) | follows pattern of | Rich rendering of interactive questions |
| navconfig `parrot.conf` | reads | `REDIS_URL`, Jira credentials, `WORKTREE_BASE_PATH`, `FLOW_*` knobs for preflight |

### Data Models

No new persisted models. New in-memory/config models only:

```python
# parrot/cli/wizard.py
class WizardFieldOverride(BaseModel):
    """Per-field presentation override (prompt text, hidden, default factory)."""
    prompt: Optional[str] = None
    hide: bool = False                      # skip + use default
    file_loadable: bool = False             # accept @path syntax

class WizardConfig(BaseModel):
    overrides: Dict[str, WizardFieldOverride] = {}
    allow_file_input: bool = True           # '@path' loads file content / YAML/JSON

# parrot/cli/devloop/bootstrap.py
class PreflightResult(BaseModel):
    ok: bool
    checks: List[PreflightCheck]            # name, passed, hint

class PreflightCheck(BaseModel):
    name: str                               # "redis", "claude-cli", "jira", ...
    passed: bool
    hint: str = ""                          # actionable fix message
```

### New Public Interfaces

```python
# parrot/cli/wizard.py — generic, reusable engine (G2)
class PydanticWizard:
    def __init__(self, model: type[BaseModel], *,
                 config: WizardConfig | None = None,
                 console: rich.console.Console | None = None) -> None: ...
    async def collect(self, *, initial: dict | None = None) -> BaseModel:
        """Prompt field-by-field; loop on ValidationError; return validated model."""

# parrot/cli/devloop/bootstrap.py
async def preflight() -> PreflightResult: ...
async def build_runtime() -> DevLoopRuntime:
    """Preflight, then construct dispatcher/toolkits/flow/DevLoopRunner."""

# parrot/cli/devloop/console.py
class DevLoopConsole:
    async def start(self, *, brief_file: str | None = None,
                    revision: bool = False) -> int: ...

# parrot/cli/devloop/__init__.py — click surface
# parrot devloop            → interactive console (wizard on first run)
# parrot devloop run [--brief FILE] [--yes]
# parrot devloop revise [--brief FILE]
```

---

## 3. Module Breakdown

### Module 1: Generic Pydantic Wizard Engine
- **Path**: `packages/ai-parrot/src/parrot/cli/wizard.py`
- **Responsibility**: Model-agnostic interactive form engine. Reads
  `model_fields` (description → prompt text, defaults, `Optional`,
  `Literal` → numbered choice, `bool` → y/n, nested `BaseModel` → sub-form,
  `List[...]` → "add another?" loop of typed sub-forms, discriminated unions
  → variant picker). `@path` file input: plain text fields inline file
  contents; list/model fields parse the file as YAML/JSON (G6). Re-prompts
  per-field on `ValidationError`. Uses prompt_toolkit async prompts + Rich.
- **Depends on**: nothing new (pydantic, rich, prompt_toolkit).

### Module 2: Embedded Runtime Bootstrap & Preflight
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py`
- **Responsibility**: `preflight()` — check Redis reachability (`REDIS_URL`),
  `claude` CLI on PATH (`shutil.which`), `jira` package importable + Jira
  creds present, `WORKTREE_BASE_PATH` configured; render a pass/fail table
  with actionable hints and abort cleanly on failure. `build_runtime()` —
  construct `ClaudeCodeDispatcher`, `JiraToolkit`, log toolkits,
  `build_dev_loop_flow(...)`, `DevLoopRunner(flow, dispatcher=...,
  jira_toolkit=..., git_toolkit=..., redis_url=..., codereview_dispatcher=...)`
  (revision deps included so `run_revision` works — mirrors
  `examples/dev_loop/quickstart.py:168-221` and `server.py`).
- **Depends on**: existing dev_loop package; navconfig.

### Module 3: Run Renderer (Rich Live envelope painter)
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`
- **Responsibility**: `RunView` — given a `SessionHost`, poll
  `replay_since(last_seq)` on a ticker; map action types
  (`NodeStarted/NodeCompleted/NodeFailed/NodeSkipped`, `Dispatch*`
  incl. streaming `DispatchDelta` text and `DispatchToolUse`,
  `JiraLinked`/`PullRequestLinked`, `GateOpened/GateResolved/GateExpired`,
  `RunClosed`) to Rich renderables in a scrolling Live region (node progress
  header + streaming tail, Claude-Code-like). Expose
  `pending_gates()` from `host.state.gates` for the console.
- **Depends on**: Module 2 (runtime types); dev_loop `session_state` models.

### Module 4: Console Engine (session, slash commands, gates)
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
- **Responsibility**: `DevLoopConsole` — owns the asyncio session: wizard →
  `runner.run()/run_revision()` as tasks; per-run `RunView`s;
  `/runs` (from `registry_state()`/`active_runs()`), `/attach <run-id>`
  (switch the Live view — same-process only), `/cancel`, `/revise`, `/new`,
  `/help`, `/quit`; gate interaction (pause Live, Rich panel with gate kind +
  TTL, approve/reject + comment → `resolve_gate(...,
  resolved_by=<$USER or configured identity>)`, 409/expiry handled
  gracefully); Ctrl-C → confirm → `cancel_run`. Follows the
  `SlashCommandDispatcher` pattern from `parrot/cli/commands.py` and
  prompt_toolkit `patch_stdout` coexistence from the agent REPL.
- **Depends on**: Modules 1–3.

### Module 5: Click Command + Wiring + Docs
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` +
  edit `packages/ai-parrot/src/parrot/cli/__init__.py`
- **Responsibility**: `devloop` click group (module attr named `devloop` so
  `LazyGroup.get_command` resolves it): bare invocation → interactive
  console; `run [--brief FILE] [--yes]` (non-interactive when a full brief
  file is given + `--yes`); `revise [--brief FILE]`. Register
  `"devloop": "parrot.cli.devloop"` in `cli._lazy_commands`. Usage doc under
  `documentation/` (mirroring `parrot-wiki-cli.md` style).
- **Depends on**: Module 4.

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/cli/test_wizard.py`,
  `packages/ai-parrot/tests/cli/devloop/…`
- **Responsibility**: unit tests per module (see §4) + an integration test
  driving `DevLoopConsole` against a **fake in-process flow** (pattern:
  `examples/dev_loop/e2e_demo.py` simulates all external services; a stub
  `AgentsFlow`/host feeding scripted actions), piped input for the wizard
  (prompt_toolkit `create_pipe_input`).
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_wizard_scalar_fields` | 1 | str/int/bool prompts honor defaults + required |
| `test_wizard_literal_choice` | 1 | `kind` Literal renders numbered choices, rejects invalid |
| `test_wizard_validation_loop` | 1 | ValidationError re-prompts same field, keeps prior answers |
| `test_wizard_list_loop` | 1 | acceptance_criteria "add another?" loop builds typed union items |
| `test_wizard_file_input` | 1 | `@path` inlines text for description; YAML file fills a list field |
| `test_wizard_workbrief_roundtrip` | 1 | full WorkBrief collected == expected model |
| `test_preflight_reports_missing` | 2 | missing claude CLI / Redis → failed checks with hints, no boot |
| `test_build_runtime_wires_revision_deps` | 2 | DevLoopRunner receives dispatcher/jira/git/redis kwargs |
| `test_renderer_maps_actions` | 3 | each action type → expected renderable; unknown action tolerated |
| `test_renderer_replay_since_cursor` | 3 | poller never re-renders seen seqs; resumes after attach |
| `test_console_gate_approve` | 4 | scripted GateOpened → prompt → resolve_gate called with resolution/comment |
| `test_console_gate_already_resolved` | 4 | ValueError/conflict from resolve_gate rendered, session continues |
| `test_console_runs_attach` | 4 | two in-session runs; /runs lists both; /attach switches view |
| `test_console_cancel_ctrl_c` | 4 | Ctrl-C → confirm → cancel_run; decline → run continues |
| `test_click_registration` | 5 | `parrot devloop --help` resolves via LazyGroup |
| `test_run_brief_file_yes` | 5 | `run --brief brief.yaml --yes` skips wizard, dispatches |

### Integration Tests

| Test | Description |
|---|---|
| `test_console_e2e_fake_flow` | Wizard (piped input) → dispatch on stub flow emitting scripted actions incl. a gate → approve → RunClosed rendered; exit code 0 |
| `test_console_revision_e2e` | `revise --brief file` path through `run_revision` on stub |

### Test Data / Fixtures

```python
@pytest.fixture
def scripted_host():
    """SessionHost fed a scripted action sequence (NodeStarted…GateOpened…RunClosed)."""

@pytest.fixture
def pipe_console():
    """prompt_toolkit pipe input + Rich Console(record=True) for deterministic IO."""

@pytest.fixture
def brief_yaml(tmp_path):
    """Valid WorkBrief as YAML for --brief / @path tests."""
```

---

## 5. Acceptance Criteria

- [ ] `parrot devloop --help` works from an installed checkout (LazyGroup
  lazy-import; no navconfig env required just for `--help`).
- [ ] Interactive session collects a valid `WorkBrief` via pydantic-driven
  prompts, including `existing_issue_key` (Jira, optional) and
  `description` accepting `@path` to a proposal/brainstorm file (G2, C4).
- [ ] List fields accepted both interactively (typed "add another?" loop)
  and from a YAML/JSON file (G6).
- [ ] Preflight blocks dispatch with an actionable table when Redis/claude
  CLI/Jira creds are missing (G3).
- [ ] A dispatched run renders live node/dispatch/link events via
  `SessionHost.replay_since` polling; no imports from dispatcher internals
  (G4, G7 — enforced by test + review).
- [ ] Pending gates prompt approve/reject+comment and resolve via
  `DevLoopRunner.resolve_gate`; expired/already-resolved gates are handled
  without crashing the session.
- [ ] `/runs` + `/attach` work across ≥2 concurrent in-session runs;
  `/cancel` and Ctrl-C-confirm cancel via `cancel_run` (G5).
- [ ] `parrot devloop revise` dispatches `run_revision(RevisionBrief)` (G5).
- [ ] No new runtime dependencies (rich/click/prompt_toolkit only); no
  changes under `parrot/flows/dev_loop/` (G7).
- [ ] All unit + integration tests pass: `pytest packages/ai-parrot/tests/cli/ -v`.
- [ ] `ruff check` clean on new modules; Google-style docstrings + type hints.
- [ ] Usage documentation added under `documentation/`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** — verified 2026-07-24 on `dev`
> (post-52df1d13c). All paths relative to repo root.

### Verified Imports

```python
from parrot.flows.dev_loop import (            # packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py:26-27,38,64
    DevLoopRunner, gate_ttl_for,               # :27
    build_dev_loop_flow, FlowEventPublisher,   # :26
)
from parrot.flows.dev_loop.models import (     # models.py
    WorkBrief, RevisionBrief, LogSource, RepoSpec,
    FlowtaskCriterion, ShellCriterion, ManualCriterion,
)
from parrot.flows.dev_loop.session_state import (  # session_state.py
    SessionHost, DevLoopSessionState, ApprovalGate,
    ActionEnvelope, Snapshot, RunRegistryState, RunSummary,
)
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher  # dispatcher.py
from parrot.cli import cli                     # cli/__init__.py:60-63 (LazyGroup)
from parrot import conf                        # navconfig-backed settings
import click, rich, prompt_toolkit             # core deps: packages/ai-parrot/pyproject.toml:77,81,82
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
def gate_ttl_for(kind: GateKind) -> int: ...                        # line 79
class DevLoopRunner:                                                 # line 156
    def __init__(self, flow: AgentsFlow, *,                          # line 165
                 max_concurrent_runs: Optional[int] = None,
                 dispatcher: Optional[Any] = None,
                 jira_toolkit: Optional[Any] = None,
                 git_toolkit: Optional[Any] = None,
                 redis_url: Optional[str] = None,
                 codereview_dispatcher: Optional[Any] = None) -> None
    def get_host(self, run_id: str) -> Optional[SessionHost]         # line 213
    def registry_state(self) -> RunRegistryState                     # line 223
    async def resolve_gate(self, run_id: str, gate_id: str,          # line 455
                 resolution: str,            # "approved" | "rejected"
                 resolved_by: str, comment: str = "",
                 origin: Optional[ActionOrigin] = None) -> ActionEnvelope
    async def cancel_run(self, run_id: str,                          # line 491
                 requested_by: str) -> ActionEnvelope
    def active_runs(self) -> Set[str]                                # line 512
    def is_active(self, run_id: str) -> bool                         # line 516
    async def run(self, brief: WorkBrief, *,                         # line 522
                  run_id: Optional[str] = None, initial_task: str = "",
                  extra_shared: Optional[Dict[str, Any]] = None) -> FlowResult
    async def run_revision(self, brief: RevisionBrief, *,            # line 594
                  run_id: Optional[str] = None) -> FlowResult
    # run() mints run_id as f"run-{uuid4().hex[:8]}" when omitted (line ~546)
    # run_revision REQUIRES dispatcher/jira/git/redis kwargs at __init__

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class ApprovalGate(_Frozen): ...                                     # line 209 (status: "pending"|...)
class DevLoopSessionState(_Frozen):                                  # line 238
    gates: Dict[str, ApprovalGate]                                   # line 257
class ActionEnvelope(_Frozen): ...                                   # line 432 (channel, server_seq, action, origin)
class Snapshot(_Frozen): ...                                         # line 442
class RunSummary(_Frozen): ...                                       # line 455
class RunRegistryState(_Frozen): ...                                 # line 469
class SessionHost:                                                   # line 723
    def __init__(self, run_id: str, *,                               # line 738
                 on_envelope: Optional[Callable[[ActionEnvelope], None]] = None)
    @property state -> DevLoopSessionState                           # line 765
    def snapshot(self) -> Snapshot                                   # line 769
    def replay_since(self, last_seen_server_seq: int)                # line 774
        -> List[ActionEnvelope]
# Action classes (renderer's dispatch table), same file:
# RunCreated:276 RunCancelled:284 RunClosed:289 NodeStarted:299
# NodeCompleted:304 NodeFailed:310 NodeSkipped:316 DispatchQueued:328
# DispatchStarted:333 DispatchDelta:338 DispatchToolUse:345
# DispatchToolResult:350 DispatchOutputInvalid:354 DispatchFailed:359
# DispatchCompleted:364 GateOpened:371 GateResolved:376 GateExpired:386
# JiraLinked:394 PullRequestLinked:399

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class WorkBrief(BaseModel):                                          # line 129
    kind: Literal['bug','enhancement','new_feature'] = 'bug'
    summary: str                       # required, ≤255 (Jira summary)
    description: str = ''
    affected_component: str            # required
    log_sources: List[LogSource]
    acceptance_criteria: List[FlowtaskCriterion|ShellCriterion|ManualCriterion]
    escalation_assignee: str           # required (Jira accountId/email)
    reporter: str                      # required
    existing_issue_key: Optional[str] = None
    dev_agents: Optional[List[DevAgentSpec]] = None
    dev_isolation: Optional[Literal['shared','isolated']] = None
class RevisionBrief(BaseModel):                                      # line 274
    repo_path: str; branch: str; pr_number: int; repository: str
    jira_issue_key: str; feedback: str; head_sha: str
# FlowtaskCriterion:44 ShellCriterion:55 ManualCriterion:70 LogSource:118 RepoSpec:222

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
def build_dev_loop_flow(*, dispatcher: ClaudeCodeDispatcher,         # line 189
    jira_toolkit: Any, log_toolkits: Dict[str, Any], redis_url: str,
    name: str = "dev-loop", publish_flow_events: bool = True,
    lifecycle_events: bool = True, development_dispatcher=None,
    development_profile=None, development_pool_config=None,
    development_dispatcher_builder=None, development_pool_max: int = 4,
    git_toolkit=None, repos: Optional[list[RepoSpec]] = None,
    codereview_dispatcher=None,
    require_deployment_approval: bool = False) -> AgentsFlow

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
class FlowResult: ...                                                # line 353 (.status, .responses, .errors)

# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                        # line 18
    def get_command(self, ctx, cmd_name)                             # line 42
        # importlib.import_module(module_path); getattr(mod, cmd_name.replace("-","_")) or getattr(mod, cmd_name)
cli._lazy_commands = { "agent": "parrot.cli.agent_repl", ... }       # lines 67-78 ← add "devloop"

# Agent REPL patterns to mirror (not modify):
# parrot/cli/repl.py      REPLConfig:27  AgentREPL:58
# parrot/cli/renderer.py  ResponseRenderer:21
# parrot/cli/commands.py  SlashCommand:23  SlashCommandDispatcher:70
# parrot/cli/agent_repl.py @click.command("agent"):27
# parrot/human/cli_companion.py  HITLCompanion (Rich HITL rendering precedent)

# packages/ai-parrot/pyproject.toml
# [project.scripts] parrot = "parrot.cli:cli"                        # lines 110-111
# rich>=13.0:77  click>=8.1.7:81  prompt_toolkit>=3.0:82
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parrot.cli.devloop` (click group) | `cli._lazy_commands` | dict entry + module attr `devloop` | `cli/__init__.py:42-57,67-78` |
| `DevLoopConsole` | `DevLoopRunner.run()` | asyncio task | `runner.py:522` |
| `DevLoopConsole` | `DevLoopRunner.run_revision()` | asyncio task | `runner.py:594` |
| `DevLoopConsole` gates | `DevLoopRunner.resolve_gate()` | await | `runner.py:455` |
| `DevLoopConsole` cancel | `DevLoopRunner.cancel_run()` | await | `runner.py:491` |
| `RunView` | `SessionHost.replay_since()` / `.state.gates` | poll (read-only) | `session_state.py:774,257` |
| `/runs` | `DevLoopRunner.registry_state()/active_runs()` | call | `runner.py:223,512` |
| `build_runtime()` | `build_dev_loop_flow(...)` + `DevLoopRunner(...)` | construction (mirror quickstart) | `flow.py:189`, `examples/dev_loop/quickstart.py:168-221` |
| `PydanticWizard` | `WorkBrief.model_fields` | pydantic v2 introspection | `models.py:129-220` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/cli/devloop.py` / `parrot.cli.devloop`~~ — created by this spec.
- ~~`SessionHost.subscribe()` / `add_listener()` / public multi-subscriber
  API~~ — only the constructor `on_envelope` sink (owned by the runner) and
  the read side (`state`/`snapshot`/`replay_since`). Do NOT chain or replace
  the runner's sink; poll `replay_since`.
- ~~`DevLoopRunner.list_runs()` / `.attach()`~~ — use `registry_state()` /
  `active_runs()` / `get_host()`.
- ~~A REST run-start endpoint in core~~ — `commands.py` only registers gate
  resolve + cancel; run-start exists only in `examples/dev_loop/server.py`.
- ~~`textual`~~ — not a dependency; do not import it.
- ~~`AgentCrew` involvement~~ — dev-loop is an `AgentsFlow`
  (`parrot.bots.flows.flow`), not an `AgentCrew`.
- ~~`BugBrief` as a distinct class~~ — legacy name; the model is `WorkBrief`
  (shared key `bug_brief` persists in `shared_data` for node compat).
- ~~`wikitoolkit`-style standalone console_script for devloop~~ — devloop is
  a `parrot` subcommand, not a new `[project.scripts]` entry.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Agent REPL stack** (`parrot/cli/agent_repl.py`, `repl.py`, `renderer.py`,
  `commands.py`) — Click entry shape, slash-command registry, Rich console
  conventions, graceful async shutdown.
- **`examples/dev_loop/quickstart.py:168-221`** — the canonical embedded
  wiring (dispatcher kwargs from `conf`, Jira toolkit reuse for identity
  resolution + flow, `_resolve_identity` fallback chain for
  reporter/escalation — reuse this logic for wizard defaults).
- **`HITLCompanion`** (`parrot/human/cli_companion.py`) — Rich rendering of
  human questions.
- prompt_toolkit **`patch_stdout`** while a Rich Live region is active; pause
  the Live for modal prompts (wizard, gate panels) instead of fighting for
  the terminal.
- Async-first throughout; `self.logger = logging.getLogger(...)`; Google
  docstrings + strict type hints; pydantic v2 models.

### Known Risks / Gotchas

- **Rich Live vs. prompt input contention** — two writers to one terminal.
  Mitigation: modal model — Live renders while idle; any prompt (gate,
  wizard, confirm) stops/suspends the Live and resumes after. The agent REPL
  already demonstrates streaming+input coexistence.
- **`runner.run()` blocks until FlowResult** — dispatch as `asyncio.Task`;
  cooperative cap means a 4th run awaits the semaphore: surface "queued
  (cap N)" in `/runs` using `active_runs()`.
- **Gate races** — a gate may expire (TTL sweep) or be resolved elsewhere
  while the prompt is open; `resolve_gate` raising/conflicting must be
  rendered as a notice, never a crash. TTLs via `gate_ttl_for(kind)`
  (`runner.py:79`) shown in the gate panel.
- **Preflight drift** — real-mode prerequisites evolve with dev-loop FEATs
  (e.g. `jira` package is lazy-imported by JiraToolkit). Keep every check in
  `bootstrap.preflight()` with a hint string; never scatter checks.
- **navconfig import cost** — `parrot.conf` boots the settings stack (see
  wizard introspection logs). Keep `parrot devloop --help` import-light:
  the LazyGroup already defers module import; inside the module, defer
  `parrot.conf`/flow imports into the command body (pattern used by other
  lazy subcommands).
- **`description` via `@path`** — inline file contents verbatim (C4,
  confidence medium in proposal): cap at a sane size (e.g. 64 KiB) and note
  the source path in the description header line.
- **Hot subsystem** — FEAT-322/323 landed recently and more dev-loop work is
  active; G7 (stable-surface-only) is the contract that keeps this feature
  from breaking. Any need beyond the read side must go through a new
  question, not a workaround.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rich` | `>=13.0` (already core, pyproject:77) | Live rendering, panels, tables |
| `click` | `>=8.1.7` (already core, pyproject:81) | command surface |
| `prompt_toolkit` | `>=3.0` (already core, pyproject:82) | async prompts, patch_stdout, pipe-input tests |
| — | — | **No new dependencies** (AC) |

---

## 8. Open Questions

> Decision trail from proposal `sdd/proposals/devloop-cli-console.proposal.md`
> (FEAT-374 Q&A) and spec-phase Q&A.

- [x] Attach mode for v1 — *Resolved in proposal*: "Embedded only — in-process
  DevLoopRunner; no remote server client in v1."
- [x] Wizard genericity — *Resolved in proposal*: "Generic engine — reusable
  pydantic-model→interactive-prompt engine, instantiated for
  WorkBrief/RevisionBrief."
- [x] Run scope — *Resolved in proposal*: "Everything incl. revision — new
  runs, list/attach, and RevisionBrief revision-mode runs in v1."
- [x] Console style — *Resolved in proposal*: "Rich Live scrolling console
  (Claude-Code-like); no textual dependency."
- [x] Attach semantics in embedded v1 — *Resolved in spec Q&A*: same-process
  only (runner in-memory catalogue); Redis-replay cross-process attach
  deferred to a follow-up FEAT.
- [x] List-field wizard UX — *Resolved in spec Q&A*: both — interactive
  "add another?" loop of typed sub-forms AND YAML/JSON file path input.
- [ ] Should `DevLoopRunner` gain an optional public envelope fan-out
  (multi-subscriber `on_envelope`) so consoles/UIs stop polling? — *Owner:
  tbd (follow-up FEAT; v1 polls `replay_since` per G7)*
- [ ] Default identity for `resolved_by`/`reporter` when navconfig has no
  Jira account mapping for the local user — fall back to `$USER`? — *Owner:
  tbd (implementation may default to `$USER` with a visible notice)*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree
  (`.claude/worktrees/feat-374-devloop-cli-console`), tasks sequential.
- **Rationale**: Modules 2–5 all live under the new `parrot/cli/devloop/`
  package and edit one shared registration point (`cli/__init__.py`);
  Module 1 (`wizard.py`) is the only truly parallelizable task but is a
  dependency of Module 4, so parallelism buys little.
- **Cross-feature dependencies**: none — dev-loop surfaces consumed as-is
  from `dev` (FEAT-322/323 already merged).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-24 | Jesus Lara + Claude (Fable 5) | Initial draft from FEAT-374 proposal |
