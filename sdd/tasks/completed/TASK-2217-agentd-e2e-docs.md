# TASK-2217: End-to-end integration tests + documentation

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2216
**Assigned-to**: unassigned

---

## Context

Spec Module 10 — cross-module integration tests exercising the REAL stack
(daemon + client + proxy + CLI together, EchoAgent, tmp sockets, no
Postgres/Redis) and the user documentation.

---

## Scope

- Integration tests in `packages/ai-parrot-integrations/tests/agentd/test_e2e.py`:
  - `test_chat_send_and_stream_end_to_end` — real AgentDaemon + real
    AgentDaemonClient (not scripted fakes).
  - `test_two_clients_isolated_sessions` — concurrent connections, distinct
    histories (EchoAgent records per-session_id).
  - `test_scheduler_interval_job_fires_and_event_emitted` — real APScheduler
    MemoryJobStore path end-to-end with a subscribed client.
  - `test_graceful_shutdown_sigterm` — spawn daemon, send SIGTERM, assert
    event.shutdown received + socket removed + exit 0.
  - `test_ask_oneshot_exit_codes` — CliRunner against a live daemon.
  - `test_mcp_stdio_ask_agent` — run_mcp_proxy handlers against a live
    daemon (initialize → tools/list → tools/call ask_agent).
  - `test_no_aiohttp_without_server_pkg` — with scheduler import blocked,
    assert `"aiohttp" not in sys.modules` after full daemon startup
    (spec Acceptance Criterion 1) — run in a subprocess for module isolation.
- Documentation `docs/agentd.md`:
  - Quickstart (`parrot serve module:Agent --name x`, `parrot attach x`).
  - YAML schema reference (all `AgentServiceConfig` fields + defaults).
  - systemd deployment (install-service, user vs system, Type=notify,
    journald), supervisord snippet.
  - Scheduler modes matrix (nothing / dsn / dsn+redis) + decorator example.
  - MCP registration: `claude mcp add mi-agente -- parrot mcp-serve mi-agente`,
    tool list, `exposed_methods` gating warning.
  - Protocol appendix: method table + error codes (from spec §2).
- Final sweep: run the ENTIRE agentd suite + touched-package suites; fix
  small integration bugs found (report anything structural instead of
  redesigning).

**NOT in scope**: new features, protocol changes, performance work.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/agentd/test_e2e.py` | CREATE | Cross-module integration tests |
| `packages/ai-parrot-integrations/tests/agentd/conftest.py` | CREATE/MODIFY | Shared `echo_daemon`, `agentd_yaml` fixtures (promote from earlier tasks if duplicated) |
| `docs/agentd.md` | CREATE | User documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Everything below exists ONLY after TASK-2208..2216 are completed — verify each:
from parrot.integrations.agentd.config import AgentServiceConfig
from parrot.integrations.agentd.service import AgentDaemon
from parrot.integrations.agentd.client import AgentDaemonClient
from parrot.integrations.agentd.mcp_server import run_mcp_proxy
from parrot.integrations.agentd import cli as agentd_cli
from tests.agentd.fakes import EchoAgent   # relative to integrations tests dir (TASK-2210)
```

### Existing Signatures to Use
```python
# Read the AS-BUILT modules — earlier tasks may have deviated in small ways;
# this task tests reality, not the spec's sketches. Verify:
#  - exact StreamEvent shape (client.py)
#  - daemon.status payload keys (service.py)
#  - CLI command names registered in core (cli/__init__.py)
```

### Does NOT Exist
- ~~Postgres/Redis in CI~~ — tests MUST NOT require external infra; MemoryJobStore only.
- ~~pexpect/pty-based REPL tests~~ — do not test the interactive prompt_toolkit loop; attach wiring was smoke-tested in TASK-2216.
- ~~docs/agentd.md~~ — created here.

---

## Implementation Notes

### Key Constraints
- Mark slow/scheduler tests with `@pytest.mark.timeout`-style bounds if the
  repo uses pytest-timeout (verify in pyproject before assuming; else use
  `asyncio.wait_for`).
- The SIGTERM test needs a real subprocess (`sys.executable -m` a tiny
  runner script or `parrot serve` with the fixture YAML) — assert exit
  code 0 within `shutdown_grace`.
- Docs in the same style as existing `docs/*.md` — skim two for tone before
  writing.

### References in Codebase
- Spec §4 Integration Tests table + §5 Acceptance Criteria — this task
  closes them all.

---

## Acceptance Criteria

- [ ] All 7 integration tests above pass without external infra.
- [ ] Spec §5 checklist fully satisfiable (each criterion mapped to a passing test or doc section — note the mapping in the Completion Note).
- [ ] `docs/agentd.md` covers quickstart, YAML, systemd, supervisord, scheduler matrix, MCP, protocol appendix.
- [ ] Full suite green: `pytest packages/ai-parrot-integrations/tests/agentd/ -v` and `pytest packages/ai-parrot-server/tests/scheduler/ -v`.
- [ ] `ruff check` clean on all agentd files.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_e2e.py
import pytest

@pytest.mark.asyncio
class TestEndToEnd:
    async def test_chat_send_and_stream_end_to_end(self, echo_daemon): ...
    async def test_two_clients_isolated_sessions(self, echo_daemon): ...
    async def test_scheduler_interval_job_fires_and_event_emitted(self, tmp_path): ...
    async def test_graceful_shutdown_sigterm(self, tmp_path): ...
    async def test_mcp_stdio_ask_agent(self, echo_daemon): ...

class TestCliE2E:
    def test_ask_oneshot_exit_codes(self, echo_daemon): ...

def test_no_aiohttp_without_server_pkg(tmp_path): ...  # subprocess-isolated
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2208..2216 ALL in `sdd/tasks/completed/`;
3. verify contract against AS-BUILT code; 4. index → in-progress; 5. implement;
6. verify criteria (map spec §5 → evidence); 7. move to completed/; 8. index → done;
9. Completion Note with the criterion→test mapping.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-16
**Notes**: Created `conftest.py` (promoted `echo_daemon`/`agentd_yaml`
fixtures + `run_daemon`/`stop_daemon`/`wait_for_socket` helpers — kept
`test_service.py`'s own local `echo_daemon` fixture untouched, since a
test-module-local fixture shadows a conftest one of the same name with no
conflict, and modifying `test_service.py` wasn't in this task's file list)
and `test_e2e.py` with all 7 cross-module integration tests exercising the
REAL stack (no scripted fakes): `chat.send`/stream roundtrip, two
concurrent clients with isolated per-`session_id` history
(`_TrackingEchoAgent`, module-level so it resolves via `importlib`), a
real APScheduler `MemoryJobStore` interval job firing + `event.job_executed`
reaching a subscribed `AgentDaemonClient` (`_IntervalEchoAgent`, same
skip-if-`ai-parrot-server`-absent pattern as TASK-2212), a real subprocess
SIGTERM graceful-shutdown test (`parrot serve` via `asyncio.create_subprocess_exec`,
exit 0 + socket removed), `run_mcp_proxy`'s handler pieces driven directly
against a real daemon, a CliRunner `parrot ask` end-to-end test (also via
subprocess — see the design-fix note below), and a subprocess-isolated
`sys.modules["parrot.scheduler.manager"] = None` test asserting `"aiohttp"
not in sys.modules` for real (unlike TASK-2212's necessary AST substitute,
a genuinely fresh subprocess makes this literal check meaningful again).
Wrote `docs/agentd.md`: quickstart, full `AgentServiceConfig` field
reference, systemd (user + `--system` print-only) + supervisord, a
scheduler-modes matrix with a decorator example, MCP registration +
`exposed_methods` gating warning, and a protocol appendix (method table +
error codes) — skimmed `bot-cleanup-lifecycle.md` for tone/structure first.

**Design fix found (documented, not a silent workaround)**: the original
plan for `test_ask_oneshot_exit_codes` ran a live `AgentDaemon` in a
background thread so a synchronous `CliRunner.invoke()` could exercise it
without an `asyncio.run()`-inside-a-running-loop conflict. This hung
every run: `AgentDaemon._install_signal_handlers()` calls
`loop.add_signal_handler()`, which raises `RuntimeError: set_wakeup_fd
only works in main thread of the main interpreter` when the daemon's loop
lives on a non-main thread — that `RuntimeError` isn't a `NotImplementedError`,
so it wasn't caught, crashing the daemon's `run()` task silently inside
the thread right after the socket was already bound, leaving a dead
listener the CLI's `ask` could connect to but never get a response from
(the actual hang). Fixed by switching this test to a real subprocess (same
technique as the SIGTERM test) instead of a thread — no daemon-code change
was needed or made; this is a testing-approach fix, not a product bug (a
real `parrot serve` process always runs in ITS OWN main thread).

**Spec §5 acceptance criteria → evidence mapping**:
1. No aiohttp in daemon path → `test_no_aiohttp_without_server_pkg` (subprocess) + `TestNoAiohttp` (TASK-2212, AST-based).
2. Headless scheduler (no DB/Redis) + DSN path exercised → `test_scheduler_interval_job_fires_and_event_emitted` (e2e) + `TestStartHeadless` (TASK-2209).
3. Web-server scheduler behaviour unchanged → `packages/ai-parrot-server/tests/scheduler/` (9 tests, unmodified, still green).
4. `parrot attach` reuses `AgentREPL` + daemon slash commands → `TestSlashCommands`/`TestProxy` (TASK-2214); interactive prompt loop itself intentionally NOT tested (out of scope, per this task's contract).
5. `parrot ask` pipe-safe → `test_ask_oneshot_exit_codes` (e2e, real subprocess) + `TestAsk` (TASK-2216).
6. MCP proxy tool gating → `test_mcp_stdio_ask_agent` (e2e) + `TestToolMatrix` (TASK-2215).
7. Socket `0600`/dir `0700`, stale/already-running → `TestServer::test_permissions/test_stale_socket_reboot/test_live_socket_refuses` (TASK-2211).
8. SIGTERM graceful, bounded by `shutdown_grace` → `test_graceful_shutdown_sigterm` (e2e, real subprocess) + `TestDegradation::test_sigterm_graceful` (TASK-2212, in-process).
9. `install-service` valid unit, `Type=notify`/degrades → `TestInstallService` (TASK-2216) + `TestSdNotify` (TASK-2212).
10. Core CLI degrades with actionable message → `TestCoreRegistration::test_missing_module_message` (TASK-2216).
11. All unit + integration tests pass → 80/80 in `agentd/`, 9/9 in `ai-parrot-server/tests/scheduler/`.
12. `docs/agentd.md` → this task.
13. No breaking changes to existing public API → all pre-existing suites (core CLI, scheduler) verified green throughout the feature; every cross-task deviation was additive-only.

Final sweep: full `agentd/` suite 80/80, `ai-parrot-server/tests/scheduler/`
9/9, core CLI 49/49 (all run individually — a `tests.conftest` module-name
collision when combining `ai-parrot` and `ai-parrot-server` test roots in
ONE invocation is a pre-existing test-infra quirk, unrelated to this
feature). `ruff check` clean across every agentd file.

**Deviations from spec**: none.
