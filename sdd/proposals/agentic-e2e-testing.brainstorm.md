---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Agentic End-to-End Testing (real servers, real keys, no mocks)

**Date**: 2026-09-12
**Author**: Jesus (jesuslarag@gmail.com)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The SDD pipeline validates features with unit tests, `ruff`/`mypy`, and a
deterministic QA pass (`sdd-qa`, `qa-runner`) — all of which run **in-process**
or against mocks. Nothing in the pipeline ever boots the code under test as a
**real process** and talks to it over a **real transport** with **real
credentials**. The consequences are the class of bugs that only appear at the
process boundary:

- A transport that starts but does not serve (verified during this brainstorm:
  `parrot mcp serve <cfg> --transport http` binds the port and **exits 0
  immediately** because `HttpMCPServer.start()` is non-blocking and
  `_run_standalone_server` never waits — see *Spike Research*).
- stdout purity on stdio MCP (navconfig's eager `print()` corrupting JSON-RPC,
  `toolkit_server.py:14-21`), env/key resolution through `navconfig`, auth
  middleware exclusions (`/mcp/info` is *not* in `ParrotMCPServer`'s
  auth-exclusion list, `parrot_server.py:193-198`), route registration on a
  live `aiohttp` app, shutdown/teardown hangs (`run.py:59-94` documents
  the interpreter hanging on non-daemon threads from torch/TF/grpc).
- On the Admin UI (`packages/ai-parrot-server/ui`, Svelte 5 + Vite): hydration
  errors, `/api` proxy misconfiguration, console errors and 5xx responses that
  a Vitest/jsdom suite can never see.

**Who is affected**: developers running `sdd-worker`/`sdd-autopilot` (their
"done" is currently unverified at the process boundary); operators who find
these defects at deploy time; the dev-loop flow (`FEAT-129`) whose QA phase
has no e2e criterion type.

**Why now**: the repo already has the three building blocks — a real-subprocess
stdio e2e test (`tests/mcp/test_mcp_local_e2e.py`), a process supervisor with
readiness + PID file (`ObscuraProcessManager`, FEAT-530) and
`chrome-devtools-mcp` declared as an npm dependency — but nothing connects
them, and no SDD stage consumes the result.

## Constraints & Requirements

- **A Claude Code sub-agent is not a process.** The `Agent` tool returns a
  single text result when the sub-agent finishes; a foreground sub-agent's
  shell commands are **terminated when it gives its final response** (Claude
  Code docs, *tools-reference § Bash tool behavior*). Therefore server
  lifecycle must be owned by a deterministic harness with PID/state files,
  never by a "server sub-agent" that stays alive.
- **Boot-to-ready budget**: the exploratory tier is viable in the dev loop only
  if the target boots in seconds, not minutes. Measured baseline (this
  sandbox, warm cache): stdio MCP `memory` toolkit **1.35 s**, HTTP MCP
  **1.45 s** to `GET /mcp/info`, minimal `BotManager`
  (`docker/integrations/server.py`, no DB) **~3.5 s** to `/healthz`. The
  full `run.py` profile is the number the spike must still produce.
- **Real keys, bounded cost**: credentials come from `navconfig`
  (`GROQ_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY` — `conf.py:401/424/416`);
  the e2e profile must pin a cheap model (e.g. `groq:<DEFAULT_GROQ_MODEL>` or
  `gemini-flash-latest`, `conf.py:443`) and low `max_tokens`. Tests gate on
  key presence via `pytest.mark.skipif(not config.get("X_API_KEY"))`
  (pattern at `tests/e2e/test_meta_live.py:31-38`) — never fail on missing
  keys.
- **Determinism where it counts**: pass/fail for the *gate* is exit-code based
  (consistent with `sdd-qa`/`qa-runner` cardinal rules). LLM judgement is
  allowed only in the *exploratory* tier and only to propose new test cases.
- **Worktree-safe**: several feature worktrees run concurrently
  (`.claude/worktrees/`); every run needs a free port, its own state dir, and
  its own log. No fixed `:5000`/`:9090`/`:9222`.
- **No orphan processes by construction**: teardown must not depend on the
  agent reaching its last step. `SubagentStop` + `SessionEnd` hooks kill
  anything left in the state dir.
- **Pipeline placement (decided in discovery)**: new `e2e-*` sub-agents
  invoked by `qa-runner` / `/sdd-done`; `/sdd-done` gate is **blocking only
  when the spec declares `e2e: required`**, advisory otherwise.
- **Ratchet (decided)**: the exploratory tier emits a verdict JSON **and**
  proposes codified pytest tests (new `e2e` marker, gated by
  `PARROT_TEST_E2E=1`).
- **UI tier (decided)**: Obscura owns the Chrome process
  (`parrot mcp obscura start`, CDP on `127.0.0.1:9222`);
  `chrome-devtools-mcp` attaches via `--browserUrl` and supplies the
  snapshot/click/console/network tools to the sub-agent.
- Assertions on LLM output are structural (status, Pydantic schema, tool-call
  trace), never on exact wording.
- Language split: code, artifacts and identifiers in English.

---

## Spike Research (boot time, lifecycle, tooling)

This section records what was **measured or verified** during the brainstorm
so `/sdd-spec` can turn it into a spike gate instead of re-discovering it.

### S1. Boot-to-ready measurements (this sandbox, Python 3.11, no GPU)

| Target | Command | Cold | Warm (3 runs) | Readiness signal | Clean shutdown |
|---|---|---|---|---|---|
| stdio MCP, `memory` toolkit | `parrot mcp-local memory` | 3.73 s | **1.36 / 1.34 s** | first JSON-RPC `initialize` response (13 tools) | stdin EOF → exit 0 |
| HTTP MCP, `WorkingMemoryToolkit` | `MCPServer(transport="http")` via YAML config + serve-forever wrapper | — | **1.49 / 1.44 / 1.44 s** | `GET /mcp/info` → 200 `{"tools_count": 13}` | `SIGTERM` to process group → exit in **0.02 s** |
| `BotManager` minimal (`docker/integrations/server.py`, `ENABLE_REGISTRY_BOTS=false`, no Postgres/Redis reachable, **tiktoken stubbed** — see S2b) | `PORT=<free> python docker/integrations/server.py` | — | **3.99 / 3.44 / 3.36 s** | `GET /healthz` → 200 `{"status":"ok"}` | `SIGTERM` to process group → exit 0 in **0.7 s** (no torch/TF loaded in this profile, so the `run.py:59-94` hang did not appear) |

Import cost: `python -X importtime -c "import parrot.cli"` → **37 ms** total
(the CLI is lazy, `cli._lazy_commands`, `parrot/cli/__init__.py:110-133`);
the ~1.3 s is toolkit + navconfig + transport import at first request.
Installing enough to *import* `parrot.manager.manager` needs the `agents`
extra plus `ai-parrot-tools/-embeddings/-loaders/-integrations` (≈ 8.6 GB
venv) — the e2e profile should be documented as requiring
`ai-parrot[agents]` + `ai-parrot-server[all]`.

Minimal-`BotManager` boot degrades gracefully without services: warnings for
Admin UI `dist/` missing, `user_socket_manager` unset, `jira_oauth_manager`
unset. But authenticated routes are **not** usable in this profile —
`GET /api/v1/agent_tools` → 500 `RuntimeError: Missing Configuration of
Session Storage` (navigator-session not configured by
`docker/integrations/server.py`). The `botmanager` target therefore needs a
session-storage setup (or an explicit "unauthenticated routes only" scope) in
the spec.

**Conclusion for the spec**: an MCP-exposed toolkit is a **sub-2-second**
target and the minimal `BotManager` is a **~3.5-second** target (warm, no
DB) — both fit comfortably inside the dev loop. The open number is the
*full* profile (`run.py`: QuerySource + navigator-auth + PBAC + registry
bots + torch/TF-backed guards), which is where the ≥ 15 s risk and the
shutdown-hang risk live; it should be measured on the dev machine with real
Postgres/Redis and, if slow, kept as the nightly/opt-in profile.

### S2b. Second defect found while measuring (boot-time network dependency)

`BotManager.setup()` → `setup_studio_routes()` (`manager.py:2540`) →
`handlers/studio/agents.py:36` → `handlers/studio/models.py:13` →
`parrot.skills` → `parrot/skills/parsers.py:29`
`_ENCODING = tiktoken.get_encoding("cl100k_base")` **at import time**.
On a machine without the BPE file cached, this downloads from
`openaipublic.blob.core.windows.net` during `setup()`; behind a blocking
proxy the whole server fails to boot (`ProxyError` → exit 1). The e2e
harness must either pre-warm `TIKTOKEN_CACHE_DIR` or the encoder should be
lazily initialised on first `_count_tokens` call — a one-line change that
is also a prerequisite task (and a good first `e2e` regression test:
"boots with network disabled").

### S2. Defect found while measuring (blocks the HTTP target)

`parrot mcp serve <cfg.yaml> --transport http --port N` logs
`Starting HTTP MCP server on 127.0.0.1:N` and **exits 0 within the same
second**. Cause: `HttpMCPServer.start()` (`transports/http.py:38-92`) returns
after `await self.site.start()`; `_run_standalone_server()` (`mcp/cli.py:138-181`)
does `await server.start()` then falls into `finally: await server.stop()`.
The stdio transport only "works" because its `start()` loops on
`sys.stdin.readline()` (`transports/stdio.py:44-50`). Unix transport
(`transports/unix.py:43`) needs the same check in the spike.
A serve-forever wrapper (`await server.start(); await asyncio.Event().wait()`)
makes the HTTP target reachable — the fix is one `await` in
`_run_standalone_server`, and it is a **prerequisite task** for this feature.

### S3. Claude Code mechanics (verified against code.claude.com/docs, 2026-09-11)

- **Sub-agent frontmatter** supports `tools`, `disallowedTools`, `model`,
  `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `background`,
  `isolation: worktree`, `memory`. `tools:` accepts MCP names
  (`mcp__chrome-devtools__click`) or server patterns (`mcp__chrome-devtools__*`).
  A sub-agent may declare its own `mcpServers` (inline stdio def, connected
  for the sub-agent's lifetime) — so `chrome-devtools-mcp` can be scoped to
  `e2e-ui-tester` only, without touching the (git-ignored, absent) `.mcp.json`.
- **Nesting**: default depth 3 → `sdd-worker` / `qa-runner` can spawn
  `e2e-*` sub-agents (`sdd-worker.md:319-344` already spawns `code-reviewer`).
- **Process lifetime**: a command started by a *foreground* sub-agent stops
  when the sub-agent returns; background sub-agents' commands live up to
  60 min (`CLAUDE_SUBAGENT_BG_SHELL_MAX_MS`); at session exit Claude Code
  kills background tasks **including `setsid`-detached processes**.
  Bash tool default timeout 120 s (`BASH_DEFAULT_TIMEOUT_MS`), max 600 s;
  `run_in_background: true` available. ⇒ The harness must be *quick to
  return* (`up` returns once ready) and the tester must own `down`; Claude
  Code's own cleanup is defence-in-depth, not the design.
- **Hooks**: `SubagentStop` payload carries `agent_type` (the `name` from the
  agent file), `agent_id`, `reason` (`completed|cancelled|error|model_error`);
  `matcher` matches on agent type. `SessionEnd` carries `reason`
  (`clear|resume|logout|prompt_input_exit|other`). Hooks may live in the
  sub-agent's frontmatter (`Stop` there auto-converts to `SubagentStop`), which
  keeps the teardown hook **inside the agent definition** rather than in the
  untracked `.claude/settings.json`.
- **Skills**: `context: fork` + `agent: <custom-agent>` runs a skill as a
  sub-agent with the skill body as prompt; `allowed-tools` pre-approves tools.
  An `/e2e` skill can therefore be the *user-facing* entry point and fork into
  `e2e-api-tester`.

### S4. Browser tooling (verified)

- `chrome-devtools-mcp` latest **1.9.0** (2026-09-08); `package.json` pins
  `^1.6.0` → resolves to 1.9.0. Node `^20.19 || ^22.12 || >=23`.
  Tools: `navigate_page`, `new_page`, `list_pages`, `select_page`,
  `close_page`, `wait_for`, `click`, `fill`, `fill_form`, `hover`, `drag`,
  `press_key`, `type_text`, `upload_file`, `handle_dialog`, `take_snapshot`,
  `take_screenshot`, `evaluate_script`, `list_console_messages`,
  `get_console_message`, `list_network_requests`, `get_network_request`,
  `emulate`, `resize_page`, `performance_*`, `lighthouse_audit`.
- Attach to an existing Chrome: `--browserUrl=http://127.0.0.1:9222` (or
  `--wsEndpoint`); the README explicitly recommends this for sandboxed
  environments that cannot launch Chrome — exactly the Obscura case.
  Security note from the README: anything on the machine can drive that port
  → bind Obscura to loopback only (already the default, `obscura.py:91-93`).
- `@playwright/mcp` 0.0.80 exists as an alternative (`--cdp-endpoint`,
  `browser_snapshot` a11y tree, multi-browser). Not chosen: Chrome-only is
  fine for an admin UI, and DevTools-native console/network/perf tools are
  the point of the UI tier.

---

## Options Explored

### Option A: `E2ECriterion` inside the existing deterministic QA (no new agents)

Extend the `AcceptanceCriterion` discriminated union consumed by `sdd-qa`
(`FlowtaskCriterion | ShellCriterion`) with an `E2ECriterion` that carries
`server_cmd`, `health_url`, `probe_cmd`, `timeout_seconds`. `sdd-qa` boots the
server, polls health, runs the probe, compares exit codes, tears down. Pytest
gets an `e2e` marker; `qa-runner` runs `pytest -m e2e` when `PARROT_TEST_E2E=1`.

✅ **Pros:**
- Zero new agents, zero LLM judgement — fully consistent with the
  "determinism over judgement" rule in `sdd-qa.md:38-40` and `qa-runner.md:38-39`.
- Cheapest to implement and to run in CI nightly.
- The dev-loop flow (`BugIntakeNode` allow-list) gets e2e for free.

❌ **Cons:**
- No exploration: it only re-runs what the spec author already imagined.
  The bugs this feature exists for (transport exits, console errors) are the
  ones nobody wrote a criterion for.
- Server lifecycle logic ends up inside `sdd-qa`'s prompt/Pydantic model
  instead of a reusable CLI — pytest fixtures and manual use would duplicate it.
- No UI coverage at all (no browser tools in `sdd-qa`'s tool list).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `httpx` | health polling + probes | already a transitive dep (`openai`) |
| `pytest` markers | `e2e` marker | `pytest.ini:4-7` has only `integration`, `live`, `real_llm` |

🔗 **Existing Code to Reuse:**
- `.claude/agents/sdd-qa.md` — criterion loop, `QAReport` contract
- `tests/mcp/test_mcp_local_e2e.py:72-114` — `_spawn/_recv/_shutdown`
- `packages/ai-parrot-integrations/tests/agentd/conftest.py:25-36` — `wait_for_socket`

---

### Option B: `parrot e2e` harness CLI + two-tier testing (deterministic gate + exploratory `e2e-*` sub-agents) — **recommended**

A new lazy CLI group `parrot e2e up|status|down|logs` generalises the
`ObscuraProcessManager` pattern (spawn → poll readiness → PID/state file →
stop) to named **targets**: `mcp` (HTTP MCP from a YAML toolkit config),
`mcp-stdio`, `botmanager` (the `docker/integrations/server.py`-style minimal
app), `ui` (Vite `build && preview`, or `dev`), `browser` (delegates to
`parrot mcp obscura start`). `up` allocates a free port, writes
`sdd/state/e2e/<run-id>.json` (`{target, pid, port, base_url, log, started_at}`)
and prints that JSON as its last stdout line; it returns as soon as readiness
succeeds or fails loudly with the log tail.

Two tiers consume the harness:

1. **Deterministic tier** — `tests/e2e/conftest.py` fixtures wrap
   `parrot e2e up/down` (subprocess, no LLM); tests carry
   `@pytest.mark.e2e`, are skipped unless `PARROT_TEST_E2E=1`, and skip
   individually on missing keys. `qa-runner` runs `pytest -m e2e` and
   folds the result into its `verdict:` line.
2. **Exploratory tier** — two sub-agents in `.claude/agents/`:
   `e2e-api-tester` (tools: Bash, Read, Write, Grep; owns `up → probe → down`)
   and `e2e-ui-tester` (same + `mcp__chrome-devtools__*`, with an inline
   `mcpServers` entry `npx chrome-devtools-mcp --browserUrl=http://127.0.0.1:9222`).
   Both read `sdd/state/<FEAT-ID>/e2e-plan.md` (produced by `/sdd-spec` from
   the spec's *Test Specification § E2E Scenarios*), probe the live target,
   and write `sdd/state/<FEAT-ID>/e2e-verdict.json` plus **candidate tests**
   in `tests/e2e/candidates/<FEAT-ID>_*.py` that `sdd-worker` may promote.
   A `SubagentStop` hook in each agent's frontmatter runs
   `parrot e2e down --stale`. `/sdd-done` reads the verdict: blocking iff the
   spec frontmatter says `e2e: required`.

✅ **Pros:**
- One lifecycle implementation, four consumers (pytest, sub-agents, hooks,
  humans). Same pattern the repo already trusts for Chrome (FEAT-530).
- The gate stays deterministic; exploration is additive and produces
  durable coverage (ratchet), not just a one-off opinion.
- Sub-agents are thin prompts over a CLI — small, testable, no
  process-management prose in the prompt.
- UI tier reuses Obscura (already has PID file + readiness) and the already
  declared `chrome-devtools-mcp`.

❌ **Cons:**
- More surface: a CLI group, a conftest, two agents, a spec-template change,
  a `/sdd-done` change.
- Exploratory runs spend real tokens and real API calls — needs a budget
  knob and a cheap default model.
- Requires the S2 fix (`parrot mcp serve --transport http` exits) before the
  `mcp` target works at all.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `click` | `parrot e2e` group | already the CLI framework (`parrot/cli/__init__.py`) |
| `httpx` / `aiohttp` | readiness polling | `aiohttp` already used by `ObscuraProcessManager.is_running` |
| `psutil>=5.9` | PID liveness, process-group kill | already a core dep (`packages/ai-parrot/pyproject.toml`) |
| `chrome-devtools-mcp` `^1.6.0` (→1.9.0) | UI tools for `e2e-ui-tester` | declared in root `package.json`; attach via `--browserUrl` |
| `pytest` `e2e` marker | deterministic tier | add to `pytest.ini`; gate `PARROT_TEST_E2E=1` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:63-354` — `ObscuraProcessManager` (`is_running`, `start` with CDP readiness, `stop`, `default_pid_file/write_pid_file/read_pid_file/remove_pid_file`) — the lifecycle template to generalise
- `packages/ai-parrot-server/src/parrot/mcp/cli.py:195-461` — `parrot mcp obscura start|stop|status` — the CLI shape to mirror
- `docker/integrations/server.py:18-34` — minimal `BotManager` app with `/healthz` — the `botmanager` target
- `packages/ai-parrot-server/src/parrot/mcp/cli.py:41-136` — `_load_from_yaml`, `_create_transport_config` — the `mcp` target
- `tests/mcp/test_mcp_local_e2e.py:37-114` — bootstrap + `_spawn/_recv/_shutdown` for `mcp-stdio`
- `.claude/agents/qa-runner.md`, `.claude/agents/sdd-qa.md` — cardinal rules and report contracts to copy
- `.claude/hooks/sdd-worker-format.sh:2-45` — `SubagentStop`/`Stop` hook skeleton keyed on `agent_type`
- `.mcp.json.example:2-21` — worktree-safe venv resolution preamble for launching servers

---

### Option C: Long-lived "server" sub-agent + parallel "client" sub-agent (the original sketch)

`sdd-worker` launches `e2e-server` in the background (`background: true`),
which boots the target and idles; `e2e-client` runs in parallel and queries
it; `sdd-worker` later messages `e2e-server` to stop.

✅ **Pros:**
- Maps 1:1 to the mental model "one agent serves, one agent tests".
- The server agent can *diagnose* a failed boot with judgement (read logs,
  retry with a different config).

❌ **Cons:**
- Synchronisation is by filesystem/port polling only; there is no primitive
  for "server agent is ready". Two LLM loops spin while waiting.
- Background sub-agent shells die at 60 min and at session end regardless;
  and a foreground server agent kills its own server the moment it returns
  (S3). Correctness depends on Claude Code internals, not on the design.
- Costs two agent contexts for what a CLI does in 1.4 s.
- Nesting depth: `sdd-worker → e2e-server → (anything)` is already 2 of 3.

📊 **Effort:** Medium (and fragile)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Claude Code `background: true`, `SendMessage` | keep server agent alive, stop it later | documented, but lifetime-capped |

🔗 **Existing Code to Reuse:**
- Same harness pieces as Option B — which is the tell: Option C still needs the
  CLI, it just adds an agent around it.

---

### Option D (unconventional): In-process e2e via `aiohttp_server` fixture + MCP client, no subprocess

Use `pytest-aiohttp`'s `aiohttp_server` (already used in
`tests/mcp/conftest.py:19`) to start the real `web.Application` **in the test
process**, mount `BotManager.setup(app)` / `ParrotMCPServer.setup(app)`, and
drive it with real `httpx` calls and real LLM keys.

✅ **Pros:**
- No process management, no ports, sub-second, trivially worktree-safe.
- Real routes, real middleware, real keys — most of the value of "no mocks".

❌ **Cons:**
- Not end-to-end at the process boundary: cannot catch S2-class bugs
  (`start()` returning), stdout purity, signal handling, `run.py`'s
  force-exit logic, CLI arg parsing, or the Vite/UI layer.
- `pytest-aiohttp` is only in `pyproject.toml:73` dev group, not in
  `requirements/requirements-dev.txt` (would need aligning).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest-aiohttp>=1.1.0` | in-process server fixture | declared in `[dependency-groups] dev` |

🔗 **Existing Code to Reuse:**
- `tests/mcp/conftest.py:19` — `aiohttp_server` usage
- `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py:265-377` — `AgentMCPMount.setup(app)`

---

## Recommendation

**Option B** is recommended because it is the only option that (a) keeps the
gate deterministic, (b) adds exploration that converts into permanent
coverage, and (c) puts process lifecycle in exactly one reusable place. The
discovery rounds already fixed the hard choices in its favour: harness as a
`parrot e2e` CLI, `e2e-*` sub-agents invoked by `qa-runner`/`/sdd-done`,
Obscura + `chrome-devtools-mcp` for the UI, verdict + candidate tests, gate
blocking only under `e2e: required`.

What is traded off: more moving parts than Option A and a token/API budget
for the exploratory tier. Both are acceptable because the harness is ~200
lines mirroring code that already exists (`ObscuraProcessManager`), and the
exploratory tier is opt-in per spec.

Option D is **not rejected** — it is the right shape for *some* e2e tests
(route + middleware + real key, no process concerns) and should be allowed
under the same `e2e` marker; the spec should say when each applies.
Option C is rejected on lifecycle grounds (S3). Option A is subsumed: an
`E2ECriterion`-like shape may still be added later for the dev-loop flow,
implemented as `ShellCriterion(command="parrot e2e run ...")`.

---

## Feature Description

### User-Facing Behavior

- `parrot e2e up <target> [--config cfg.yaml] [--run-id X] [--timeout 60]`
  boots a target, waits for readiness, prints one JSON line
  (`base_url`, `pid`, `log`, `run_id`) and exits 0. On failure exits non-zero
  with the log tail on stderr. Targets: `mcp`, `mcp-stdio`, `botmanager`,
  `ui`, `browser`.
- `parrot e2e status [run-id]`, `parrot e2e logs <run-id> [--tail N]`,
  `parrot e2e down <run-id> | --all | --stale`.
- `PARROT_TEST_E2E=1 pytest -m e2e` runs the deterministic tier; tests skip
  cleanly when the gate var or a specific API key is absent.
- `/sdd-spec` gains a *Test Specification § E2E Scenarios* subsection and an
  `e2e: required|optional|none` frontmatter key; it writes
  `sdd/state/<FEAT-ID>/e2e-plan.md`.
- `qa-runner` (autopilot Stage 3) runs `pytest -m e2e` and, when the plan
  exists, invokes `e2e-api-tester` (and `e2e-ui-tester` if the plan has UI
  scenarios). Its `verdict:` line incorporates the e2e result.
- `/sdd-done` shows `E2E: PASS|FAIL|MISSING` in its evidence table; blocks
  only when the spec says `e2e: required`.
- Developers can run `/e2e <FEAT-ID>` (skill, `context: fork`,
  `agent: e2e-api-tester`) manually.

### Internal Behavior

1. **Harness** (`parrot.e2e` package in `ai-parrot-server`, lazy command
   `"e2e"` in `cli._lazy_commands`): a `TargetSpec` registry (command
   builder, readiness probe, shutdown strategy) + `RunState` Pydantic model
   persisted to `sdd/state/e2e/<run-id>.json`. Spawn with
   `start_new_session=True`, stdout+stderr to `<state>/<run-id>.log`, free
   port from an ephemeral bind, env injected (`PORT`, `MCP_SERVER_PORT`,
   `PUBLIC_API_URL`, `E2E_RUN_ID`, `LLM_MODEL=<cheap>`). Readiness probes:
   `mcp` → `GET {base}/mcp/info`; `botmanager` → `GET /healthz`;
   `ui` → `GET /admin/` returns 200; `browser` → Obscura `/json/version`;
   `mcp-stdio` → `initialize` round-trip. Shutdown: `SIGTERM` to the process
   group, wait, `SIGKILL`; `--stale` walks the state dir and kills PIDs that
   are alive but whose run is older than a TTL or whose owner session ended.
2. **Deterministic tier**: `tests/e2e/conftest.py` provides session-scoped
   fixtures `e2e_mcp`, `e2e_botmanager`, `e2e_ui` that call the harness via
   subprocess and yield a `RunState`. `pytest.ini` registers `e2e`;
   the root `conftest.py` adds the `PARROT_TEST_E2E` skip hook (the existing
   `PARROT_TEST_REAL_LLM` hook lives only in `packages/ai-parrot/tests/conftest.py`).
3. **Exploratory tier**: `e2e-api-tester` reads the plan, runs
   `parrot e2e up`, executes scenarios with `httpx`/`curl` (structural
   assertions; optional `judge` step through a cheap model for semantic
   checks), always runs `down`, writes `e2e-verdict.json`
   (`{feature, run_id, target, passed, scenarios[], failures[], candidates[]}`)
   and candidate tests. `e2e-ui-tester` additionally runs
   `parrot e2e up browser` + `up ui`, then drives the page through
   `chrome-devtools-mcp` (`navigate_page` → `take_snapshot` → `click`/`fill` →
   `list_console_messages` + `list_network_requests` after every step;
   `take_screenshot` on failure into `sdd/state/<FEAT-ID>/e2e/`).
4. **Safety net**: frontmatter `hooks.Stop` (→ `SubagentStop`) in both agents
   runs `parrot e2e down --stale`; a repo-tracked
   `.claude/hooks/e2e-teardown.sh` is documented for `SessionEnd`
   (settings are machine-local and git-ignored, `.gitignore:411-413`).
5. **Gate**: `/sdd-done` step 4 reads `sdd/state/<FEAT-ID>/e2e-verdict.json`
   if the spec frontmatter has `e2e: required`; missing or `passed: false`
   → `❌ NO EVIDENCE` / `⚠️ PARTIAL` respectively, and the close aborts.

### Edge Cases & Error Handling

- **Boot failure**: `up` exits non-zero with the last 4 KB of log; the tester
  records a `boot_failure` verdict and stops — never retries with a different
  config silently.
- **Port race**: free-port allocation then bind; if the target reports
  `EADDRINUSE`, `up` retries once with a new port.
- **Readiness timeout**: default 60 s (`botmanager` may need more — spike
  decides); on timeout, kill the process group and fail loudly.
- **Missing keys**: deterministic tier skips per test; exploratory tier marks
  scenarios `skipped_missing_credential` and the verdict is `passed: true`
  only if no *required* scenario was skipped.
- **Shutdown hangs** (`run.py:59-94` class): `down` escalates
  `SIGTERM → wait 10 s → SIGKILL` on the whole process group; the harness
  records `shutdown_forced: true` in the run state so the spike/tests can
  flag targets that do not stop cleanly.
- **Orphans**: `--stale` uses PID liveness (`psutil`) + `started_at` TTL;
  hooks call it on `SubagentStop`/`SessionEnd`; Claude Code's own exit cleanup
  is the last layer.
- **Multiple worktrees**: run ids embed the worktree slug; state dir is
  per-repo (`sdd/state/e2e/`, on `dev`) — `down --all` must filter by
  worktree unless `--everywhere` is passed.
- **Cost runaway**: `E2E_MAX_LLM_CALLS` and `E2E_MODEL` env knobs; the
  exploratory prompt caps scenarios per run and tokens per call.
- **UI without backend**: `up ui` refuses to start unless `PUBLIC_API_URL`
  points to a live `botmanager` run (or `--no-backend` is explicit).
- **CDP port contention**: `browser` target checks Obscura `status` first and
  adopts a running instance rather than starting a second one.

---

## Capabilities

### New Capabilities
- `e2e-harness-cli`: `parrot e2e up|status|logs|down` with target registry,
  run-state files, readiness probes and process-group teardown.
- `e2e-pytest-tier`: `e2e` marker, `PARROT_TEST_E2E` gate, session fixtures
  over the harness, first tests for `mcp` (HTTP + stdio) and `botmanager`.
- `e2e-api-tester-agent`: exploratory API/MCP sub-agent producing
  `e2e-verdict.json` + candidate tests.
- `e2e-ui-tester-agent`: exploratory UI sub-agent over Obscura +
  `chrome-devtools-mcp`.
- `e2e-sdd-gate`: spec frontmatter `e2e:` key, `e2e-plan.md` generation in
  `/sdd-spec`, verdict consumption in `qa-runner` and `/sdd-done`, `/e2e`
  skill.

### Modified Capabilities
- `mcp-server-cli` (`parrot mcp serve`): standalone HTTP/Unix transports must
  serve forever (S2 fix) — prerequisite.
- `sdd-spec` template: new *E2E Scenarios* subsection under § 4 Test
  Specification.
- `sdd-done`: evidence step reads the e2e verdict.
- `qa-runner`: runs the `e2e` marker and invokes `e2e-*` agents.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/__init__.py` (`_lazy_commands`) | extends | add `"e2e": "parrot.e2e.cli"` + install hint in `_lazy_extras` |
| `packages/ai-parrot-server/src/parrot/mcp/cli.py` (`_run_standalone_server`) | modifies | S2 fix: wait forever after `start()` for http/unix |
| `packages/ai-parrot-server/src/parrot/mcp/obscura.py` | depends on / extracts | generalise PID-file + readiness helpers into `parrot.e2e.process` (keep Obscura API intact) |
| `docker/integrations/server.py` | depends on | promote to `parrot.e2e.targets.botmanager` entrypoint (or import it as-is) |
| `pytest.ini`, root `conftest.py` | extends | `e2e` marker; `PARROT_TEST_E2E` skip hook |
| `tests/e2e/` | extends | add `conftest.py`, `__init__.py`, `candidates/` |
| `.claude/agents/` | extends | `e2e-api-tester.md`, `e2e-ui-tester.md` (frontmatter hooks + inline `mcpServers`) |
| `.claude/agents/qa-runner.md`, `.claude/commands/sdd-done.md`, `.claude/commands/sdd-spec.md`, `sdd/templates/spec.md` | modifies | plan generation, verdict consumption, gate |
| `.claude/skills/e2e/SKILL.md` | new | `context: fork`, `agent: e2e-api-tester` |
| `.claude/hooks/e2e-teardown.sh` | new | `SessionEnd`/`SubagentStop` teardown, documented for local settings |
| `package.json` / `Makefile:948` | depends on | `chrome-devtools-mcp` already declared; `make install-chrome-devtools` exists |
| CI (`.github/workflows/ci.yml`) | extends | optional nightly job `PARROT_TEST_E2E=1 pytest -m e2e` with secrets |

No breaking changes. New runtime dependency: none (psutil, click, aiohttp,
httpx already present). New dev/CI dependency: Node ≥ 20.19 for the UI tier.

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (conversation sketch, 2026-09-11) — harness shape the CLI should keep
# up(): free port → Popen(start_new_session=True, stdout→log) → poll health until deadline
#       → write state json {pid, port, base_url, log} → print json
# down(): read state → os.killpg(pid, SIGTERM) → unlink state
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-server/src/parrot/mcp/obscura.py:63
class ObscuraProcessManager:
    def __init__(self, config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None) -> None:  # :73
    @property
    def endpoint(self) -> str:  # :91  → f"http://{host}:{port}"
    async def is_running(self) -> bool:  # :95  GET {endpoint}/json/version
    async def start(self) -> str:  # :142  start (or adopt) and wait for CDP readiness
    async def stop(self) -> None:  # :259
    async def status(self) -> ...:  # :284
# module-level PID helpers: default_pid_file / write_pid_file / read_pid_file / remove_pid_file  (:316-354)

# From packages/ai-parrot-server/src/parrot/mcp/cli.py:41-49
@mcp.command()
def serve(config_file: str, transport: Optional[str], socket: Optional[str], port: Optional[int], log_level: str): ...
def _load_from_yaml(config_path: Path) -> ParrotMCPServer: ...          # :109
def _create_transport_config(transport: str, socket: Optional[str], port: Optional[int]): ...  # :129
async def _run_standalone_server(mcp_server: ParrotMCPServer): ...      # :138  (no serve-forever wait — S2)

# From packages/ai-parrot-server/src/parrot/mcp/transports/http.py:22
class HttpMCPServer(OAuthRoutesMixin, RemoteMCPServerBase):
    async def start(self): ...                       # :38  non-blocking; TCPSite.start() at :92
    def _register_routes(self, router, base_route: str) -> None: ...  # :94  POST base, GET base/info
    async def _handle_info(self, request): ...       # :152  {"name","version","transport":"http","tools_count"}

# From packages/ai-parrot-server/src/parrot/mcp/config.py:134
class MCPServerConfig(BaseModel):  # transport="stdio", host="localhost", port=8080, base_path="/mcp", auth_method=AuthMethod.NONE

# From packages/ai-parrot-server/src/parrot/mcp/server.py:36
class MCPServer:
    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None): ...  # :39
    async def start(self): ...  # :68
    async def stop(self): ...   # :72

# From packages/ai-parrot/src/parrot/mcp/local_server.py:36
class StdioMCPServer(LocalMCPServerBase):
    async def start(self): ...  # :44  loops on sys.stdin.readline(); methods: initialize, tools/list, tools/call, notifications/initialized (:91-100)

# From packages/ai-parrot-server/src/parrot/manager/manager.py:178
class BotManager:
    def setup(self, app, *, agent_mount_config=None, agent_mount_auth_template=None,
              agent_mount_pbac_resolver=None, agent_mount_audit_sink=None) -> web.Application: ...  # :2222
    async def on_startup(self, app): ...  # :2684  (load_bots :2712, ChatStorage :2723, IntegrationBotManager :2739)

# From docker/integrations/server.py:18-34
async def healthz(request): ...                 # :18 → {"status": "ok"}
def build_app() -> web.Application: ...         # :22  web.Application() + /healthz + BotManager().setup(app)
# web.run_app(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))  # :29-34

# From tests/mcp/test_mcp_local_e2e.py
def _spawn(cwd: Path, *args: str) -> subprocess.Popen: ...   # :72
def _recv(proc: subprocess.Popen, timeout: float = 10.0) -> dict: ...  # :90
def _shutdown(proc: subprocess.Popen) -> None: ...            # :107

# From packages/ai-parrot-integrations/tests/agentd/conftest.py
async def wait_for_socket(socket_path: Path, timeout: float = 5.0): ...  # :25
```

#### Verified Imports
```python
from parrot.cli import cli                                   # packages/ai-parrot/src/parrot/cli/__init__.py:103 (LazyGroup; _lazy_commands :110)
from parrot.mcp.cli import _load_from_yaml, _create_transport_config   # ai-parrot-server, verified by running the spike wrapper
from parrot.mcp.config import MCPServerConfig                # packages/ai-parrot-server/src/parrot/mcp/config.py:134
from parrot.mcp.server import MCPServer                      # packages/ai-parrot-server/src/parrot/mcp/server.py:36
from parrot.mcp.obscura import ObscuraProcessManager         # packages/ai-parrot-server/src/parrot/mcp/obscura.py:63
from parrot.tools.working_memory.tool import WorkingMemoryToolkit  # toolkit_config.py:98-101 (BUILTIN_TOOLKITS["memory"]); 13 tools
from navconfig import config                                 # used at tests/e2e/test_meta_live.py:26
```

#### Key Attributes & Constants
- `cli._lazy_commands: dict[str, str]` → module path per subcommand (`parrot/cli/__init__.py:110-133`); `cli._lazy_extras` → install hints (`:135`)
- `MCPServerConfig.base_path = "/mcp"` → readiness endpoint is `GET /mcp/info` (`config.py:134-177`, `http.py:94-105`)
- `conf.py:216-221` — `MCP_SERVER_TRANSPORT="http"`, `MCP_SERVER_HOST="127.0.0.1"`, `MCP_SERVER_PORT=9090`
- `conf.py:401-402` — `GROQ_API_KEY`, `DEFAULT_GROQ_MODEL="qwen/qwen3-32b"`; `conf.py:443` — `DEFAULT_LLM_MODEL="gemini-flash-latest"`
- `conf.py:94-98` — `ENABLE_SWAGGER/ENABLE_DASHBOARDS/ENABLE_CREWS/ENABLE_DATABASE_BOTS` default `False`; `ENABLE_REGISTRY_BOTS` default **`True`** (heavy default to disable in the e2e profile)
- `conf.py:367` — `os.environ.setdefault("HF_HOME", ...)` side effect at import
- `pytest.ini:4-7` markers: `integration`, `live`, `real_llm`
- `packages/ai-parrot/tests/conftest.py:16-19` — `PARROT_TEST_REAL_LLM` skip hook (package-local only)
- `packages/ai-parrot-server/ui/package.json:11-15` — scripts `dev`, `build` (`pnpm generate && vite build`), `preview`, `test`; `vite.config.ts:47-48,78-83` — `PUBLIC_API_URL` (default `http://localhost:5000`), `base: '/admin/'`, `/api` proxy
- `run.py:20-52` — force-exit handler (3rd signal → `os._exit(1)`); `run.py:59-94` — hard exit after graceful shutdown
- `.claude/agents/sdd-worker.md:319-344` — existing `Agent(code-reviewer)` invocation (nesting precedent)
- `.claude/commands/sdd-done.md:99-124` — evidence step; `:114-116` states tests are intentionally not re-run
- `.mcp.json.example:2-21` — venv-resolution preamble for stdio servers

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot e2e`~~ — no such command; `cli._lazy_commands` has no `e2e` key
- ~~`parrot.e2e`~~ package — does not exist in any workspace package
- ~~`/health`, `/ready`, `/ping` routes~~ — never registered; `/health` and `/ready` appear only in `a2a/security.py:1461-1466` skip-paths. Only `docker/integrations/server.py:24` serves `/healthz`, and `app.py`/`run.py` do not
- ~~MCP `ping` JSON-RPC method~~ — not handled by `StdioMCPServer` (`local_server.py:91-102`) nor HTTP transports
- ~~`e2e`, `smoke`, `slow` pytest markers~~ — `pytest.ini` has only `integration`, `live`, `real_llm`
- ~~`PARROT_TEST_E2E`~~ — no such env gate (only `PARROT_TEST_REAL_LLM`, package-local)
- ~~`tests/e2e/conftest.py`, `tests/e2e/__init__.py`~~ — absent
- ~~`.mcp.json`~~ — absent (git-ignored, `.gitignore:389`); only `.mcp.json.example`
- ~~`.claude/settings.json`, `.claude/settings.local.json`~~ — absent (git-ignored, `.gitignore:411-413`); hook wiring is machine-local
- ~~`make test-e2e` / `make serve`~~ — absent (`Makefile:407-413` has `test`, `test-pytest` only)
- ~~`APP_HOST` / `APP_PORT` read in Python~~ — documented in README only; the only port fallback is `PORT` in `docker/integrations/server.py:33`
- ~~a working standalone `parrot mcp serve --transport http`~~ — exits immediately (S2); stdio is the only transport that blocks
- ~~a `BotManager` boot that works offline~~ — `parrot/skills/parsers.py:29` downloads the tiktoken BPE at import via `setup_studio_routes` (S2b)
- ~~session storage in `docker/integrations/server.py`~~ — not configured; authenticated routes return 500
- ~~an HTTP variant of `parrot mcp-local`~~ — stdio only (`packages/ai-parrot/src/parrot/mcp/local_cli.py:58-104`)
- ~~a generic HTTP readiness helper~~ — only `wait_for_socket` (file existence) and `ObscuraProcessManager.is_running` (CDP)
- ~~a test that boots `BotManager` as a subprocess~~ — `test_tools_list_route.py:18-22` bypasses `__init__` and checks routes structurally
- ~~Playwright test suite / `playwright.config.*`~~ — Playwright exists only as a scraping driver (`parrot_tools/scraping/drivers/playwright_driver.py`)
- ~~`sdd-quality` agent/command~~ — does not exist; the QA surfaces are `sdd-qa` (dev-loop) and `qa-runner` (autopilot)
- ~~`E2ECriterion`~~ — `AcceptanceCriterion` is `FlowtaskCriterion | ShellCriterion` only
- ~~`parrot.services.mcp`~~ — dead import path in `examples/jira_mcp_server.py:6`; live class is `parrot.mcp.simple_server.SimpleMCPServer`
- ~~`.parrot/mcp-toolkits.yaml`~~ — absent; toolkit resolution falls back to `BUILTIN_TOOLKITS`

---

## Parallelism Assessment

- **Internal parallelism**: high. Four independent lanes once the harness
  contract (`RunState` JSON + `up/down` CLI) is fixed in TASK-1:
  (1) harness CLI + S2 fix, (2) pytest tier (`conftest`, marker, first tests),
  (3) `e2e-api-tester` agent + `/e2e` skill + `qa-runner`/`sdd-done`/`sdd-spec`
  edits, (4) `e2e-ui-tester` + Obscura/`chrome-devtools-mcp` wiring.
  Lanes 2–4 only need the CLI's stdout contract, not its implementation.
- **Cross-feature independence**: touches `parrot/mcp/cli.py` (S2 fix) and
  `parrot/mcp/obscura.py` (helper extraction) — check in-flight specs against
  FEAT-530 (Obscura) and any MCP-transport work; touches shared SDD command
  files (`sdd-spec.md`, `sdd-done.md`, `qa-runner.md`) which other SDD-process
  features also edit — serialise those edits.
- **Recommended isolation**: `mixed` — TASK-1 (harness + S2 fix) sequential
  in the feature worktree; lanes 2–4 may run in individual worktrees after
  TASK-1 lands.
- **Rationale**: the CLI contract is small and stable; agents and fixtures are
  thin consumers. Parallelising them shortens the critical path to the spike
  result, which is what decides the dev-loop viability question.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: `feature` on `dev`
- [x] Spike target — *Owner: Jesus*: both MCP server and minimal BotManager; measured MCP 1.4 s, minimal BotManager 3.5 s (S1)
- [x] Pipeline slot — *Owner: Jesus*: new `e2e-*` sub-agents invoked by `qa-runner` / `/sdd-done`
- [x] Browser stack — *Owner: Jesus*: Obscura owns Chrome; `chrome-devtools-mcp` attaches via `--browserUrl`
- [x] Harness home — *Owner: Jesus*: `parrot e2e up|down|status` CLI
- [x] Ratchet — *Owner: Jesus*: verdict JSON + candidate pytest tests under `e2e` marker
- [x] Gate force — *Owner: Jesus*: blocking only when spec declares `e2e: required`
- [ ] **Spike gate**: boot-to-ready and clean-shutdown time of the *full* profile (`run.py`, real Postgres/Redis, `ENABLE_REGISTRY_BOTS` default) on the dev machine — threshold to accept for the dev-loop tier (proposal: ≤ 15 s warm, SIGTERM exit ≤ 10 s); minimal profile already measured at ~3.5 s / 0.7 s — *Owner: Jesus*
- [ ] **Prerequisite fixes** discovered by the spike: (S2) `_run_standalone_server` serve-forever for http/unix; (S2b) lazy tiktoken encoder in `parrot/skills/parsers.py:29` or `TIKTOKEN_CACHE_DIR` pre-warm in the harness — ship as TASK-0 of this feature or as a separate hotfix? — *Owner: Jesus*
- [ ] `botmanager` target scope: configure navigator-session storage in the minimal entrypoint (authenticated routes 500 today with `Missing Configuration of Session Storage`) or restrict the target to unauthenticated routes + MCP mount? — *Owner: Jesus*
- [ ] **Spike gate**: does a `parrot e2e up`-spawned process (`start_new_session=True`) survive (a) the Bash call returning, (b) a *foreground* sub-agent returning? Docs say sub-agent-started commands stop at final response; confirm whether that covers detached grandchildren. Design assumes *no* — *Owner: Jesus*
- [ ] Should the `mcp` target boot a **real agent** (LLM-backed, `AgentMCPMount`/FEAT-477 path with a cheap model) or a **toolkit** (`WorkingMemoryToolkit`, no LLM)? Proposal: both as separate targets `mcp-toolkit` / `mcp-agent`; the agent one is the "real keys" tier — *Owner: Jesus*
- [ ] Where does `parrot.e2e` live: `ai-parrot-server` (has aiohttp, Obscura, MCP transports) vs `ai-parrot` core (has the CLI)? Proposal: `ai-parrot-server`, registered lazily with an install hint like agentd — *Owner: Jesus*
- [ ] Unix transport: does `UnixMCPServer.start()` block or return like HTTP (S2)? Verify in the spike — *Owner: sdd-worker*
- [ ] Budget knobs: `E2E_MODEL`, `E2E_MAX_LLM_CALLS` — env vs `sdd/state/<FEAT>/e2e-plan.md` frontmatter? — *Owner: Jesus*
- [ ] Candidate-test promotion policy: does `sdd-worker` auto-promote candidates that pass twice, or is promotion always a human review in `/pr-review`? — *Owner: Jesus*
- [ ] CI: add a nightly `e2e` job with secrets now, or after the first two features declare `e2e: required`? — *Owner: Jesus*
- [ ] `run.py` vs `docker/integrations/server.py` as the `botmanager` target: the former exercises `QuerySource`/auth/PBAC (realistic, heavy), the latter is minimal. Proposal: minimal by default, `--profile full` opt-in — *Owner: Jesus*
