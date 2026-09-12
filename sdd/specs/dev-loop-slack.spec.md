---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Dev-Loop Slack Kick-off — dispatch and steer dev-loop runs from Slack

**Feature ID**: FEAT-555
**Date**: 2026-09-12
**Author**: Jesus Lara + Claude (Fable 5.1)
**Status**: draft
**Target version**: next minor of `ai-parrot` / `ai-parrot-integrations`
**Brainstorm**: `sdd/proposals/dev-loop-slack.brainstorm.md` (accepted, Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The dev-loop / dev-flow orchestration can today be started from exactly two
front-ends: the example HTML console (`examples/dev_loop/server_dev.py` +
`static/dev.html`) and the experimental `parrot devloop` terminal console.
Both require the operator to be at a workstation with the repo checked out,
Redis reachable and the coding CLIs installed. A developer who wants to say
"fix this bug" or "build this feature" from their phone, from a stand-up, or
from a conversation that is already happening in Slack has no way to hand
the request to the pipeline.

The dev-flow topology (FEAT-412) also has a human-in-the-loop step that is
*designed* for chat: the `sdd-ideation` subagent writes a brainstorm and
opens one `open_questions` gate per round with the questions it could not
answer alone. Today those questions are only answerable from the HTML
Open-Questions panel. Slack is where the requester already is, so it is the
natural place to answer them.

Every primitive exists — the ideation gates (FEAT-412), the per-run session
state on Redis (FEAT-322), the REST gate-resolve contract, the Slack command
router (FEAT-225), Block Kit modals and a bot token that can push messages —
only the glue is missing.

### Goals

- **G1 — Kick-off from Slack.** `/devloop --type feature|bug [--jira KEY]
  [--base dev|staging] <prompt>` dispatches a run and answers within Slack's
  3 s ack window.
- **G2 — Subprocess isolation.** Every run executes in its own headless
  `parrot devloop run` child process; a crashed or hung run never takes the
  Slack bot down and never runs inside it.
- **G3 — Open Questions in Slack.** Every `open_questions` gate becomes a
  message in the run thread with an **Answer** button (Block Kit modal) and
  a threaded `N: answer` free-text fallback; answers reach the run through
  the existing gate contract unchanged.
- **G4 — No new public surface.** Gate answers travel over a per-run Unix
  domain socket (loopback TCP + bearer token fallback); the Slack endpoints
  remain the only externally reachable routes.
- **G5 — Transport-agnostic core.** Parsing, brief building, subprocess
  lifecycle, state tailing, bridging and the run registry live in a
  channel-neutral `parrot.integrations.devloop` package; Slack is an adapter.
- **G6 — Ownership and authorization.** The existing `allowed_user_ids` /
  `allowed_channel_ids` whitelist gates dispatch; only the initiator may
  answer, approve, reject or cancel their run.
- **G7 — Restart-safe.** Run records are mirrored in Redis; children keep
  running when the bot stops; on bot startup live runs are re-attached.
- **G8 — Bug intake without friction.** `--type bug` builds a `WorkBrief`
  from defaults and asks for confirmation on a card (Confirm / Edit / Cancel).
- **G9 — Progress visibility.** Dispatch, gate, terminal messages always;
  a live node status card as the last, optional module.
- **G10 — `--base` is honoured for both kinds**, including feature runs,
  by threading the base branch into the ideation document frontmatter.

### Non-Goals (explicitly out of scope)

- `--type enhancement` and document intake (`--doc <path>` → `FeatureBrief`)
  from Slack. The headless child MAY accept them (§8), Slack v1 does not
  expose them.
- A Telegram adapter (follow-up spec on top of the transport-agnostic core).
- Multi-host deployment (Slack bot and children on different machines) —
  the Redis inbound command stream was weighed as brainstorm Option B and
  deferred; the `RunCommandChannel` protocol keeps that door open.
- Running dev-loop in-process inside the integrations server (brainstorm
  Option C, rejected) or promoting `server_dev.py` into a long-lived service
  (Option D, deferred).
- Any change to gate arbitration, `runner.py`, `session_state.py` or the
  REST contract in `commands.py`.
- Concurrency limits: runs are unlimited by decision; only an optional soft
  cap in config is provided.
- Slack shortcut / message-action entry points, Assistant-pane integration,
  file attachments as run input.

---

## 2. Architectural Design

### Overview

One headless child process per run, driven by the Slack bot through two
existing surfaces:

1. **Outbound (run → Slack)**: the child publishes session-state actions on
   `flow:{run_id}:actions` exactly as it does for the HTML console; the
   integration tails them with `FlowStreamMultiplexer(view="state")` and
   reduces every envelope to a `RunEvent` handed to the transport.
2. **Inbound (Slack → run)**: the child mounts the existing
   `register_command_routes(app, runner)` on a per-run **Unix domain socket**
   (or 127.0.0.1 port + bearer token when sockets are unavailable) and
   prints a one-line JSON **handshake** on stdout; the integration POSTs the
   existing `ResolveGateRequest` / `CancelRunRequest` bodies there.

`parrot devloop run` gains a `--headless` mode: it requires `--brief`, runs
the existing `bootstrap.preflight()`, builds the runtime for the brief's
kind (`WorkBrief`/`FeatureBrief` → existing `build_runtime()`;
`DevRequestBrief` → new `build_dev_flow_runtime()` lifted from
`server_dev.py::_on_startup`), mounts the command endpoint, prints the
handshake, awaits `runner.run(brief, run_id=...)` and exits `0` completed /
`1` failed / `2` cancelled / `3` preflight or bootstrap failure.

On the integration side, the channel-neutral `DevLoopDispatchService`
parses the command, builds the brief, spawns `HeadlessRunProcess`, awaits
the handshake, registers a `RunRecord` (memory + Redis mirror
`devloop:runs:{run_id}`), starts a `RunStateTail` and calls back into a
`DevLoopTransport` for every user-visible moment. `SlackDevLoopTransport`
renders those into a **run thread** (root = the public dispatch message).

Resolved-question decisions that shape this design (brainstorm §Open
Questions, all `[x]`): feature → `dev`; subprocess + bridge; `/devloop`
slash command; modal + threaded `N:` fallback; `feature` and `bug` types
only; bug defaults + confirm card; status card last/optional; whitelist +
initiator-only ownership; Slack-only on a channel-neutral core; unlimited
concurrency; flags `--jira`, `--base`, subcommands `status`/`cancel`/`help`;
Unix socket default with TCP fallback; `--base` threaded for feature runs;
Redis-persisted registry with children kept running on shutdown.

### Component Diagram

```
Slack (slash cmd / block_actions / view_submission / thread message)
   │  webhook  ──────────────► SlackAgentWrapper._handle_command / _handle_events / _interactive_handler
   │  socket   ──────────────► SlackSocketHandler._handle_slash_command / _handle_event / _handle_interactive
   ▼
SlackCommandRouter("devloop") ──► slack/devloop/commands.py ──┐
ActionRegistry("devloop_*", "modal:devloop_*") ─► slack/devloop/actions.py ──┤
wrapper.add_message_interceptor(...) ─► thread `N:` answers ──────────────────┤
                                                                              ▼
                                   parrot.integrations.devloop.service.DevLoopDispatchService
                                     │ parser.parse_command → DevLoopCommand
                                     │ briefs.build_*_brief → WorkBrief | DevRequestBrief → temp YAML
                                     │ process.HeadlessRunProcess.spawn → handshake JSON (stdout)
                                     │ registry.RunRegistry (memory + Redis devloop:runs:{id})
                                     │ tail.RunStateTail ◄── Redis flow:{run_id}:actions
                                     │ bridge.LoopbackRestChannel ──► unix://…/run-xxx.sock (or 127.0.0.1:port + token)
                                     ▼
                              transport.DevLoopTransport (protocol)
                                     ▲
                    slack/devloop/transport.SlackDevLoopTransport ── chat.postMessage / chat.update in run thread

child:  parrot devloop run --brief <yaml> --yes --headless --command-socket <path> --run-id run-xxx
          preflight() → build_runtime() | build_dev_flow_runtime() → register_command_routes(app, runner)
          → print handshake → await runner.run(brief, run_id) → exit 0/1/2/3
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.cli.devloop.__init__.run_cmd` (`packages/ai-parrot/src/parrot/cli/devloop/__init__.py:73`) | extends | new `--headless`, `--command-socket`, `--command-port`, `--run-id` options; headless path bypasses `DevLoopConsole` |
| `parrot.cli.devloop.bootstrap` (`bootstrap.py:84/249/378`) | extends | reuse `preflight()`, `build_runtime()`, `default_identities()`; add `build_dev_flow_runtime()`, `DevFlowRuntime`, `load_headless_brief()` |
| `parrot.flows.dev_loop.commands.register_command_routes` (`commands.py:208`) | uses | mounted verbatim on the child's `web.Application` |
| `parrot.flows.dev_loop.streaming.FlowStreamMultiplexer` (`streaming.py:73`) | uses | `state_replay()` + `state_tail()` on `flow:{run_id}:actions` |
| `parrot.flows.dev_loop.session_state` models (`session_state.py:243-520`) | uses | `ApprovalGate`, `NodeState`, `DevLoopSessionState`, `ActionEnvelope` decoding |
| `parrot.flows.dev_flow.models.DevRequestBrief` (`dev_flow/models.py:61`) | extends | `flow_type` / `base_branch` fields (G10) |
| `parrot.flows.dev_flow.nodes.ideation._IdeationBrief` (`ideation.py:101`) | extends | `base_branch` passthrough into the subagent payload; `sdd-ideation.md` frontmatter instruction |
| `parrot.flows.dev_flow.flow.build_dev_flow` (`dev_flow/flow.py:86`) | uses | called by `build_dev_flow_runtime()` |
| `examples/dev_loop/server_dev.py::_on_startup` (`server_dev.py:883`) | refactor (optional) | may call `build_dev_flow_runtime()` to stop drifting from the package |
| `SlackAgentWrapper` (`slack/wrapper.py:72`) | modifies (additive) | `post_message()` returning `ts`, `update_message()`, `add_message_interceptor()`; interceptor consulted in `_handle_events` |
| `SlackSocketHandler._handle_event` (`socket_handler.py:173`) | modifies (additive) | consults the same interceptor before `_safe_answer` |
| `SlackCommandRouter` (`slack/commands/__init__.py:26`) | uses | `register("devloop", handler)` |
| `SlackInteractiveHandler.action_registry` (`slack/interactive.py:109-116`) | uses | `register_prefix("devloop_", …)`, `register("modal:devloop_answers", …)` |
| `SlackAgentConfig` (`slack/models.py`) | extends | `devloop: Optional[DevLoopIntegrationConfig]` + `from_dict` parsing |
| `IntegrationBotManager._start_slack_bot` (`manager.py:858`) / `shutdown` (`manager.py:943`) | extends | builds the service when `devloop.enabled`; `service.stop()` on shutdown (children keep running) |
| `ai-parrot-integrations/pyproject.toml` | extends | `[devloop]` extra = `redis>=5.0` |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/devloop/models.py  (new)
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

RequestType = Literal["feature", "bug"]

@dataclass
class DevLoopIntegrationConfig:
    """`devloop:` section of a Slack bot entry in integrations_bots.yaml (env fallbacks {NAME}_DEVLOOP_*)."""
    enabled: bool = False
    repo_path: str = ""                       # cwd of the child; default conf.PROJECT_ROOT
    command: list[str] = field(default_factory=lambda: ["parrot", "devloop", "run"])
    redis_url: str = ""                       # default conf.REDIS_URL
    socket_dir: str = ""                      # default <tempdir>/parrot-devloop; "" + use_tcp=True ⇒ TCP fallback
    use_tcp: bool = False                     # force --command-port instead of --command-socket
    default_component: str = "ai-parrot"      # WorkBrief.affected_component default
    default_acceptance_criteria: list[dict[str, Any]] = field(default_factory=list)  # ShellCriterion dicts
    status_card: bool = True
    max_concurrent_runs: Optional[int] = None # None = unlimited (decision)
    run_retention_seconds: int = 86400
    handshake_timeout_seconds: float = 120.0
    cancel_grace_seconds: float = 45.0        # parent-side escalation to terminate() (S7); > child --cancel-grace
    tail_drain_seconds: float = 5.0           # how long the tail may run after the child exits (S8)
    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "DevLoopIntegrationConfig": ...

class DevLoopCommand(BaseModel):
    """Parsed `/devloop …` text."""
    action: Literal["dispatch", "status", "cancel", "help"]
    type: Optional[RequestType] = None        # required when action == "dispatch"
    prompt: str = ""
    title: Optional[str] = None               # --title (feature)
    jira_issue_key: Optional[str] = None      # --jira
    base_branch: Optional[Literal["dev", "staging"]] = None  # --base
    component: Optional[str] = None           # --component (bug)
    acceptance_command: Optional[str] = None  # --ac "<shell command>" (bug)
    run_id: Optional[str] = None              # cancel <run-id>

class Requester(BaseModel):
    """Channel-neutral identity of the human behind a command."""
    transport: str                            # "slack"
    tenant_id: str = ""                       # Slack team_id
    user_id: str
    display_name: str = ""
    email: str = ""
    @property
    def actor(self) -> str: ...               # f"{transport}:{tenant_id}:{user_id}" → resolved_by / requested_by

class RunRecord(BaseModel):
    """One dispatched run; mirrored to Redis at devloop:runs:{run_id}."""
    run_id: str
    kind: RequestType
    title: str
    requester: Requester
    channel_id: str
    thread_ts: str = ""
    command_endpoint: str = ""                # "unix:///…/run-xxx.sock" | "http://127.0.0.1:NNNN"
    command_token: str = ""                   # per-run bearer capability, required in both socket and TCP modes (S4)
    pid: Optional[int] = None
    phase: str = "starting"                   # starting|running|blocked|completed|failed|cancelled
    current_node: str = ""
    pending_gate_id: str = ""
    pr_url: str = ""
    jira_issue_key: str = ""
    error: str = ""
    last_seen_seq: int = 0
    status_message_ts: str = ""
    brief_path: str = ""
    started_at: float
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None

class GateView(BaseModel):
    """Transport-facing projection of ApprovalGate."""
    gate_id: str
    kind: str
    title: str
    instructions: str = ""
    payload_ref: str = ""
    questions: list[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    status: str = "pending"
    resolved_by: str = ""
    answers: dict[str, str] = Field(default_factory=dict)

class RunEvent(BaseModel):
    """Reduced session-state action."""
    run_id: str
    kind: Literal["snapshot", "gate_opened", "gate_resolved", "gate_expired",
                  "node_changed", "jira_linked", "run_closed", "run_cancelled", "process_exited"]
    seq: int = 0
    gate: Optional[GateView] = None
    node_id: str = ""
    node_status: str = ""
    state: Optional[dict[str, Any]] = None    # DevLoopSessionState.model_dump() on snapshot / terminal
    exit_code: Optional[int] = None
    stderr_tail: str = ""

class BridgeResult(BaseModel):
    ok: bool
    status: int
    reason: str = ""                          # "", "invalid_body", "answers_required", "not_found", "already_resolved", "unreachable"
```

```python
# packages/ai-parrot/src/parrot/cli/devloop/headless.py  (new)
class HeadlessHandshake(BaseModel):
    """The single JSON line the child prints on stdout when ready."""
    event: Literal["ready"] = "ready"
    run_id: str
    command_endpoint: str                     # "unix:///path" | "http://127.0.0.1:port"
    kind: Literal["bug", "enhancement", "new_feature", "feature"]
    pid: int

class HeadlessExit(IntEnum):
    COMPLETED = 0
    FAILED = 1
    CANCELLED = 2
    BOOTSTRAP_FAILED = 3
```

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/models.py  (modifies :61)
class DevRequestBrief(BaseModel):
    ...  # existing fields unchanged
    flow_type: Optional[Literal["feature", "hotfix"]] = None   # None ⇒ "feature"
    base_branch: Optional[str] = None                          # None ⇒ "dev"; validator: hotfix ⇒ "main"
```

### New Public Interfaces

```python
# parrot.cli.devloop.headless
async def run_headless(*, brief_path: str, run_id: str | None, command_socket: str | None,
                       command_port: int | None) -> int: ...

# parrot.cli.devloop.bootstrap
async def build_dev_flow_runtime(*, console: Console | None = None) -> DevFlowRuntime: ...
def load_headless_brief(path: str) -> WorkBrief | FeatureBrief | DevRequestBrief: ...

# parrot.integrations.devloop
class DevLoopDispatchService:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def dispatch(self, command: DevLoopCommand, requester: Requester, channel_id: str) -> RunRecord: ...
    async def confirm(self, pending_id: str, requester: Requester, overrides: dict[str, Any] | None = None) -> RunRecord: ...
    async def answer_gate(self, run_id: str, gate_id: str, requester: Requester, answers: dict[str, str]) -> BridgeResult: ...
    async def resolve_gate(self, run_id: str, gate_id: str, requester: Requester, resolution: str, comment: str = "") -> BridgeResult: ...
    async def cancel(self, run_id: str, requester: Requester) -> BridgeResult: ...
    async def status(self, requester: Requester) -> list[RunRecord]: ...

# parrot.integrations.slack.devloop
def register_devloop(wrapper: SlackAgentWrapper, service: DevLoopDispatchService) -> None: ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Headless CLI mode | yes | Click options, `HeadlessHandshake`, exit codes, `web.UnixSite`/`TCPSite`, bearer token via `PARROT_DEVLOOP_COMMAND_TOKEN` env | — |
| M2: Dev-flow runtime builder + brief loader | no | `build_dev_flow(**kwargs)` signature is fixed, but which review dispatcher the headless default uses (judge panel vs plan review pair) must be pinned by the thinking model while lifting `_on_startup` | judge-panel helper lives in `examples/dev_loop/server.py:580`, must be re-homed |
| M3: `--base` threading for feature runs | yes | `DevRequestBrief.flow_type/base_branch`, `_IdeationBrief.base_branch`, `sdd-ideation.md` frontmatter rule | — |
| M4: Integration models + config | yes | dataclass/pydantic shapes above; env fallbacks `{NAME}_DEVLOOP_*` mirror `SlackAgentConfig.__post_init__` | — |
| M5: Command parser + brief builders | yes | `shlex.split` + `argparse` (exit_on_error=False), usage text, default rules in §7 | — |
| M6: Subprocess + command channel | yes | `asyncio.create_subprocess_exec(start_new_session=True)`, handshake line, `aiohttp.UnixConnector`, error mapping table in §7 | — |
| M7: State tail + run registry | yes | `FlowStreamMultiplexer(view="state")`, envelope → `RunEvent` mapping table, Redis hash `devloop:runs:{run_id}` + set `devloop:runs:live` | — |
| M8: Dispatch service + transport protocol | no | orchestration of M5–M7 with re-attach on start; ownership rules | sequencing/cleanup decisions belong to the thinking model |
| M9: Slack wrapper hooks + config parsing | yes | three additive methods on `SlackAgentWrapper`, interceptor consult in both event paths, `SlackAgentConfig.devloop` | — |
| M10: Slack commands + blocks | yes | `/devloop` handler contract, Block Kit builders, action ids | — |
| M11: Slack gates + transport + terminal summary | yes | action/modal ids, `N:` regex, `SlackDevLoopTransport` method table | — |
| M12: Manager wiring, packaging extra, docs | yes | `_start_slack_bot` hook, `[devloop]` extra, `docs/integrations/slack-devloop.md` | — |
| M13: Status card (optional, last) | yes | node glyph table, `chat.update` debounce 2 s, best-effort | — |

### Module 1: Headless CLI mode
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/headless.py` (new); `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` (modifies `run_cmd`, :73-121)
- **Responsibility**: Non-interactive child mode: load brief, preflight, build runtime, mount the command endpoint, print the handshake, await the run, exit with a status code. Removes the socket file on exit.
- **Depends on**: Module 2; existing `bootstrap.preflight()`, `bootstrap.build_runtime()`, `register_command_routes`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/cli/devloop/headless.py  (new)
  class HeadlessHandshake(BaseModel):
      """Single JSON line printed to stdout once the command endpoint is listening."""
      event: Literal["ready"] = "ready"
      run_id: str
      command_endpoint: str
      kind: Literal["bug", "enhancement", "new_feature", "feature"]
      pid: int

  class HeadlessExit(IntEnum):
      """Process exit codes: 0 completed, 1 failed, 2 cancelled, 3 bootstrap/preflight failure."""

  async def mount_command_endpoint(
      runner: Any, *, socket_path: str | None, port: int | None, token: str, on_cancelled: Callable[[], None]
  ) -> tuple[web.AppRunner, str]:
      """Mount ``register_command_routes(app, runner)`` on a UnixSite (socket_path) or a 127.0.0.1 TCPSite (port; 0 = ephemeral).
      A middleware rejects every request without ``Authorization: Bearer <token>`` (401) in BOTH modes — the token is the
      per-run capability (design research S4). The cancel route is wrapped: after ``cancel_run_handler`` answers 200 the
      ``on_cancelled`` callback fires so the child actually stops its run task (S7 — ``DevLoopRunner.cancel_run`` only records
      ``run/cancelled``, runner.py:1064-1067). Returns the runner and the endpoint string (``unix://<path>`` | ``http://127.0.0.1:<port>``)."""
      # register_command_routes verified: flows/dev_loop/commands.py:208 ; cancel_run_handler verified: commands.py:163

  async def run_headless(
      *, brief_path: str, run_id: str | None, command_socket: str | None, command_port: int | None
  ) -> int:
      """Load the brief (bootstrap.load_headless_brief), preflight for the brief's topology, build the runtime for its kind,
      mount the endpoint, print HeadlessHandshake (the ONLY stdout line — all logging is routed to stderr), run
      ``runner.run(brief, run_id=run_id)`` as an asyncio task, and map FlowResult / exceptions / cancellation to HeadlessExit.
      On ``on_cancelled`` the run task is cancelled and awaited (bounded by ``--cancel-grace`` seconds, default 30) and the exit
      code is 2. Never raises; always removes the socket file and closes the endpoint."""

  # packages/ai-parrot/src/parrot/cli/devloop/__init__.py  (modifies run_cmd :73)
  @click.option("--headless", is_flag=True, default=False, help="Non-interactive child mode (requires --brief).")
  @click.option("--command-socket", default=None, help="Unix socket path for the gate/cancel REST endpoint.")
  @click.option("--command-port", type=int, default=None, help="127.0.0.1 port (0 = ephemeral) instead of a socket; token from PARROT_DEVLOOP_COMMAND_TOKEN.")
  @click.option("--run-id", default=None, help="Externally minted run id (run-<hex8>); generated when omitted.")
  @click.option("--cancel-grace", type=float, default=30.0, help="Seconds to wait for the run task to unwind after a cancel before exiting 2.")
  def run_cmd(..., headless: bool = False, command_socket: str | None = None,
              command_port: int | None = None, run_id: str | None = None, cancel_grace: float = 30.0) -> None:
      """--headless ⇒ ``asyncio.run(run_headless(...))`` and ``SystemExit(code)``; --brief is mandatory, --text forbidden.
      The bearer token is read from ``PARROT_DEVLOOP_COMMAND_TOKEN`` (mandatory in headless mode, never argv)."""
  ```

### Module 2: Dev-flow runtime builder + headless brief loader
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` (extends); optional refactor of `examples/dev_loop/server_dev.py:883-1098`
- **Responsibility**: A library-level, importable builder for the dev-flow topology (today only wired inside the example) and a brief loader that routes on `kind` to the right model. Decided default for the headless child: `codereview_dispatcher=None` so the FEAT-486 model-plan review pair is assembled by the factories (no dependency on the example's judge-panel helper); `model_plan=resolve_model_plan(None)`; `development_dispatcher_builder=functools.partial(build_dispatcher, redis_url=…, max_concurrent=…, stream_ttl_seconds=…)`; `development_pool_max=resolve_pool_max(conf.config.get)`; `graph_memory=await DevLoopGraphMemory.from_config()`; `wiki_search=DevLoopWikiSearch.from_project()`; `git_toolkit`/`wiki_toolkit` built by two new private helpers mirroring `_build_jira_toolkit` (None when unconfigured); `research_mcp_servers/tools=None`; `name="dev-flow-headless"`.
- **Depends on**: existing `build_dev_flow`, `DevFlowRunner`, `resolve_model_plan`, `build_dispatcher`, `parse_pool_env`/`resolve_pool_max`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py  (modifies; DevLoopRuntime verified :71, build_runtime :249, _build_jira_toolkit :414)
  Topology = Literal["dev_loop", "dev_flow"]

  async def preflight(*, console: Optional[Console] = None, topology: Topology = "dev_loop") -> PreflightResult:
      """(modifies :84) Design research S3: ``topology="dev_flow"`` makes the ``jira`` check advisory (passed=True with a hint
      when unconfigured — the dev-flow never creates issues) while ``redis``, backend CLI and ``worktree-base`` stay hard;
      both topologies now PING Redis (3 s timeout) instead of only checking that a URL is set. Default keeps today's behaviour."""

  @dataclass
  class DevFlowRuntime:
      """Wired dev-flow runtime (mirror of DevLoopRuntime for the FEAT-412 topology)."""
      runner: Any          # DevFlowRunner
      flow: Any            # AgentsFlow
      dispatcher: Any
      dev_loop_flow_kwargs: dict[str, Any]   # the exact kwargs build_dev_flow was called with (recovery contract, S2)
      jira_toolkit: Any = None
      redis_url: str = ""
      model_plan: Any = None
      graph_memory: Any = None

  async def build_dev_flow_runtime(*, console: Optional[Console] = None) -> DevFlowRuntime:
      """preflight(topology="dev_flow"), then wire ``build_dev_flow(**kwargs)`` + ``DevFlowRunner(flow, ..., dev_loop_flow_kwargs=kwargs)``
      with the decided defaults above; every dependency is built here (no example-module import). Raises SystemExit(1) when
      preflight fails (same contract as build_runtime). ``examples/dev_loop/server_dev.py::_on_startup`` delegates to it."""
      # build_dev_flow verified: flows/dev_flow/flow.py:86 ; DevFlowRunner verified: flows/dev_flow/runner.py:41

  def load_headless_brief(path: str) -> Any:
      """Read YAML/JSON; ``kind`` in {"new_feature","enhancement"} ⇒ parse_dev_brief; otherwise parse_brief
      (``feature`` ⇒ FeatureBrief, else WorkBrief). Raises ValueError on an unknown kind."""
      # parse_dev_brief verified: flows/dev_flow/models.py:131 ; parse_brief verified: flows/dev_loop/models/base.py:1123

  def _build_git_toolkit() -> Any: ...   # GitToolkit from parrot_tools.gittoolkit; None + warning when unavailable
  def _build_wiki_toolkit() -> Any: ...  # same pattern; None when wikitoolkit is not installed
  ```

### Module 3: `--base` threading for feature runs
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/models.py` (:61), `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` (:101 `_IdeationBrief`, :475-485 payload), `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` (:170-182)
- **Responsibility**: Make `--base staging` real for feature runs. The feature-mode base branch is *the document's frontmatter* (`feature_handoff._resolve_base_branch` reads the committed spec, `feature_handoff.py:348`; `/sdd-spec` resolves it from the brainstorm via `resolve_flow`). So the brief's `base_branch` is passed to the `sdd-ideation` subagent, which writes it into the frontmatter it already emits; nothing downstream changes and `FeatureBrief` needs no new field (the brainstorm's "thread into FeatureBrief" intent is satisfied through the document, which is the FeatureBrief's authoritative source).
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_flow/models.py  (modifies DevRequestBrief :61)
  class DevRequestBrief(BaseModel):
      flow_type: Optional[Literal["feature", "hotfix"]] = Field(default=None, description="None ⇒ feature.")
      base_branch: Optional[str] = Field(default=None, description="None ⇒ dev. hotfix ⇒ must be main (model validator).")

  # packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py  (modifies _IdeationBrief :101 and the payload :477)
  class _IdeationBrief(BaseModel):
      base_branch: str = "dev"   # rendered into the subagent payload next to mode/title/description/context

  # packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md  (modifies Step 3 frontmatter block :170-182)
  # "base_branch: <the payload's base_branch>" replaces the hard-coded "base_branch: dev"; type stays feature.
  ```

### Module 4: Integration models + config
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/devloop/__init__.py`, `models.py` (new); `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` (extends `SlackAgentConfig`)
- **Responsibility**: The data models in §2 and the `devloop:` config section with env fallbacks.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/devloop/models.py  (new) — see §2 Data Models
  class DevLoopIntegrationConfig: ...
  class DevLoopCommand(BaseModel): ...
  class Requester(BaseModel): ...
  class RunRecord(BaseModel): ...
  class GateView(BaseModel): ...
  class RunEvent(BaseModel): ...
  class BridgeResult(BaseModel): ...
  class DevLoopError(Exception): """Base."""
  class CommandSyntaxError(DevLoopError): """Bad /devloop text; carries usage."""
  class NotRunOwnerError(DevLoopError): """Actor is not the run's initiator."""
  class RunNotFoundError(DevLoopError): ...
  class SpawnError(DevLoopError): """Child failed before the handshake; carries stderr tail + exit code."""

  # packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py  (modifies SlackAgentConfig)
  @dataclass
  class SlackAgentConfig:
      devloop: Optional["DevLoopIntegrationConfig"] = None   # parsed in from_dict from data.get("devloop")
  ```

### Module 5: Command parser + brief builders
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/devloop/parser.py`, `briefs.py` (new)
- **Responsibility**: `/devloop` text → `DevLoopCommand`; command + requester + config → validated brief + temp YAML file.
- **Depends on**: Module 4; `WorkBrief`, `ShellCriterion`, `DevRequestBrief`.
- **Interface Skeleton**:
  ```python
  # parser.py
  USAGE: str  # multi-line help text returned by `/devloop help` and on syntax errors
  def parse_command(text: str) -> DevLoopCommand:
      """shlex.split + argparse (exit_on_error=False, add_help=False). First bare word in {status,cancel,help}
      selects a subcommand; otherwise action="dispatch" and --type is mandatory. Raises CommandSyntaxError."""

  # briefs.py
  def build_bug_brief(command: DevLoopCommand, requester: Requester, config: DevLoopIntegrationConfig,
                      *, reporter: str, escalation_assignee: str) -> WorkBrief:
      """Defaults: summary = first line of prompt clipped to 255 (padded to ≥10 chars with the type when shorter);
      description = prompt; affected_component = --component or config.default_component;
      acceptance_criteria = [ShellCriterion(name="slack-ac", command=--ac)] or config.default_acceptance_criteria;
      existing_issue_key = --jira; flow_type/base_branch = "feature"/--base when --base given, else None (kind default)."""
      # WorkBrief verified: flows/dev_loop/models/base.py:138 ; ShellCriterion :56
  def build_feature_brief(command: DevLoopCommand, config: DevLoopIntegrationConfig) -> DevRequestBrief:
      """kind="new_feature"; title = --title or first sentence (≤80 chars) of prompt; description = prompt;
      jira_issue_key = --jira; base_branch = --base (flow_type="feature")."""
      # DevRequestBrief verified: flows/dev_flow/models.py:61
  def brief_to_file(brief: BaseModel, directory: str, run_id: str) -> str:
      """Write ``<directory>/<run_id>.brief.json`` (mode 0600) via model_dump(mode="json"); returns the path."""
  def brief_summary_fields(brief: BaseModel) -> dict[str, str]:
      """Display projection for confirm cards (kind, summary/title, component, criteria, jira, base)."""
  ```

### Module 6: Subprocess + command channel
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/devloop/process.py`, `bridge.py` (new)
- **Responsibility**: Spawn/observe the headless child; send commands to it.
- **Depends on**: Module 4; `ResolveGateRequest`/`CancelRunRequest` body shapes (`commands.py:46/64`).
- **Interface Skeleton**:
  ```python
  # process.py
  class HeadlessRunProcess:
      """One child. Spawned with ``asyncio.create_subprocess_exec(*argv, cwd=repo_path, start_new_session=True,
      stdout=PIPE, stderr=PIPE, env={**os.environ, "PARROT_DEVLOOP_COMMAND_TOKEN": token})``. Both pipes are drained
      continuously by background reader tasks from spawn until exit (S8) — a chatty child can never block on a full pipe;
      stdout after the handshake and all of stderr go to bounded ring buffers (last 4 KiB each) and DEBUG logs."""
      @classmethod
      async def spawn(cls, *, config: DevLoopIntegrationConfig, run_id: str, brief_path: str,
                      socket_path: str | None, port: int | None, token: str) -> "HeadlessRunProcess": ...
      async def wait_ready(self, timeout: float) -> HeadlessHandshakeView:
          """Await the first stdout line that validates as a handshake; raises SpawnError on EOF/exit/timeout (kills the child on timeout)."""
      async def wait(self) -> int: """Exit code (also cancels the reader tasks)."""
      def stderr_tail(self) -> str: ...
      async def terminate(self, grace: float = 10.0) -> None: """SIGTERM, then SIGKILL after ``grace`` seconds (S7/S8 escalation)."""
      def cleanup(self) -> None: """Remove the socket file and the brief file if the child left them behind (parent-side, idempotent)."""
      pid: int

  # bridge.py
  class RunCommandChannel(Protocol):
      async def resolve_gate(self, run_id: str, gate_id: str, *, resolution: str, resolved_by: str,
                             comment: str = "", answers: dict[str, str] | None = None) -> BridgeResult: ...
      async def cancel(self, run_id: str, *, requested_by: str) -> BridgeResult: ...

  class LoopbackRestChannel:
      """RunCommandChannel over the child's REST routes. ``unix://`` ⇒ aiohttp.UnixConnector; ``http://127.0.0.1`` ⇒ TCP.
      ``Authorization: Bearer <token>`` is sent in BOTH modes (per-run capability, S4). Bodies are ResolveGateRequest /
      CancelRunRequest (client_seq=0). Status → reason mapping: 200 ok · 400 invalid_body|answers_required (from body) ·
      404 not_found · 409 already_resolved · 401 unauthorized · ClientConnectorError/timeout ⇒ ok=False, status=0, reason="unreachable"."""
      def __init__(self, endpoint: str, *, token: str, timeout: float = 10.0) -> None: ...
      async def probe(self) -> bool: """GET / (any HTTP response, even 401/404, ⇒ reachable); used by re-attach."""
  ```

### Module 7: State tail + run registry
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/devloop/tail.py`, `registry.py` (new)
- **Responsibility**: Turn `flow:{run_id}:actions` into `RunEvent`s; persist `RunRecord`s.
- **Depends on**: Module 4; `FlowStreamMultiplexer` (`streaming.py:73`), `ActionEnvelope`/`reduce` (`session_state.py:626/879`).
- **Interface Skeleton**:
  ```python
  # tail.py
  class RunStateTail:
      """Wraps FlowStreamMultiplexer(redis, run_id=run_id, view="state")."""
      def __init__(self, redis: Any, run_id: str) -> None: ...
      async def events(self, *, last_seen: int | None = None) -> AsyncIterator[RunEvent]:
          """state_replay(last_seen=last_seen) then state_tail(). Frame mapping (payload = ActionEnvelope.model_dump()):
          snapshot ⇒ RunEvent(kind="snapshot", state=payload["state"]);
          action.type gate/opened ⇒ gate_opened(GateView from action.gate); gate/resolved ⇒ gate_resolved;
          gate/expired ⇒ gate_expired; node/started|completed|failed|skipped ⇒ node_changed(node_id, status);
          run/jiraLinked ⇒ jira_linked; run/closed ⇒ run_closed (terminal, fold state via reduce); run/cancelled ⇒ run_cancelled.
          Unknown action types are skipped. Reconnects with exponential backoff (1→30 s) on redis errors, resuming from last seq."""
      async def close(self) -> None: ...

  # registry.py
  class RunRegistry:
      """In-memory dict + Redis mirror. Keys: hash ``devloop:runs:{run_id}`` (RunRecord JSON, EX retention) and set ``devloop:runs:live``."""
      def __init__(self, redis: Any, *, retention_seconds: int, namespace: str = "devloop") -> None: ...
      async def save(self, record: RunRecord) -> None: ...
      async def get(self, run_id: str) -> RunRecord | None: ...
      async def list_for(self, actor: str) -> list[RunRecord]: ...
      async def live(self) -> list[RunRecord]: """Records in the live set whose phase is not terminal."""
      async def mark_terminal(self, run_id: str) -> None: """SREM from live; EXPIRE hash to retention."""
  ```

### Module 8: Dispatch service + transport protocol
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py`, `transport.py` (new)
- **Responsibility**: Orchestrate M5–M7; own the run lifecycle, ownership checks, pending bug confirmations, re-attach on start, cleanup.
- **Depends on**: Modules 4–7.
- **Interface Skeleton**:
  ```python
  # transport.py
  class DevLoopTransport(Protocol):
      """What a channel adapter must render. Every method is best-effort: exceptions are logged, never propagated to the run."""
      async def post_run_dispatched(self, record: RunRecord) -> str: """Post the thread root; return its message id (Slack ts)."""
      async def post_bug_confirm(self, pending_id: str, fields: dict[str, str], requester: Requester, channel_id: str) -> str: ...
      async def post_run_started(self, record: RunRecord) -> None: ...
      async def post_spawn_failed(self, record: RunRecord, error: str) -> None: ...
      async def post_gate(self, record: RunRecord, gate: GateView) -> None: ...
      async def update_gate(self, record: RunRecord, gate: GateView) -> None: """After gate_resolved/expired."""
      async def update_status(self, record: RunRecord, state: dict[str, Any]) -> None: """Node card (M13); no-op by default."""
      async def post_terminal(self, record: RunRecord, event: RunEvent) -> None: ...

  # service.py
  class DevLoopDispatchService:
      def __init__(self, *, config: DevLoopIntegrationConfig, transport: DevLoopTransport, redis: Any,
                   identity_resolver: Callable[[Requester], Awaitable[tuple[str, str]]] | None = None) -> None: ...
      async def start(self) -> None:
          """Load registry.live(); for each record with a reachable endpoint restart RunStateTail from last_seen_seq;
          unreachable ⇒ mark failed + post_terminal(process_exited)."""
      async def stop(self) -> None: """Cancel tail tasks only; children keep running (decision)."""
      async def dispatch(self, command: DevLoopCommand, requester: Requester, channel_id: str) -> RunRecord | str:
          """type=feature ⇒ build brief, _launch(). type=bug ⇒ build brief, store PendingConfirmation (TTL 15 min),
          transport.post_bug_confirm, return pending_id. Enforces config.max_concurrent_runs when set."""
      async def confirm(self, pending_id: str, requester: Requester, overrides: dict[str, Any] | None = None) -> RunRecord: ...
      async def discard(self, pending_id: str, requester: Requester) -> None: ...
      async def answer_gate(self, run_id: str, gate_id: str, requester: Requester, answers: dict[str, str]) -> BridgeResult:
          """Ownership check (NotRunOwnerError) then channel.resolve_gate(resolution="approved", answers=answers)."""
      async def resolve_gate(self, run_id: str, gate_id: str, requester: Requester, resolution: str, comment: str = "") -> BridgeResult: ...
      async def cancel(self, run_id: str, requester: Requester) -> BridgeResult:
          """Ownership check, channel.cancel(); then supervise: if neither a terminal action nor process exit arrives within
          ``config.cancel_grace_seconds`` (default 45 s, > the child's --cancel-grace) ⇒ process.terminate() (S7)."""
      async def status(self, requester: Requester) -> list[RunRecord]: ...
      def pending_gate(self, run_id: str) -> GateView | None: ...
      async def _launch(self, brief: BaseModel, kind: RequestType, title: str, requester: Requester, channel_id: str) -> RunRecord:
          """mint run_id (run-<hex8>) + token (secrets.token_urlsafe(32)), brief_to_file, HeadlessRunProcess.spawn,
          wait_ready(handshake_timeout), post_run_dispatched (thread root), registry.save, start _tail_task + _wait_task."""
      async def _supervise(self, record: RunRecord) -> None:
          """Bounded supervisor (S8): when the child exits, give the tail ``tail_drain_seconds`` (5 s) to deliver the terminal
          action, then cancel it; without a terminal action emit RunEvent(process_exited, exit_code, stderr_tail); always
          registry.mark_terminal + process.cleanup(). A tail whose Redis backoff exceeds the child's lifetime is cancelled too."""
  ```

### Module 9: Slack wrapper hooks + config parsing
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (modifies :201-321, :585-626), `socket_handler.py` (modifies :173-266), `slack/models.py` (`from_dict`)
- **Responsibility**: Three additive wrapper capabilities the adapter needs; both connection modes consult the interceptor. Plus two **pre-existing ingress gaps that this feature would widen** (design research S5, verified): the webhook interactive route is mounted directly on `SlackInteractiveHandler.handle` with no Slack signature check (`wrapper.py:144`, `interactive.py` has no `verify_slack_signature_raw` call), and Socket Mode authorizes by channel only (`socket_handler.py:243,279` call `_is_authorized(channel)` without the user). Both are fixed here because gate approve/reject/cancel actions must never be reachable unsigned or by a non-whitelisted user.
- **Depends on**: Module 4.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py  (modifies SlackAgentWrapper :72)
  MessageInterceptor = Callable[[dict[str, Any]], Awaitable[bool]]   # returns True when the event was consumed

  class SlackAgentWrapper:
      async def _handle_interactive(self, request: web.Request) -> web.Response:
          """NEW route target for ``self.interactive_route`` (:144): verifies the Slack signature with
          ``verify_slack_signature_raw(raw_body, headers, signing_secret)`` exactly like ``_handle_events`` (:201) and
          ``_handle_command`` (:323), then delegates the parsed payload dict to ``self._interactive_handler.handle(payload)``.
          Also checks ``_is_authorized(channel, user)`` from payload["channel"]["id"] / payload["user"]["id"] before dispatch."""
      # socket_handler.py: _handle_event (:243) and _handle_slash_command (:279) pass ``user`` to ``_is_authorized(channel, user)``;
      # _handle_interactive (:352) applies the same channel+user check before delegating.
      def add_message_interceptor(self, interceptor: MessageInterceptor) -> None:
          """Registered interceptors run in order inside _handle_events (:296, after auth, before _safe_answer)
          and SlackSocketHandler._handle_event (:249) with the raw event dict; the first returning True stops routing to the LLM."""
      async def post_message(self, channel: str, text: str, blocks: list[dict[str, Any]] | None = None,
                             thread_ts: str | None = None) -> str | None:
          """chat.postMessage; returns the message ``ts`` (None on failure). ``_post_message`` (:585) becomes a thin wrapper."""
      async def update_message(self, channel: str, ts: str, text: str, blocks: list[dict[str, Any]] | None = None) -> bool:
          """chat.update; False on failure (rate-limit ⇒ log + False, never raise)."""
      async def open_dm(self, user_id: str) -> str | None:
          """conversations.open ⇒ channel id (fallback thread root when not_in_channel)."""   # pattern: SlackOAuthNotifier oauth_callback.py:73
  ```

### Module 10: Slack commands + blocks
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/__init__.py`, `commands.py`, `blocks.py` (new)
- **Responsibility**: `/devloop` on the router; dispatch ack; bug confirm card; `status`/`cancel`/`help`.
- **Depends on**: Modules 8, 9.
- **Interface Skeleton**:
  ```python
  # slack/devloop/__init__.py
  def register_devloop(wrapper: SlackAgentWrapper, service: DevLoopDispatchService) -> SlackDevLoopTransport:
      """router.register("devloop", …) ; action_registry.register_prefix("devloop_", …) ;
      action_registry.register("modal:devloop_answers", …) ; register("modal:devloop_bug_edit", …) ;
      wrapper.add_message_interceptor(thread_answer_interceptor). Returns the transport bound to wrapper."""
      # SlackCommandRouter.register verified: slack/commands/__init__.py:50 ; ActionRegistry.register_prefix :48 ; modal routing :192-213

  # commands.py
  async def devloop_command_handler(payload: dict[str, Any], *, service: DevLoopDispatchService,
                                    transport: "SlackDevLoopTransport") -> dict[str, Any]:
      """payload keys: team_id, user_id, channel_id, text, response_url (wrapper.py:357-363). Returns the ephemeral ack dict
      immediately; dispatch runs in a background task tracked in wrapper._background_tasks.
      help ⇒ USAGE ; status ⇒ list of caller's runs with permalinks ; cancel <id> ⇒ service.cancel ; dispatch ⇒ service.dispatch."""

  # blocks.py  (pure functions → Block Kit JSON)
  def dispatch_root_blocks(record: RunRecord) -> list[dict]: ...
  def bug_confirm_blocks(pending_id: str, fields: dict[str, str]) -> list[dict]:   # actions: devloop_confirm:<id>, devloop_edit:<id>, devloop_discard:<id>
  def bug_edit_modal(pending_id: str, fields: dict[str, str]) -> dict:              # callback_id devloop_bug_edit, private_metadata=pending_id
  def run_started_blocks(record: RunRecord) -> list[dict]: ...
  def status_list_text(records: list[RunRecord], permalink: Callable[[RunRecord], str]) -> str: ...
  ```

### Module 11: Slack gates + transport + terminal summary
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/actions.py`, `transport.py`, `blocks.py` (extends) (new)
- **Responsibility**: Gate cards, answers modal, generic approve/reject with optional comment, threaded `N:` fallback, terminal summaries, ownership errors.
- **Depends on**: Modules 8–10.
- **Interface Skeleton**:
  ```python
  # blocks.py (extends)
  def gate_blocks(record: RunRecord, gate: GateView) -> list[dict]:
      """open_questions ⇒ numbered questions + buttons devloop_answer:<run>:<gate>, devloop_reject:<run>:<gate>;
      other kinds ⇒ title/instructions/payload_ref + devloop_approve:<run>:<gate>, devloop_reject:<run>:<gate>."""
  def answers_modal(record: RunRecord, gate: GateView) -> dict:
      """callback_id devloop_answers; private_metadata json {run_id, gate_id}; one optional multiline plain_text_input per
      question, block_id q<N>; opened via SlackInteractiveHandler.open_modal(trigger_id, form_definition) (interactive.py:308)."""
  def gate_resolved_blocks(record: RunRecord, gate: GateView) -> list[dict]: ...
  def terminal_blocks(record: RunRecord, event: RunEvent) -> list[dict]: ...

  # actions.py
  THREAD_ANSWER_RE = re.compile(r"^\s*(\d+)\s*[:)\.-]\s*(.+)$", re.M)
  async def handle_block_action(payload: dict, action: dict, *, service, transport) -> None:
      """Routes on action_id prefix: devloop_confirm/edit/discard (bug card), devloop_answer (open modal),
      devloop_approve/reject (service.resolve_gate). Non-owner ⇒ ephemeral 'This run belongs to <@initiator>' via response_url."""
  async def handle_answers_submission(payload: dict, *, service, transport) -> dict | None:
      """extract_form_values (interactive.py:554) → {question: answer} for non-empty inputs → service.answer_gate.
      answers_required ⇒ return {"response_action": "errors", "errors": {"q1": "Answer at least one question"}}."""
  async def handle_bug_edit_submission(payload: dict, *, service, transport) -> dict | None: ...
  async def thread_answer_interceptor(event: dict, *, service, transport) -> bool:
      """True (consumed) iff event.thread_ts matches a RunRecord.thread_ts. Owner + pending open_questions gate + ≥1 THREAD_ANSWER_RE
      match ⇒ answer_gate; otherwise ephemeral hint. Never forwards run-thread messages to the LLM."""

  # transport.py
  class SlackDevLoopTransport:
      """DevLoopTransport over SlackAgentWrapper.post_message/update_message/open_dm; falls back to a DM thread on not_in_channel."""
      def __init__(self, wrapper: SlackAgentWrapper) -> None: ...
      # implements every DevLoopTransport method; update_status is a no-op until M13
  ```

### Module 12: Manager wiring, packaging extra, docs
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (`_start_slack_bot` :858, `shutdown` :943), `packages/ai-parrot-integrations/pyproject.toml`, `docs/integrations/slack-devloop.md` (new), `examples/dev_loop/README.md` (headless note)
- **Responsibility**: Build and start the service per Slack bot with `devloop.enabled`; stop it on shutdown; declare the extra; document the Slack app manifest (scopes `commands`, `chat:write`, `chat:write.public`, `im:write`, `users:read`, `users:read.email`; interactivity URL; `/devloop` command), YAML config, command syntax and headless mode.
- **Depends on**: Modules 1–11.
- **Interface Skeleton**:
  ```python
  # manager.py  (modifies _start_slack_bot :858)
  #   if getattr(config, "devloop", None) and config.devloop.enabled:
  #       service = DevLoopDispatchService(config=config.devloop, transport=<bound later>, redis=aioredis.from_url(...))
  #       transport = register_devloop(wrapper, service); await service.start(); self._devloop_services[name] = service
  # shutdown (:943): await service.stop() for each (tails only; children keep running)
  ```

### Module 13: Status card (optional, last)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/blocks.py` (extends), `transport.py` (implements `update_status`)
- **Responsibility**: One message per run listing nodes with ✅ completed / 🔄 running / ⚪ idle / ❌ failed / ⏭ skipped, created on the first `node_changed`, edited via `update_message`, debounced to ≤1 edit per 2 s per run, coalescing bursts; failure never affects the run. Enabled by `config.status_card`.
- **Depends on**: Modules 7, 9, 11.
- **Interface Skeleton**:
  ```python
  def status_card_blocks(record: RunRecord, nodes: dict[str, dict[str, Any]]) -> list[dict]: ...
  class SlackDevLoopTransport:
      async def update_status(self, record: RunRecord, state: dict[str, Any]) -> None:
          """Create-or-update record.status_message_ts with a 2 s trailing-edge debounce per run_id."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_headless_requires_brief` | M1 | `--headless` without `--brief` exits with usage error |
| `test_headless_handshake_line` | M1 | stdout's first line validates as `HeadlessHandshake` with `unix://` endpoint |
| `test_mount_command_endpoint_unix_socket` | M1 | routes `/runs/{id}/gates/{gid}/resolve` and `/runs/{id}/cancel` answer over `UnixConnector` |
| `test_mount_command_endpoint_tcp_requires_token` | M1 | 401 without bearer, 200 with |
| `test_headless_exit_codes` | M1 | completed/failed/cancelled/bootstrap failure → 0/1/2/3; socket file removed |
| `test_build_dev_flow_runtime_wiring` | M2 | `build_dev_flow` called with the decided kwargs (mocked); `DevFlowRunner` receives `dev_loop_flow_kwargs` |
| `test_load_headless_brief_routes_on_kind` | M2 | `new_feature` → `DevRequestBrief`, `feature` → `FeatureBrief`, `bug` → `WorkBrief`, unknown → `ValueError` |
| `test_devrequestbrief_base_branch_validator` | M3 | `hotfix` with non-`main` base rejected; defaults None |
| `test_ideation_payload_carries_base_branch` | M3 | `_IdeationBrief.base_branch` equals the brief's value (default `dev`) |
| `test_config_from_dict_and_env_fallbacks` | M4 | `devloop:` section parsed; `{NAME}_DEVLOOP_REPO_PATH` fallback |
| `test_parse_command_*` | M5 | dispatch with flags, subcommands, missing `--type`, unknown flag, quoted prompt |
| `test_build_bug_brief_defaults` | M5 | summary clipping/padding, component default, `--ac` → `ShellCriterion`, `--base` → `flow_type`/`base_branch` |
| `test_build_feature_brief_title_derivation` | M5 | `--title` wins; first sentence fallback; `base_branch` set |
| `test_spawn_reads_handshake` | M6 | fake child script prints handshake; `wait_ready` returns it |
| `test_spawn_timeout_kills_child` | M6 | no handshake → `SpawnError`, process terminated |
| `test_bridge_status_mapping` | M6 | 200/400(answers_required)/404/409/401/unreachable → `BridgeResult.reason` |
| `test_tail_maps_actions_to_events` | M7 | fakeredis stream with gate/opened, node/*, run/closed → expected `RunEvent`s; terminal stops |
| `test_tail_resumes_from_last_seen` | M7 | `state_replay(last_seen=N)` skips ≤N |
| `test_registry_roundtrip_and_live_set` | M7 | save/get/list_for/live/mark_terminal with fakeredis |
| `test_service_dispatch_feature` | M8 | brief file written, spawn called, thread root posted, record saved, tail started |
| `test_service_bug_confirm_flow` | M8 | dispatch returns pending id; confirm launches; discard drops; non-owner rejected |
| `test_service_ownership_on_answer_cancel` | M8 | `NotRunOwnerError` for other actors |
| `test_service_start_reattaches_live_runs` | M8 | live record with reachable endpoint → tail restarted from `last_seen_seq` |
| `test_wrapper_interceptor_consumes_event` | M9 | interceptor returning True prevents `_safe_answer` in both webhook and socket paths |
| `test_post_message_returns_ts` | M9 | mocked `chat.postMessage` → ts |
| `test_interactive_route_rejects_bad_signature` | M9 | webhook interactive POST without a valid `X-Slack-Signature` → 401; valid → handled |
| `test_socket_mode_enforces_user_whitelist` | M9 | Socket Mode event / slash / interactive payloads from a non-whitelisted user are dropped |
| `test_preflight_topology_dev_flow_jira_advisory` | M2 | unconfigured Jira passes with a hint for `dev_flow`, fails for `dev_loop`; Redis PING failure fails both |
| `test_headless_cancel_stops_run_task` | M1 | POST cancel → 200, run task cancelled, exit code 2 within `--cancel-grace` |
| `test_process_pipes_drained` | M6 | child writing 1 MiB to stdout/stderr after the handshake never blocks; ring buffers hold the tail |
| `test_command_handler_ack_and_subcommands` | M10 | ephemeral ack shape; help/status/cancel paths |
| `test_bug_confirm_card_actions` | M10 | action ids and button values |
| `test_gate_blocks_and_answers_modal` | M11 | one input per question; private_metadata |
| `test_answers_submission_partial_and_empty` | M11 | partial answers accepted; empty → validation error response |
| `test_thread_answer_interceptor` | M11 | `1: x` / `2) y` parsed; non-owner and non-run-thread ignored |
| `test_manager_wires_service_when_enabled` | M12 | `_start_slack_bot` builds service only with `enabled: true` |
| `test_status_card_debounce` | M13 | 10 node events in 1 s → 1 `chat.update` |

### Integration Tests
| Test | Description |
|---|---|
| `test_headless_child_end_to_end_stub_runner` | Spawn `parrot devloop run --headless` with a stub runner (env `PARROT_DEVLOOP_STUB_RUNNER=1`, see fixtures) that opens an `open_questions` gate, publishes to fakeredis-compatible Redis; integration answers via `LoopbackRestChannel`; child exits 0 |
| `test_slack_feature_run_thread_flow` | Slash command → thread root → gate card → modal submission → gate resolved → terminal summary, with mocked Slack Web API and a fake child |
| `test_slack_bug_confirm_then_run` | `/devloop --type bug` → confirm card → Confirm → run started |
| `test_restart_reattach` | Service stopped and restarted with a live child keeps delivering events |
| `test_cross_process_command_contract` | Real `web.UnixSite` child + `UnixConnector` client (S11): handshake, `open_questions` answers, first-writer 409 on a second resolve, cancel → child exit 2, missing bearer → 401, socket file removed |
| `test_child_crash_before_terminal_action` | Child killed after the handshake: `process_exited` event with exit code + stderr tail, record marked failed, tail cancelled |
| `test_tail_survives_redis_loss` | Redis connection dropped mid-run: tail backs off, resumes from `last_seen_seq`, no duplicate gate messages |
| `test_slack_auth_parity_webhook_vs_socket` | The same unauthorized user / channel / unsigned cases through `SlackAgentWrapper` routes and `SlackSocketHandler` handlers yield identical rejections |
| `test_devloop_extra_installs_redis` | `ai-parrot-integrations[devloop]` metadata lists `redis>=5.0` (S12) |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_child(tmp_path):
    """Path to a python script that prints a HeadlessHandshake for a given socket path, serves
    register_command_routes over a stub runner exposing resolve_gate/cancel_run, and exits with a chosen code."""

@pytest.fixture
def fake_redis():
    """fakeredis.aioredis.FakeRedis(decode_responses=True) pre-loaded with flow:{run_id}:actions envelopes."""

@pytest.fixture
def slack_api(monkeypatch):
    """Records chat.postMessage / chat.update / views.open / conversations.open calls and returns canned ts/ids."""

@pytest.fixture
def devloop_config(tmp_path):
    return DevLoopIntegrationConfig(enabled=True, repo_path=str(tmp_path), socket_dir=str(tmp_path / "sock"),
                                    default_acceptance_criteria=[{"kind": "shell", "name": "unit", "command": "pytest -q"}])
```

Tests live at `packages/ai-parrot/tests/cli/devloop/test_headless.py`,
`packages/ai-parrot/tests/flows/dev_flow/test_base_branch_threading.py`,
`packages/ai-parrot-integrations/tests/integrations/devloop/…` and
`packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_*.py`.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 `pytest packages/ai-parrot/tests/cli/devloop packages/ai-parrot/tests/flows/dev_flow -q` passes.
- [ ] AC2 `pytest packages/ai-parrot-integrations/tests/integrations/devloop packages/ai-parrot-integrations/tests/integrations/slack -q` passes.
- [ ] AC3 `ruff check` and `black --check --line-length 120` pass on every touched file (TID251 import bans included).
- [ ] AC4 `parrot devloop run --brief b.yaml --yes --headless --command-socket /tmp/x.sock` prints exactly one `HeadlessHandshake` JSON line on stdout before any run output and exits 0/1/2/3 per outcome; the socket file is gone afterwards.
- [ ] AC5 A `kind: new_feature` brief runs the dev-flow topology headless (ideation → planner → …) via `build_dev_flow_runtime()`; no import from `examples/` anywhere in the package.
- [ ] AC6 `/devloop --type feature <prompt>` from a whitelisted user posts a public thread root within the Slack ack window and a "started" message after the handshake; a non-whitelisted user gets "Unauthorized." and nothing is spawned.
- [ ] AC7 An `open_questions` gate appears in the run thread with **Answer**/**Abort** buttons; a modal submission with ≥1 answer resolves the gate (`ResolveGateRequest.answers`) and the message is edited to "Answered by @user (k of n)"; an empty submission shows a validation error; a `N:` thread reply by the owner resolves it too.
- [ ] AC8 Non-initiator clicks/replies never resolve a gate and receive an ephemeral ownership notice.
- [ ] AC9 A second resolve (409) or an expired gate updates the card to the real state without error.
- [ ] AC10 `/devloop --type bug <prompt>` posts a confirm card; Confirm dispatches, Edit opens a pre-filled modal, Cancel discards; the resulting `WorkBrief` validates with the defaults in M5.
- [ ] AC11 `--base staging` on a feature run yields `base_branch: staging` in the ideation document frontmatter (verified by inspecting the `_IdeationBrief` payload and the subagent instructions); on a bug run it sets `WorkBrief.base_branch="staging"` and `flow_type="feature"`.
- [ ] AC12 `/devloop status` lists only the caller's runs; `/devloop cancel <id>` cancels only the caller's run.
- [ ] AC13 Run records survive a bot restart: after `service.stop()` + `service.start()` with a live child, gate and terminal messages still arrive; children are spawned with `start_new_session=True` and are never terminated by shutdown.
- [ ] AC14 Child crash before the handshake ⇒ thread message with exit code + stderr tail; crash after ⇒ "exited unexpectedly" terminal message.
- [ ] AC15 Gate answers only travel over the Unix socket / 127.0.0.1 endpoint; no new route is added to the public aiohttp app; the child rejects requests without the per-run bearer token (401) in BOTH socket and TCP modes.
- [ ] AC20 The webhook interactive route rejects unsigned/invalid-signature payloads (401) and Socket Mode enforces `allowed_user_ids` for events, slash commands and interactive payloads; the existing Slack whitelist suites plus the new parity test pass.
- [ ] AC21 `/devloop cancel <id>` makes the child exit with code 2 within the cancel grace (run task cancelled); if it does not, the service terminates the process and the thread reports it.
- [ ] AC22 `preflight(topology="dev_flow")` lets a feature run start without Jira credentials (advisory hint only) and both topologies fail fast when Redis does not answer PING.
- [ ] AC16 Status card (when enabled) reflects node states and issues ≤1 `chat.update` per 2 s per run; disabling it changes nothing else.
- [ ] AC17 Both Slack connection modes (webhook and Socket Mode) deliver slash commands, block actions, modal submissions and thread replies to the same handlers (test coverage for both paths).
- [ ] AC18 `docs/integrations/slack-devloop.md` documents manifest scopes, YAML config, command syntax, headless mode and limitations; `examples/dev_loop/README.md` links to it.
- [ ] AC19 No behaviour change for Slack bots without `devloop.enabled`; existing Slack and dev-loop test suites stay green.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Re-verified on 2026-09-12 against `dev` @ `cc48ee845` (brainstorm anchors carried forward).

### Verified Imports
```python
# Core — packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py
from parrot.flows.dev_loop import DevLoopRunner            # verified: flows/dev_loop/__init__.py:30
from parrot.flows.dev_loop import WorkBrief, ShellCriterion, FeatureBrief   # verified: :71-73
from parrot.flows.dev_loop import register_command_routes  # verified: :12
from parrot.flows.dev_loop import build_dev_loop_flow      # verified: :29
from parrot.flows.dev_loop import FlowStreamMultiplexer    # verified: :34
from parrot.flows.dev_loop.commands import ResolveGateRequest, CancelRunRequest, resolve_gate_handler, cancel_run_handler  # verified: commands.py:46,64,77,163
from parrot.flows.dev_loop.session_state import ApprovalGate, NodeState, DevLoopSessionState, ActionEnvelope, GateOpened, GateResolved, GateExpired, SessionHost, reduce, session_channel  # verified: session_state.py:257,243,330,626,492,497,511,1134,879,88
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer  # verified: streaming.py:73
from parrot.flows.dev_loop.models import parse_brief, DevAgentSpec, JudgePanelConfig, default_judge_panel  # verified: models/base.py:1123,412,971,982
from parrot.flows.dev_loop.agent_builder import build_dispatcher, parse_pool_env, resolve_pool_max  # verified: examples/dev_loop/server.py:159 (import site)
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory   # verified: bootstrap.py:269
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch     # verified: bootstrap.py:271
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput, parse_dev_brief, DevFlowModelPlan, resolve_model_plan  # verified: dev_flow/models.py:61,166,131 + re-exports :33-36
from parrot.flows.dev_flow.runner import DevFlowRunner      # verified: dev_flow/runner.py:41
from parrot.flows.dev_flow.flow import build_dev_flow       # verified: dev_flow/flow.py:86
from parrot.flows.dev_flow.model_plan import resolve_model_plan, DevFlowModelPlan  # verified: model_plan.py:334,167
from parrot.cli.devloop.bootstrap import preflight, build_runtime, default_identities, DevLoopRuntime  # verified: bootstrap.py:84,249,378,71
from parrot.cli.devloop.intake import _slugify              # verified: intake.py:43 (private helper; copy the regexes rather than import if preferred)

# Integrations — packages/ai-parrot-integrations/src/parrot/integrations/slack/__init__.py
from parrot.integrations.slack import SlackAgentWrapper, SlackAgentConfig, SlackInteractiveHandler, ActionRegistry, SlackSocketHandler  # verified: slack/__init__.py:3-20
from parrot.integrations.slack.commands import SlackCommandRouter                  # verified: slack/commands/__init__.py:26
from parrot.integrations.slack.security import verify_slack_signature_raw          # verified: slack/__init__.py:17 (re-export); used at wrapper.py:333
from parrot.integrations.slack.commands.jira_commands import register_jira_commands  # verified: jira_commands.py:166
from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier            # verified: oauth_callback.py:73
from parrot.integrations.manager import IntegrationBotManager                      # verified: manager.py:63
from parrot.integrations.models import IntegrationBotConfig                        # verified: models.py:25

# Third party (already declared)
import redis.asyncio as aioredis      # verified: examples/dev_loop/server_dev.py:59; ai-parrot-integrations/pyproject.toml:56,104 (optional extras)
from aiohttp import web, ClientSession, UnixConnector       # core dependency
import fakeredis                      # verified in tests: packages/ai-parrot/tests/flows/dev_loop/test_streaming_state_view.py
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    def __init__(self, flow: AgentsFlow, *, max_concurrent_runs: Optional[int] = None, dispatcher: Optional[Any] = None,
                 jira_toolkit: Optional[Any] = None, git_toolkit: Optional[Any] = None, wiki_toolkit: Optional[Any] = None,
                 redis_url: Optional[str] = None, codereview_dispatcher: Optional[Any] = None, graph_memory: Optional[Any] = None,
                 checkpoint_store: Optional[Union[str, CheckpointStore]] = None,
                 dev_loop_flow_kwargs: Optional[Dict[str, Any]] = None) -> None:   # line 417
    def get_host(self, run_id: str) -> Optional[SessionHost]:                       # line 516
    async def resolve_gate(self, run_id: str, gate_id: str, resolution: str, resolved_by: str, comment: str = "",
                           origin: Optional[ActionOrigin] = None, answers: Optional[Dict[str, str]] = None) -> ActionEnvelope:  # line 1005
    async def cancel_run(self, run_id: str, requested_by: str) -> ActionEnvelope:  # line 1051
    def active_runs(self) -> Set[str]:                                              # line 1072
    async def run(self, brief: Union[WorkBrief, FeatureBrief], *, run_id: Optional[str] = None, initial_task: str = "",
                  extra_shared: Optional[Dict[str, Any]] = None, flow_kwargs_overrides: Optional[Dict[str, Any]] = None) -> FlowResult:  # line 1189 — awaits the whole run

# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):                                                 # line 41
    async def run(self, brief: DevRequestBrief | FeatureBrief, *, run_id: str | None = None, initial_task: str = "",
                  extra_shared: dict[str, Any] | None = None, model_plan: DevFlowModelPlan | None = None) -> FlowResult:  # line 80

# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py
def build_dev_flow(*, dispatcher: Any, redis_url: str, jira_toolkit=None, git_toolkit=None, wiki_toolkit=None,
                   codereview_dispatcher=None, development_dispatcher_builder=None, development_pool_max: int = 4,
                   graph_memory=None, wiki_search=None, skip_qa: bool = False, require_plan_approval: bool = False,
                   ideation_max_rounds: int | None = None, model_plan: DevFlowModelPlan | None = None,
                   research_coordinator=None, research_mcp_servers: dict | None = None, research_mcp_tools: list | None = None,
                   name: str = "dev-flow", publish_flow_events: bool = True, lifecycle_events: bool = True,
                   checkpoint: bool = False, checkpoint_required: bool = False, checkpoint_store=None, flow_id: str | None = None) -> AgentsFlow:  # line 86

# packages/ai-parrot/src/parrot/flows/dev_flow/models.py
DevRequestKind = Literal["enhancement", "new_feature"]
class DevRequestBrief(BaseModel):   # line 61 — kind, title (min 1), description (min 1), context="", jira_issue_key=None, dev_agents=None, judge_panel=None; NO flow_type/base_branch today
def parse_dev_brief(data: dict[str, Any]) -> DevRequestBrief | FeatureBrief:      # line 131
class IdeationOutput(BaseModel):    # line 166 — document_path, document_kind, slug, resumed_existing, open_questions: list[str], summary, committed

# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
_MODE_FOR_KIND = {"new_feature": "brainstorm", "enhancement": "proposal"}          # line 75
class _IdeationBrief(BaseModel):    # line 101 — mode, title, description, context="", graph_context="", answers={}, document_path="", round=1, partner_findings, partner_findings_path
#   payload built at line 477-487 ; gate: host.open_gate(kind="open_questions", node_id=self.name, title=f"Open questions — {document_path}", instructions=..., questions=..., ttl_seconds=conf.DEV_FLOW_GATE_TTL_QUESTIONS|86400, on_expiry="fail")  # ~line 596
#   FeatureBrief emitted at line 317-324 (document_path, document_kind, jira_issue_key, dev_agents, judge_panel)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py
    def _resolve_base_branch(planner: PlannerOutput) -> str:                       # line 348 — reads the committed spec's frontmatter; fallback "dev"

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
NodeStatus = Literal["idle", "running", "completed", "failed", "skipped"]          # line 161
GateKind   = Literal[...,"plan_approval","review_escalation","open_questions",...] # line 174-181
GateStatus = Literal["pending", "approved", "rejected", "expired"]                 # line 183
class NodeState(_Frozen): node_id, status="idle", started_at, finished_at, error="", dispatch, summary: Dict[str,str]   # line 243
class ApprovalGate(_Frozen): gate_id, kind, node_id, status, on_expiry, title, instructions, payload_ref, opened_at, expires_at, resolved_by, resolved_at, comment, questions: List[str], answers: Dict[str,str]   # line 257 (questions/answers :291-292)
class DevLoopSessionState(_Frozen): run_id, channel, revision, phase, created_at, finished_at, work_kind, summary, jira_issue_key, pr_url, nodes: Dict[str,NodeState], gates: Dict[str,ApprovalGate], cancel_requested_by, error, judge_verdicts, feedback_decisions, docs_artifacts, qa_attempts, qa_notes   # line 330
class GateOpened(_ActionBase):   type="gate/opened"; gate: ApprovalGate            # line 492
class GateResolved(_ActionBase): type="gate/resolved"; gate_id; resolution; resolved_by; comment=""; answers={}  # line 497
class GateExpired(_ActionBase):  type="gate/expired"; gate_id                      # line 511
class ActionOrigin(_Frozen): ...                                                    # line 619
class ActionEnvelope(_Frozen): channel: str; server_seq: int; action: DevLoopAction; origin: Optional[ActionOrigin]; rejection_reason: str = ""   # line 626
def session_channel(run_id: str) -> str                                             # line 88
def reduce(state: DevLoopSessionState, action: DevLoopAction) -> DevLoopSessionState  # line 879
class SessionHost:                                                                  # line 1134
    def resolve_gate(self, gate_id, resolution, resolved_by, comment="", origin=None, answers=None) -> ActionEnvelope   # line 1226
    def open_gate(self, *, kind, node_id, title, instructions="", payload_ref="", ttl_seconds=None, on_expiry="fail", questions=None) -> Tuple[str, ActionEnvelope]  # line 1290
    async def wait_gate(self, gate_id: str) -> ApprovalGate                        # line 1374

# packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py
class FlowStreamMultiplexer:                                                        # line 73
    def __init__(self, redis: Any, *, run_id: str, view: ViewLiteral = "both", dispatch_refresh_seconds: float = 2.0, block_ms: int = 1000) -> None   # line 76
    #  keys: f"flow:{run_id}:flow" (:102), f"flow:{run_id}:dispatch:" (:103), f"flow:{run_id}:actions" (:106)
    async def state_replay(self, *, last_seen: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]   # line 291
    #  yields {"source":"state","node_id":None,"event_kind":"snapshot","ts":…,"payload": Snapshot.model_dump()} when last_seen is None (:341-347)
    #  else {"event_kind":"action","payload": ActionEnvelope.model_dump()} for server_seq > last_seen (:351-359)
    _TERMINAL_ACTION_TYPES = frozenset({"run/closed", "run/cancelled"})            # line 360
    async def state_tail(self) -> AsyncIterator[Dict[str, Any]]                     # line 410 — frames {"event_kind":"action","payload": ActionEnvelope.model_dump()} (:397-402); stops after a terminal action
    #  live entries carry the JSON envelope in field "envelope" (:386-389)

# packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
class ResolveGateRequest(BaseModel):  # frozen, extra="forbid" — resolution: Literal["approved","rejected"]; resolved_by: str(min 1); comment=""; client_seq: int = 0; answers: dict[str,str] = {}   # line 46
class CancelRunRequest(BaseModel):    # requested_by: str(min 1)                    # line 64
async def resolve_gate_handler(request: web.Request) -> web.Response              # line 77  — 200 / 400 invalid_body|answers_required / 404 / 409
async def cancel_run_handler(request: web.Request) -> web.Response                # line 163
def register_command_routes(app: web.Application, runner: DevLoopRunner) -> None  # line 208 — app["dev_loop_runner"]=runner; POST /runs/{run_id}/gates/{gate_id}/resolve ; POST /runs/{run_id}/cancel

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ShellCriterion(_AcceptanceCriterionBase): kind="shell"; command: str; name: str; timeout_seconds=300; expected_exit_code=0   # line 56
WorkKind = Literal["bug", "enhancement", "new_feature"]                            # line 116
class WorkBrief(BaseModel):   # line 138 — kind="bug"; summary (10..255); description=""; affected_component: str (REQUIRED); log_sources=[]; acceptance_criteria (min 1); escalation_assignee: str; reporter: str; existing_issue_key=None; dev_agents=None; dev_isolation=None; flow_type=None (:219); base_branch=None (:226)
class FeatureBrief(BaseModel):  # line 817 — kind="feature"; document_path (must exist); document_kind; jira_issue_key; dev_agents; judge_panel — NO base_branch
def parse_brief(data: Dict[str, Any]) -> Union[WorkBrief, FeatureBrief]           # line 1123

# packages/ai-parrot/src/parrot/cli/__init__.py
#   cli._lazy_commands["devloop"] = "parrot.cli.devloop"                            # line 125

# packages/ai-parrot/src/parrot/cli/devloop/__init__.py
@devloop.command("run")   # line 73 — options --brief, --yes(skip_wizard), --dev-agent(multiple), --text
def run_cmd(brief_file=None, skip_wizard=False, dev_agent_flags=(), intake_text=None) -> None   # line 93 — always drives DevLoopConsole

# packages/ai-parrot/src/parrot/cli/devloop/console.py
_KIND_CHOICES = ("bug", "enhancement", "feature")                                   # line 32
class DevLoopConsole:  async def start(self, *, brief_file=None, revision=False, dev_agents=None, intake_text=None, skip_confirm=False) -> int   # line 66
    def _load_brief(self, path_str: str) -> Any            # line 687 — parse_brief only (no dev-flow kinds)
    async def _dispatch_run(self, brief: Any) -> str       # line 760 — run_id = f"run-{uuid.uuid4().hex[:8]}" (:768); asyncio.create_task(runner.run(brief, run_id=run_id))

# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
@dataclass class DevLoopRuntime: runner; flow; dispatcher; jira_toolkit=None; redis_url=""; reporter=""; escalation_assignee=""; graph_memory=None   # line 71
async def preflight(*, console: Optional[Console] = None) -> PreflightResult        # line 84 — never raises; checks REDIS_URL, backend CLI, …
async def build_runtime(*, console: Optional[Console] = None) -> DevLoopRuntime    # line 249 — SystemExit(1) on preflight failure; dev-loop (bug) topology
async def default_identities(jira_toolkit: Any) -> Tuple[str, str]                 # line 378 — (reporter, escalation); env JIRA_REPORTER_ACCOUNT_ID / JIRA_ESCALATION_ACCOUNT_ID / FLOW_BOT_JIRA_ACCOUNT_ID, fallback $USER
def _build_jira_toolkit() -> Any                                                    # line 414 — JiraToolkit(server_url=conf.JIRA_URL, username=conf.JIRA_USERNAME, token=conf.JIRA_API_TOKEN) or None

# packages/ai-parrot/src/parrot/cli/devloop/intake.py
def _slugify(value: str) -> str                                                     # line 43

# examples/dev_loop/server_dev.py  (example — NOT importable from the package; imports sibling `server as ops_server`, `llm_catalog`, `mcp_wiring` :40-42)
def _build_dev_brief_from_form(form) -> DevRequestBrief | Any                       # line 266
async def handle_run(request) -> web.Response                                       # line 580 — run_id minted :655; asyncio.create_task(runner.run(...)) → app["flow_tasks"] :801
async def handle_resolve_gate(request) -> web.Response                              # line 834 — delegates to resolve_gate_handler
async def _on_startup(app) -> None                                                  # line 883 — ClaudeCodeDispatcher :892; build_dispatcher cascade :898-928; _resolve_codereview_dispatcher :939; DEV_FLOW_USE_REVIEW_PAIR :947; _build_judge_panel_dispatcher :955; parse_pool_env/resolve_pool_max :966-967; development_dispatcher_builder partial :968-973; _console_default_model_plan :989; DevLoopGraphMemory.from_config :1002; DevLoopWikiSearch.from_project :1003; mcp_wiring.build_research_mcp :1011; jira/git/wiki toolkits :1020-1023; dev_loop_flow_kwargs :1036-1060; build_dev_flow :1061; DevFlowRunner(...) :1062-1077; app["dev_loop_runner"] :1091
# examples/dev_loop/server.py helpers used by the above (example-only): _DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV :187, _log_development_agent_selection :199, _resolve_codereview_dispatcher :508, _build_judge_panel_dispatcher :580, _build_git_toolkit :642, _build_wiki_toolkit :726, _apply_flow_override :1050

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:                                                            # line 72
    def __init__(self, agent, config: SlackAgentConfig, app: web.Application, oauth_manager=None)   # line 83
    #   self._concurrency_semaphore (:109); self._background_tasks: set[asyncio.Task] (:112); self._command_router = SlackCommandRouter() (:118)
    #   routes /api/slack/{id}/events|commands|interactive (:136-144); self._interactive_handler = SlackInteractiveHandler(self) (:143); auth exclude list (:151-155)
    def _is_authorized(self, channel_id: str, user_id: str = None) -> bool         # line 179
    async def _handle_events(self, request) -> web.Response                         # line 201 — auth :289-297; text/thread_ts/session_id :299-302; _safe_answer task :305-315
    async def _handle_command(self, request) -> web.Response                        # line 323 — command_payload keys team_id,user_id,channel_id,text,response_url (:357-363); router.dispatch (:369-375); returns handler dict as JSON
    async def _safe_answer(self, channel, user, text, thread_ts, session_id, files=None) -> None   # line 414
    async def _post_message(self, channel, text, blocks=None, thread_ts=None) -> None   # line 585 — returns None
    async def _delete_message(self, channel: str, ts: str) -> None                 # line 713

# packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:                                                           # line 20
    async def _handle_event(self, payload) -> None                                  # line 173 — auth :246-248; _safe_answer task :255-266
    async def _handle_slash_command(self, payload) -> None                          # line 266 — router.dispatch :300-306; replies via _send_response(response_url, …)
    async def _handle_interactive(self, payload) -> None                            # line 352 — wrapper._interactive_handler.handle(payload)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py
class SlackCommandRouter:   def register(self, command: str, handler: Callable) -> None (:50) ; async def dispatch(self, command, payload) -> Optional[Dict] (:68) ; registered_commands (:97)   # line 26

# packages/ai-parrot-integrations/src/parrot/integrations/slack/interactive.py
class ActionRegistry: register(action_id, handler) (:39); register_prefix(prefix, handler) (:48); get_handler(action_id) (:57)   # line 23
class SlackInteractiveHandler:                                                      # line 96
    def __init__(self, wrapper): self.action_registry = ActionRegistry()            # line 109-116
    async def handle(self, request_or_payload: web.Request | dict) -> Optional[web.Response]   # line 124 — block_actions → handler(payload, action); view_submission → handler registered as f"modal:{callback_id}" (:192-213) returning an optional dict (errors/update)
    async def open_modal(self, trigger_id: str, form_definition: dict) -> bool     # line 308 — keys id, title, fields; trigger_id valid ~3 s
    async def update_modal(self, view_id: str, form_definition: dict) -> bool      # line 366
    def _build_form_blocks(self, fields: List[dict]) -> List[dict]                 # line 417 — field types text/select/…; supports id,label,type,optional,hint
    def extract_form_values(self, payload: dict) -> Dict[str, Any]                 # line 554 — {block_id: value}

# packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
@dataclass class SlackAgentConfig: name; chatbot_id; bot_token; signing_secret; kind="slack"; welcome_message; commands: Dict[str,str]; allowed_channel_ids; allowed_user_ids; webhook_path; app_token; connection_mode="webhook"; enable_assistant; suggested_prompts; max_concurrent_requests=10; jira_client_id/secret/redirect_uri
    __post_init__: env fallbacks {NAME}_SLACK_BOT_TOKEN / _SIGNING_SECRET / _APP_TOKEN / _JIRA_* / _SLACK_ALLOWED_USER_IDS
    @classmethod def from_dict(cls, name: str, data: Dict[str, Any]) -> SlackAgentConfig

# packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py
class SlackOAuthNotifier: __init__(self, bot_token: str); async def notify_connected(...)   # line 73 — chat.postMessage DM by user id with bot token

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
class IntegrationBotManager:                                                        # line 63
    def _get_config_path(self) -> Path                                              # line 102 — ENV_DIR/"integrations_bots.yaml"
    async def startup(self, extra_config=None) -> None                              # line 152 — dispatches per config kind (:173-186)
    async def _start_slack_bot(self, name: str, config: SlackAgentConfig)           # line 858 — SlackAgentWrapper(...) :898; wrapper.start() :906; SlackSocketHandler when connection_mode=="socket" :909-921
    async def shutdown(self) -> None                                                # line 943 — Slack bots stopped :990-999

# packages/ai-parrot-integrations/src/parrot/integrations/models.py
class IntegrationBotConfig: from_dict(data) — kind == 'slack' → SlackAgentConfig.from_dict(name, agent_data) (:64) ; validate() (:74)   # line 25
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `headless.mount_command_endpoint` | `register_command_routes(app, runner)` | function call on a private `web.Application` | `flows/dev_loop/commands.py:208` |
| `headless.run_headless` | `bootstrap.preflight()`, `build_runtime()`, `build_dev_flow_runtime()` | awaits | `cli/devloop/bootstrap.py:84,249` |
| `headless.run_headless` | `DevLoopRunner.run(brief, run_id=…)` / `DevFlowRunner.run(...)` | await (blocks until terminal) | `runner.py:1189`, `dev_flow/runner.py:80` |
| `run_cmd --headless` | Click group `devloop` | new options | `cli/devloop/__init__.py:73-121` |
| `build_dev_flow_runtime` | `build_dev_flow(**kwargs)`, `DevFlowRunner(flow, …, dev_loop_flow_kwargs=kwargs)` | mirrors `_on_startup` | `dev_flow/flow.py:86`, `server_dev.py:1036-1077` |
| `load_headless_brief` | `parse_dev_brief`, `parse_brief` | kind routing | `dev_flow/models.py:131`, `models/base.py:1123` |
| `DevRequestBrief.base_branch` | `_IdeationBrief.base_branch` → subagent payload → document frontmatter | field passthrough | `ideation.py:101,477`; `sdd-ideation.md:170-182`; consumed by `feature_handoff.py:348` |
| `LoopbackRestChannel.resolve_gate` | `POST /runs/{run_id}/gates/{gate_id}/resolve` (`ResolveGateRequest`) | aiohttp `UnixConnector` / TCP | `commands.py:46,77,221` |
| `LoopbackRestChannel.cancel` | `POST /runs/{run_id}/cancel` (`CancelRunRequest`) | same | `commands.py:64,163,224` |
| `RunStateTail.events` | `FlowStreamMultiplexer.state_replay()/state_tail()` | async iteration; `payload` = `ActionEnvelope.model_dump()` | `streaming.py:291,410,397-402` |
| `RunStateTail.events` (snapshot on terminal) | `reduce(state, action)` | fold | `session_state.py:879` |
| `register_devloop` | `wrapper._command_router.register("devloop", …)` | method call | `wrapper.py:118`, `commands/__init__.py:50` |
| `register_devloop` | `wrapper._interactive_handler.action_registry.register_prefix("devloop_", …)` / `.register("modal:devloop_answers", …)` | method call | `interactive.py:116,48,39,192-213` |
| `register_devloop` | `wrapper.add_message_interceptor(…)` (new, M9) | method call; consulted at `wrapper.py:~303` and `socket_handler.py:~253` | `wrapper.py:299-315`, `socket_handler.py:249-266` |
| `SlackAgentWrapper._handle_interactive` (new, M9) | `verify_slack_signature_raw(raw_body, headers, signing_secret)` then `SlackInteractiveHandler.handle(payload_dict)` | replaces the direct route target | `wrapper.py:144,201-240` (events precedent), `slack/security.py` via `slack/__init__.py:17` |
| `SlackSocketHandler._handle_event/_handle_slash_command/_handle_interactive` (M9) | `wrapper._is_authorized(channel, user)` | pass the user id | `socket_handler.py:243,279,352` |
| `SlackDevLoopTransport` | `wrapper.post_message()` / `update_message()` / `open_dm()` (new, M9) | method calls; pattern `_post_message` + `SlackOAuthNotifier` | `wrapper.py:585`, `oauth_callback.py:73` |
| `devloop_command_handler` | slash payload dict | keys `team_id,user_id,channel_id,text,response_url` | `wrapper.py:357-363`, `socket_handler.py:293-299` |
| `handle_answers_submission` | `SlackInteractiveHandler.extract_form_values(payload)` | method call | `interactive.py:554` |
| `actions.handle_block_action` (Answer) | `SlackInteractiveHandler.open_modal(trigger_id, form_definition)` | method call | `interactive.py:308` |
| `IntegrationBotManager._start_slack_bot` | `DevLoopDispatchService(...)`, `register_devloop(wrapper, service)`, `service.start()` | after `wrapper.start()` | `manager.py:906` |
| `IntegrationBotManager.shutdown` | `service.stop()` | before `wrapper.stop()` | `manager.py:990-999` |
| `SlackAgentConfig.from_dict` | `DevLoopIntegrationConfig.from_dict(name, data["devloop"])` | dataclass parse | `slack/models.py:from_dict` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.integrations.devloop`~~, ~~`parrot/integrations/slack/devloop/`~~, ~~`slack/commands/devloop_commands.py`~~ — all new in this spec.
- ~~`parrot devflow` CLI~~ / ~~any CLI entry hosting `DevFlowRunner`~~ — the dev-flow topology is wired only in `examples/dev_loop/server_dev.py::_on_startup`; `parrot devloop` knows only `bug`/`enhancement`/`feature` (`_KIND_CHOICES`, `console.py:32`) and `_load_brief` (`console.py:687`) calls `parse_brief` only.
- ~~`parrot devloop run --headless` / `--command-socket` / `--command-port` / `--run-id`~~ — none today; `run_cmd` always drives `DevLoopConsole`.
- ~~`bootstrap.build_dev_flow_runtime()`~~, ~~`bootstrap.DevFlowRuntime`~~, ~~`bootstrap.load_headless_brief()`~~, ~~`bootstrap._build_git_toolkit()` / `_build_wiki_toolkit()`~~ — new (the git/wiki helpers exist only in `examples/dev_loop/server.py:642/726`, which is not importable).
- ~~`parrot.flows.dev_loop.commands` mounted on any app by the package~~ — only `examples/dev_loop/server_dev.py:834` mounts the resolve handler; nothing in `parrot/handlers` or `ai-parrot-server` does.
- ~~`flow:{run_id}:commands` inbound Redis stream~~ — the runner consumes no Redis commands; Redis is publish-only for state.
- ~~`DevLoopRunner.start_run()` / any fire-and-forget API~~ — `run()` awaits completion; callers wrap it in `asyncio.create_task`.
- ~~`DevLoopRunner.max_concurrent_runs` applying across processes~~ — per-process semaphore (`runner.py:433`); irrelevant with one child per run.
- ~~`SlackAgentWrapper.post_message()` / `update_message()` / `open_dm()` / `add_message_interceptor()` / `_handle_interactive()`~~ — new in M9; today `_post_message` returns `None` (`wrapper.py:585`), only `_delete_message` exists (`:713`), and the interactive route is mounted straight on `SlackInteractiveHandler.handle` (`:144`) with **no signature verification** (`interactive.py` never calls `verify_slack_signature_raw`).
- ~~`SlackSocketHandler` user-level whitelist checks~~ — `_handle_event` (`socket_handler.py:243`) and `_handle_slash_command` (`:279`) call `_is_authorized(channel)` without the user today; M9 adds it.
- ~~`bootstrap.preflight(topology=…)`~~ — the existing `preflight()` has no topology parameter and treats Jira and worktree-base as hard checks (`bootstrap.py:202,223`).
- ~~`run_cmd --cancel-grace`~~, ~~a child-side cancel hook~~ — new in M1; `DevLoopRunner.cancel_run` only records `run/cancelled` (`runner.py:1064-1067`) and nothing in the flow consumes `cancel_requested_by`.
- ~~A pre-LLM hook in `_handle_events` / `SlackSocketHandler._handle_event`~~ — every authorized message goes straight to `_safe_answer` (`wrapper.py:305`, `socket_handler.py:255`).
- ~~`SlackAgentConfig.devloop`~~, ~~`IntegrationBotConfig` devloop keys~~, ~~`IntegrationBotManager._devloop_services`~~ — new.
- ~~`SlackCommandRouter` multi-word subcommand support~~ — dispatches on one command word; `status`/`cancel`/`help` are parsed from `text` inside the `/devloop` handler.
- ~~`DevRequestBrief.flow_type` / `.base_branch`~~ — added by M3; ~~`FeatureBrief.base_branch`~~ — does not exist and is NOT added (the document frontmatter is authoritative, `feature_handoff.py:348`).
- ~~`_IdeationBrief.base_branch`~~ — added by M3; today the subagent instructions hard-code `base_branch: dev` (`sdd-ideation.md:181`).
- ~~`WorkBrief.affected_component` optional~~ — it is a required `str` with no default (`models/base.py:178`).
- ~~Proactive Slack modals~~ — `views.open` needs a `trigger_id` from a user interaction (`interactive.py:315`).
- ~~`SlackInteractiveHandler` support for `response_action: errors` on view_submission~~ — the handler returns whatever dict the modal handler returns (`interactive.py:150-156`); the errors dict shape is Slack's, not a wrapper helper.
- ~~`examples/dev_loop/server.py::_build_judge_panel_dispatcher` importable from the package~~ — example-only; M2 deliberately uses `codereview_dispatcher=None` (model-plan review pair) instead.
- ~~`fakeredis` as a runtime dependency~~ — test-only.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Handshake contract** (M1 ↔ M6): the child prints exactly one line
  `{"event":"ready","run_id":"run-…","command_endpoint":"unix:///…|http://127.0.0.1:N","kind":"…","pid":N}`
  on stdout *before* any other stdout output, only after the endpoint is
  listening. All run logging goes to stderr. The parent reads stdout line by
  line until it validates as `HeadlessHandshake`; any earlier line is
  ignored but logged at DEBUG.
- **Endpoint & auth**: `--command-socket <path>` ⇒ `web.UnixSite`, socket
  file mode `0600`, directory `config.socket_dir` (created `0700`).
  `--command-port N` ⇒ `web.TCPSite("127.0.0.1", N)` (`0` = ephemeral, the
  real port is in the handshake). In **both** modes a middleware requires
  `Authorization: Bearer $PARROT_DEVLOOP_COMMAND_TOKEN` (token generated by
  the parent with `secrets.token_urlsafe(32)`, passed only via env, never
  argv, stored in `RunRecord.command_token` in the Redis registry so a
  restarted bot can still command the run). The socket authenticates the
  *process*, the token is the *per-run capability*, and the Slack-user
  authorization (whitelist + initiator ownership) is enforced in the
  service before any command is forwarded — the REST routes stay
  auth-agnostic by design (`commands.py:19`, S4). Socket is the default;
  TCP only when `config.use_tcp` or the platform lacks AF_UNIX.
- **Cancellation semantics** (S7): `DevLoopRunner.cancel_run()` only
  records `run/cancelled` (`runner.py:1064-1067`); nothing in the flow
  consumes it and `wait_gate` wakes only on gate events. The headless child
  therefore wraps the cancel route: after the library handler answers 200,
  it cancels its own `run_task`, awaits it for `--cancel-grace` seconds and
  exits 2. The service supervises with a longer `cancel_grace_seconds` and
  escalates to `terminate()` (SIGTERM → SIGKILL) if neither a terminal
  action nor an exit arrives.
- **Supervisor bounds** (S8): stdout and stderr are drained from spawn to
  exit by reader tasks (bounded ring buffers); the handshake has
  `handshake_timeout_seconds`; on child exit the tail gets
  `tail_drain_seconds` (5 s) then is cancelled; the tail's Redis backoff is
  bounded by the child's lifetime; socket and brief files are removed by
  the child on exit and by `process.cleanup()` on the parent, idempotently.
- **Preflight by topology** (S3): `preflight(topology="dev_flow")` treats
  Jira as advisory (the dev-flow never creates issues; `server_dev.py`
  builds the toolkit optionally) and both topologies PING Redis instead of
  only checking that a URL is configured.
- **Exit codes**: `FlowResult` reached and state phase `completed` ⇒ 0;
  exception or phase `failed` ⇒ 1; `run/cancelled` ⇒ 2; preflight/bootstrap
  failure (before the handshake) ⇒ 3. The parent treats "exit without a
  terminal action" as `process_exited` regardless of code.
- **Identity**: `resolved_by` / `requested_by` = `Requester.actor` =
  `slack:<team_id>:<user_id>` (stable, auditable in session state).
  `WorkBrief.reporter` / `escalation_assignee`: `identity_resolver` (Slack
  `users.info` email when the `users:read.email` scope is granted) with
  fallback to `bootstrap.default_identities(jira_toolkit)` — never a raw
  Slack user id (open question Q3 keeps the exact precedence adjustable).
- **Bug defaults** (M5): summary = first line of the prompt, clipped to 255;
  if shorter than 10 chars, prefixed with `"bug: "` and padded from the
  description; `affected_component = --component or config.default_component`;
  `acceptance_criteria = [ShellCriterion(name="slack-ac", command=--ac)]`
  when `--ac` is given, else `config.default_acceptance_criteria` parsed as
  `ShellCriterion` dicts (config validation rejects an empty list when
  `enabled` — a `WorkBrief` cannot be built without one); `flow_type` /
  `base_branch` set only when `--base` is given (`"feature"` + the value), so
  the kind default (`bug ⇒ hotfix/main`) is preserved otherwise.
- **Feature defaults** (M5): `kind="new_feature"`; `title = --title` or
  the prompt's first sentence (split on `.`/`\n`, ≤80 chars, ≥1 char);
  `description = prompt`; `jira_issue_key = --jira`; `base_branch = --base`
  and `flow_type="feature"` when given.
- **Run thread**: the public dispatch message is the thread root; every
  later message uses `thread_ts=record.thread_ts`. If `chat.postMessage`
  returns `not_in_channel`, `open_dm(requester.user_id)` provides the
  channel and the ephemeral ack says so.
- **Gate cards**: `open_questions` ⇒ numbered list + **Answer** (opens
  `answers_modal`) + **Abort ideation** (reject). Other kinds ⇒ **Approve** /
  **Reject** with an optional comment modal. After `gate_resolved` /
  `gate_expired` the card is edited in place via `update_message`.
- **Thread fallback regex**: `^\s*(\d+)\s*[:)\.-]\s*(.+)$` per line, numbers
  map 1-based onto `GateView.questions`; out-of-range numbers are ignored
  with an ephemeral hint; at least one valid line is required.
- **Ownership**: every `answer_gate` / `resolve_gate` / `cancel` / `confirm`
  / `discard` compares `requester.actor` to `record.requester.actor` and
  raises `NotRunOwnerError` otherwise; the Slack layer renders it as an
  ephemeral message via `response_url`.
- **Registry keys**: hash `devloop:runs:{run_id}` (JSON `RunRecord`,
  `EX run_retention_seconds` set on terminal), set `devloop:runs:live`;
  pending bug confirmations live only in memory (15 min TTL) — a bot restart
  simply expires them.
- **Re-attach on start**: for each live record, probe the endpoint with a
  `GET` on a non-existent route (any HTTP response ⇒ reachable) then restart
  `RunStateTail.events(last_seen=record.last_seen_seq)`; unreachable ⇒ mark
  `failed` + `post_terminal(process_exited)`.
- **Temp files**: the brief JSON is written under `config.socket_dir`
  (mode `0600`) and deleted on terminal; the socket file is removed by the
  child on exit and, defensively, by the parent on terminal.
- **Both Slack modes**: never add code to only one of `wrapper.py` /
  `socket_handler.py`; the interceptor consult and the router/handler
  registration are shared by construction (the socket handler delegates to
  the wrapper's router and interactive handler already).
- Async-first everywhere; `self.logger = logging.getLogger(__name__)`;
  Pydantic v2 models; Google docstrings; `black` 120; `ruff` TID251 (no
  `requests`/`httpx`, aiohttp only).
- Keep `runner.py`, `session_state.py`, `commands.py`, `streaming.py`
  untouched (G4 / non-goals).

### Known Risks / Gotchas
- **Slash-command 3 s ack**: the handler must return the ephemeral dict
  immediately and do everything else in a tracked background task; the
  child handshake alone can take tens of seconds (preflight + runtime
  bootstrap).
- **Modal trigger_id expires in ~3 s**: `open_modal` must be the first await
  after the block action arrives; look up the gate from the in-memory
  registry, never from Redis, before opening.
- **`chat.update` rate limit** (Tier 3): status card edits are debounced
  (2 s trailing edge) and coalesced; `ratelimited` responses back off with
  `Retry-After` and drop the edit rather than retry-storm.
- **Slash text is capped at 3000 chars** by Slack: the ack tells the user
  to shorten; document intake is a follow-up.
- **`WorkBrief.summary` min 10 / max 255** and `affected_component`
  required: enforced by M5 defaults; validation errors are returned to the
  user as ephemeral text, never raised into Slack's 500 path.
- **Gate expiry**: `open_questions` gates are fail-closed with a 24 h TTL
  (`DEV_FLOW_GATE_TTL_QUESTIONS`); the card shows the deadline; an expired
  gate aborts ideation and the run ends `failed` — surfaced verbatim.
- **Concurrent resolvers**: the HTML console (if also running) or a TTL
  sweep can resolve first ⇒ 409; the card is refreshed from the
  `gate_resolved` event, and the clicker gets an ephemeral notice.
- **Redis outage while tailing**: exponential backoff (1→30 s) and resume
  from `last_seen_seq` via `state_replay(last_seen=…)`; the run itself only
  publishes and keeps going.
- **Bot restart**: in-memory tails die; Redis records survive; `start()`
  re-attaches (G7). Children are session leaders (`start_new_session=True`)
  and are **not** killed by the bot's process group.
- **Child crash before handshake**: `SpawnError` carries the exit code and
  the last 4 KiB of stderr; the thread root is still posted (as failed) so
  the user has a trace.
- **Headless preflight needs the coding CLIs and Jira env in the *bot's*
  environment** (the child inherits it): document this in
  `docs/integrations/slack-devloop.md`; `preflight()` failures exit 3 and
  are shown to the user.
- **`build_dev_flow_runtime` drift**: the example console keeps its own
  wiring; M2's optional refactor of `server_dev.py` is the mitigation. If
  it is skipped, add a test asserting both call `build_dev_flow` with the
  same key set.
- **Dev-flow review dispatcher choice**: the headless default uses the
  model-plan review pair (`codereview_dispatcher=None`) rather than the
  example's judge panel; the two differ in QA behaviour. Recorded as the
  decided default; revisit in Q5 if operators need the judge panel headless.
- **`--dev-agent` is not exposed** in v1 Slack flags; the child accepts the
  brief's `dev_agents` if a future flag sets it.
- **Socket path length**: AF_UNIX paths are limited (~108 bytes); keep
  `socket_dir` short (default under `tempfile.gettempdir()`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing core dep | child command server (`UnixSite`/`TCPSite`), client `UnixConnector` |
| `redis` (`redis.asyncio`) | `>=5.0` (existing optional; new `[devloop]` extra in `ai-parrot-integrations`) | `FlowStreamMultiplexer` tail, run registry |
| `slack-sdk` | `>=3.27` (existing optional `[slack]`) | Socket Mode only; unchanged |
| `click`, `pydantic` | existing | CLI options, models |
| `fakeredis` | test-only (already used by dev_loop tests) | tail/registry tests |
| stdlib `shlex`, `argparse`, `secrets`, `asyncio.subprocess` | — | parser, token, child lifecycle |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → `dev`.
- [x] Execution model — *Resolved in brainstorm*: subprocess per run with a REST/Redis bridge (Option A: loopback command endpoint + Redis state tail).
- [x] Intake surface — *Resolved in brainstorm*: `/devloop` slash command on `SlackCommandRouter`.
- [x] Open-Questions UX — *Resolved in brainstorm*: button → Block Kit modal, plus threaded `N:` reply fallback.
- [x] Request types in v1 — *Resolved in brainstorm*: `feature` (new_feature) and `bug`; `enhancement` and document intake deferred.
- [x] Bug intake with required WorkBrief fields — *Resolved in brainstorm*: defaults, then a confirm card (Confirm / Edit → modal / Cancel).
- [x] Status card scope — *Resolved in brainstorm*: in v1 as the last, optional task (M13).
- [x] Authorization — *Resolved in brainstorm*: existing whitelist for dispatch; initiator-only for answers and cancel.
- [x] Telegram — *Resolved in brainstorm*: Slack-only v1 on a transport-agnostic core; Telegram adapter is a follow-up spec.
- [x] Concurrency — *Resolved in brainstorm*: unlimited (optional soft cap `max_concurrent_runs` in config).
- [x] Extra flags — *Resolved in brainstorm*: `--jira KEY`, `--base dev|staging`, subcommands `status` / `cancel` / `help`.
- [x] Bridge transport — *Resolved in brainstorm*: Unix domain socket by default (`--command-socket`, filesystem permissions); loopback TCP + per-run bearer token (`--command-port`) as fallback.
- [x] `--base` for feature runs — *Resolved in brainstorm*: add `flow_type` / `base_branch` to `DevRequestBrief` in this spec and thread them into the `FeatureBrief` that ideation emits. *Spec note*: realised through the ideation document frontmatter (M3) — the FeatureBrief's base branch is read from the committed document (`feature_handoff.py:348`), so no `FeatureBrief` field is added.
- [x] Run registry persistence — *Resolved in brainstorm*: Redis-persisted registry (`devloop:runs:{run_id}`, TTL = retention); on bot startup live records are re-attached via `state_replay()`.
- [x] Orphan policy — *Resolved in brainstorm*: children keep running (`start_new_session=True`); the bot never cancels them on shutdown.
- [ ] Q1 Should **feature** runs also get a confirm card before dispatch (title/description/jira/base preview), or dispatch immediately? Spec default: dispatch immediately (M8); flipping to a card reuses M10's confirm machinery. — *Owner: Jesus Lara*
- [ ] Q2 Default acceptance criterion for bug runs: a configured `ShellCriterion` list (spec default, `config.default_acceptance_criteria`, must pass `ACCEPTANCE_CRITERION_ALLOWLIST`) or require `--ac` and refuse otherwise? — *Owner: Jesus Lara*
- [ ] Q3 Identity for `WorkBrief.reporter` / `escalation_assignee`: request `users:read.email` and map Slack email → Jira (spec default when the scope is present) or always fall back to `bootstrap.default_identities()`? — *Owner: Jesus Lara*
- [ ] Q4 Expose the headless mode for the `enhancement` kind (light proposal) at zero extra cost, even though Slack v1 does not expose `--type enhancement`? Spec default: `load_headless_brief` accepts it (it is free); Slack rejects it. — *Owner: Jesus Lara*
- [ ] Q5 Headless dev-flow review dispatcher: keep the model-plan review pair as the default (spec decision, M2) or re-home the judge-panel helper from `examples/dev_loop/server.py:580` into the package so the child matches the console? — *Owner: Jesus Lara*
- [ ] Q6 Where should `build_dev_flow_runtime()` live: `parrot/cli/devloop/bootstrap.py` (spec choice, next to `build_runtime`) or a new `parrot/flows/dev_flow/bootstrap.py` importable without the CLI? — *Owner: Claude / spec author* (spec choice stands unless objected)
- [ ] Q7 Should `IntegrationBotManager.shutdown` also persist a "bot going down" marker so `status` can tell "unobserved since" for runs that were live during the outage? — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning high) · Status: completed
> · Transcript: `sdd/state/FEAT-555/design_research/`
> Every `affected_paths` entry passed repository containment and `test -e`; every CONFIRM below was re-verified in the
> cited source before adoption (line anchors in the Reason column).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Use an explicit topology discriminator (architecture) | CONFIRM | `console._load_brief` (console.py:687) only knows `parse_brief`; `DevRequestBrief` has no base-branch field. The headless loader routes on the brief's `kind`; `flow_type`/`base_branch` added. | §3 M2 `load_headless_brief`, M3, M5 |
| S2 | Extract a package-owned dev-flow builder (architecture) | CONFIRM | `server_dev.py::_on_startup` imports sibling example modules (server_dev.py:40-42). Builder returns the exact `dev_loop_flow_kwargs`; the example delegates. | §3 M2 (`DevFlowRuntime.dev_loop_flow_kwargs`) |
| S3 | Split preflight by topology (risk) | CONFIRM | `PreflightResult.ok = all(c.passed)` (bootstrap.py:223) with Jira as a hard check (:202) while the dev-flow treats Jira as optional; the Redis check only tests URL presence (:92-105). | §3 M2 `preflight(topology=…)`, §7, AC22 |
| S4 | Enforce initiator authorization outside the REST contract (risk) | CONFIRM | `commands.py:19` documents the routes as auth-agnostic; handlers trust `resolved_by`. Ownership is persisted in the Redis registry and the per-run bearer token is now required in both socket and TCP modes. | §3 M1/M6, §7 endpoint & auth, AC15 |
| S5 | Fix Slack ingress authentication and mode parity first (risk) | CONFIRM | `interactive.py` has no signature verification and the route is mounted directly (wrapper.py:144); `socket_handler.py:243,279` call `_is_authorized(channel)` without the user. Pre-existing gaps the new gate actions would widen. | §3 M9, §4, AC20 |
| S6 | Add a gate-reply interceptor before normal message handling (architecture) | CONFIRM | Both paths go straight to `_safe_answer` (wrapper.py:305, socket_handler.py:255). Designed as `add_message_interceptor`, consulted in both modes. | §3 M9, M11 |
| S7 | Make cancellation terminate the child flow (risk) | CONFIRM | `cancel_run` only applies `RunCancelled` (runner.py:1064-1067); no node consumes `cancel_requested_by`; `wait_gate` wakes only on gate events (session_state.py:1394-1400). Child cancels its run task after a 200 cancel; parent escalates to SIGTERM/SIGKILL. | §3 M1, M6, M8, §7, AC21 |
| S8 | Specify a bounded subprocess supervisor (risk) | CONFIRM | Stdout handshake needs continuous pipe draining; the tail must stop on child exit; deterministic socket cleanup. | §3 M6, M8, §7 |
| S9 | Add integration-level admission control (architecture) | REJECT | The user explicitly decided "unlimited" concurrency in discovery (brainstorm §Open Questions); the spec provides an opt-in `max_concurrent_runs`, TTL cleanup of pending confirmations, and documents unlimited as the explicit default. | — |
| S10 | Extend the Slack wrapper for debounced status updates (api) | CONFIRM | `_post_message` returns None (wrapper.py:585); Slack API calls stay in the wrapper (`post_message`/`update_message`), debounce lives in the transport. | §3 M9, M13 |
| S11 | Test the real cross-process contract (testing) | CONFIRM | Existing tests are in-process; added explicit integration rows: Unix-site/client contract, first-writer 409, cancel, crash before terminal, Redis loss, socket cleanup, Slack auth parity in both modes. | §4 Integration Tests |
| S12 | Declare Redis in the devloop integration extra (risk) | CONFIRM | `redis>=5.0` is only under the `msteams` and `broadcast` extras (pyproject.toml:56,104). `[devloop]` extra + install-path test. | §3 M12, §4, §7 External Dependencies |

Summary: **11** confirmed · **1** rejected · **0** escalated.

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Cross-feature dependencies**: none — no in-flight task (27 in
  `sdd/tasks/active/`) touches `parrot/integrations/slack/`,
  `parrot/cli/devloop/` or `parrot/flows/dev_loop|dev_flow/`; pending
  indexes (`contracts-card-ontology`, `fireflies-wiki-knowledgebase-agent`,
  `meta-llm-client`, `msteams-formdesigner-renderer`) are unrelated.
- **Lanes** (parallelizable once the handshake contract in §7 and the
  `RunEvent`/`DevLoopTransport` protocols in §2/§3 are fixed):
  1. **Core lane** — M1, M2, M3 (all under `packages/ai-parrot/`): can run
     in its own worktree; only M1 depends on M2.
  2. **Integration-core lane** — M4 → M5 → M6/M7 (parallel) → M8 (all under
     `packages/ai-parrot-integrations/…/devloop/`): testable against a fake
     child script and fakeredis, independent of lane 1 at build time.
  3. **Slack lane** — M9 → M10 → M11 → M12 → M13 (`…/slack/…`, manager,
     docs): depends on M4/M8 models; sequential within one worktree.
- **Merge order**: lane 1 and lane 2 can merge in either order; lane 3
  after lane 2; M13 last. End-to-end integration tests (§4) run only after
  all three lanes are on the feature branch.
- **Shared files with recent history** (keep edits additive):
  `parrot/cli/devloop/__init__.py` / `console.py` / `bootstrap.py`
  (FEAT-374/388), `slack/wrapper.py` / `socket_handler.py` (FEAT-225),
  `dev_flow/models.py` / `nodes/ideation.py` (FEAT-412/482/486).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-12 | Jesus Lara + Claude (Fable 5.1) | Initial draft from accepted brainstorm (Option A); 4 open questions resolved at spec time; codex design research (gpt-5.6-luna) folded: 11 confirmed / 1 rejected |
