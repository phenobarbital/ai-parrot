# HOTFIX-792b6e2a8f25-1: Real-subprocess launcher-exit survival scenarios for `parrot e2e up`

**Feature**: BRIEF-792b6e2a8f25 — e2e-up-launcher-exit-survival
**Spec**: `sdd/briefs/e2e-up-launcher-exit-survival.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Ledger issue `issue:792b6e2a8f25` (major, feature_gap, from the TASK-3534 /
FEAT-581 code review): the `up` command's detached-daemon lifecycle is only
unit-tested with monkeypatched `asyncio.create_subprocess_exec` and a faked
`E2ESupervisor`. AC5's sub-claim — the started daemon+target **survive the
launcher's exit** — is designed-for (`start_new_session=True`) but never
empirically verified with real subprocesses. The opt-in process-boundary
scenario suite this belongs to (`packages/ai-parrot-server/tests/e2e/`,
`PARROT_TEST_E2E=1`) now exists; this task adds the missing scenario file.

---

## Scope

- Add `packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py`
  with two `@pytest.mark.e2e` async scenarios that spawn the REAL CLI
  (`sys.executable -m parrot.e2e.cli …`) as subprocesses — no monkeypatching
  of `asyncio.create_subprocess_exec`, no fake supervisor:
  1. **Natural launcher exit**: run `up mcp-stdio`, let the launcher exit 0,
     parse its RunState JSON line, then assert the daemon
     (`supervisor_identity`) and target (`process_identity`) processes are
     still alive (pid exists AND psutil create_time matches the identity's
     `create_time`, so PID reuse can't fake a pass).
  2. **Launcher killed mid-wait**: start `up mcp-stdio`, SIGKILL the launcher
     process while it is still polling for the readiness ticket, then poll the
     ticket file yourself until the daemon writes it (bounded deadline);
     assert the daemon still reached readiness and daemon+target are alive.
- Both scenarios tear down deterministically in `finally`: invoke
  `… -m parrot.e2e.cli down <run_id>` as a real subprocess, wait (bounded)
  for the daemon pid to disappear, and assert the final persisted state has
  `cleanup_complete is True`; fall back to `os.killpg` on both pgids plus
  `e2e_state.delete_state` if `down` fails, so no process or state file leaks.
- Write both tests to be independent of each other and of the other suite
  files (unique `--owner-id` / `--run-id` per test, `uuid4().hex` based).

**NOT in scope**:
- Any change to `packages/ai-parrot-server/src/parrot/e2e/cli.py` or the
  supervisor — this is a test-only task. If a scenario exposes a real product
  bug, record it in the Completion Note and open a ledger issue instead of
  patching the product code here.
- The existing monkeypatched unit tests in
  `packages/ai-parrot-server/tests/unit/e2e/test_cli.py` (they stay as-is).
- Wiring the scenario into any E2E plan markdown under `tests/e2e/plans/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py` | CREATE | Two real-subprocess AC5 survival scenarios + teardown helpers |
| `packages/ai-parrot-server/src/parrot/e2e/cli.py` | MODIFY | `_detach_from_loop` so the launcher's loop teardown no longer kills the daemon (approved scope expansion) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import psutil  # already used by packages/ai-parrot-server/tests/e2e/test_supervisor.py
from parrot.e2e import state as e2e_state  # packages/ai-parrot-server/src/parrot/e2e/state.py
from parrot.e2e.models import RunState  # packages/ai-parrot-server/src/parrot/e2e/models.py:336
from parrot.e2e.cli import _ticket_path  # packages/ai-parrot-server/src/parrot/e2e/cli.py:455
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/e2e/cli.py:455
def _ticket_path(worktree: Path, invocation_id: str) -> Path: ...

# packages/ai-parrot-server/src/parrot/e2e/cli.py:467 — behavior under test (do not call directly)
async def _spawn_detached_target(target, config, *, invocation_id, owner_id, worktree, feature_id) -> RunState: ...
# cli.py:527 — start_new_session=True is the survival mechanism being verified

# packages/ai-parrot-server/src/parrot/e2e/cli.py:616 — the daemon loop; exits when
# a SIGTERM/SIGINT arrives or the persisted state shows cleanup_complete
async def _run_daemon(target_id, config, *, owner_id, worktree, feature_id, ticket_path) -> int: ...

# packages/ai-parrot-server/src/parrot/e2e/models.py:300
class ProcessIdentity(_E2EBaseModel):
    pid: int        # line 317
    pgid: int       # line 318
    create_time: datetime  # line 319 (UTC)
    boot_id: str
    owned: bool

# packages/ai-parrot-server/src/parrot/e2e/models.py:336
class RunState(_E2EBaseModel):
    run_id: str
    supervisor_identity: ProcessIdentity  # the detached daemon
    process_identity: ProcessIdentity     # the supervised target
    status: str  # "ready" on success
    cleanup_complete: bool

# packages/ai-parrot-server/tests/e2e/conftest.py:32
@pytest.fixture(scope="session")
def e2e_worktree() -> Path: ...  # repo root; pass as cwd= so cli._resolve_worktree finds it

# packages/ai-parrot-server/src/parrot/e2e/state.py — persisted-state helpers used by the suite
e2e_state.read_state(run_id, worktree=...)   # used at cli.py:664
e2e_state.delete_state(run_id, worktree=...) # used by tests/e2e/test_supervisor.py teardown
```

CLI invocations (subprocess argv, never in-process):
```text
sys.executable -m parrot.e2e.cli up mcp-stdio --owner-id <owner> --run-id <ticket-id> [--timeout <s>]
sys.executable -m parrot.e2e.cli down <run_id>
# both with cwd=str(e2e_worktree): cli._resolve_worktree() (cli.py:107) walks up from cwd to .git
```

### Does NOT Exist
- ~~`RunState.daemon_pid`~~ — the daemon's identity is `supervisor_identity`
- ~~a public `parrot.e2e.cli.ticket_path`~~ — only the private `_ticket_path` (cli.py:455)
- ~~an `E2ESupervisor` fixture that manages `up`-spawned daemons~~ — the
  `e2e_supervisor_factory` fixture owns in-process supervisors only; `up`'s
  daemon is NOT registered there and must be torn down via `down`/killpg
- ~~a `PARROT_E2E_WORKTREE` env var~~ — worktree resolution is cwd-based only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/e2e/cli.py#_spawn_detached_target",
    "sym:packages/ai-parrot-server/src/parrot/e2e/cli.py#_run_daemon",
    "sym:packages/ai-parrot-server/src/parrot/e2e/cli.py#_ticket_path"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror the suite's existing conventions
(`packages/ai-parrot-server/tests/e2e/test_supervisor.py`,
`test_mcp_stdio.py`): module docstring naming FEAT-581, `@pytest.mark.e2e`
on every test (the conftest `pytest_runtest_setup` hook enforces the
`PARROT_TEST_E2E=1` opt-in), `asyncio_mode = "auto"` so async tests need no
extra marker, bounded `asyncio.wait_for` on every wait, and `finally` blocks
that killpg + delete state with `contextlib.suppress`.

Survival assertion — never trust the pid alone (PID-reuse guard, same rule
the product's `ProcessIdentity` doc states):

```python
def _is_alive(identity: ProcessIdentity) -> bool:
    try:
        proc = psutil.Process(identity.pid)
        observed = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
    except psutil.NoSuchProcess:
        return False
    return abs((observed - identity.create_time).total_seconds()) < 1.0
```

Scenario 1 sketch: spawn `up` with `stdout=PIPE`; `await wait_for(proc.communicate(), 90)`;
assert returncode 0; parse the LAST line of stdout as JSON →
`RunState.model_validate`; assert `status == "ready"`; the launcher has now
exited by construction — assert `_is_alive(state.supervisor_identity)` and
`_is_alive(state.process_identity)`.

Scenario 2 sketch: compute `ticket = _ticket_path(e2e_worktree, ticket_id)`
and unlink it if present; spawn `up` with a known `--run-id <ticket_id>`;
after ~0.5s (launcher is polling, daemon already forked or forking) send
`launcher.kill()` and reap it; then poll `ticket.is_file()` under a bounded
deadline (use the target's 30s startup timeout + grace); parse the ticket with
`RunState.model_validate(json.loads(...))` (fail the test on an `"error"`
payload); assert daemon+target `_is_alive`. Note the small race: if the
daemon itself failed before the kill, the ticket carries `error` — surface
that as a failed assertion with the daemon log
(`artifacts/logs/e2e/<daemon-logs-dir>/<ticket_id>.log`) in the message.

Teardown helper (shared by both): run `down <run_id>` via subprocess with
cwd=worktree, then `wait_for` daemon-pid death (poll `_is_alive`, ≤30s), read
final persisted state and assert `cleanup_complete`; on any failure,
`os.killpg(identity.pgid, SIGKILL)` for target then daemon under
`contextlib.suppress(ProcessLookupError)` and `e2e_state.delete_state`.

Keep every subprocess handle reaped (`await proc.wait()`), including the
SIGKILLed launcher, to avoid zombie warnings under pytest-asyncio.

---

## Acceptance Criteria

- [ ] `test_up_daemon_and_target_survive_launcher_exit`: real `up mcp-stdio`
      launcher exits 0 with a `status == "ready"` RunState, and BOTH
      `supervisor_identity` and `process_identity` are alive afterwards with
      matching `create_time` (identity-verified, not pid-only).
- [ ] `test_up_daemon_survives_launcher_sigkill_mid_wait`: SIGKILLing the
      launcher before the ticket appears does not kill the daemon; the ticket
      is still written, the RunState is `ready`, and daemon+target are alive.
- [ ] Both tests tear the run down (`down` CLI, killpg fallback) and leave no
      live process and no persisted run state behind, asserting
      `cleanup_complete is True` on the clean path.
- [ ] No monkeypatching of subprocess creation, no fake supervisor, no
      product-code changes.
- [ ] Without `PARROT_TEST_E2E=1` the new tests are skipped (existing conftest
      gate — do not reimplement it).
- [ ] `ruff check` passes on the new file.

---

## Validation Commands

- `PARROT_TEST_E2E=1 PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py -q`

(Also run `ruff check packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py` per the Acceptance Criteria — kept out of the bullet list above because the validation contract accepts pytest invocations only.)

---

## Test Specification

The deliverable IS the tests (see Acceptance Criteria). Known environment
caveat: ledger issue `issue:e21ec87c6aba` records resource-contention
flakiness when many real-subprocess tests run together — these scenarios must
pass when their file is run alone (the validation command above), which is
the suite's established bar.

---

## Agent Instructions

1. Read the brief (`sdd/briefs/e2e-up-launcher-exit-survival.brief.md`) and
   `packages/ai-parrot-server/src/parrot/e2e/cli.py:455-705` before writing code.
2. Create only the one file listed. Follow the Codebase Contract verbatim;
   verify any additional symbol with grep before using it.
3. Run the Validation Commands; both tests must pass with the opt-in set and
   skip without it.
4. Commit only the new test file:
   `fix(e2e): HOTFIX-792b6e2a8f25-1 — real-subprocess launcher-exit survival tests for up`.

---

## Completion Note

**Completed by**: sdd-start (Claude)
**Status**: done

- Created `packages/ai-parrot-server/tests/e2e/test_up_detached_lifecycle.py` (two real-subprocess scenarios, identity-verified liveness, `down` teardown with killpg fallback).
- The natural-exit scenario exposed a real product bug (`issue:0a04d048dab5`), root-caused by strace: the launcher's asyncio loop teardown (`BaseSubprocessTransport.close()`) SIGKILLs the detached daemon, then the watchdog tears the target down. **Scope expansion approved by the user**: fixed in `packages/ai-parrot-server/src/parrot/e2e/cli.py` with a new `_detach_from_loop()` helper, called once the readiness ticket appears in `_spawn_detached_target` (drops the transport's Popen reference; it touches asyncio's private `_transport._proc`, guarded by getattr/hasattr).
- Validation: `PARROT_TEST_E2E=1 pytest …/test_up_detached_lifecycle.py` → 2 passed; `tests/unit/e2e/test_cli.py` → 40 passed; skipped without opt-in; ruff + black clean.
- Follow-up: `issue:0a04d048dab5` should be closed with this fix; the private-attribute detach is a pragmatic choice — a `subprocess.Popen`-based spawn would avoid it but would require rewriting the monkeypatched unit tests.
