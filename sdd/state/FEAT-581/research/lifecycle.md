# TASK-3517 Research: Supervisor Crash Recovery and Obscura Process Isolation Contracts

**Feature**: FEAT-581 — Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Module**: M3/M4 (spike gate, per spec §3 "Implementation Spike Gates")
**Acceptance criteria addressed**: AC5, AC6, AC13
**Date**: 2026-09-19

---

## 0. Baseline and Provenance

| Item | Value |
|---|---|
| Spec research baseline | `7b89150e1cd4426cd78a809a32aa7d3706d456ad` (`dev`) |
| Worktree HEAD at spike time | `6ce4e4f21` (descendant of the baseline, confirmed via `git merge-base`) |
| Host | Linux 7.0.0-30-generic x86_64 (Ubuntu 24.04 base) |
| Python | the shared workspace `.venv` interpreter (3.12), invoked read-only |
| Obscura binary | `/home/jesuslara/.local/bin/obscura`, `obscura --version` → `obscura 0.2.2` (matches spec's pinned v0.2.2) |
| psutil | `7.2.2` installed (spec requires `>=5.9`) |

Source anchors re-verified byte-for-byte against the task's Codebase Contract:

- `packages/ai-parrot-server/src/parrot/mcp/obscura.py` — sha256
  `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73` (read in full;
  unmodified by this task).
- `tests/mcp/test_mcp_local_e2e.py` — sha256
  `4849a8cf317883d64dcc0c2f9c41b6dec4ebd7ac646d1506a48ae3606e03d1de` (read in full).

**Method.** All experiments below run the *real, unmodified* production
`ObscuraProcessManager`/`ObscuraProcessConfig` classes and the *real* installed
Obscura v0.2.2 binary — no mocks, no stubs (the existing
`packages/ai-parrot-server/tests/mcp/test_obscura.py` suite already covers the
mocked-unit-test side; this spike is the process-boundary complement it
explicitly does not attempt). Disposable driver/fixture scripts and raw logs
live under `artifacts/logs/FEAT-581/TASK-3517/spike/` (gitignored,
**not** part of this task's file scope, not committed):

- `manager_child.py` — a disposable "supervisor" process that owns exactly one
  `ObscuraProcessManager`, printing timestamped markers (`SPAWNING`,
  `OWNED_PID=`, `READY`) so a driver can observe internal event ordering
  without modifying `obscura.py`.
- `driver.py` — spawns `manager_child.py`, kills it with `SIGTERM`/`SIGKILL` at
  controlled points (before/after CDP readiness), and measures whether/when
  the owned Obscura process is cleaned up. Also drives a 3-level
  controller→supervisor→target case.
- `socket_roundtrip.py` — a private Unix-domain control-socket prototype
  exercising the register/heartbeat wire shape proposed in §3 below.
- `run_*.log` — raw stdout of each run (all reproduced below in sanitized/
  condensed form; no secrets, no full environment dumps).

Every experiment's exact command and full raw output is preserved in that
`artifacts/` directory for anyone re-running this spike; this report embeds
the sanitized, load-bearing excerpts only.

This spike was itself executed inside a `bwrap --unshare-pid` sandbox (the
harness's own command isolation), so process IDs below (e.g. `pid=26`,
`pid=6`) are namespace-local, small integers, not host PIDs — noted because
it also means any process this spike left "orphaned" inside a single Bash
invocation was reaped automatically at the end of that invocation by the
kernel tearing down the PID namespace, **not** by any code under test. This
does not change the conclusions (SIGKILL-uncatchability and no-cascade-on-
detached-descendant are host-independent OS facts), but it means the
"orphaned indefinitely" observations below hold for the *real* production
host/CI process tree, where no such namespace exists to eventually reap
them — which is exactly the gap the spec's separate watchdog process is
designed to close.

---

## 1. Q1 — Controller/supervisor death before and after target registration

**Verdict: PASS** (reproduced with the real `ObscuraProcessManager`; bounded
recovery measured for every catchable-signal case; the uncatchable-signal
gap is precisely characterized, not hand-waved).

### 1.1 Event ordering (verified by reading `obscura.py` + confirmed empirically)

Inside `ObscuraProcessManager.start()` (`obscura.py:222-324`), ownership is
recorded **synchronously, with no `await` in between**, immediately after
`asyncio.create_subprocess_exec` returns:

```
await asyncio.create_subprocess_exec(...)   # spawn
self._owns_process = True                   # ownership recorded
self._owned_pid = self.process.pid          # <- both of these happen before
self._register_cleanup_hooks()              #    the readiness-polling loop starts
# ... THEN the readiness polling loop (is_running() every 0.2s) begins
```

This means the "registered" (owned + cleanup-hook-armed) state is reached
*before* CDP readiness, not after — confirmed by instrumenting a concurrent
watcher task in `manager_child.py` that observes `manager.process` the
instant it is set, independent of `start()`'s own return:

| Run | `spawn → owned` | `spawn → CDP ready` |
|---|---|---|
| case_a (post-ready kill) | 0.0129s | 0.2149s |
| case_b (post-ready kill) | 0.0126s | 0.2103s |
| case_c (pre-ready kill)  | 0.0133s | (killed before ready) |
| case_d (pre-ready kill)  | 0.0124s | (killed before ready) |

Ownership is recorded ~13ms after spawn, ~200ms before the CDP endpoint is
actually ready — a real, ~190ms pre-readiness window exists on this host,
and the manager's own bookkeeping already covers it (registration precedes
readiness by design, not by accident).

### 1.2 Bounded recovery — catchable signal (SIGTERM to the supervisor)

| Case | When killed | Signal | Owned Obscura process | Cleanup time |
|---|---|---|---|---|
| case_a | after CDP ready | `SIGTERM` | cleaned | **0.1644s** |
| case_c | before CDP ready (mid-launch) | `SIGTERM` | cleaned | **5.1004s** |

Both go through `ObscuraProcessManager._register_cleanup_hooks()` →
`_sync_kill_owned_process()` (SIGTERM to the owned pid, poll up to 5s,
escalate to SIGKILL) — this path is **unmodified, exercised as-is**. The
~30x slower cleanup in case_c is a genuine, reproducible finding, not noise
(reran; consistent order of magnitude): a freshly-spawned Obscura process
killed with SIGTERM *during* its own startup takes materially longer to
honor the signal than a fully-initialized one — plausibly still inside V8
isolate/runtime bring-up when the signal arrives. **This is a concrete
number the spec's teardown-deadline documentation should carry**: the
existing 5-second escalation window in `_sync_kill_owned_process` is
already large enough to cover this case (case_c finished in 5.10s, just
past the nominal 5s loop before the final `SIGKILL` — i.e. cleanup actually
completed via the escalation `SIGKILL`, not the initial `SIGTERM`), and it
comfortably fits inside the spec's 15-second watchdog heartbeat-timeout
budget, but a *tighter* deadline than ~5-6s for "kill mid-launch" would be
unsafe based on this measurement.

### 1.3 Bounded recovery — uncatchable signal (SIGKILL to the supervisor)

| Case | When killed | Signal | Owned Obscura process |
|---|---|---|---|
| case_b | after CDP ready | `SIGKILL` | **orphaned** (still alive after 10s poll) |
| case_d | before CDP ready | `SIGKILL` | **orphaned** (still alive after 10s poll) |

`SIGKILL` cannot be caught, so neither the registered `signal.signal()`
handler nor the `atexit` hook ever runs — there is **no in-process recovery
path for this case, by construction**, regardless of pre/post-readiness
timing. This is not a bug in `obscura.py`; it is the precise reason the
spec mandates a *separate* watchdog process (§2, "A separate watchdog
monitors supervisor identity and a 5-second heartbeat"): only a process
other than the crashed one can detect the missing heartbeat and reap the
orphan. **Do not treat `ObscuraProcessManager`'s atexit/signal hooks as a
substitute for the watchdog** — they cover the graceful-shutdown and
catchable-signal cases only.

### 1.4 Controller death does not cascade to a detached supervisor

Reproduced a 3-level tree: driver ("controller") → `subprocess.Popen(...,
start_new_session=True)` ("supervisor", same detachment mode
`ObscuraProcessManager.start()` itself uses for Obscura) → owned Obscura
process.

```
{'port': 9285, 'supervisor_pid': 6, 'owned_pid': 27,
 'supervisor_alive_after_controller_sigkill': True,
 'target_alive_after_controller_sigkill': True,
 'target_alive_after_supervisor_sigterm_cleanup': False}
```

`SIGKILL`ing the controller left both the supervisor **and** its owned
target running, untouched, confirmed alive 1 second later. Only then
`SIGTERM`ing the supervisor cleaned the target (via the same signal-handler
path as §1.2). **Verified**: OS-level process death does not propagate
from a controller to a `start_new_session=True` descendant — the spec's
explicit choice of a dedicated watchdog process (rather than relying on
process-group/session signal propagation, or on the controller itself) is
the only way to detect and react to controller death for a foreground
`run`; nothing about a plain parent/child relationship does it for free.

---

## 2. Q2 — Obscura version/help, private-profile argument, DevTools attachment

**Verdict: PASS.**

### 2.1 Version and CLI surface (verified, `obscura --version` / `--help` / `serve --help` / `mcp --help`)

```
$ obscura --version
obscura 0.2.2

$ obscura --help
Obscura - A lightweight headless browser for web scraping and automation
Commands: serve, fetch, scrape, mcp, help
Global options include: -p/--port, --proxy, --stealth, --obey-robots,
  --user-agent, --storage-dir, --allow-private-network, --v8-flags

$ obscura serve --help
Options: -p/--port, --host, --proxy, --user-agent, --workers,
  --max-connections, --allow-file-access, --stealth, --storage-dir,
  --obey-robots, --quiet, --allow-private-network
```

`obscura mcp` is a **separate**, unrelated subcommand (Obscura's own native
MCP server, on a different default port 3000) — not used by
`ObscuraProcessManager`, which only ever drives `obscura serve` (confirmed
by reading `_build_command()`, `obscura.py:206-220`). Do not conflate the
two in M4 target-adapter work.

### 2.2 No "profile" flag — `--storage-dir` is the private-profile equivalent

Confirms the spec's "Does NOT Exist" note precisely: there is no
`--profile` flag, and `ObscuraProcessConfig` has no `profile`/`storage_dir`
field today. The actual mechanism is `serve --storage-dir <PATH>`:

- **With** `--storage-dir <dir>`: Obscura writes persistent state
  (confirmed: a `cookies.json` file) into that directory.
- **Without** `--storage-dir`: verified Obscura leaves **no** state
  anywhere under `$HOME` (`~/.obscura`, `~/.config/obscura`,
  `~/.local/share/obscura` all absent after a serve+CDP-round-trip+stop
  cycle) — the default profile is fully ephemeral/in-memory.

**Implication for AC6** (concurrent worktrees need distinct browser
profiles): isolation is achievable simply by (a) using the default
ephemeral profile per run (already isolated, zero config needed), or (b)
passing a unique, run-scoped `--storage-dir` (e.g. under the run's
mode-0700 state directory) when persistence across restarts is required.
M4 must add a `storage_dir: Optional[str]` field to `ObscuraProcessConfig`
and thread it into `_build_command()` — this is new work, not something
already wired up.

### 2.3 DevTools/CDP attachment — verified real endpoint shape

```
$ curl http://127.0.0.1:9295/json/version
{
  "Browser": "Chrome/145.0.0.0", "Protocol-Version": "1.3",
  "V8-Version": "14.5.0.0", "WebKit-Version": "537.36",
  "webSocketDebuggerUrl": "ws://127.0.0.1:9295/devtools/browser"
}

$ curl http://127.0.0.1:9295/json/list
[{"id": "page-1", "type": "page", "url": "about:blank",
  "webSocketDebuggerUrl": "ws://127.0.0.1:9295/devtools/page/page-1"}]
```

This is a real Chrome DevTools Protocol surface (`/json/version` +
`/json/list`, per-target `webSocketDebuggerUrl`) — exactly what
`chromium.connect_over_cdp()` (Playwright, per `obscura.py`'s own module
docstring) needs to attach. `ObscuraProcessManager.is_running()` already
polls `/json/version` (`obscura.py:186`), so the manager's own readiness
probe is hitting the correct, real endpoint — confirmed, not assumed.

### 2.4 Newly-added signal/atexit behavior — preserved and exercised, not modified

`obscura.py` was **not edited** by this task. Its `atexit`/`SIGTERM`/
`SIGINT` handling (`_register_cleanup_hooks`/`_sync_kill_owned_process`,
lines 104-159) is exactly what produced the successful cleanups in
§1.2/§1.4 above — this spike is evidence that behavior works as designed
for catchable signals, without touching the module.

---

## 3. Q3 — Watchdog registration/ACK/heartbeat schema, private socket shapes, owned browser argv

**Verdict: PASS**, with an explicit scope note: per this task's own
Codebase Contract ("No new cross-task public signature beyond the approved
spec... Dependency Interfaces (new, not existing): None"), what follows
freezes the **wire shape and identity fields**, informed by (a) the spec's
already-normative `RunState`/`ProcessIdentity` models (§2) and (b) a
working prototype (verified below) — it does **not** invent new
cross-task Python class/method names. M3's implementation task chooses its
own internal class names; it must not choose different field names or a
different framing/correlation strategy than what is frozen here.

### 3.1 Concrete, verified owned-browser argv (not BLOCKED — the binary is present)

```python
[resolved_binary, "serve", "--host", host, "--port", str(port)]
# + "--stealth" if config.stealth
# + "--allow-private-network" if config.allow_private_network
# + "--storage-dir", storage_dir   # NEW field M4 must add; verified flag exists today
```

Exact real argv captured from a spike run: `/home/jesuslara/.local/bin/obscura
serve --host 127.0.0.1 --port 9281 --allow-private-network`. No shell
string is used — `asyncio.create_subprocess_exec(*cmd, ...)` argv execution,
already matching the spec's "Commands use argv execution, never shell
strings" requirement.

### 3.2 Two distinct channels — do not conflate them

The spec text names two different things under similar wording; verified
separately:

**(a) Watchdog control-plane (one per run: register once, heartbeat every
5s).** No implementation exists yet (`parrot/e2e/{watchdog,control}.py` are
new M3 paths, correctly listed as "Does NOT Exist"). Frozen proposed wire
contract, reusing the newline-delimited JSON-RPC envelope already proven
working in `tests/mcp/test_mcp_local_e2e.py` (`_send`/`_recv`) and
re-verified end-to-end over a Unix domain socket in this spike
(`socket_roundtrip.py`, output below):

```jsonc
// register (supervisor -> watchdog), once at target spawn:
{"jsonrpc": "2.0", "id": "<uuid>", "method": "register",
 "params": {"run_id": "<run-id>", "target_id": "<target-id>",
            "identity": {"pid": 0, "pgid": 0, "create_time": 0.0,
                         "boot_id": "<str>", "owned": true}}}
// ack (watchdog -> supervisor):
{"jsonrpc": "2.0", "id": "<same id>", "result":
 {"status": "ack", "run_id": "<run-id>", "target_id": "<target-id>"}}

// heartbeat (supervisor -> watchdog), every 5s per spec:
{"jsonrpc": "2.0", "id": "<uuid>", "method": "heartbeat",
 "params": {"run_id": "<run-id>", "seq": 1, "ts": 0.0}}
// heartbeat ack:
{"jsonrpc": "2.0", "id": "<same id>", "result": {"status": "ok", "seq": 1}}

// error (any unknown/malformed method):
{"jsonrpc": "2.0", "id": "<id-or-null>",
 "error": {"code": -32601, "message": "unknown method"}}
```

`identity` fields map 1:1 onto the spec's already-normative
`ProcessIdentity` model (`pid`, `pgid`, `create_time`, `boot_id`, `owned`) —
no new field names invented. All four are practically obtainable on this
host: `psutil.Process(pid).create_time()`, `os.getpgid(pid)`, and
`/proc/sys/kernel/random/boot_id` all resolved successfully in this spike
(psutil `7.2.2` installed, satisfies the spec's `>=5.9`).

Verified over a real `asyncio.start_unix_server` at a mode-0700 run
directory / mode-0600 socket (both permissions set and confirmed via
`os.stat`), including that two concurrent in-flight requests with
different artificial delays resolve to the *correct* caller purely by
`"id"` correlation despite completing out of send order:

```
run_dir_mode=0o700 sock_mode=0o600
register -> {'id': 'reg-1', 'result': {'status': 'ack', 'run_id': 'run-abc', 'target_id': 'browser-1'}}
heartbeat -> {'id': 'hb-1', 'result': {'status': 'ok', 'seq': 1}}
fast -> {'id': 'hb-fast', 'result': {'status': 'ok', 'seq': 3}}    # completed first
slow -> {'id': 'hb-slow', 'result': {'status': 'ok', 'seq': 2}}    # completed second, sent first
unknown -> {'id': 'bad-1', 'error': {'code': -32601, 'message': 'unknown method'}}
ALL_ASSERTIONS_PASSED
```

This validates the spec's "requests are serialized and checked for
matching JSON-RPC IDs" requirement is achievable with plain
dictionary-keyed correlation on the client side; no additional framing
beyond newline-delimited JSON is required.

**(b) Per-`mcp-stdio`-target private socket (data-plane, one per stdio
target instance).** Frozen contract: **no new schema at all** — the
supervisor tunnels the existing, already-verified MCP JSON-RPC methods
(`initialize`, `notifications/initialized`, `tools/list`, `tools/call`;
exact shapes proven live in `tests/mcp/test_mcp_local_e2e.py`) 1:1 through
the socket to the stdio child it exclusively owns, correlating by the
caller's original `"id"` exactly as in §3.1's control-plane prototype. This
is the minimal-risk choice per this task's own "no new cross-task public
signature" constraint — it reuses a contract already proven working in
production tests rather than defining a second one.

### 3.3 A real gap this spike surfaces for M3 (not resolved here — flagged)

`obscura.py`'s own cross-invocation PID-file adapter
(`default_pid_file`/`write_pid_file`/`read_pid_file`, lines 402-447)
persists **only a bare PID** — no `create_time`/`boot_id`. The spec's
`ProcessIdentity` model explicitly requires those fields ("no signaling
based on a bare PID"). **This adapter is insufficient, as-is, for a
watchdog to safely reconcile ownership after a crash** (PID reuse risk on
a long-lived host); M3 must not reuse it unmodified for watchdog
reconciliation — it needs a `ProcessIdentity`-shaped persisted record
instead. This is a finding, not a fix — no code was changed.

---

## 4. Q4 — Launch-before-registration crash window, documented with tested recovery

**Verdict: PASS** — this is the synthesis of §1.1-§1.4, restated explicitly
because the task requires it not be "resolved using prose alone":

- The window is real and measured: ~13ms (spawn→owned) to ~200ms
  (spawn→CDP-ready) on this host with this Obscura build.
- **Tested, bounded recovery exists** for the entire window (both before
  and after CDP readiness) when the supervisor receives a **catchable**
  signal (`SIGTERM`): 0.16s (post-ready) to ~5.1s (mid-launch) — both
  measured, not assumed.
- **No recovery exists, by construction,** for an **uncatchable** signal
  (`SIGKILL`) to the supervisor, anywhere in the window — measured (10s
  poll, still alive) on both sides of readiness. This is the concrete,
  irreducible reason M3 needs an external watchdog process rather than
  relying solely on `ObscuraProcessManager`'s own signal/atexit hooks.
- Controller death (SIGKILL) does **not** cascade to a detached supervisor
  or its owned target — measured directly (§1.4) — so "controller death
  triggers teardown" in the spec must be implemented by the watchdog
  detecting the loss (e.g. no more foreground-run liveness, or an explicit
  controller-death signal into the watchdog), not by any OS-level
  propagation, which does not happen for a `start_new_session=True` tree.

---

## 5. Selected Contract (frozen, for M3/M4 to build against)

1. Ownership recording precedes CDP readiness by design (§1.1) — M3's
   watchdog registration handshake must be able to fire during this
   pre-readiness window, not only after readiness.
2. Catchable-signal cleanup bound: budget **≥6s** for a mid-launch kill
   (measured 5.10s), well inside the spec's 15s heartbeat-timeout and
   10s-SIGTERM/kill teardown language — do not tighten below this without
   re-measuring.
3. Uncatchable-signal (SIGKILL) cleanup has **zero** in-process recovery —
   the watchdog is mandatory for this case, not optional hardening.
4. Controller death does not cascade OS-level to a detached supervisor —
   the watchdog (not the controller, not the OS) is the sole detector.
5. Private-profile mechanism is `--storage-dir <path>`, a **new**
   `ObscuraProcessConfig` field M4 must add — not `--profile`, not already
   present.
6. Default (no `--storage-dir`) profile is verified ephemeral — safe
   default for concurrent, isolated runs without any extra bookkeeping.
7. CDP attachment point (`/json/version`, `/json/list`,
   `webSocketDebuggerUrl`) is real and already what
   `ObscuraProcessManager.is_running()` probes — no gap here.
8. Watchdog control-plane wire shape: newline-delimited JSON-RPC over a
   private Unix socket (mode 0600 in a mode-0700 run dir), fields per
   §3.2(a), correlated by `"id"` — verified working end-to-end, including
   out-of-order concurrent responses.
9. Stdio-target private socket: reuse the existing MCP JSON-RPC methods
   verbatim as a 1:1 tunnel — no second schema.
10. `ProcessIdentity` fields (`pid`, `pgid`, `create_time`, `boot_id`,
    `owned`) are all practically obtainable via `psutil` + stdlib on this
    host; the existing PID-file adapter does **not** provide them and must
    not be reused unmodified for watchdog reconciliation (§3.3).

## 6. Rejected Assumptions

- Rejected: that `ObscuraProcessConfig` already exposes a profile
  parameter — verified absent; `--storage-dir` is the real flag, and it is
  not yet wired into the dataclass.
- Rejected: that OS-level parent death cascades to
  `start_new_session=True` children — verified false, directly, twice
  (§1.4): a SIGKILLed controller leaves both supervisor and target running.
- Rejected: that the legacy `_recv(proc, timeout=10.0)` helper in
  `tests/mcp/test_mcp_local_e2e.py` enforces a real deadline — re-read the
  source: it calls a plain blocking `proc.stdout.readline()` and never uses
  `timeout` at all. M3's real supervisor must use `asyncio.wait_for`-backed
  reads for its stdio target proxying — copying this helper's *shape*
  without fixing this would silently reintroduce an unbounded hang.
- Rejected: that a single fixed cleanup deadline is safe regardless of
  when the crash occurs — measured a ~30x difference in cleanup latency
  between a post-ready kill (0.16s) and a mid-launch kill (5.10s) with the
  identical code path and signal.
- Rejected: that the existing PID-file cross-invocation adapter is
  sufficient for crash reconciliation — it has no `create_time`/`boot_id`,
  which the spec's own `ProcessIdentity` model requires precisely to avoid
  PID-reuse false positives.

## 7. Acceptance Criteria Mapping

- **AC5** (timeout/cancellation/controller-or-supervisor-death cleans owned
  processes within documented deadlines; foreign/reused PIDs and adopted
  browsers never killed): supported by §1.2-§1.4 with measured numbers;
  the foreign-PID/reused-PID risk is called out as an open gap in §3.3/§6
  that M3 must close (not yet implemented — this is a spike, not M3
  itself).
- **AC6** (concurrent worktrees use distinct ports/state/data/browser
  profiles): supported by §2.2 (ephemeral-by-default + unique
  `--storage-dir` capability) and by `ObscuraProcessConfig.port` already
  being per-instance configurable (existing field, unchanged).
- **AC13** (owned browser/UI lane verifies real navigation/console/network
  via the allocated endpoint; absent tooling reported explicitly):
  supported by §2.3 (real CDP endpoint verified reachable and
  DevTools-compatible on this host). Obscura was **present** in this
  environment (`~/.local/bin/obscura`), so absence could not be exercised
  here — CI/other hosts must rely on the existing
  `ObscuraProcessManager._resolve_binary()` (`shutil.which`) failing
  closed with `"Obscura binary not found"` (verified code path,
  `obscura.py:272-274`, exercised indirectly by the existing
  `test_obscura_manager_start_failure` unit test) rather than silently
  skipping — this task does not claim to have tested the true-absence
  path on a host without the binary.

## 8. BLOCKED Items

None. Every required question in this task's Scope had the necessary
binaries/environment access to produce a concrete, measured answer on this
host (Obscura v0.2.2 present, psutil present, Unix sockets available). The
one genuinely open item — extending `ObscuraProcessConfig`/the PID-file
adapter to close the gaps in §3.3/§6 — is implementation work correctly
deferred to M3/M4's own task packets, not a blocked research question.

## 9. Artifacts

Raw, unedited outputs and disposable driver scripts (not part of this
task's file scope; gitignored, not committed):

- `artifacts/logs/FEAT-581/TASK-3517/spike/manager_child.py`
- `artifacts/logs/FEAT-581/TASK-3517/spike/driver.py`
- `artifacts/logs/FEAT-581/TASK-3517/spike/socket_roundtrip.py`
- `artifacts/logs/FEAT-581/TASK-3517/spike/run_case_a_sigterm_after_ready.log`
- `artifacts/logs/FEAT-581/TASK-3517/spike/run_case_b_sigkill_after_ready.log`
- `artifacts/logs/FEAT-581/TASK-3517/spike/run_case_c_sigterm_before_ready.log`
- `artifacts/logs/FEAT-581/TASK-3517/spike/run_case_d_sigkill_before_ready.log`
- `artifacts/logs/FEAT-581/TASK-3517/spike/run_case_e_controller_death_no_cascade.log`
- `artifacts/logs/FEAT-581/TASK-3517/spike/run_socket_roundtrip.log`

## 10. Validation Commands Run

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src \
  python3 -m pytest packages/ai-parrot-server/tests/mcp/test_obscura.py -q
```

Result: `10 passed, 4 warnings in 2.22s` — existing mocked unit-test file,
unmodified by this task, confirming this spike's real-process/real-binary
experiments above did not regress `ObscuraProcessManager`'s already-tested
mocked behavior.
