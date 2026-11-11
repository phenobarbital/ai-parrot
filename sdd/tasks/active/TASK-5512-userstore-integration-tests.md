# TASK-5512: Integration tests — no MongoDB on the request path, copy round-trip, centralised vault access

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5497, TASK-5498, TASK-5499, TASK-5500, TASK-5501, TASK-5503, TASK-5504, TASK-5505, TASK-5506, TASK-5509
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and AC5, AC8, AC11. The per-module tasks test each store in isolation. This task
proves the feature end to end: (1) the per-request paths that produced the 2026-11-10 log — OAuth toolkit
hydration, toolkit overrides, MCP restore — make **zero** DocumentDB connection attempts with all stores on
Redis; (2) documents for all eight collections copied from DocumentDB read back through their services;
(3) no module outside the allowed set touches `user_credentials`.

---

## Scope

- `test_agenttalk_without_mongodb.py`: `PARROT_USER_STORE=redis`, `DOCUMENTDB_HOSTNAME` set to a closed port,
  `DocumentDb.documentdb_connect` patched to fail the test; run `UserObjectsHandler._hydrate_oauth_toolkits`,
  `AgentTalk._apply_user_toolkit_overrides` and `AgentTalk._restore_user_mcp_servers` with stubbed agents/sessions.
- `test_userstore_copy_roundtrip.py`: seed a fake DocumentDB with one document per collection (sealed with a test
  keyring where applicable), run `copy_to_redis`, read each back through its service with `redis` switches.
- `test_vault_access_centralised.py`: scan `packages/*/src` for the literal `"user_credentials"` and
  `VAULT_CRED_COLLECTION`; fail on any module outside the allow-list.

**NOT in scope**: changing production code. If a test exposes a defect, record it in the Completion Note and
open a ledger issue (`wikitoolkit ledger open … --discovered-from spec:FEAT-878`) — do not patch other tasks' files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/unit/test_agenttalk_without_mongodb.py` | CREATE | AC8 |
| `packages/ai-parrot-server/tests/unit/test_userstore_copy_roundtrip.py` | CREATE | AC11 across services |
| `packages/ai-parrot-server/tests/unit/test_vault_access_centralised.py` | CREATE | AC5 grep test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.user_objects import UserObjectsHandler        # verified: handlers/user_objects.py:25
from parrot.handlers.agent import AgentTalk                         # verified: handlers/agent.py:133
from parrot.interfaces.documentdb import DocumentDb                 # verified: interfaces/documentdb.py:65
from parrot.userstore.copy import copy_to_redis                     # TASK-5509
from parrot.userstore.testing import redis_test_settings            # TASK-5496
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride   # verified: toolkit_persistence.py:17,38
from parrot.handlers.mcp_persistence import MCPPersistenceService   # verified: mcp_persistence.py
from parrot.handlers.dashboard_store import get_dashboard_store     # TASK-5506
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/user_objects.py
class UserObjectsHandler:                                                          # line 25
    async def _hydrate_oauth_toolkits(self, user_id: str, agent_id: str, session_key: str,
                                      request_session: Any) -> Optional[ToolManager]:  # line 202 — calls list_users_integrations (line 224)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView):                                                         # line 133
    async def _apply_user_toolkit_overrides(self, agent: AbstractBot, request_session: Any,
                                            tool_manager: Optional[ToolManager]) -> Optional[ToolManager]:  # line 1070 — never raises
    async def _restore_user_mcp_servers(self, tool_manager: Any, request_session: Any, agent_name: str) -> None:  # line 1127

# packages/ai-parrot/src/parrot/interfaces/documentdb.py
class DocumentDb:
    async def documentdb_connect(self) -> None:                                    # line 237 — patch this to fail the test

# Implementations the round-trip test reads through (created by the dependencies):
#   packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py            (TASK-5500) via list_users_integrations
#   packages/ai-parrot/src/parrot/auth/broker/byok_redis.py                   (TASK-5501) via _UserLLMKeyResolver
#   packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence_redis.py (TASK-5505) via TelegramMCPPersistenceService
#   packages/ai-parrot/src/parrot/security/vault_store_redis.py               (TASK-5497) via retrieve_vault_credential
#   packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence_redis.py (TASK-5503) via ToolkitConfigService
#   packages/ai-parrot-server/src/parrot/handlers/mcp_persistence_redis.py     (TASK-5504) via MCPPersistenceService
```

### Does NOT Exist
- ~~A live MongoDB in CI~~ — the "without MongoDB" test asserts no connection attempt; it never connects.
- ~~`fakeredis`~~ — Redis tests use db 15 via `redis_test_settings`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/unit/test_agenttalk_without_mongodb.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/unit/test_userstore_copy_roundtrip.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/unit/test_vault_access_centralised.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/user_objects.py#UserObjectsHandler._hydrate_oauth_toolkits",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._apply_user_toolkit_overrides",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._restore_user_mcp_servers",
    "sym:packages/ai-parrot/src/parrot/interfaces/documentdb.py#DocumentDb"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Build handler instances without a live HTTP request: `AgentTalk.__new__(AgentTalk)` + set `logger` and the
  attributes each method reads (inspect the method bodies first); same for `UserObjectsHandler`.
- AC5 allow-list (exact repo-relative paths): `packages/ai-parrot/src/parrot/security/vault_utils.py`,
  `packages/ai-parrot/src/parrot/security/vault_store_redis.py`, `packages/ai-parrot/src/parrot/security/__init__.py`
  (re-export), `packages/ai-parrot/src/parrot/handlers/vault_utils.py` (legacy re-export), `packages/ai-parrot/src/parrot/vault_targets.py`,
  `packages/ai-parrot/src/parrot/userstore/collections.py`, `packages/ai-parrot/src/parrot/userstore/settings.py`,
  `packages/ai-parrot/src/parrot/userstore/copy.py`, the Studio storage modules `vault_store.py`, `vault_targets.py`, `secrets_copy.py`
  under `packages/ai-parrot-server/src/parrot/handlers/studio/storage/`, and `packages/ai-parrot-server/src/parrot/handlers/credentials.py`
  (its `COLLECTION` constant is kept for compatibility, but the file must not contain `DocumentDb`).
  Re-derive the list with `grep -rln '"user_credentials"\|VAULT_CRED_COLLECTION' packages/*/src` once all dependencies are done;
  anything else is a finding.

---

## Implementation Blueprint

### Steps (in order)
1. Write the AC5 grep test first — *why*: cheapest, and it tells you whether TASK-5498/5499 left a bypass.
2. Write the "without MongoDB" test — *why*: AC8 is the user-visible goal (no 20 s stall).
3. Write the copy round-trip test.

### `packages/ai-parrot-server/tests/unit/test_vault_access_centralised.py` (CREATE)
```python
"""AC5 (FEAT-878): only vault_utils and the storage plumbing may name the user_credentials collection."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ALLOWED = {
    # FILL IN: the exact allow-list from Implementation Notes
}
NEEDLES = ('"user_credentials"', "VAULT_CRED_COLLECTION")


def test_user_credentials_access_is_centralised():
    offenders = []
    for path in REPO.glob("packages/*/src/**/*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(n in text for n in NEEDLES) and str(path.relative_to(REPO)) not in ALLOWED:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_handlers_do_not_import_documentdb():
    for rel in ("packages/ai-parrot-server/src/parrot/handlers/credentials.py",
                "packages/ai-parrot-server/src/parrot/handlers/agent.py"):
        assert "DocumentDb" not in (REPO / rel).read_text(encoding="utf-8")
```

### `packages/ai-parrot-server/tests/unit/test_agenttalk_without_mongodb.py` (CREATE)
```python
"""AC8 (FEAT-878): with every store on Redis, the per-request user-store paths never contact DocumentDB."""
import pytest

from parrot.interfaces.documentdb import DocumentDb
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def no_mongo(monkeypatch):
    monkeypatch.setenv("PARROT_USER_STORE", "redis")
    monkeypatch.setenv("DOCUMENTDB_HOSTNAME", "127.0.0.1")
    monkeypatch.setenv("DOCUMENTDB_PORT", "1")

    async def _forbidden(self):
        raise AssertionError("DocumentDB contacted with PARROT_USER_STORE=redis")

    monkeypatch.setattr(DocumentDb, "documentdb_connect", _forbidden)
    async with redis_test_settings(monkeypatch):
        yield


async def test_oauth_hydration_without_mongodb(no_mongo): ...      # returns None (no connections) without AssertionError
async def test_toolkit_overrides_without_mongodb(no_mongo): ...    # seed one override via ToolkitConfigService; applied
async def test_mcp_restore_without_mongodb(no_mongo): ...          # seed one MCP config + vault secret; restore registers it
# FILL IN: stub agents/sessions/tool managers minimally; assert the expected effect, not just "no exception".
```

### `packages/ai-parrot-server/tests/unit/test_userstore_copy_roundtrip.py` (CREATE)
```python
"""AC11 (FEAT-878): DocumentDB documents for all 8 collections, copied to Redis, read back through their services."""
import pytest

from parrot.userstore import copy as copy_mod
from parrot.userstore.testing import redis_test_settings


async def test_copy_then_read_through_services(monkeypatch): ...
# FILL IN: fake DocumentDb (as in packages/ai-parrot/tests/userstore/test_copy.py) seeded with one document per collection —
#   seal user_credentials / user_llm_keys with the test keyring exactly as vault_utils / the BYOK handler do; run
#   copy_to_redis(); then read through vault_utils.retrieve_vault_credential, _UserLLMKeyResolver, ToolkitConfigService,
#   MCPPersistenceService, TelegramMCPPersistenceService (skip with pytest.importorskip if ai-parrot-integrations is absent),
#   list_users_integrations, get_dashboard_store().get_dashboard / list_tabs.
```

### FILL IN checklist
- [ ] AC5 allow-list (re-derived after dependencies land)
- [ ] three no-Mongo tests with real assertions
- [ ] copy round-trip across all eight collections

---

## Acceptance Criteria

- [ ] AC5 grep test passes; `credentials.py` and `agent.py` contain no `DocumentDb`
- [ ] AC8: hydration, overrides and MCP restore run with zero DocumentDB connection attempts
- [ ] AC11: every collection round-trips; sealed values decrypt with the same keyring
- [ ] `ruff check` clean on the three files

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_vault_access_centralised.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_agenttalk_without_mongodb.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_userstore_copy_roundtrip.py -q`

---

## Test Specification

See the three blueprint blocks above; every test asserts the behaviour named in its docstring.

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§4 Integration Tests, AC5/AC8/AC11)
3. **Check dependencies** — all ten listed tasks must be `done`
4. **Verify the Codebase Contract** — re-read each method you stub around
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5512 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
