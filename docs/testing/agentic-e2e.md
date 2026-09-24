# Agentic End-to-End Testing (FEAT-581)

**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Task**: TASK-3546 (M9 — CI, documentation and performance evidence)
**Acceptance criteria addressed**: AC15, AC16
**Baseline verified against**: worktree commit `98a217451` (`dev` lineage)

This document is the operational reference for `parrot e2e` (the FEAT-581
deterministic gate) and its adjacent optional lanes: install/preflight,
fixture Redis/session limits, live-provider cost semantics, browser setup,
ownership/lease recovery and evidence reuse. It documents what is actually
implemented on this branch — every command below was run and its output is
reproduced verbatim or lightly trimmed; nothing here is a proposal.

---

## 1. Install / Preflight

`parrot.e2e` ships in **`ai-parrot-server`**, registered lazily by core's
`LazyGroup` (`packages/ai-parrot/src/parrot/cli/__init__.py`):

```python
cli._lazy_commands = {
    ...
    # FEAT-581 — Deterministic E2E gate, ships in ai-parrot-server.
    "e2e": "parrot.e2e.cli",
}
cli._lazy_extras = {
    ...
    "e2e": "ai-parrot-server: pip install ai-parrot-server",
}
```

A checkout without `ai-parrot-server` installed still runs every other
`parrot` subcommand; invoking `parrot e2e ...` without it fails with that
install hint rather than an opaque `ImportError` (AC2). Inside this
workspace, `ai-parrot-server` is a normal uv workspace member (no extra
`pip install` needed once the workspace is synced); there is **no**
dedicated `e2e` package extra to select — the CLI module is unconditionally
part of the distribution.

Confirmed real on this branch (worktree `.venv`-equivalent: main checkout's
shared interpreter, `PYTHONPATH` pointed at every changed package's own
`src/`, per `.claude/rules/worktree-management.md` §4):

```
$ python -c "from parrot.cli import cli; cli(['e2e','--help'])"
Usage: -c e2e [OPTIONS] COMMAND [ARGS]...

  Deterministic E2E gate: run, verify, up, status, logs, down (FEAT-581).

Options:
  --help  Show this message and exit.

Commands:
  down    Idempotently terminate one run, every owned run, or every stale...
  logs    Print one run's captured target log (spec §2:...
  run     Foreground bounded runner: execute a plan; JSON verdict on...
  status  Print one run's persisted state, or every run's state in this...
  up      Start a supervised, detached target; one RunState JSON line...
  verify  Read-only evidence validation; JSON :class:`VerificationResult`...
```

### 1.1 Per-target external prerequisites

| Target | Prerequisite | Missing behavior |
|---|---|---|
| `mcp-toolkit` / `mcp-stdio` | Only the already-declared `mcp` extra (`aioquic`, `pylsqpack`, `click`, `PyYAML`) | N/A — no external service |
| `botmanager` (minimal) | `redis-server` binary on `PATH` (`parrot.e2e.targets.redis.find_redis_server_binary`) | `E2EPrerequisiteError` (`reason_code="redis_server_missing"`), exit 3 (BLOCKED); plain MCP scenarios still execute |
| `mcp-agent` (live) | `ai-parrot-client-google` installed; `PARROT_TEST_E2E=1`, `PARROT_TEST_REAL_LLM=1`, `GOOGLE_API_KEY` | `E2EPrerequisiteError`, exit 3, **before any client is constructed** |
| `ui` | `pnpm`/`node` on `PATH`, `node_modules` installed, admin UI build | Adapter-level prerequisite error |
| `browser` | `obscura` binary (owns Chrome via CDP) | `E2EPrerequisiteError` before launch |
| owned-browser pytest scenario (`test_ui.py`) | `playwright` importable in the harness process | `E2EPrerequisiteError` (`reason_code="playwright_missing"`) |

Verified in this sandbox (2026-09-24, this worktree):

| Tool | Present? | Version |
|---|---|---|
| `redis-server` | **No** | — (`command -v redis-server` → not found) |
| `pnpm` | Yes | `/usr/bin/pnpm` |
| `node` | Yes | `v20.20.2` |
| `obscura` | Yes | `0.2.2` |
| `playwright` (Python, shared `.venv`) | Yes | `1.52.0` |
| `docker` | Yes (daemon reachable, no containers running) | — |
| `psql` / `pg_ctl` (Postgres) | **No** | — |

This matches the disposition already recorded by the tasks that implemented
these adapters: TASK-3530's completion note states `redis-server` is "absent
on this host" (skip-guarded, real-subprocess tests skip); TASK-3548's
completion note reports `test_ui.py` "correctly reports BLOCKED in this
environment (missing `redis-server`/UI build toolchain) rather than a false
PASS". `redis-server`'s continued absence in this environment is therefore
consistent across independent tasks, not a regression introduced here.

---

## 2. Fixture Redis / session limits

Authenticated `botmanager` scenarios use `SessionHandler(storage="redis")`
against a **private, per-run Redis instance** — never the operator's shared
Redis (`docker-compose.yml`'s `redis` service at `6379`, or any other
already-running instance). Ownership contract
(`parrot.e2e.targets.redis`, sha256 `c23da9a7…ebce2`):

- `find_redis_server_binary()` resolves `redis-server` on `PATH` or raises
  `E2EPrerequisiteError` (`redis_server_missing`) **before spawning
  anything** — this module never inspects, connects to, or touches an
  already-running instance.
- `allocate_loopback_port()` picks one free loopback port per run.
- `build_redis_argv()` binds `127.0.0.1` only, on that unique port, with a
  unique per-run data directory (mode `0700`), and disables persistence
  entirely: `--save "" --appendonly no`. `--protected-mode no` is required
  because loopback-only binding alone still refuses unauthenticated clients
  under Redis's own default protected mode.
- `spawn_private_redis()` never calls `start_new_session` — the Redis child
  inherits the caller's own process group, so the supervisor's single
  `killpg` on the top-level target also reaches this Redis child (the same
  owned-process-group teardown model as every other target).
- Readiness is a raw-socket `PING`/`+PONG` round-trip (no `redis` client
  import in the bootstrap path, so this stays usable from the target
  child's synchronous bootstrap script before `navigator_session` is ever
  imported).

**Session limits.** `TargetConfig.profile` for `botmanager` accepts only
`"minimal"` (the default); `profile="full"` is explicitly rejected —
`_require_minimal_profile()` (`botmanager.py:138-159`) raises
`E2EConfigError` (`reason_code="botmanager_full_profile_unsupported"`)
rather than guessing an undefined contract, per TASK-3530's completion
note: *"explicitly rejects `profile='full'` ... implementing only the
'minimal' profile this task's title scopes."* There is therefore no
supported way to request a full-profile `botmanager` session through this
adapter — see §6 and §8 for how that gap intersects with AC16's
full-profile measurement.

The minimal target's own auth surface (`docker/integrations/server.py`
pattern, verified sha256 `c5805019…3ebc302`): a real
`navigator_session.new_session`-backed bootstrap login issues the normal
session cookie; a protected fixture route validates it; anonymous and
invalid-cookie requests are denied (AC4). `BotManager`'s minimal
constructor flags (verified sha256 `4a02c5fe…8c80844`,
`packages/ai-parrot-server/src/parrot/manager/manager.py:188`) explicitly
disable database bots, crews and registry bots for this fixture profile.

Missing `redis-server` blocks the `botmanager-auth-and-offline` deterministic
scenario (BLOCKED, exit 3); the `mcp-http-lifecycle`/`mcp-stdio-roundtrip`
scenarios in the same deterministic plan still execute, since they need no
Redis at all (`packages/ai-parrot-server/tests/e2e/plans/deterministic.md`:
*"`mcp-http-lifecycle`/`mcp-stdio-roundtrip` need only the already-declared
`mcp` extra"*).

---

## 3. Live cost semantics

The `live` tier is opt-in and separately budgeted; no live/model call is
possible through the deterministic plan. Confirmed real, reproduced from
`parrot.e2e.live` (sha256 `7365bbb8…19301fd`):

- **Opt-in gate** (`require_live_opt_in`), checked *before any client is
  constructed*:
  - `PARROT_TEST_E2E=1`
  - `PARROT_TEST_REAL_LLM=1`
  - `GOOGLE_API_KEY` set and nonempty
  - Missing any of the three → `E2EPrerequisiteError`, exit 3 (BLOCKED).
- **Default budget** (`LiveBudget`, plan default in
  `packages/ai-parrot-server/tests/e2e/plans/live.md`):

  | Field | Default | Live plan override |
  |---|---|---|
  | `model` | `google:gemini-2.5-flash-lite` | same |
  | `max_calls` | 4 | same |
  | `max_output_tokens` | 512 | same |
  | `max_request_bytes` | 16384 | same |
  | `timeout_s` | 60 | 90 (per-scenario `live-google-mcp-agent-tool`) |

  `E2E_MODEL` / `E2E_MAX_LLM_CALLS` env vars can override the model/call
  ceiling per run; both overrides — when present — are captured verbatim
  into `LiveOptIn.env_overrides` and therefore into evidence, never silently
  applied.
- **v1 provider restriction**: only a `google:` model spec is accepted; any
  other provider prefix in `E2E_MODEL` raises `E2EConfigError`
  (`unsupported_provider`) — a configuration error, never a fallback. No
  Groq requirement anywhere in this lane.
- **One shared budget per run**: `build_live_generation_budget()` is called
  once per run; every sequential `live_ask` call against the same
  `mcp-agent` child reuses the same `GenerationBudget` instance — "sequential
  live scenarios reuse it and cannot create fresh allowances per test."
  Budget exhaustion (`GenerationBudgetExceeded`) is converted to
  `E2EBudgetError` at the harness boundary (exit 1) and is **non-retryable**
  — no fallback call follows it.
- **Handshake performs no generation**: MCP `initialize`/`tools/list` never
  constructs the underlying `Agent`; only an actual `tools/call` for
  `live_ask` does (`_ensure_agent()` is lazy, first-call-only).
- **Dispatch scope**: the live plan (`live.md`) is `policy: required`
  *scoped to that dedicated plan only* — the deterministic CI plan carries
  no live scenario at all (AC14: "the deterministic CI plan must contain no
  required live node IDs"). The live CI job only runs on an explicit
  `workflow_dispatch` with `run_live: true`, after the deterministic job has
  already passed, and only a repository secret (`GOOGLE_API_KEY`) ever
  reaches it — never a fork-visible `pull_request` context.
- Every model call still goes through `LLMFactory`/`AbstractClient`
  (`parrot.clients.factory.LLMFactory.create(...)`); the harness never
  imports a provider SDK directly, and `clients/base.py` is untouched by
  this feature.

Published Google Flash-Lite pricing is **not** a locked contractual budget;
this feature enforces request/byte/output/call/deadline caps instead of
assuming a dollar ceiling (spec §2 "Live Provider Budget").

---

## 4. Browser setup

Obscura owns the actual Chrome process; DevTools/Playwright only ever
*attaches* to the CDP endpoint Obscura reports (`browser.py`, sha256
`02f31185…d22fed`):

- `profile="minimal"` (the codified/deterministic default): a fresh,
  deterministic, owned-only loopback CDP port plus a private
  `--storage-dir`. The supervisor owns and can signal this process.
- `profile="full"` **and** `options["adopt"]=True`: exploratory-only.
  `prepare()` returns a `LaunchSpec` for a benign sentinel the supervisor
  owns/kills instead of the real browser, so supervisor teardown can
  **never** signal the externally-owned adopted process — verified
  end-to-end by TASK-3531 with a real `obscura serve` process still alive
  after a full `E2ESupervisor.start()`/`.stop()` cycle.
- `ready()` only ever reads `ObscuraProcessManager`'s side-effect-free
  `endpoint`/`is_running()` members — spawning/killing stays the
  supervisor's own job via `LaunchSpec`, never the adapter's.

The `ui` target (`ui.py`, sha256 `4ae47a4a…2abb4008`) builds the admin UI
with `pnpm build`, then `os.execv`s into `pnpm preview --strictPort` inside
the launched child, pointed at the fixture backend via `PUBLIC_API_URL`
before the build step. Readiness is HTTP `/admin/` returning 200 **plus** a
best-effort backend-reachability probe (any response counts — only a
connection failure/timeout means "not ready"); per spec, "health alone is
not browser evidence," so the codified browser scenario additionally drives
real navigation via Playwright (`test_ui.py`:
`test_ui_browser_console_network`) — connects over CDP, navigates
`/admin/` then `/admin/login`, and asserts no console `error` and no 5xx
responses, capturing a screenshot and JSON diagnostics under the run's
`sdd/state/e2e/<run_id>/` directory on failure.

The codified browser scenario in the deterministic CI plan is deliberately
`required: false` (`ui-browser-console-network`): CI does not install a
pinned Node/pnpm/browser toolchain, so its true, explicit outcome (`passed`
when the toolchain is present, `blocked` when it is not) is always recorded
in evidence and uploaded on failure — never silently skipped as green, and
never gating the deterministic policy.

Exploration (M8, separate lane, never gate evidence): `.claude/agents/
e2e-ui-tester.md` drives the same owned CDP endpoint for open-ended
API/UI probing; its own completion note records that `chrome-devtools-mcp`
is declared in the repo root `package.json` but was not yet registered in
`.mcp.json` at that time, so the exploration agent's host-capability
precondition reports `unavailable` — the documented, spec-required
behavior ("unavailable exploration is reported as unavailable and cannot
invalidate valid deterministic evidence"), not a defect.

---

## 5. Ownership / lease recovery

Every started target carries a `ProcessIdentity` (`pid`, `pgid`,
`create_time`, `boot_id`, `owned: bool`) — **no signal is ever sent based on
a bare PID.** (`parrot.e2e.state`, sha256 `6d121c78…137047ccef`;
`parrot.e2e.watchdog`, sha256 `6745ceb5…901dbc7da9`.)

- `is_authorized_to_signal()` requires: the record is `owned` (never an
  adopted browser), the recorded worktree matches the resolved worktree
  root, the (optional) `owner_id` matches, and `process_identity_matches()`
  confirms the live process's `create_time`/`boot_id` still agree with the
  recorded identity — a foreign or PID-reused process is refused.
- `is_stale()` is `True` when the absolute deadline has passed **or** the
  recorded identity no longer matches a live process; it never authorizes a
  signal by itself — callers must additionally pass the ownership check.
- **Heartbeat/lease**: the watchdog expects a heartbeat touch every 5s;
  15s without one, controller death for a foreground `run`, or absolute
  deadline expiry starts teardown. Detached `up` intentionally survives
  launcher exit but always expires at a default 600-second lease (maximum
  3600s, per `E2EPlan.run_timeout_s`'s own 1..3600 bound).
- **Startup handshake**: the watchdog acknowledges its own start
  immediately (`ACK_FILENAME`), then acknowledges the target's identity
  (`REGISTERED_FILENAME`) before the supervisor is allowed to poll target
  readiness at all — "target identity must be acknowledged before readiness
  can be reported."
- **Crash recovery path**: `reconcile_stale_run()` is idempotent and never
  speculative — a run that is not stale, or already `cleanup_complete`, is
  returned unchanged; it only ever signals a process it has independently
  confirmed is stale. This is the documented recovery path for "simultaneous
  watchdog/host destruction cannot guarantee cleanup" (spec §2).
- **CLI surface** (`cli.py`, sha256 `8a2a4c82…3692f3b43`):
  - `parrot e2e down RUN_ID --owner-id ID` — refuses a cross-owner teardown
    (`E2EConfigError`, `reason_code="foreign_owner"`) if the run's recorded
    owner disagrees.
  - `parrot e2e down --all --owner-id ID` — stops every run owned by that
    identity in this worktree only.
  - `parrot e2e down --stale --owner-id ID` — reconciles every stale,
    owner-matching run via `reconcile_stale_run`; never a global,
    machine-wide kill.
  - Owner defaults to `$PARROT_E2E_OWNER_ID` or the sanitized OS username
    (`cli`, if neither is resolvable) — never invented from agent output.

Reproduced live in this sandbox (no persisted runs exist yet, so `status`
with no argument returns an empty list — the expected, documented shape,
not an error):

```
$ python -c "from parrot.cli import cli; cli(['e2e','status'])"
{"runs":[]}
```

---

## 6. Evidence reuse

`capture_identity()` / `verify_evidence()` (`parrot.e2e.evidence`, sha256
`4d52f464…4916604642e3c`) implement spec §2 "Evidence Identity and Gate
Evaluation" exactly:

- **Manifest**: a canonical, sorted hash of every tracked file plus
  nonignored untracked files — path, git-style mode (`100644`/`100755`/
  `120000`), and either a `sha256:<hex>` content digest or, for a symlink,
  the raw `readlink()` target string (never the dereferenced content).
- **Excluded** (and only these): `artifacts/logs/e2e/`, this feature's own
  run evidence/candidates, pytest caches/bytecode, and SDD task bookkeeping
  (`sdd/tasks/`, `sdd/ledger/`). Arbitrary source, templates, specs, plans
  and dependency metadata are **never** excluded — the plan/spec are hashed
  separately from the source manifest.
- **Environment fingerprint**: interpreter version/path, installed
  distribution versions, `uv.lock`, the selected model, each target's
  `kind`/`profile` (not its free-form `options`, which are deferred to
  per-adapter allow-listing), nonsecret fixture configuration and opt-in
  settings — credential *values* are excluded, but whether a secret is
  configured is not hidden.
- **Reuse rule** (closeout, AC8/AC9): a later commit's evidence is still
  valid only if it is the *same commit or a descendant* with an identical
  source manifest, spec/plan hashes and environment fingerprint — only the
  excluded bookkeeping paths may differ. Any other change, including a
  merge-conflict resolution or a model/config change, invalidates the run
  and requires a fresh one; there is no freshness TTL substitute.
- **`verify` never fabricates a run.** Reproduced live in this sandbox
  (no run has ever executed against this plan in this worktree):

  ```
  $ python -c "from parrot.cli import cli; cli(['e2e','verify','--plan',
      'packages/ai-parrot-server/tests/e2e/plans/deterministic.md'])"
  {"gate_satisfied":false,"reason_codes":["evidence_pointer_missing"],"status":"MISSING"}
  # exit code 4 (EXIT_EVIDENCE)
  ```

  This matches the exit-code table below exactly: `MISSING` (no prior
  evidence pointer) maps to exit `4`, distinct from an executed `FAIL` (exit
  `1`) or `BLOCKED` (exit `3`) — never a fabricated `PASS`.

### Exit-code reference (`parrot.e2e.errors`, sha256 `f63146c6…c029bc419f9b6`)

| Exit | Meaning | `run` | `verify` |
|---|---|---|---|
| 0 | Success / satisfied coverage, or explicit `policy: none` | `EXIT_SUCCESS` | `status="PASS"` |
| 1 | Executed assertion/target/budget/teardown/coverage failure | `E2ETargetError`, `E2EBudgetError` | `status="FAIL"` |
| 2 | Invalid plan/config/model, unsafe path, malformed evidence | `E2EConfigError` | — |
| 3 | Required prerequisite absent, or no codified scenario ran (BLOCKED) | `E2EPrerequisiteError` | `status="BLOCKED"` |
| 4 | Missing/stale/revision-mismatched evidence, or source changed | `E2EEvidenceError` | `status="MISSING"` |
| 130 / 143 | Interrupted by SIGINT / SIGTERM after bounded cleanup | signal handling in `run_command` | — |

`--force` cannot fabricate `PASS` or bypass a required gate anywhere in this
implementation — there is no such flag on `run`/`verify` in the first place.

---

## 7. CLI quick reference

```bash
# Deterministic gate, foreground, bounded — JSON verdict on stdout
PARROT_TEST_E2E=1 parrot e2e run --plan packages/ai-parrot-server/tests/e2e/plans/deterministic.md

# Read-only evidence check (no execution)
parrot e2e verify --plan packages/ai-parrot-server/tests/e2e/plans/deterministic.md

# Start one supervised, detached target (fixed registry names only)
parrot e2e up botmanager --owner-id my-agent

# Inspect / tail / tear down
parrot e2e status [RUN_ID]
parrot e2e logs RUN_ID --tail 200
parrot e2e down RUN_ID --owner-id my-agent
parrot e2e down --all --owner-id my-agent
parrot e2e down --stale --owner-id my-agent

# Optional live tier (dispatch-only; needs GOOGLE_API_KEY + both opt-in flags)
PARROT_TEST_E2E=1 PARROT_TEST_REAL_LLM=1 GOOGLE_API_KEY=... \
  parrot e2e run --plan packages/ai-parrot-server/tests/e2e/plans/live.md
```

CI wiring: `.github/workflows/e2e.yml` runs the deterministic plan on a
`0 3 * * *` cron and on `workflow_dispatch` with no provider secret;
the `live` job runs only on `workflow_dispatch` with `run_live: true`, after
the deterministic job passes, and is the only job that reads
`secrets.GOOGLE_API_KEY`.

---

## 8. Full-profile eligibility

See `sdd/state/FEAT-581/research/full-profile.md` for the AC16 measurement
itself (three warm start/stop cycles, or the explicit BLOCKED disposition
recorded when authorized services are unavailable). Summary: the `full`
`botmanager` profile is **not implemented** by any adapter shipped so far
(`E2EConfigError("botmanager_full_profile_unsupported")` on the only target
that models an application profile at all), and this sandbox has neither a
`redis-server` binary nor a configured Postgres instance nor the
application entry point (`run.py`'s `from app import Main`) needed to boot
one — so the measurement is **BLOCKED**, not merely "not yet run." Full
stays nightly/opt-in; it is not eligible for automatic dev-loop use.

---

## Revision History

| Date | Change |
|---|---|
| 2026-09-24 | Initial version (TASK-3546), verified against worktree commit `98a217451` |
