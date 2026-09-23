# TASK-3669: Bound DocumentDb connect timeout and isolate integrations tests from real DocumentDB

**Feature**: FEAT-591 — speech_report pluggable TTS backends (fast-path)
**Spec**: `sdd/specs/speech-report-models.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:312c1988479b

---

## Context

Promoted from ledger issue `issue:312c1988479b` [critical] — "Full ai-parrot-integrations
pytest sweep hangs deterministically (merge-tier core escalation)". Every FEAT-591 task
(TASK-3619…3623) hit it at the merge-tier validation: the
`packages/ai-parrot-integrations/tests` sweep stalls at ~40–43% for its whole budget
(1200s / 2400s). It is not caused by FEAT-591's diff; it blocks FEAT-591's merge gate.

Root cause (verified 2026-09-23, diagnosed by /sdd-fix):

- `asyncdb.interfaces.abstract` sets `self._timeout = kwargs.get("timeout", 600)`. The
  asyncdb `mongo` driver then builds its Motor client with
  `serverSelectionTimeoutMS=self._timeout * 1000`, which is **10 minutes**.
- `parrot.interfaces.documentdb.DocumentDb._get_connection()` builds
  `AsyncDB(engine, params=params)` with no `timeout`, so it inherits the 600s default.
  Against an unreachable host (the dev `.env` points at `localhost:27017`, nothing
  listening) `async with DocumentDb()` blocked for >150s (measured, then killed).
  `AsyncDB("mongo", params=..., timeout=3)` raised `DriverError` after 3.0s (measured).
- Test path that hangs:
  `tests/integrations/telegram/test_oauth2_integration.py::TestHandleWebAppDataRoutes::test_handle_web_app_data_routes_to_strategy`
  → `TelegramAgentWrapper.handle_web_app_data` (wrapper.py:2296)
  → `_initialize_user_context` (wrapper.py:1385)
  → `rehydrate_user_mcp_servers` (mcp_commands.py:259)
  → `TelegramMCPPersistenceService.list` (mcp_persistence.py:178)
  → `DocumentDb.__aenter__` → `documentdb_connect` → asyncdb `mongo.connection()` ping.
  The test's `MagicMock` agent returns a non-`None` `tool_manager.clone()`, so MCP
  rehydration runs against the real DocumentDB.

This is also a production defect: a Telegram login blocks for up to 10 minutes when
DocumentDB is unreachable.

---

## Scope

- Make `DocumentDb._get_connection()` pass a bounded, configurable `timeout` to `AsyncDB`
  (`DOCUMENTDB_TIMEOUT`, fallback **30** seconds, pymongo's own default server-selection
  timeout).
- Add a package-level autouse fixture in `packages/ai-parrot-integrations/tests/conftest.py`
  that makes `DocumentDb.documentdb_connect` raise `ConnectionError` immediately, so no
  integrations test can reach a real DocumentDB by accident. Tests marked `live_vendor`
  are exempt.
- Write unit tests for both behaviours.

**NOT in scope**: changing `rehydrate_user_mcp_servers`, `_initialize_user_context`, or
any Telegram wrapper logic; editing the hanging test itself; pinning or patching
asyncdb; fixing the other, unrelated pre-existing failures in the sweep (list them in
the Completion Note instead).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/documentdb.py` | MODIFY | Pass bounded `timeout` to `AsyncDB` in `_get_connection` |
| `packages/ai-parrot/tests/interfaces/test_documentdb_timeout.py` | CREATE | Unit tests: default 30s, env override forwarded to the driver |
| `packages/ai-parrot-integrations/tests/conftest.py` | CREATE | Autouse DocumentDB network-isolation guard |
| `packages/ai-parrot-integrations/tests/test_documentdb_isolation.py` | CREATE | Asserts the guard makes `async with DocumentDb()` fail fast |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                      # verified: packages/ai-parrot/src/parrot/interfaces/documentdb.py:31
from navconfig import config, BASE_DIR           # verified: packages/ai-parrot/src/parrot/interfaces/documentdb.py:32
from parrot.interfaces.documentdb import DocumentDb  # verified: packages/ai-parrot/src/parrot/interfaces/documentdb.py:63
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/documentdb.py
class DocumentDb:                                     # line 63
    def __init__(self, max_retries: int = DEFAULT_MAX_RETRIES, ...)  # line 91
    @property
    def db(self) -> AsyncDB: ...                      # line 122 — lazily calls _get_connection()
    def _get_connection(self) -> AsyncDB: ...         # line 184 — reads config.get/getboolean, returns AsyncDB(engine, params=params) at line 228
    async def documentdb_connect(self) -> None: ...   # line 234 — awaits self.db.connection(); on failure raises ConnectionError
    async def __aenter__(self) -> "DocumentDb": ...   # line 299 — calls documentdb_connect()
    async def __aexit__(self, *args) -> None: ...     # line 304 — calls close()

# navconfig: config.getint(key, fallback=int) exists (verified: returns 30 for a missing key with fallback=30)
# asyncdb: AsyncDB(driver, **kwargs) returns the driver instance; driver._timeout = kwargs.get("timeout", 600)
#          (.venv/.../asyncdb/interfaces/abstract.py:18); mongo driver uses it at asyncdb/drivers/mongo.py:186,193
```

### Does NOT Exist
- ~~`DocumentDb(timeout=...)`~~ — `DocumentDb.__init__` has no timeout parameter; do not add one (config only).
- ~~`DOCUMENTDB_TIMEOUT` in any settings file~~ — new key; fallback only, do not add it to `.env`/`settings`.
- ~~`packages/ai-parrot-integrations/tests/conftest.py`~~ — does not exist yet (only `tests/integrations/telegram/conftest.py` does; do not edit that one).
- ~~`pytest-timeout`~~ — not installed; do not use `@pytest.mark.timeout`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/documentdb.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_documentdb_timeout.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/test_documentdb_isolation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/documentdb.py#DocumentDb",
    "sym:packages/ai-parrot/src/parrot/interfaces/documentdb.py#DocumentDb._get_connection",
    "sym:packages/ai-parrot/src/parrot/interfaces/documentdb.py#DocumentDb.documentdb_connect"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The timeout must reach the asyncdb driver as the `timeout` kwarg: that is the only input
  the mongo driver turns into `serverSelectionTimeoutMS`.
- The isolation guard must patch the **class attribute**
  `parrot.interfaces.documentdb.DocumentDb.documentdb_connect`, not the `DocumentDb` name
  in any importing module: tests that `patch("...mcp_persistence.DocumentDb")` then keep
  their mock and are unaffected.
- The guard is async and raises `ConnectionError` because that is exactly what the real
  `documentdb_connect` raises on failure, so production error handling
  (`rehydrate` logs and continues) is exercised as in an outage.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `_get_connection` to read `DOCUMENTDB_TIMEOUT` and pass `timeout=` to `AsyncDB` — *why*: removes the inherited 600s server-selection wait.
2. Create the integrations `tests/conftest.py` guard — *why*: unit tests must never block on a real network service.
3. Write both test files and run the Validation Commands — *why*: AC1–AC3.
4. Run the single previously-hanging test, then the full integrations sweep, and record timings — *why*: AC4–AC5.

### `packages/ai-parrot/src/parrot/interfaces/documentdb.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "engine = config.get('DOCUMENTDB_ENGINE', fallback='mongo')" packages/ai-parrot/src/parrot/interfaces/documentdb.py)
# AFTER — insert below `engine = config.get('DOCUMENTDB_ENGINE', fallback='mongo')` (verified: documentdb.py:209)
        # Server-selection/connect timeout in seconds. asyncdb defaults to 600s,
        # which blocks a caller for 10 minutes when DocumentDB is unreachable.
        timeout = config.getint('DOCUMENTDB_TIMEOUT', fallback=30)

# occurrences: 1 (verified: grep -c 'return AsyncDB(engine, params=params)' packages/ai-parrot/src/parrot/interfaces/documentdb.py)
# REPLACE `return AsyncDB(engine, params=params)` (verified: documentdb.py:228) with:
        return AsyncDB(engine, params=params, timeout=timeout)
```
**Why**: the driver reads `timeout` from kwargs, not `params`. 30s matches pymongo's
default, so a healthy deployment sees no behaviour change.

### `packages/ai-parrot-integrations/tests/conftest.py` (CREATE)
```python
"""Package-wide fixtures for ai-parrot-integrations tests.

Network isolation: no test may open a real DocumentDB connection. asyncdb's
mongo driver can block for minutes on an unreachable host, which hung the full
test sweep (ledger issue:312c1988479b).
"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_documentdb(request, monkeypatch):
    """Make ``DocumentDb.documentdb_connect`` fail fast with ``ConnectionError``.

    Tests marked ``live_vendor`` are exempt. Tests that patch the ``DocumentDb``
    name at its import site keep their own mock.
    """
    if request.node.get_closest_marker("live_vendor"):
        return
    # FILL IN: import DocumentDb lazily inside the fixture (so a missing optional dep
    #          never breaks collection) and monkeypatch.setattr the class attribute
    #          `documentdb_connect` with an `async def` that raises
    #          ConnectionError("DocumentDB access is disabled in unit tests") — bounded by
    #          Key Constraints (class attribute, ConnectionError).
```
**Why**: the fixture lives at package level so every test in this distribution is covered, not only the Telegram ones.

### `packages/ai-parrot/tests/interfaces/test_documentdb_timeout.py` (CREATE)
```python
"""DocumentDb forwards a bounded connect timeout to the asyncdb driver."""
from parrot.interfaces.documentdb import DocumentDb


def test_default_timeout_is_bounded(monkeypatch):
    """Without DOCUMENTDB_TIMEOUT the driver gets 30s, not asyncdb's 600s."""
    # FILL IN: make config.getint('DOCUMENTDB_TIMEOUT', ...) return its fallback
    #          (monkeypatch the `config` object used in parrot.interfaces.documentdb),
    #          build DocumentDb()._get_connection() and assert driver._timeout == 30.


def test_timeout_env_override(monkeypatch):
    """DOCUMENTDB_TIMEOUT overrides the default."""
    # FILL IN: same, returning 7; assert driver._timeout == 7.
```

### `packages/ai-parrot-integrations/tests/test_documentdb_isolation.py` (CREATE)
```python
"""The package conftest keeps tests off real DocumentDB."""
import time

import pytest

from parrot.interfaces.documentdb import DocumentDb


async def test_documentdb_connect_fails_fast():
    """``async with DocumentDb()`` raises ConnectionError immediately under the guard."""
    start = time.monotonic()
    with pytest.raises(ConnectionError):
        async with DocumentDb():
            pass
    # FILL IN: assert elapsed time < 1s — bounded by AC2.
```

### FILL IN checklist
- [ ] `conftest.py::_no_real_documentdb` — class-attribute patch raising `ConnectionError`; live_vendor exempt
- [ ] `test_documentdb_timeout.py` — both tests patch config without touching the real `.env`
- [ ] `test_documentdb_isolation.py` — elapsed-time assertion

---

## Acceptance Criteria

- [ ] AC1: `DocumentDb()._get_connection()._timeout == 30` by default and follows `DOCUMENTDB_TIMEOUT`.
- [ ] AC2: under the integrations conftest, `async with DocumentDb()` raises `ConnectionError` in < 1s.
- [ ] AC3: `test_mcp_commands.py` (which mocks `DocumentDb` at its import site) still passes.
- [ ] AC4: `test_oauth2_integration.py::TestHandleWebAppDataRoutes::test_handle_web_app_data_routes_to_strategy` completes in < 10s.
- [ ] AC5: `pytest packages/ai-parrot-integrations/tests` runs to completion (no stall); pre-existing unrelated failures are listed in the Completion Note.
- [ ] `ruff check` clean on all four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_documentdb_timeout.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_documentdb_isolation.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py -q`

---

## Agent Instructions

1. Read the spec and this task's Context (the diagnosis is already done — do not re-derive it).
2. Verify the Codebase Contract anchors (`grep -c`) before editing.
3. Implement from the blueprint, completing every `# FILL IN:`.
4. Run the Validation Commands, then AC4/AC5.
5. Move this file to `sdd/tasks/completed/`, set the index entry to `done`, and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
