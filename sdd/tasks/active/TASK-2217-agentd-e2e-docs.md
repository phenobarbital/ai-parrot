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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
