# TASK-805: Rewrite MCP Command Handlers and Rehydration

**Feature**: FEAT-113 — Vault-Backed Credentials for Telegram /add_mcp
**Spec**: `sdd/specs/mcp-command-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-803, TASK-804
**Assigned-to**: unassigned

---

## Context

This is the core rewrite task for FEAT-113. It replaces all Redis-backed
persistence in `mcp_commands.py` with the Vault + DocumentDB pattern:

- `add_mcp_handler` → split payload, persist public config, store secrets in Vault,
  register with ToolManager (with rollback on failure).
- `list_mcp_handler` → list from DocumentDB via `TelegramMCPPersistenceService`.
- `remove_mcp_handler` → soft-delete from DocumentDB + hard-delete from Vault.
- `rehydrate_user_mcp_servers` → load from DocumentDB + Vault, rebuild `MCPClientConfig`.
- `register_mcp_commands` → remove `redis_client` parameter.
- Remove Redis helpers: `_REDIS_KEY_TEMPLATE`, `_redis_key`, `_persist_config`,
  `_load_all_configs`, `_forget_config`.

Implements **Module 3** of the spec (§3).

**CRITICAL — operation order for `add_mcp_handler`** (from spec §7):
1. `TelegramMCPPersistenceService.save(...)` — persist public config.
2. `store_vault_credential(...)` — persist secret (if any).
3. `tool_manager.add_mcp_server(config)` — register live tools.

On failure at step 2, roll back step 1. On failure at step 3, roll back steps 1 and 2.

---

## Scope

### Removals from `mcp_commands.py`

- Delete `_REDIS_KEY_TEMPLATE = "mcp:{channel}:{user_id}:servers"` (line 51).
- Delete `_redis_key(user_id: str) -> str` function (line 86).
- Delete `async def _persist_config(...)` (line 164).
- Delete `async def _load_all_configs(...)` (line 184).
- Delete `async def _forget_config(...)` (line 204).

### New imports to add

```python
from .mcp_persistence import (
    TelegramMCPPersistenceService,
    TelegramMCPPublicParams,
    UserTelegramMCPConfig,
)
from parrot.handlers.vault_utils import (
    store_vault_credential,
    retrieve_vault_credential,
    delete_vault_credential,
)
```

### Rewrites

**`add_mcp_handler(message, tool_manager_resolver)`** — drop `redis_client`:
```
1. Validate user/private-chat.
2. Parse JSON → call _build_config (raises → reply _USAGE).
3. Call _split_secret_and_public(payload) → (public_params, secret_params).
4. user_id = f"tg:{message.from_user.id}"
5. vault_name = f"tg_mcp_{public_params.name}" if secret_params else None
6. persistence = TelegramMCPPersistenceService()
7. await persistence.save(user_id, name, public_params, vault_name)
8. If secret_params:
     try: await store_vault_credential(user_id, vault_name, secret_params)
     except: await persistence.remove(user_id, name); reply error; return
9. try: registered = await tool_manager.add_mcp_server(config)
   except: (rollback vault + doc); reply error; return
10. reply f"Connected {name!r} with {len(registered)} tool(s)."
11. await _maybe_delete(message)
```

**`list_mcp_handler(message)`** — drop `redis_client`:
```
1. Validate user/private-chat.
2. user_id = f"tg:{message.from_user.id}"
3. persistence = TelegramMCPPersistenceService()
4. configs = await persistence.list(user_id)
5. If empty → reply "No MCP servers registered yet."
6. lines = ["Your MCP servers:"] + [f"• {c.name} — {c.params.url} ({c.params.auth_scheme})" for c in sorted(configs, key=lambda c: c.name)]
7. reply "\n".join(lines)
```

**`remove_mcp_handler(message, tool_manager_resolver)`** — drop `redis_client`:
```
1. Validate user/private-chat.
2. Parse name from command text.
3. user_id = f"tg:{message.from_user.id}"
4. persistence = TelegramMCPPersistenceService()
5. config_doc = await persistence.read_one(user_id, name)
6. If tool_manager available: await tool_manager.remove_mcp_server(name) (best-effort)
7. removed = await persistence.remove(user_id, name)
8. If config_doc and config_doc.vault_credential_name:
     try: await delete_vault_credential(user_id, config_doc.vault_credential_name)
     except KeyError: pass  (missing Vault entry is not an error)
9. reply removed/not-found message
```

**`rehydrate_user_mcp_servers(tool_manager, user_id) -> int`** — drop `redis_client`:
```
1. If tool_manager is None: return 0
2. persistence = TelegramMCPPersistenceService()
3. configs = await persistence.list(user_id)
4. count = 0
5. for each config in configs:
     try:
       secret_params = {}
       if config.vault_credential_name:
         try: secret_params = await retrieve_vault_credential(user_id, config.vault_credential_name)
         except KeyError:
           logger.warning("Vault entry missing for MCP server %r / %s — skipping", config.name, user_id)
           continue
       payload = {**config.params.model_dump(), **secret_params}
       mcp_config = _build_config(payload)
       await tool_manager.add_mcp_server(mcp_config)
       count += 1
     except Exception: logger.exception(...); continue
6. return count
```

**`register_mcp_commands(router, tool_manager_resolver)`** — drop `redis_client`:
- Remove the `redis_client` parameter.
- Update inner `_add`, `_list`, `_remove` closures to not pass `redis_client`.

**NOT in scope**: wrapper.py changes (TASK-806), tests (TASK-807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py` | MODIFY | Remove Redis helpers; rewrite handlers + register fn; drop redis_client params |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in mcp_commands.py — keep:
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from ...mcp.client import AuthCredential, AuthScheme, MCPClientConfig

if TYPE_CHECKING:
    from ...tools.manager import ToolManager

# New imports to add:
from .mcp_persistence import (
    TelegramMCPPersistenceService,
    TelegramMCPPublicParams,
    UserTelegramMCPConfig,
)
from parrot.handlers.vault_utils import (
    store_vault_credential,    # vault_utils.py:69
    retrieve_vault_credential, # vault_utils.py:116 — raises KeyError if not found
    delete_vault_credential,   # vault_utils.py:149
)

# _split_secret_and_public is defined in TASK-804 — it's in the same file, already present.
```

### Existing Signatures to Use

```python
# mcp_commands.py:249-263 — _reject_non_private (keep unchanged)
async def _reject_non_private(message: Message) -> bool: ...

# mcp_commands.py:431-436 — _maybe_delete (keep unchanged)
async def _maybe_delete(message: Message) -> None: ...

# mcp_commands.py:90 — _build_config (keep unchanged)
def _build_config(payload: Dict[str, Any]) -> MCPClientConfig: ...

# mcp_persistence.py (TASK-803):
class TelegramMCPPersistenceService:
    async def save(self, user_id, name, params, vault_credential_name) -> None: ...
    async def list(self, user_id) -> List[UserTelegramMCPConfig]: ...
    async def read_one(self, user_id, name) -> Optional[UserTelegramMCPConfig]: ...
    async def remove(self, user_id, name) -> bool: ...

# mcp_mixin.py:57-61 — ToolManager.add_mcp_server:
async def add_mcp_server(self, config: 'MCPServerConfig', context=None) -> List[str]: ...

# mcp_mixin.py:354 — ToolManager.remove_mcp_server:
async def remove_mcp_server(self, server_name: str) -> bool: ...

# vault_utils.py:69 — store_vault_credential:
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None: ...

# vault_utils.py:116 — retrieve_vault_credential (raises KeyError if not found):
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]: ...

# vault_utils.py:149 — delete_vault_credential:
async def delete_vault_credential(user_id: str, vault_name: str) -> None: ...
```

### Does NOT Exist

- ~~`redis_client.hmget / hset / hdel / hgetall`~~ — Redis removed from this module.
- ~~`_REDIS_KEY_TEMPLATE`~~ — deleted in this task.
- ~~`_redis_key()`~~ — deleted in this task.
- ~~`_persist_config()`~~ — deleted in this task.
- ~~`_load_all_configs()`~~ — deleted in this task.
- ~~`_forget_config()`~~ — deleted in this task.
- ~~`rehydrate_user_mcp_servers(redis_client, tool_manager, user_id)`~~ — signature changes; `redis_client` is removed.
- ~~`retrieve_vault_credential` returning `None`~~ — it raises `KeyError` on miss; catch `KeyError`, not `None` check.
- ~~`parrot.integrations.telegram.mcp_commands.VaultClient`~~ — does not exist.

---

## Implementation Notes

### Rollback Logic for `add_mcp_handler`

```python
# Step-by-step with rollback:
persistence = TelegramMCPPersistenceService()
vault_name = f"tg_mcp_{name}" if secret_params else None

# Step 1: persist public config
try:
    await persistence.save(user_id, name, public_params, vault_name)
except Exception as exc:
    logger.exception("add_mcp: failed to save config for %r / %s", name, user_id)
    await message.reply(f"Could not save MCP server config: {exc}", parse_mode=None)
    return

# Step 2: store secret (if any)
if secret_params:
    try:
        await store_vault_credential(user_id, vault_name, secret_params)
    except Exception as exc:
        logger.exception("add_mcp: Vault store failed for %r / %s", name, user_id)
        await persistence.remove(user_id, name)  # rollback step 1
        await message.reply(
            f"Could not store credentials for {name!r}: {exc}",
            parse_mode=None,
        )
        return

# Step 3: register live tools
try:
    registered = await tool_manager.add_mcp_server(config)
except Exception as exc:
    logger.exception("add_mcp: ToolManager register failed for %r / %s", name, user_id)
    # rollback steps 1 & 2
    await persistence.remove(user_id, name)
    if secret_params:
        try:
            await delete_vault_credential(user_id, vault_name)
        except Exception:
            pass
    await message.reply(
        f"Could not connect to MCP server {name!r}: {exc}",
        parse_mode=None,
    )
    return

await message.reply(f"Connected {name!r} with {len(registered)} tool(s).", parse_mode=None)
await _maybe_delete(message)
```

### User ID Convention

Always use `f"tg:{message.from_user.id}"` as the `user_id`. This is the
`TelegramUserSession.user_id` unauthenticated fallback (auth.py:93). Do NOT use
the bare integer `message.from_user.id`.

### Key Constraints

- `rehydrate_user_mcp_servers` signature changes from
  `(redis_client, tool_manager, user_id)` to `(tool_manager, user_id)`.
  `grep` the codebase for other callers before committing (`wrapper.py` is the
  only known one; TASK-806 updates it).
- `register_mcp_commands` drops `redis_client` from the signature and from inner closures.
- Never log the raw payload, token, or any secret field — log only `name` and `user_id`.
- Preserve `_reject_non_private` and `_maybe_delete` untouched.
- Preserve `_build_config` untouched (still needed by `add_mcp_handler` and `rehydrate`).
- Keep `_TELEGRAM_CHANNEL = "telegram"` constant (used by other code if any).
- Remove `_REDIS_KEY_TEMPLATE` and `_redis_key` — they are no longer referenced.

---

## Acceptance Criteria

- [ ] `_REDIS_KEY_TEMPLATE`, `_redis_key`, `_persist_config`, `_load_all_configs`, `_forget_config` are all deleted.
- [ ] `add_mcp_handler` signature is `(message, tool_manager_resolver)` — no `redis_client`.
- [ ] `list_mcp_handler` signature is `(message)` — no `redis_client`.
- [ ] `remove_mcp_handler` signature is `(message, tool_manager_resolver)` — no `redis_client`.
- [ ] `register_mcp_commands` signature is `(router, tool_manager_resolver)` — no `redis_client`.
- [ ] `rehydrate_user_mcp_servers` signature is `(tool_manager, user_id)` — no `redis_client`.
- [ ] `add_mcp_handler` calls `persistence.save` then `store_vault_credential` then `tool_manager.add_mcp_server` with rollback on each step.
- [ ] `list_mcp_handler` replies with `name — url (scheme)` lines only (no secrets).
- [ ] `remove_mcp_handler` calls `persistence.remove` + `delete_vault_credential` (best-effort on vault miss).
- [ ] `rehydrate_user_mcp_servers` skips servers with missing Vault entries (logs warning) without aborting others.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`

---

## Test Specification

Full tests in TASK-807. Ensure the rewritten module imports cleanly:

```python
from parrot.integrations.telegram.mcp_commands import (
    register_mcp_commands,
    rehydrate_user_mcp_servers,
)
import inspect
sig = inspect.signature(rehydrate_user_mcp_servers)
assert "redis_client" not in sig.parameters
assert "tool_manager" in sig.parameters
assert "user_id" in sig.parameters

sig2 = inspect.signature(register_mcp_commands)
assert "redis_client" not in sig2.parameters
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-803 and TASK-804 are completed**.
2. **Read** `mcp_commands.py` in full (it now has `_split_secret_and_public` from TASK-804).
3. **grep** for all callers of `register_mcp_commands` and `rehydrate_user_mcp_servers`:
   ```bash
   grep -rn "register_mcp_commands\|rehydrate_user_mcp_servers" packages/ai-parrot/src/
   ```
   Expected: only `wrapper.py`. If more callers found, note them in the Completion Note.
4. **Implement** the rewrites as described above.
5. Run `ruff check` and fix issues.
6. **Commit**: `git add packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`
7. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
