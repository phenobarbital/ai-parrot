# TASK-4981: End-to-end tests: login → connect → tool call, stdio auth-required, O365 device via connect

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4976, TASK-4977, TASK-4978, TASK-4971
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests: prove the pieces work together against fakes — a fake navigator-auth AS and a fake parrot
server (aiohttp test apps). `test_cli_devicecode_e2e.py` is rewritten from the removed `O365_PRINCIPAL` bootstrap to the
`parrot connect o365 --device` path; its WorkIQ OBO interop assertion moves to the S-3a backlog (spec §7) — file a
ledger issue for it instead of deleting it silently.

---

## Scope

- `packages/ai-parrot/tests/integration/test_cli_connections_e2e.py`: `test_e2e_cli_login_connect_tool_call` (login →
  connect (poll) → standalone agent tool with `credential_provider="fake"` → server `/token` called once; second call is
  a cache hit).
- `tests/mcp/test_stdio_auth_required_e2e.py`: `parrot mcp-local` subprocess with a login but no connection →
  `tools/call` returns the auth-required envelope; stdout carries only JSON-RPC frames.
- Rewrite `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py`: O365 device grant via `run_connect(...,
  device=True)` against a fake provider; token persisted server-side.
- `wikitoolkit ledger open` one issue for the moved WorkIQ OBO assertion (`--discovered-from spec:FEAT-774`).

**NOT in scope**: production code changes — if an e2e test exposes a bug, fix it only if it is a one-line fix in a file this feature touched, otherwise file a ledger issue and mark the test `xfail(strict=True)` with the issue id.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_cli_connections_e2e.py` | CREATE | login→connect→tool e2e |
| `tests/mcp/test_stdio_auth_required_e2e.py` | CREATE | stdio envelope e2e |
| `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` | MODIFY | rewrite to connect --device |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.cli.login import LoginRecord, LoginStore, login                 # TASK-4968
from parrot.cli.connect import run_connect                                  # TASK-4977
from parrot.auth.oauth2.remote_client import ServerConnectionsClient        # TASK-4972
from parrot.auth.oauth2.local_cache import build_cli_broker, open_connection_cache   # TASK-4973
from parrot.tools.abstract import AbstractTool, ToolResult, current_credential   # abstract.py:45, :251
```

### Existing Signatures to Use
```python
# Existing e2e patterns:
#   tests/mcp/test_toolkit_server.py — in-process toolkit server tests (no subprocess)
#   packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py (208 lines) — current O365 device + WorkIQ OBO tests;
#     after TASK-4978 it no longer imports parrot.cli.identity bootstrap helpers
#   FEAT-485 e2e (TASK-2650) spawned `parrot mcp-local` with a pure-stdout assertion — find it with
#     `grep -rln "mcp-local" tests/mcp packages/ai-parrot/tests/mcp` and reuse its subprocess helper
# Server API shapes: see TASK-4972 signatures; device endpoints: TASK-4971
```

### Does NOT Exist
- ~~a shared conftest fixture for the fake AS / fake server~~ — define fixtures locally in each test file (a shared
  conftest change would make the task exclusive).
- ~~WorkIQ OBO interop in S-4~~ — moved to S-3a; do not keep a failing assertion.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/integration/test_cli_connections_e2e.py",
      "action": "CREATE"
    },
    {
      "path": "tests/mcp/test_stdio_auth_required_e2e.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Isolate every test: `HOME`, `PARROT_LOGIN_FILE` → `tmp_path`; patch `webbrowser.open`; patch `asyncio.sleep` in poll
  loops.
- Fake parrot server: `/api/v1/connections/me`, `/{provider}` status, `/{provider}/start`, `/{provider}/token`
  (counts calls), `/{provider}/complete`, `/device/start`, `/device/poll`.
- The stdio subprocess test needs a toolkit config: write `.parrot/mcp-toolkits.yaml` in `tmp_path` pointing at a small
  credentialed stub toolkit module placed on `PYTHONPATH`; the fake server URL goes in the login file. Mark it
  `@pytest.mark.integration` if the repo uses that marker for subprocess tests (check `pyproject.toml` markers first).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write the login→connect→tool e2e — *why*: proves G3 cache-hit semantics.
2. Write the stdio subprocess e2e — *why*: AC-8 stdout purity across a real process.
3. Rewrite `test_cli_devicecode_e2e.py` and file the OBO ledger issue — *why*: spec §7 hard cut.
4. Run the validation commands.

### `packages/ai-parrot/tests/integration/test_cli_connections_e2e.py` (CREATE)
```python
"""E2E: parrot login → parrot connect → credentialed tool (FEAT-774 §4)."""
import pytest


@pytest.fixture
async def fake_parrot_server(aiohttp_server):
    # FILL IN: aiohttp app with the M3 routes + GET /{provider}; records /token calls
    ...


async def test_e2e_cli_login_connect_tool_call(fake_parrot_server, tmp_path, monkeypatch):
    # FILL IN: write a 0600 login (or run `login` against a fake AS); run_connect("fake", poll path); build_cli_broker;
    #          AbstractTool(credential_provider="fake").execute(_broker=..., _cred_channel="cli", _cred_user_id=...) twice →
    #          current_credential() == token both times; server /token called exactly once
    ...
```

### `tests/mcp/test_stdio_auth_required_e2e.py` (CREATE)
```python
"""E2E: parrot mcp-local with a login but no connection returns the auth-required envelope (AC-8)."""
import pytest


def test_e2e_stdio_toolkit_auth_required(tmp_path):
    # FILL IN: spawn `python -m parrot` / `parrot mcp-local fake` (reuse the FEAT-485 subprocess helper) with HOME and
    #          PARROT_LOGIN_FILE in tmp; initialize + tools/call → result.isError, result.structuredContent.provider == "fake";
    #          every stdout line parses as JSON-RPC
    ...
```

### `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` (MODIFY — rewrite)
```python
# FILL IN: replace the device-code tests with `test_e2e_cli_devicecode_e2e`: run_connect(..., provider="o365", device=True)
#          against a fake server whose /device/poll returns pending → completed; assert the CLI never sees device_code and
#          the token lands in the cache. Remove the WorkIQ OBO test and open a ledger issue:
#          wikitoolkit ledger open --kind tech_debt --severity minor --discovered-from spec:FEAT-774 \
#            --title "Re-home WorkIQ OBO interop assertion (moved from test_cli_devicecode_e2e)" --body "..."
```

### FILL IN checklist
- [ ] fake AS / fake parrot server fixtures
- [ ] the three e2e test bodies
- [ ] ledger issue id recorded in the Completion Note

---

## Acceptance Criteria

- [ ] Login → connect (poll) → credentialed tool resolves from the cache; `/token` is called once for two calls
- [ ] A `parrot mcp-local` process with a login but no connection returns the auth-required envelope; stdout is JSON-RPC only (AC-8)
- [ ] `test_cli_devicecode_e2e.py` exercises `parrot connect o365 --device`; the OBO assertion is tracked by a ledger issue
- [ ] `ruff check` clean on the test files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/integration/test_cli_connections_e2e.py -q`
- `pytest tests/mcp/test_stdio_auth_required_e2e.py -q`
- `pytest packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py -q`

---

## Test Specification

```python
# see the blueprint blocks
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-sol (codex) (1 attempt), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Implemented as specified; task tests green. Merge-tier: only sandbox-limited tests/cli/test_session.py::test_stream_closed_in_turn_task_after_final_message fails (read-only ~/.parrot/cli).
