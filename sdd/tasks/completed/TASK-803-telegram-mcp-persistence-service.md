# TASK-803: Telegram MCP Persistence Service

**Feature**: FEAT-113 — Vault-Backed Credentials for Telegram /add_mcp
**Spec**: `sdd/specs/mcp-command-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the new `mcp_persistence.py` module inside
`parrot/integrations/telegram/`, implementing the Pydantic data models
(`TelegramMCPPublicParams`, `UserTelegramMCPConfig`) and the
`TelegramMCPPersistenceService` CRUD service.

This is the foundation layer for the entire FEAT-113 refactor. Modules 2-3
(splitter, rewritten handlers) depend on the models defined here. The service
mirrors the pattern of `MCPPersistenceService` in
`parrot/handlers/mcp_persistence.py` but is scoped to the Telegram `/add_mcp`
free-form flow (no `agent_id`, dedicated collection `telegram_user_mcp_configs`).

Implements **Module 1** of the spec (§3).

---

## Scope

- Create `packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py`.
- Define `TelegramMCPPublicParams` (Pydantic v2 `BaseModel`) with fields:
  `name`, `url`, `transport`, `description`, `auth_scheme`, `api_key_header`,
  `use_bearer_prefix`, `headers`, `allowed_tools`, `blocked_tools`.
- Define `UserTelegramMCPConfig` (Pydantic v2 `BaseModel`) with fields:
  `user_id`, `name`, `params: TelegramMCPPublicParams`,
  `vault_credential_name`, `active`, `created_at`, `updated_at`.
- Implement `TelegramMCPPersistenceService` class with:
  - `COLLECTION: str = "telegram_user_mcp_configs"` class attribute.
  - `async def save(self, user_id, name, params, vault_credential_name) -> None` — upsert.
  - `async def list(self, user_id) -> List[UserTelegramMCPConfig]` — active only.
  - `async def read_one(self, user_id, name) -> Optional[UserTelegramMCPConfig]`.
  - `async def remove(self, user_id, name) -> bool` — soft-delete (`active=False`).
- Follow the exact upsert + soft-delete pattern of `MCPPersistenceService`.

**NOT in scope**: The `_split_secret_and_public` helper, command handler rewrites,
wrapper changes, or tests (those are TASK-804 through TASK-807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py` | CREATE | Data models + TelegramMCPPersistenceService |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/handlers/mcp_persistence.py:19-27 — pattern to mirror
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional
from navconfig.logging import logging
from parrot.interfaces.documentdb import DocumentDb

# Use standard logging (not navconfig) if navconfig is not available in the new module.
# mcp_commands.py already uses standard logging — be consistent:
import logging
logger = logging.getLogger(__name__)
```

### Existing Signatures to Use

```python
# parrot/handlers/mcp_persistence.py:84-85 — upsert pattern (COPY EXACTLY)
async with DocumentDb() as db:
    await db.update_one(COLLECTION, query, update_data, upsert=True)

# parrot/handlers/mcp_persistence.py:117-118 — read-all pattern
async with DocumentDb() as db:
    docs = await db.read(COLLECTION, query)

# parrot/handlers/mcp_persistence.py:163 — read-one pattern
async with DocumentDb() as db:
    existing = await db.read_one(COLLECTION, query)

# Strip _id before parsing into Pydantic (mcp_persistence.py:124):
doc.pop("_id", None)
configs.append(UserMCPServerConfig(**doc))

# MCPPersistenceService soft-delete pattern (mcp_persistence.py:136-190):
# Sets active=False + updated_at via update_one. Returns True/False based on existence.
```

### Does NOT Exist

- ~~`DocumentDb.upsert()`~~ — use `db.update_one(..., upsert=True)` instead.
- ~~`DocumentDb.soft_delete()`~~ — no such method; update the document manually.
- ~~`TelegramMCPPersistenceService.get()`~~ — the method is named `read_one`.
- ~~`TelegramMCPPersistenceService.delete()`~~ — the method is named `remove` (soft).
- ~~`UserTelegramMCPConfig.agent_id`~~ — this model has no `agent_id`; scoping is by `(user_id, name)`.
- ~~`parrot.interfaces.VaultInterface`~~ — does not exist; Vault access is via `vault_utils` functions.

---

## Implementation Notes

### Pattern to Follow

```python
# Mirror MCPPersistenceService exactly. Key differences vs that service:
# - compound key: (user_id, name) instead of (user_id, agent_id, server_name)
# - collection: "telegram_user_mcp_configs" instead of "user_mcp_configs"
# - params field stores TelegramMCPPublicParams (Pydantic model, dump to dict on save)

class TelegramMCPPersistenceService:
    COLLECTION: str = "telegram_user_mcp_configs"

    async def save(
        self,
        user_id: str,
        name: str,
        params: TelegramMCPPublicParams,
        vault_credential_name: Optional[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        query = {"user_id": user_id, "name": name}
        update_data = {
            "$set": {
                "params": params.model_dump(),
                "vault_credential_name": vault_credential_name,
                "active": True,
                "updated_at": now,
            },
            "$setOnInsert": {
                "user_id": user_id,
                "name": name,
                "created_at": now,
            },
        }
        async with DocumentDb() as db:
            await db.update_one(self.COLLECTION, query, update_data, upsert=True)
```

### Key Constraints

- Pydantic v2 (`BaseModel` + `Field`). Use `model_dump()` (not `.dict()`).
- `params` is stored as a plain dict in DocumentDB (call `params.model_dump()` on save).
- `list()` must filter `active=True` (only return active configs).
- `remove()` sets `active=False` + updates `updated_at`; returns `True` if doc existed.
- Logging: module-level `logger = logging.getLogger(__name__)`. Log only `user_id` and `name`, never secrets.
- Use `from __future__ import annotations` at top.

### References in Codebase

- `parrot/handlers/mcp_persistence.py` — exact pattern to follow (read this file completely before implementing).
- `packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py` — this file will import from the new module.

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py` created.
- [ ] `TelegramMCPPublicParams` and `UserTelegramMCPConfig` are valid Pydantic v2 models importable from the new module.
- [ ] `TelegramMCPPersistenceService.save` performs an upsert on `telegram_user_mcp_configs`.
- [ ] `TelegramMCPPersistenceService.list` returns only `active=True` docs as `UserTelegramMCPConfig` instances.
- [ ] `TelegramMCPPersistenceService.read_one` returns `None` for missing or inactive docs.
- [ ] `TelegramMCPPersistenceService.remove` soft-deletes (sets `active=False`) and returns `True` if found.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py`

---

## Test Specification

Tests are written in TASK-807. However, a quick smoke check:

```python
# packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py
# (partial — full test suite in TASK-807)
from parrot.integrations.telegram.mcp_persistence import (
    TelegramMCPPublicParams,
    UserTelegramMCPConfig,
    TelegramMCPPersistenceService,
)

def test_import():
    assert TelegramMCPPersistenceService.COLLECTION == "telegram_user_mcp_configs"

def test_public_params_model():
    p = TelegramMCPPublicParams(name="fireflies", url="https://api.fireflies.ai/mcp")
    assert p.auth_scheme == "none"
    assert p.transport == "http"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/mcp-command-credentials.spec.md` — especially §2 (Data Models) and §3 (Module 1).
2. **Read** `packages/ai-parrot/src/parrot/handlers/mcp_persistence.py` in full — this is the exact pattern to mirror.
3. **Verify the Codebase Contract** — confirm `DocumentDb` is at `parrot/interfaces/documentdb.py` and has `update_one`, `read`, `read_one` methods.
4. **Implement** the new file as described above.
5. **Run** `ruff check` and fix any issues.
6. **Commit**: `git add packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py`
7. **Move** this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
