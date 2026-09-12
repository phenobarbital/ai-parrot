---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Dev-Loop Slack Kick-off — dispatch and steer dev-loop runs from Slack

**Date**: 2026-09-12
**Author**: Jesus Lara + Claude (Fable 5.1)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

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

**Who is affected**: developers and tech leads who kick off dev-loop runs
(the "requester"), and the operator who hosts the integration server.

**Why now**: the dev-flow ideation gates (FEAT-412), the per-run session
state on Redis (FEAT-322) and the REST gate-resolve contract (FEAT-322 /
FEAT-412) already exist and are stable. The Slack integration already has a
command router (FEAT-225), Block Kit modals and a bot token that can push
messages on demand. Every primitive exists; only the glue is missing.

### Decisions taken during discovery (Rounds 0–3)

| Topic | Decision |
|---|---|
| Flow type / base | `feature` → `dev` |
| Execution model | Dev-loop runs in a **subprocess**; the integration talks to it through a REST/Redis bridge (bridge shape weighed below) |
| Intake surface | Slack **slash command** `/devloop` registered on the existing `SlackCommandRouter` |
| Open-Questions UX | Message + "Answer" button → **Block Kit modal** (primary) **and** threaded free-text reply (fallback) |
| Request types (v1) | `--type feature` (dev-flow `new_feature` → brainstorm + Open Questions) and `--type bug` (dev-loop `WorkBrief` topology). `enhancement` and document intake deferred |
| Bug intake | Build the `WorkBrief` from defaults, post a **confirm card** (Confirm / Edit / Cancel); Edit opens a modal |
| Status card | **In v1 as the last, optional task** — one message per run edited on node lifecycle events |
| Authorization | Existing `allowed_user_ids` whitelist gates dispatch; **only the initiator** may answer gates or cancel their run |
| Telegram | **Slack-only in v1**, on top of a transport-agnostic core so a Telegram adapter is a follow-up spec |
| Concurrency | **Unlimited** — every request spawns a subprocess (a soft, optional cap may be added by config) |
| Extra flags | `--jira KEY`, `--base dev\|staging`, subcommands `status` / `cancel` / `help` |

## Constraints & Requirements

- **Subprocess isolation is a hard requirement.** A run must never execute
  inside the Slack bot process; a crashed or hung run must not take the
  integration down.
- **No new inbound-network surface on the bot for gate answers.** Whatever
  bridge is chosen must be loopback / Redis only; the public Slack endpoints
  stay the only externally reachable routes.
- **Reuse the existing gate contract.** Answers must reach the run through
  `SessionHost.resolve_gate(...)` semantics (first writer wins, 409 on
  double-resolve, `answers` required for `open_questions`); the integration
  must never re-implement gate arbitration.
- **Reuse the Slack wrapper's extension points.** New commands register on
  `SlackCommandRouter`; new buttons/modals register on
  `SlackInteractiveHandler.action_registry`; no parallel Slack client.
- **Both Slack connection modes must work** (webhook and Socket Mode) — both
  already funnel slash commands and interactive payloads through the same
  router / handler.
- **Transport-agnostic core.** Everything that is not Slack-specific
  (option parsing, brief building, subprocess lifecycle, state tailing, gate
  bridging) lives in a channel-neutral module so Telegram can be added
  without touching it.
- **The dev-flow topology has no CLI today.** Only
  `examples/dev_loop/server_dev.py` knows how to wire `DevFlowRunner`; that
  wiring is in an *example*, not in the package, so the headless subprocess
  entry must get a library-level runtime builder.
- **Slack platform limits**: modals need a `trigger_id` from a user
  interaction (never proactive); `chat.update` is rate-limited (Tier 3,
  ~50/min per channel) so status-card refreshes must be debounced; slash
  command acks must be returned within 3 s.
- **Host prerequisites for the subprocess**: repo checkout, `.venv`, Redis,
  the coding CLIs (`claude`, `codex`, …), Jira credentials — the same
  preflight `parrot devloop` already runs (`bootstrap.preflight`).
- No new third-party dependencies beyond what `ai-parrot-integrations[slack]`
  and `redis>=5.0` already declare.
- Async-first, Pydantic v2 models, `self.logger`, Google docstrings, `black`
  line length 120, `ruff` TID251 import bans.

---

## Options Explored

### Option A: Headless dev-loop subprocess with a loopback command endpoint + Redis state tail

The integration spawns one headless process per run:
`parrot devloop run --brief <tmpfile> --yes --headless --command-socket <path>`
(a new headless mode of the existing Click command). The child process boots
the runtime exactly like the CLI console does today (`bootstrap.build_runtime`
for `--type bug`; a new, library-level `build_dev_flow_runtime` — extracted
from `server_dev.py::_on_startup` — for `--type feature`), mounts the
already-existing `register_command_routes(app, runner)` on a tiny aiohttp
server bound to a Unix domain socket (or a loopback TCP port when sockets are
unavailable), prints a one-line JSON handshake on stdout
(`{"event": "ready", "run_id": ..., "command_endpoint": ...}`), then awaits
`runner.run(brief, run_id=...)` and exits with the run's status.

The integration tails `flow:{run_id}:actions` through
`FlowStreamMultiplexer(redis, run_id=..., view="state").state_tail()`. A
`gate/opened` action becomes a Slack message in the run thread; the user's
answer (modal submission or thread reply) becomes a
`POST /runs/{run_id}/gates/{gate_id}/resolve` on the child's command
endpoint with the existing `ResolveGateRequest` body; `node/*` actions feed
the status card; `run/closed` / `run/cancelled` (or the child exiting) close
the run with a summary.

✅ **Pros:**
- Reuses the **proven REST contract** (`ResolveGateRequest`, 200/400/404/409
  semantics) verbatim; zero new gate logic.
- Reuses the **existing Redis state stream** the HTML console already
  consumes; the integration is just another `view="state"` client.
- The child is the same `parrot devloop` entry operators already know; the
  headless mode is also useful for CI / cron kick-offs, not only Slack.
- Crash isolation: a dying run just ends a thread with "failed".
- Unix socket = filesystem permissions = no token to manage; no listening
  TCP port.

❌ **Cons:**
- Single-host only: the integration server must run on the same machine as
  the subprocesses (socket / loopback). Multi-host needs Option B later.
- Needs a new library-level dev-flow runtime builder (today the wiring lives
  only in `examples/dev_loop/server_dev.py`).
- One aiohttp server per run (cheap, but N of them).
- If the bot process restarts, its in-memory run registry is lost; runs keep
  going but Slack stops receiving updates unless the registry is persisted
  (see Open Questions).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | child command server (`web.UnixSite` / `web.TCPSite`) + client (`UnixConnector`) | already a core dependency |
| `redis>=5.0` (`redis.asyncio`) | `FlowStreamMultiplexer` state tail | already an optional dep of `ai-parrot-integrations` (`[devloop]` extra to add it) |
| `asyncio.create_subprocess_exec` (stdlib) | spawn/monitor the headless child | no new dep |
| `shlex` + `argparse` (stdlib) | parse `/devloop --type bug --jira KEY <prompt>` | no new dep; `click` is not needed on the parsing side |
| `slack-sdk>=3.27` | Socket Mode only (already optional) | unchanged |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` — `run_cmd` (`--brief`, `--yes`) gains `--headless` / `--command-socket`.
- `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` — `preflight()`, `build_runtime()`, `default_identities()`, `DevLoopRuntime`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` — `register_command_routes`, `ResolveGateRequest`, `CancelRunRequest`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` — `FlowStreamMultiplexer.state_replay()` / `state_tail()`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` — `ApprovalGate`, `NodeState`, `GateOpened`, `GateResolved`, `GateExpired`.
- `examples/dev_loop/server_dev.py` — `_on_startup` (source of the dev-flow wiring to lift into the package), `_build_dev_brief_from_form` (brief-building precedent).
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py` — `SlackCommandRouter`; `jira_commands.register_jira_commands` as the registration pattern.
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/interactive.py` — `SlackInteractiveHandler.open_modal`, `extract_form_values`, `ActionRegistry.register_prefix`.
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` — `SlackOAuthNotifier` (bot-token DM push pattern).

---

### Option B: Inbound Redis command stream consumed by the runner

Keep the subprocess, but replace the loopback REST endpoint with a new
inbound stream `flow:{run_id}:commands`. The child process runs a consumer
task that reads `resolve_gate` / `cancel` entries and applies them through
`runner.resolve_gate(...)` / `runner.cancel_run(...)`; the integration only
ever talks to Redis (XADD to send, XREAD to tail). The ack/result of each
command is itself published on `flow:{run_id}:actions` (a `gate/resolved`
action already is), so the integration confirms by observing state.

✅ **Pros:**
- Fully decoupled and **multi-host**: the Slack bot and the run workers can
  live on different machines; only Redis is shared.
- Symmetric with the existing outbound stream design (FEAT-322).
- No per-run listening socket at all.

❌ **Cons:**
- New runner code in the hottest area of the codebase (`runner.py` /
  `session_state.py`, which FEAT-322/377/412/480 all touched recently).
- A new wire protocol to design: idempotency keys, at-least-once delivery,
  error reporting for a rejected command (a REST 409 becomes "watch the
  stream and infer"), consumer-group semantics if a run is ever resumed.
- Anyone with Redis access can drive a run; Redis becomes a control plane and
  needs the corresponding hardening.
- Does not by itself solve the missing dev-flow headless entry (still
  needed).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis>=5.0` | XADD / XREADGROUP for the command stream | already available |
| `asyncio.create_subprocess_exec` (stdlib) | spawn the child | no new dep |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` — `resolve_gate()` / `cancel_run()` as the apply target of consumed commands.
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` — `SessionHost` action sink (publish precedent for the outbound stream).
- `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` — `_read_action_envelopes` / `_fields_to_envelope` (envelope encoding precedent).

---

### Option C: In-process `DevFlowRunner` inside the integrations server

Mirror `server_dev.py` inside the integration: the bot process builds the
dev-loop and dev-flow runtimes at startup, `/devloop` calls
`asyncio.create_task(runner.run(...))`, gates are answered by calling
`runner.resolve_gate(...)` directly, and status updates come from
`runner.get_host(run_id)` snapshots or the same Redis tail.

✅ **Pros:**
- The least code: no subprocess, no handshake, no bridge; gate answers are a
  method call.
- `active_runs()` / `registry_state` give a free `/devloop status`.

❌ **Cons:**
- Violates the isolation requirement: a run's memory / CPU / hung coding CLI
  lives inside the chat bot; a runner bug restarts every Slack bot.
- Ties the integration server's deployment to the full dev-loop host
  prerequisites (repo checkout, coding CLIs, Jira) even when only chat is
  wanted.
- Rejected during discovery (Round 1) in favour of the subprocess model;
  kept here for the record.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | — |

🔗 **Existing Code to Reuse:**
- `examples/dev_loop/server_dev.py` — `_on_startup`, `handle_run`, `handle_resolve_gate` wholesale.

---

### Option D (unconventional): Long-lived dev console service, Slack as a thin client

Invert the ownership: run `server_dev.py` (or a productised
`parrot devloop serve`) as a permanent daemon that owns all runs, and make
the Slack integration a pure front-end that POSTs `/api/flow/run`, POSTs
`/api/flow/{run_id}/gates/{gate_id}/resolve` and tails the same WebSocket /
Redis stream the HTML UI uses. Slack, the HTML console and the terminal
console become three equal clients of one service.

✅ **Pros:**
- Zero new runtime code; the REST contract already exists in `server_dev.py`.
- Runs survive Slack bot restarts; `/devloop status` can list *every* run,
  not only Slack-started ones.
- Multiple front-ends can watch and answer the same run (HTML + Slack).

❌ **Cons:**
- Not a subprocess per run: one daemon hosts everything, so one crashing run
  can take the others down (the isolation the user asked for is weaker).
- `server_dev.py` is an *example*, explicitly "development-only"; it would
  need to be promoted into a package module with auth, before becoming a
  dependency of an integration.
- Requires the daemon to be up; there is no lazy "spawn on demand".
- Answers from Slack must be attributed (`resolved_by`) through a service
  that has its own identity model — two auth layers to reconcile.

📊 **Effort:** Medium (High if `server_dev.py` is promoted properly)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` client | HTTP + WebSocket client to the console | already core |

🔗 **Existing Code to Reuse:**
- `examples/dev_loop/server_dev.py` — `handle_run`, `handle_resolve_gate`, `handle_checkpoint`, `/api/config`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` — the WS `view=state` protocol.

---

## Recommendation

**Option A** is recommended because:

- It honours every hard constraint from discovery: subprocess isolation, no
  new public surface, the existing gate contract reused verbatim, and a
  transport-agnostic core.
- It is the **smallest change to the hot code**: nothing in `runner.py` or
  `session_state.py` moves. The only core-package additions are a headless
  mode on an existing Click command and lifting the dev-flow wiring out of
  an example file into an importable builder — a change that also pays back
  by de-duplicating `server_dev.py`.
- Option B's multi-host benefit is real but speculative for v1 (the Slack
  bot and the runs share one workstation today), and it costs a new control
  protocol in the most churned module of the repo. Option A should therefore
  define the integration-side bridge behind a small interface
  (`RunCommandChannel` with `resolve_gate()` / `cancel()`) so that a Redis
  implementation (Option B) can be dropped in later without touching the
  Slack adapter.
- Option D is attractive as a *future* consolidation (one service, many
  front-ends) but promotes a development-only example into production
  infrastructure, which is a separate spec.

**What we trade off**: single-host deployment for v1, and one small aiohttp
listener per run (Unix socket, filesystem-permissioned). Both are acceptable
for the stated use case (a team workstation / build box hosting the bot).

---

## Feature Description

### User-Facing Behavior

**Kick-off**

```
/devloop --type feature Add a per-tool token budget to the compression stage
/devloop --type bug --jira NAV-8241 The customer sync drops the last row when the CSV has a trailing newline
/devloop --type feature --base staging Ship the Slack status card before the freeze
/devloop status
/devloop cancel run-3f9a1c2b
/devloop help
```

1. The slash command is acknowledged within 3 s with an ephemeral
   "Validating…" reply (the existing router already returns the handler's
   dict as the ack).
2. Authorization: the channel/user must pass the existing
   `allowed_channel_ids` / `allowed_user_ids` whitelist; otherwise the user
   gets the existing ephemeral "Unauthorized."
3. Option parsing: `--type {feature,bug}` (required), `--jira KEY`,
   `--base {dev,staging}`, `--title "…"` (optional, feature only — the slug
   source when the first line of the prompt is not a good title); everything
   that is not a flag is the prompt. Unknown flags → ephemeral usage error.
4. **`--type feature`** → the integration builds a
   `DevRequestBrief(kind="new_feature", title=<--title or first sentence>,
   description=<prompt>, jira_issue_key=<--jira>)` and dispatches
   immediately. It posts a **public message in the channel**
   ("🚀 Development flow dispatched — run `run-…` for *<title>*, started by
   @user"); that message's `ts` becomes the **run thread**. Everything
   further happens in that thread.
5. **`--type bug`** → the integration builds a `WorkBrief(kind="bug")` from
   defaults (summary = first line ≤255 chars, description = prompt,
   `affected_component` = `--component` or a configured default, reporter /
   escalation = the initiator's identity, one default `ShellCriterion`
   acceptance criterion from config, `existing_issue_key` = `--jira`,
   `flow_type` / `base_branch` from `--base`) and posts a **confirm card**
   in the channel showing those fields with **Confirm / Edit / Cancel**
   buttons. *Edit* opens a modal pre-filled with the fields; *Confirm*
   dispatches and converts the card into the run thread root; *Cancel*
   deletes it. Only the initiator's clicks are honoured.
6. When the subprocess reports ready, the thread receives "Run `run-…`
   started" with the base branch and Jira key (if any).

**Open Questions round (feature runs)**

7. When the ideation node opens an `open_questions` gate, the thread receives
   a message titled with the gate title (which already carries the document
   path), the round instructions, the numbered questions, and two buttons:
   **Answer** (opens a modal with one multiline input per question, all
   optional — partial answers are allowed by the gate contract) and
   **Abort ideation** (rejects the gate).
8. **Thread fallback**: the initiator may instead reply in the thread with
   lines like `1: pgvector` / `2) async flush` — one `N:` / `N)` prefix per
   answer. The integration maps numbers to questions and resolves the gate
   with those answers. A reply that matches no `N:` pattern is ignored with
   an ephemeral hint (it is *not* forwarded to the chat LLM).
9. Successful resolution edits the gate message to "✅ Answered by @user
   (k of n)"; a 409 (already resolved / expired) edits it to the actual
   state. Anyone who is not the initiator gets an ephemeral "This run
   belongs to @initiator."

**Other gates** (`plan_approval`, `manual_criterion`, `deployment_approval`,
`review_escalation`, `revision_approval`): a generic gate card with the
title / instructions / payload reference and **Approve / Reject** buttons
plus an optional comment modal. Same ownership rule.

**Progress and completion**

10. Status card (optional last task): one message in the thread listing the
    flow's nodes with ✅ completed / 🔄 running / ⚪ idle / ❌ failed /
    ⏭ skipped, edited via `chat.update` on `node/*` actions, debounced to at
    most one edit per ~2 s per run.
11. On `run/closed`: "✅ Completed" (PR URL, Jira key, docs artifacts when
    present) or "❌ Failed: <error>"; on `run/cancelled`: "⛔ Cancelled by
    @user". If the subprocess exits without a terminal action (crash before
    publishing), the thread gets "❌ The run process exited unexpectedly
    (code N)" with the tail of its stderr.
12. `/devloop status` → ephemeral list of the caller's runs (run id, kind,
    phase, current node, pending gate, thread permalink). `/devloop cancel
    <run-id>` → `POST /runs/{id}/cancel` on the child; only the initiator.

### Internal Behavior

**Package layout (transport-agnostic core + Slack adapter)**

```
packages/ai-parrot-integrations/src/parrot/integrations/devloop/   # NEW, channel-neutral
    __init__.py
    models.py        # DevLoopIntegrationConfig, DevLoopCommand, RunRecord, GateView, RunEvent
    parser.py        # "/devloop …" text → DevLoopCommand (shlex + argparse), usage text
    briefs.py        # DevLoopCommand + initiator identity → WorkBrief | DevRequestBrief (defaults)
    process.py       # HeadlessRunProcess: spawn, handshake, wait, kill, stderr capture
    bridge.py        # RunCommandChannel (protocol) + LoopbackRestChannel (aiohttp UnixConnector / TCP)
    tail.py          # RunStateTail: FlowStreamMultiplexer(view="state").state_tail() → RunEvent stream
    service.py       # DevLoopDispatchService: registry of RunRecord, dispatch(), answer_gate(), cancel(), status()
    transport.py     # DevLoopTransport protocol the service calls back into (post_run_started, post_gate, update_status, post_terminal)

packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/  # NEW, Slack adapter
    __init__.py      # register_devloop(wrapper, service) — commands + actions + thread interceptor
    commands.py      # /devloop handler on SlackCommandRouter (dispatch / status / cancel / help)
    blocks.py        # Block Kit builders: dispatch ack, bug confirm card, gate card, answers modal, status card, terminal summary
    actions.py       # action_registry handlers (prefix "devloop_"), view_submission handlers
    transport.py     # SlackDevLoopTransport(DevLoopTransport): chat.postMessage / chat.update in the run thread
```

**Core-package additions (ai-parrot)**

- `parrot devloop run --headless --command-socket <path> [--command-port N]`:
  non-interactive mode of the existing `run_cmd` that (a) requires
  `--brief`, (b) runs `bootstrap.preflight()`, (c) builds the runtime for
  the brief's topology, (d) mounts `register_command_routes(app, runner)` on
  a `web.UnixSite` (or `web.TCPSite` on 127.0.0.1), (e) prints the JSON
  handshake line on stdout, (f) awaits `runner.run(brief, run_id=...)`,
  (g) exits 0 / 1 / 2 (completed / failed / cancelled).
- `build_dev_flow_runtime()` — a library-level builder (in
  `parrot/cli/devloop/bootstrap.py`, next to `build_runtime`) that wires
  `build_dev_flow(...)` + `DevFlowRunner(...)` exactly as
  `examples/dev_loop/server_dev.py::_on_startup` does today. The example
  should be refactored to call it (optional task) so the two never drift.
- The headless brief file carries the dev-flow `kind` (`new_feature`) so the
  loader can route to the dev-flow runtime; today the CLI loader only knows
  `bug` / `enhancement` / `feature` (`_KIND_CHOICES`).

**Run lifecycle (sequence)**

1. Slack slash command → `SlackCommandRouter.dispatch("devloop", payload)` →
   `parser.parse(text)` → `DevLoopCommand`.
2. `service.dispatch(command, initiator, channel)`: builds the brief
   (`briefs.py`), writes it to a temp YAML/JSON file, mints `run_id`
   (`run-<hex8>`, same convention as the console), spawns
   `HeadlessRunProcess`, awaits the handshake (timeout → "failed to start"
   with stderr), registers a `RunRecord(run_id, initiator_user_id,
   channel_id, thread_ts, command_endpoint, process, kind, started_at)`.
3. `transport.post_run_started(record)` posts the public message; its `ts`
   is stored as `thread_ts`.
4. `RunStateTail` starts: `state_replay()` (to catch anything published
   before the tail attached) then `state_tail()`; each action envelope is
   reduced to a `RunEvent` (`gate_opened`, `gate_resolved`, `gate_expired`,
   `node_changed`, `run_closed`, `run_cancelled`, `jira_linked`) and handed
   to the transport.
5. A gate answer from Slack → `service.answer_gate(run_id, gate_id,
   resolution, resolved_by, answers, comment)` → ownership check →
   `LoopbackRestChannel.resolve_gate(...)` → HTTP status mapped to a
   user-facing result (200 ok / 400 answers_required / 404 unknown /
   409 already resolved).
6. Terminal action or process exit → `transport.post_terminal(record,
   outcome)`; the record is kept for `status` for a configurable retention,
   the socket file is removed, the temp brief deleted.

**Identity mapping**: `resolved_by` / `requested_by` = `slack:<team_id>:<user_id>`
(stable and auditable in session state). For the `WorkBrief` reporter /
escalation fields (Jira accountId or email), the integration uses
`users.info` (`users:read.email` scope) when available and falls back to
`bootstrap.default_identities()` (the Jira toolkit's current user) exactly
like the terminal console does.

**Configuration** (`integrations_bots.yaml`, per Slack bot):

```yaml
kind: slack
name: devbot
chatbot_id: dev-assistant
allowed_user_ids: [U0123, U0456]
devloop:
  enabled: true
  repo_path: /srv/ai-parrot            # cwd of the subprocess
  command: ["parrot", "devloop", "run"]  # resolved on PATH / .venv
  redis_url: redis://localhost:6379/0
  socket_dir: /run/parrot/devloop
  default_component: ai-parrot
  default_acceptance_criteria:
    - {kind: shell, name: unit-tests, command: "pytest packages/ai-parrot/tests -q"}
  status_card: true
  max_concurrent_runs: null            # null = unlimited (decision)
  run_retention_seconds: 86400
```

`SlackAgentConfig` gains an optional `devloop: DevLoopIntegrationConfig`
(dataclass, env fallbacks `{NAME}_DEVLOOP_*`), parsed in `from_dict`.
`IntegrationBotManager._start_slack_bot` calls `register_devloop(wrapper,
service)` when `devloop.enabled` is true.

### Edge Cases & Error Handling

- **Unauthorized user / channel** → existing ephemeral "Unauthorized." (no
  information leak about runs).
- **Malformed command** (`--type` missing, unknown flag, empty prompt) →
  ephemeral usage text; nothing spawned.
- **Preflight failure in the child** (no Redis, missing CLI, no Jira creds)
  → the child exits non-zero before the handshake; the thread root is
  posted with "❌ Could not start: <first stderr lines>".
- **Handshake timeout** (child hung during bootstrap) → kill the child, post
  failure, clean up socket/temp file.
- **Bot not a member of the channel** (`chat.postMessage` `not_in_channel`)
  → fall back to a DM thread with the initiator (`conversations.open`, as
  `SlackOAuthNotifier` does) and say so in the ephemeral ack.
- **Gate already resolved / expired** (HTML console or TTL got there first)
  → 409 from the child; the gate message is edited to the real state; the
  clicker gets an ephemeral notice.
- **Non-initiator clicks / replies** → ephemeral "This run belongs to
  @initiator"; the gate stays pending.
- **Thread reply that is not an answer** (no `N:` prefix, or no pending gate
  on that run) → ephemeral hint; never forwarded to the chat LLM. A thread
  reply on a thread that is *not* a run thread is untouched (normal chat).
- **Modal submission with zero answers** → the child returns 400
  `answers_required` (host rule); the modal shows a validation error instead
  of closing.
- **Redis unavailable while tailing** → the tail reconnects with backoff;
  the run continues (it only publishes); when the tail resumes it uses
  `state_replay()` from the last seen seq so no gate is missed.
- **Bot restart** → in-memory `RunRecord`s are lost; children spawned with
  `start_new_session=True` keep running. v1 behaviour: on restart, records
  are not recovered (Open Question: persist the registry in Redis under
  `devloop:slack:runs:*` so tails can be re-attached from `state_replay`).
- **Cancel of an already-terminal run** → 409 → ephemeral "already
  finished".
- **`--base` on a feature run**: `DevRequestBrief` has no `flow_type` /
  `base_branch` fields; the value is inert for feature runs unless the spec
  adds them (see Does NOT Exist / Open Questions). For bug runs it maps to
  `WorkBrief.base_branch` (and `flow_type="feature"` when a non-`main` base
  is given, since `kind="bug"` derives `hotfix → main` by default).
- **Status card rate limits** → debounce edits, coalesce bursts, and on
  `ratelimited` back off using `Retry-After`; the card is best-effort and a
  failed edit never affects the run.
- **Very long prompts** (> 3000 chars in a slash command) → Slack truncates
  slash text at 3000 chars; the ack tells the user to shorten or attach a
  document (document intake is a follow-up).

---

## Capabilities

### New Capabilities
- `devloop-headless-run`: `parrot devloop run --headless` — non-interactive
  child mode with a loopback command endpoint, JSON handshake and exit codes
  (core package).
- `devflow-runtime-builder`: library-level `build_dev_flow_runtime()` lifted
  from `examples/dev_loop/server_dev.py::_on_startup` (core package).
- `devloop-integration-core`: channel-neutral
  `parrot.integrations.devloop` — models, command parser, brief defaults,
  subprocess lifecycle, `RunCommandChannel` bridge, Redis state tail,
  dispatch service, transport protocol.
- `slack-devloop-commands`: `/devloop` dispatch / status / cancel / help on
  `SlackCommandRouter`, run thread creation, bug confirm card.
- `slack-devloop-gates`: gate cards, answers modal, generic approve/reject,
  threaded `N:` answer fallback, initiator-only ownership.
- `slack-devloop-status-card`: optional live node card via `chat.update`
  (last task).
- `devloop-integration-config`: `devloop:` section on `SlackAgentConfig` /
  `integrations_bots.yaml` + manager wiring.

### Modified Capabilities
- `slack-wrapper-integration` (`sdd/specs/slack-wrapper-integration.spec.md`):
  the wrapper needs (a) a message-posting helper that **returns the message
  `ts`** and a `chat.update` helper, and (b) a small **thread-message
  interceptor hook** consulted in `_handle_events` before `_safe_answer`, so
  run-thread replies never reach the chat LLM.
- `devloop-cli-console` (`sdd/specs/devloop-cli-console.spec.md` /
  `devloop-cli-homologation*.spec.md`): new headless mode and a brief loader
  that accepts the dev-flow `new_feature` kind.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` (`run_cmd`) | extends | `--headless`, `--command-socket`, `--command-port`; non-interactive exit codes |
| `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` | extends | `build_dev_flow_runtime()`; reuse `preflight`, `default_identities` |
| `packages/ai-parrot/src/parrot/cli/devloop/console.py` / brief loader | modifies | accept `kind: new_feature` → dev-flow runtime; today `_KIND_CHOICES = ("bug", "enhancement", "feature")` |
| `examples/dev_loop/server_dev.py` | modifies (optional) | call `build_dev_flow_runtime()` instead of inlining the wiring |
| `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` | depends on | `register_command_routes`, `ResolveGateRequest`, `CancelRunRequest` — unchanged |
| `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` | depends on | `FlowStreamMultiplexer` `view="state"` — unchanged |
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | depends on | `ApprovalGate`, `NodeState`, action types — unchanged |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/` | new | channel-neutral core |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/` | new | Slack adapter |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | modifies | `_post_message` returning `ts` (or a new `_post_message_ts`), `_update_message`, thread-interceptor hook |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` | extends | `SlackAgentConfig.devloop` |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | extends | `_start_slack_bot` registers the dev-loop service when enabled |
| `packages/ai-parrot-integrations/pyproject.toml` | extends | `[devloop]` extra = `redis>=5.0` (+ `slack` extra) |
| Slack app manifest (docs) | documents | scopes `commands`, `chat:write`, `chat:write.public` (optional), `im:write`, `users:read`, `users:read.email`; interactivity URL; `/devloop` slash command |
| `docs/` | new | `docs/integrations/slack-devloop.md` — setup, manifest, config, command syntax |

No breaking changes: every existing Slack route, command and gate contract
keeps its behaviour; the feature is off unless `devloop.enabled` is set.

---

## Code Context

### User-Provided Code

No code snippets were provided; the request was prose (see Problem
Statement and the discovery table).

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:                                                        # line ~410
    def __init__(self, flow: AgentsFlow, *, max_concurrent_runs: Optional[int] = None,
                 dispatcher: Optional[Any] = None, jira_toolkit: Optional[Any] = None,
                 git_toolkit: Optional[Any] = None, wiki_toolkit: Optional[Any] = None,
                 redis_url: Optional[str] = None, codereview_dispatcher: Optional[Any] = None,
                 graph_memory: Optional[Any] = None,
                 checkpoint_store: Optional[Union[str, CheckpointStore]] = None,
                 dev_loop_flow_kwargs: Optional[Dict[str, Any]] = None) -> None: ...   # line 417
    def get_host(self, run_id: str) -> Optional[SessionHost]: ...                       # line 516
    @property
    def registry_state(self) -> RunRegistryState: ...                                   # line 526
    async def resolve_gate(self, run_id: str, gate_id: str, resolution: str, resolved_by: str,
                           comment: str = "", origin: Optional[ActionOrigin] = None,
                           answers: Optional[Dict[str, str]] = None) -> ActionEnvelope: ...  # line 1005
    async def cancel_run(self, run_id: str, requested_by: str) -> ActionEnvelope: ...  # line 1051
    def active_runs(self) -> Set[str]: ...                                              # line 1072
    async def run(self, brief: Union[WorkBrief, FeatureBrief], *, run_id: Optional[str] = None,
                  initial_task: str = "", extra_shared: Optional[Dict[str, Any]] = None,
                  flow_kwargs_overrides: Optional[Dict[str, Any]] = None) -> FlowResult: ...  # line 1189
    # NOTE: run() awaits the whole flow; it returns only when the run terminates.

# From packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):                                          # line 41
    async def run(self, brief: DevRequestBrief | FeatureBrief, *, run_id: str | None = None,
                  initial_task: str = "", extra_shared: dict[str, Any] | None = None,
                  model_plan: DevFlowModelPlan | None = None) -> FlowResult: ...       # line 80

# From packages/ai-parrot/src/parrot/flows/dev_flow/flow.py
def build_dev_flow(...) -> AgentsFlow: ...                                   # line 86

# From packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
NodeStatus = Literal["idle", "running", "completed", "failed", "skipped"]   # line 161
GateKind   = Literal[... "plan_approval", "review_escalation", "open_questions", ...]  # line 174-181
GateStatus = Literal["pending", "approved", "rejected", "expired"]          # line 183
class NodeState(_Frozen):                                                    # line 243
    node_id: NodeId; status: NodeStatus = "idle"; started_at: Optional[float]; finished_at: Optional[float]
    error: str = ""; dispatch: Optional[DispatchState]; summary: Dict[str, str]
class ApprovalGate(_Frozen):                                                 # line 257
    gate_id: str; kind: GateKind; node_id: NodeId; status: GateStatus = "pending"
    on_expiry: Literal["fail", "approve"] = "fail"; title: str = ""; instructions: str = ""
    payload_ref: str = ""; opened_at: float; expires_at: Optional[float]
    resolved_by: str = ""; resolved_at: Optional[float]; comment: str = ""
    questions: List[str] = []; answers: Dict[str, str] = {}                 # FEAT-412, line 291-292
class DevLoopSessionState(_Frozen):                                          # line 330
    run_id: str; channel: str; phase: RunPhase; work_kind: Literal["bug","enhancement","new_feature",""]
    summary: str; jira_issue_key: str; pr_url: str; nodes: Dict[str, NodeState]; gates: Dict[str, ApprovalGate]
    cancel_requested_by: str; error: str; docs_artifacts: List[DocsArtifact]; ...
class GateOpened(_ActionBase):   type = "gate/opened";   gate: ApprovalGate  # line 492
class GateResolved(_ActionBase): type = "gate/resolved"; gate_id: str; resolution: Literal["approved","rejected"]
                                 resolved_by: str; comment: str = ""; answers: Dict[str, str] = {}  # line 497
class GateExpired(_ActionBase):  type = "gate/expired";  gate_id: str        # line 511
class SessionHost:                                                           # line 1134
    def resolve_gate(self, gate_id: str, resolution: Literal["approved","rejected"], resolved_by: str,
                     comment: str = "", origin: Optional[ActionOrigin] = None,
                     answers: Optional[Dict[str, str]] = None) -> ActionEnvelope: ...  # line 1226
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str, instructions: str = "",
                  payload_ref: str = "", ttl_seconds: Optional[int] = None,
                  on_expiry: Literal["fail","approve"] = "fail",
                  questions: Optional[List[str]] = None) -> Tuple[str, ActionEnvelope]: ...  # line 1290
    async def wait_gate(self, gate_id: str) -> ApprovalGate: ...              # line 1374

# From packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py
class FlowStreamMultiplexer:                                                 # line 73
    def __init__(self, redis: Any, *, run_id: str, view: ViewLiteral = "both",
                 dispatch_refresh_seconds: float = 2.0, block_ms: int = 1000) -> None: ...  # line 76
    # stream keys: f"flow:{run_id}:flow" (line 102), f"flow:{run_id}:dispatch:" (103), f"flow:{run_id}:actions" (106)
    async def state_replay(self, *, last_seen: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]: ...  # line 291
    async def state_tail(self) -> AsyncIterator[Dict[str, Any]]: ...          # line 410 (stops on run/closed | run/cancelled)

# From packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
class ResolveGateRequest(BaseModel):  # frozen, extra="forbid"              # line 46
    resolution: Literal["approved", "rejected"]; resolved_by: str (min_length=1)
    comment: str = ""; client_seq: int = 0; answers: dict[str, str] = {}
class CancelRunRequest(BaseModel):    requested_by: str (min_length=1)      # line 64
async def resolve_gate_handler(request: web.Request) -> web.Response: ...    # line 77  (200/400 invalid_body|answers_required/404/409)
async def cancel_run_handler(request: web.Request) -> web.Response: ...      # line 163
def register_command_routes(app: web.Application, runner: DevLoopRunner) -> None: ...  # line 208
    # binds app["dev_loop_runner"]; POST /runs/{run_id}/gates/{gate_id}/resolve ; POST /runs/{run_id}/cancel

# From packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ShellCriterion(_AcceptanceCriterionBase):                              # line 56
    kind: Literal["shell"] = "shell"; command: str; name: str; timeout_seconds: int = 300; expected_exit_code: int = 0
WorkKind = Literal["bug", "enhancement", "new_feature"]                      # line 116
class WorkBrief(BaseModel):                                                  # line 138
    kind: WorkKind = "bug"; summary: str (min 10, max 255); description: str = ""
    affected_component: str                       # REQUIRED, no default (line 178)
    log_sources: List[LogSource] = []; acceptance_criteria: List[AcceptanceCriterion] (min_length=1)
    escalation_assignee: str; reporter: str       # REQUIRED — Jira accountId or email
    existing_issue_key: Optional[str] = None; dev_agents: Optional[List[DevAgentSpec]] = None
    dev_isolation: Optional[Literal["shared","isolated"]] = None
    flow_type: Optional[Literal["feature","hotfix"]] = None   # None ⇒ bug→hotfix, else feature (line 219)
    base_branch: Optional[str] = None                          # None ⇒ hotfix→main, feature→dev (line 226)
class DevAgentSpec(BaseModel): ...                                           # line 412
class FeatureBrief(BaseModel): ...                                           # line 817

# From packages/ai-parrot/src/parrot/flows/dev_flow/models.py
DevRequestKind = Literal["enhancement", "new_feature"]
class DevRequestBrief(BaseModel):                                            # line 61
    kind: DevRequestKind; title: str (min 1); description: str (min 1); context: str = ""
    jira_issue_key: str | None = None; dev_agents: list[DevAgentSpec] | None = None
    judge_panel: JudgePanelConfig | None = None
    # NO flow_type / base_branch fields
def parse_dev_brief(data: dict[str, Any]) -> DevRequestBrief | FeatureBrief: ...  # line 131
class IdeationOutput(BaseModel):                                             # line 166
    document_path: str; document_kind: Literal["brainstorm","proposal"]; slug: str
    resumed_existing: bool = False; open_questions: list[str] = []; summary: str = ""; committed: bool = False

# From packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
#   host.open_gate(kind="open_questions", node_id=self.name, title=f"Open questions — {document_path}",
#                  instructions=..., questions=questions,
#                  ttl_seconds=int(getattr(conf, "DEV_FLOW_GATE_TTL_QUESTIONS", 86400)), on_expiry="fail")  # line ~596
#   gate = await host.wait_gate(gate_id); answers = dict(gate.answers or {})                                # line ~614-624

# From packages/ai-parrot/src/parrot/cli/__init__.py
#   cli._lazy_commands["devloop"] = "parrot.cli.devloop"                     # line 125

# From packages/ai-parrot/src/parrot/cli/devloop/__init__.py
@devloop.command("run")                                                      # line 73
@click.option("--brief", ...) @click.option("--yes", "skip_wizard", ...) @click.option("--dev-agent", ...) @click.option("--text", ...)
def run_cmd(brief_file: str | None = None, skip_wizard: bool = False,
            dev_agent_flags: tuple[str, ...] = (), intake_text: str | None = None) -> None: ...  # line 93

# From packages/ai-parrot/src/parrot/cli/devloop/console.py
_KIND_CHOICES: tuple[str, ...] = ("bug", "enhancement", "feature")           # line 32
class DevLoopConsole:                                                        # line 47
    async def start(self, *, brief_file: str | None = None, revision: bool = False,
                    dev_agents: list[DevAgentSpec] | None = None, intake_text: str | None = None,
                    skip_confirm: bool = False) -> int: ...                  # line 66

# From packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
@dataclass class DevLoopRuntime: runner; flow; dispatcher; jira_toolkit=None; redis_url=""; reporter=""; escalation_assignee=""; graph_memory=None  # line 71
async def preflight(*, console: Optional[Console] = None) -> PreflightResult: ...        # line 84
async def build_runtime(*, console: Optional[Console] = None) -> DevLoopRuntime: ...     # line 249 (dev-loop/bug topology only)
async def default_identities(jira_toolkit: Any) -> tuple[str, str]: ...                  # line 378 (reporter, escalation)

# From examples/dev_loop/server_dev.py  (example — NOT importable from the package)
def _build_dev_brief_from_form(form: dict[str, Any]) -> DevRequestBrief | Any: ...     # line 266
async def handle_run(request: web.Request) -> web.Response: ...                        # line 580 (asyncio.create_task(runner.run(...)) → app["flow_tasks"])
async def handle_resolve_gate(request: web.Request) -> web.Response: ...               # line 834 (delegates to resolve_gate_handler)
async def _on_startup(app: web.Application) -> None: ...                               # line 883 (build_dev_flow + DevFlowRunner wiring, line 1061-1079)

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:                                                     # line 72
    def __init__(self, agent: 'AbstractBot', config: SlackAgentConfig, app: web.Application,
                 oauth_manager: Optional['JiraOAuthManager'] = None): ...    # line 83
    #   self._command_router = SlackCommandRouter()                          # line 118
    #   self._interactive_handler = SlackInteractiveHandler(self)            # line 143
    #   routes: /api/slack/{chatbot_id}/events | /commands | /interactive   # line 136-144
    def _is_authorized(self, channel_id: str, user_id: str = None) -> bool: ...          # line 179
    async def _handle_events(self, request: web.Request) -> web.Response: ...            # line 201 (message/app_mention → _safe_answer, no hook)
    async def _handle_command(self, request: web.Request) -> web.Response: ...           # line 323 (router.dispatch first; returns handler dict as JSON)
    async def _safe_answer(self, channel: str, user: str, text: str, thread_ts: Optional[str],
                           session_id: str, files: Optional[List[Dict[str, Any]]] = None) -> None: ...  # line 414
    async def _post_message(self, channel: str, text: str, blocks: Optional[List[Dict[str, Any]]] = None,
                            thread_ts: Optional[str] = None) -> None: ...    # line 585 — returns None (no ts)
    async def _delete_message(self, channel: str, ts: str) -> None: ...     # line 713
def convert_markdown_to_mrkdwn(text: str) -> str: ...                        # line 27

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py
class SlackCommandRouter:                                                    # line 26
    def register(self, command: str, handler: Callable) -> None: ...         # line 50  (handler: async (payload: dict) -> dict | None)
    async def dispatch(self, command: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]: ...  # line 68
    # payload keys: team_id, user_id, channel_id, text, response_url (wrapper.py:357-363 / socket_handler.py:293-299)

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py
def register_jira_commands(router: "SlackCommandRouter", oauth_manager: "JiraOAuthManager") -> None: ...  # line 166

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/interactive.py
class ActionRegistry:                                                        # line 23
    def register(self, action_id: str, handler: Callable) -> None: ...       # line 39
    def register_prefix(self, prefix: str, handler: Callable) -> None: ...   # line 48  (handler(payload, action))
class SlackInteractiveHandler:                                               # line 96
    def __init__(self, wrapper: 'SlackAgentWrapper'): self.action_registry = ActionRegistry() ...  # line 109
    async def handle(self, request_or_payload: web.Request | dict) -> Optional[web.Response]: ...  # line 124
    async def _handle_view_submission(self, payload: dict) -> Optional[dict]: ...  # line 192 (routes by callback_id via action_registry)
    async def open_modal(self, trigger_id: str, form_definition: dict) -> bool: ...   # line 308 (keys: id, title, fields)
    async def update_modal(self, view_id: str, form_definition: dict) -> bool: ...    # line 366
    def extract_form_values(self, payload: dict) -> Dict[str, Any]: ...      # line 554

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
class SlackSocketHandler:                                                    # line 20
    async def _handle_slash_command(self, payload: Dict[str, Any]) -> None: ...  # line 266 (same router.dispatch; replies via response_url)
    async def _handle_interactive(self, payload: Dict[str, Any]) -> None: ...    # line 352 (→ wrapper._interactive_handler.handle)

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
@dataclass class SlackAgentConfig:  name; chatbot_id; bot_token; signing_secret; commands: Dict[str,str]
    allowed_channel_ids: Optional[List[str]]; allowed_user_ids: Optional[List[str]]; app_token; connection_mode: str = "webhook"
    jira_client_id / jira_client_secret / jira_redirect_uri
    @classmethod def from_dict(cls, name: str, data: Dict[str, Any]) -> 'SlackAgentConfig': ...

# From packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py
class SlackOAuthNotifier:  def __init__(self, bot_token: str); async def notify_connected(...)   # line 73 (chat.postMessage DM via bot token)

# From packages/ai-parrot-integrations/src/parrot/integrations/manager.py
class IntegrationBotManager:                                                 # line 63
    def _get_config_path(self) -> Path: ...   # ENV_DIR / "integrations_bots.yaml"   # line 102
    async def _start_slack_bot(self, name: str, config: SlackAgentConfig): ...        # line 858 (builds SlackAgentWrapper, optional SlackSocketHandler)
# From packages/ai-parrot-integrations/src/parrot/integrations/models.py
class IntegrationBotConfig:  @classmethod from_dict(...)  # kind == 'slack' → SlackAgentConfig.from_dict  # line 25 / 47 / 64
```

#### Verified Imports

```python
# Core (packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py)
from parrot.flows.dev_loop import DevLoopRunner, WorkBrief, ShellCriterion, FeatureBrief   # lines 30, 71-73
from parrot.flows.dev_loop import register_command_routes, FlowStreamMultiplexer, build_dev_loop_flow  # lines 12, 29, 34
from parrot.flows.dev_loop.commands import ResolveGateRequest, CancelRunRequest, resolve_gate_handler, cancel_run_handler
from parrot.flows.dev_loop.session_state import ApprovalGate, NodeState, DevLoopSessionState, GateOpened, GateResolved, GateExpired, SessionHost
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput, parse_dev_brief, DevFlowModelPlan
from parrot.flows.dev_flow.runner import DevFlowRunner          # lazy via parrot.flows.dev_flow.__getattr__ too
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.cli.devloop.bootstrap import preflight, build_runtime, default_identities, DevLoopRuntime

# Integrations (packages/ai-parrot-integrations/src/parrot/integrations/slack/__init__.py)
from parrot.integrations.slack import SlackAgentWrapper, SlackAgentConfig, SlackInteractiveHandler, ActionRegistry, SlackSocketHandler
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.jira_commands import register_jira_commands
from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier
from parrot.integrations.manager import IntegrationBotManager

# Third party already declared
import redis.asyncio as aioredis        # ai-parrot-integrations optional extras (pyproject.toml:56/104) and examples/dev_loop/server_dev.py:59
from aiohttp import web, ClientSession  # core dependency
```

#### Key Attributes & Constants
- `SlackAgentWrapper._command_router` → `SlackCommandRouter` (wrapper.py:118) — where `/devloop` registers.
- `SlackAgentWrapper._interactive_handler.action_registry` → `ActionRegistry` (interactive.py:116) — where `devloop_*` buttons / `callback_id`s register.
- `SlackAgentWrapper._background_tasks` → `set[asyncio.Task]` (wrapper.py:112) — track long-lived tail tasks for graceful shutdown.
- `SlackAgentWrapper.config.allowed_user_ids` / `allowed_channel_ids` → whitelist consulted by `_is_authorized` (wrapper.py:179).
- Redis stream keys: `flow:{run_id}:actions` (state, streaming.py:106), `flow:{run_id}:flow`, `flow:{run_id}:dispatch:*`.
- Terminal action types that stop `state_tail`: `run/closed`, `run/cancelled` (streaming.py:410 docstring).
- Gate resolve HTTP statuses: 200 / 400 `invalid_body` / 400 `answers_required` / 404 / 409 (commands.py:77 docstring; server_dev.py:834 docstring).
- Run-id convention: `f"run-{uuid.uuid4().hex[:8]}"` (server_dev.py:655; runner.py:1189 docstring).
- Ideation gate TTL: `conf.DEV_FLOW_GATE_TTL_QUESTIONS` default 86400 s, `on_expiry="fail"` (ideation.py:~600).
- Slack modal `trigger_id` validity ≈ 3 s (interactive.py:315 docstring).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.integrations.devloop`~~ / ~~`parrot/integrations/slack/devloop/`~~ / ~~`slack/commands/devloop_commands.py`~~ — none exist; all new.
- ~~`parrot devflow` CLI~~ / ~~any CLI entry that hosts `DevFlowRunner`~~ — the dev-flow topology is only wired in `examples/dev_loop/server_dev.py::_on_startup`; `parrot devloop` knows only `bug` / `enhancement` / `feature` (`_KIND_CHOICES`, console.py:32) and boots `DevLoopRunner` via `bootstrap.build_runtime`.
- ~~`parrot devloop run --headless`~~ / ~~`--command-socket`~~ / ~~`--command-port`~~ — no headless mode today; `run_cmd` always drives `DevLoopConsole` (Rich + prompt_toolkit).
- ~~`build_dev_flow_runtime()`~~ — no library-level dev-flow runtime builder; must be lifted out of the example.
- ~~`flow:{run_id}:commands` inbound Redis stream~~ — the runner consumes no Redis commands; Redis is publish-only (`flow:{run_id}:actions`). Commands enter only via `DevLoopRunner.resolve_gate()` / `cancel_run()` in-process or `register_command_routes` REST.
- ~~`DevLoopRunner.start_run()` / fire-and-forget API~~ — `run()` awaits completion; `server_dev.py` wraps it in `asyncio.create_task`.
- ~~`SlackAgentWrapper._post_message()` returning `ts`~~ — it returns `None`; ~~`_update_message()` / `chat.update` helper~~ — none exists (only `_delete_message`).
- ~~A thread-reply interceptor / pre-LLM hook in `_handle_events`~~ — every authorized `message` / `app_mention` goes straight to `_safe_answer` → the chat LLM.
- ~~`SlackAgentConfig.devloop`~~ — no such section; ~~`IntegrationBotConfig` devloop keys~~ — none.
- ~~`DevRequestBrief.flow_type` / `.base_branch`~~ — not fields (server_dev.py:330-337 comment confirms the override is inert for dev-flow briefs); `--base` only maps onto `WorkBrief`.
- ~~`WorkBrief.affected_component` optional~~ — it is a required `str` with no default.
- ~~Proactive Slack modals~~ — `views.open` requires a `trigger_id` from a user interaction; a bot cannot pop a modal on its own.
- ~~`DevLoopRunner.max_concurrent_runs` applying across processes~~ — it is a per-process semaphore; with one subprocess per run it never limits anything (hence the integration-level optional cap).
- ~~`SlackCommandRouter` support for multi-word subcommands~~ — it dispatches on a single command word; `status` / `cancel` / `help` must be parsed from `text` inside the `/devloop` handler.

---

## Parallelism Assessment

- **Internal parallelism**: yes, three lanes once the handshake contract
  (JSON ready line + command endpoint + exit codes) and the `RunEvent` /
  `DevLoopTransport` protocols are fixed in the spec:
  1. **Core lane** (`ai-parrot`): headless `run_cmd` mode +
     `build_dev_flow_runtime()` + brief-loader `new_feature` support (+
     optional `server_dev.py` refactor). Touches only `parrot/cli/devloop/`.
  2. **Integration-core lane** (`ai-parrot-integrations/…/devloop/`):
     parser, brief defaults, process, bridge, tail, service — testable
     against a fake child process and a fake Redis.
  3. **Slack lane** (`…/slack/devloop/` + wrapper hooks + config +
     manager): commands, blocks, actions, transport.
  The status card is a fourth, strictly-last task on lane 3.
- **Cross-feature independence**: no in-flight task (27 in
  `sdd/tasks/active/`) touches `parrot/integrations/slack/`,
  `parrot/cli/devloop/` or `parrot/flows/dev_loop/`; pending indexes
  (`contracts-card-ontology`, `fireflies-wiki-knowledgebase-agent`,
  `meta-llm-client`, `msteams-formdesigner-renderer`) are unrelated. Shared
  files with *recent* history: `parrot/cli/devloop/__init__.py` /
  `console.py` (FEAT-374/388), `slack/wrapper.py` (FEAT-225) — keep the
  wrapper edits additive (new helpers + one hook call).
- **Recommended isolation**: `mixed`.
- **Rationale**: the core lane and the two integration lanes live in
  different distributions with a contract between them; they can run in
  separate worktrees and merge independently. The Slack lane depends on the
  integration-core models, so tasks 2 → 3 are sequential inside one
  worktree, while lane 1 can proceed in parallel.

---

## Open Questions

- [x] Feature or hotfix, and base branch? — *Owner: Jesus Lara*: feature → `dev`.
- [x] Execution model? — *Owner: Jesus Lara*: subprocess per run with a REST/Redis bridge (Option A recommended; B as later evolution).
- [x] Intake surface? — *Owner: Jesus Lara*: `/devloop` slash command on `SlackCommandRouter`.
- [x] Open-Questions UX? — *Owner: Jesus Lara*: button → Block Kit modal, plus threaded `N:` reply fallback.
- [x] Request types in v1? — *Owner: Jesus Lara*: `feature` (new_feature) and `bug`; `enhancement` and document intake deferred.
- [x] Bug intake with required WorkBrief fields? — *Owner: Jesus Lara*: defaults, then a confirm card (Confirm / Edit → modal / Cancel).
- [x] Status card scope? — *Owner: Jesus Lara*: in v1 as the last, optional task.
- [x] Authorization? — *Owner: Jesus Lara*: existing whitelist for dispatch; initiator-only for answers and cancel.
- [x] Telegram? — *Owner: Jesus Lara*: Slack-only v1 on a transport-agnostic core; Telegram adapter is a follow-up spec.
- [x] Concurrency? — *Owner: Jesus Lara*: unlimited (optional soft cap in config).
- [x] Extra flags? — *Owner: Jesus Lara*: `--jira KEY`, `--base dev|staging`, subcommands `status` / `cancel` / `help`.
- [ ] Bridge transport for the child's command endpoint: Unix domain socket (recommended on Linux, permission-based) vs loopback TCP + per-run bearer token (portable)? Support both with socket as default? — *Owner: Jesus Lara*
- [ ] `--base` for **feature** runs: add `flow_type` / `base_branch` to `DevRequestBrief` (and thread them to the `FeatureBrief` ideation emits) in this spec, or accept that `--base` is bug-only in v1 and document it? — *Owner: Jesus Lara*
- [ ] Should **feature** runs also get a confirm card before dispatch (title/description/jira/base preview), or dispatch immediately as decided for the "defaults" path? — *Owner: Jesus Lara*
- [ ] Run registry persistence: keep `RunRecord`s only in memory (lost on bot restart; children keep running headless) or persist them in Redis (`devloop:slack:runs:{run_id}`) so tails re-attach via `state_replay()` after a restart? — *Owner: Jesus Lara*
- [ ] Orphan policy: when the bot stops, should children be left running (`start_new_session=True`) or cancelled via their command endpoint during shutdown? — *Owner: Jesus Lara*
- [ ] Identity for `WorkBrief.reporter` / `escalation_assignee`: request `users:read.email` and map Slack email → Jira, or always fall back to `bootstrap.default_identities()` (the Jira toolkit's current user)? — *Owner: Jesus Lara*
- [ ] Default acceptance criterion for bug runs: a single configured `ShellCriterion` (must pass `ACCEPTANCE_CRITERION_ALLOWLIST`), or require `--ac "<command>"` and refuse otherwise? — *Owner: Jesus Lara*
- [ ] Should the headless mode also be exposed for the `enhancement` kind (light proposal) at zero extra cost, even though Slack v1 does not expose `--type enhancement`? — *Owner: Jesus Lara*
- [ ] Where should the `build_dev_flow_runtime()` builder live: `parrot/cli/devloop/bootstrap.py` (next to `build_runtime`) or `parrot/flows/dev_flow/bootstrap.py` (importable without the CLI)? — *Owner: Claude / spec author*
