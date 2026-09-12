<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Option A (recommended) — body
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

### Verified code anchors (paths only — open them yourself)
examples/dev_loop/server_dev.py
packages/ai-parrot-integrations/src/parrot/integrations/manager.py
packages/ai-parrot-integrations/src/parrot/integrations/models.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/__init__.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/interactive.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/socket_handler.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
packages/ai-parrot/src/parrot/cli/__init__.py
packages/ai-parrot/src/parrot/cli/devloop/__init__.py
packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
packages/ai-parrot/src/parrot/cli/devloop/console.py
packages/ai-parrot/src/parrot/flows/dev_flow/flow.py
packages/ai-parrot/src/parrot/flows/dev_flow/models.py
packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py
packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py

### Questions still open in the exploration document
- [ ] Should **feature** runs also get a confirm card before dispatch (title/description/jira/base preview), or dispatch immediately as decided for the "defaults" path? — *Owner: Jesus Lara*
- [ ] Identity for `WorkBrief.reporter` / `escalation_assignee`: request `users:read.email` and map Slack email → Jira, or always fall back to `bootstrap.default_identities()` (the Jira toolkit's current user)? — *Owner: Jesus Lara*
- [ ] Default acceptance criterion for bug runs: a single configured `ShellCriterion` (must pass `ACCEPTANCE_CRITERION_ALLOWLIST`), or require `--ac "<command>"` and refuse otherwise? — *Owner: Jesus Lara*
- [ ] Should the headless mode also be exposed for the `enhancement` kind (light proposal) at zero extra cost, even though Slack v1 does not expose `--type enhancement`? — *Owner: Jesus Lara*
- [ ] Where should the `build_dev_flow_runtime()` builder live: `parrot/cli/devloop/bootstrap.py` (next to `build_runtime`) or `parrot/flows/dev_flow/bootstrap.py` (importable without the CLI)? — *Owner: Claude / spec author*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
