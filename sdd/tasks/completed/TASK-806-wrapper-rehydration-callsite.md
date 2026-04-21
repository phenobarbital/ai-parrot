# TASK-806: Update Wrapper Rehydration Call Site

**Feature**: FEAT-113 — Vault-Backed Credentials for Telegram /add_mcp
**Spec**: `sdd/specs/mcp-command-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-805
**Assigned-to**: unassigned

---

## Context

After TASK-805 rewrites `rehydrate_user_mcp_servers` to drop the `redis_client`
parameter, the only call site — `TelegramAgentWrapper._initialize_user_context`
in `wrapper.py` (lines 963-983) — must be updated to match the new signature.

This is a two-line change: remove the `redis_client` variable from the MCP
rehydration block and update the call. The `redis_client` variable itself can
stay (it is still used by other post-login operations in `_initialize_user_context`
such as JIRA post-auth); only its use as an argument to `rehydrate_user_mcp_servers`
is removed.

Implements **Module 4** of the spec (§3).

---

## Scope

- Modify `wrapper.py` lines 963-983:
  - Keep the `redis_client = self.app.get("redis") if self.app is not None else None` line.
  - Change the condition: remove the `and redis_client is not None` guard from
    the `if user_tm is not None ...` block (or keep it if it's needed for other ops —
    just ensure the rehydrate call is not gated on redis_client).
  - Update the call: `await rehydrate_user_mcp_servers(user_tm, str(session.telegram_id))`.
    Drop `redis_client` from the arguments.
  - Keep the outer `try/except` guard unchanged.

**NOT in scope**: Removing redis_client from `_initialize_user_context` entirely
(it is still used by other parts of the method for jira_post_auth, etc.).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Drop `redis_client` arg from `rehydrate_user_mcp_servers` call; remove redis guard from rehydration condition |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# wrapper.py:969 — existing import (keep as-is):
from .mcp_commands import rehydrate_user_mcp_servers
```

### Existing Signatures to Use

```python
# wrapper.py:963-983 — CURRENT state (before this task):
user_tm = self._get_user_tool_manager(session)
redis_client = (
    self.app.get("redis") if self.app is not None else None
)
if user_tm is not None and redis_client is not None:
    try:
        from .mcp_commands import rehydrate_user_mcp_servers
        count = await rehydrate_user_mcp_servers(
            redis_client, user_tm, str(session.telegram_id)
        )
        if count:
            self.logger.info(
                "Rehydrated %d MCP server(s) for tg:%s",
                count,
                session.telegram_id,
            )
    except Exception:  # noqa: BLE001
        self.logger.exception(
            "MCP rehydration failed for tg:%s (continuing)",
            session.telegram_id,
        )

# After TASK-805, rehydrate_user_mcp_servers has this new signature:
async def rehydrate_user_mcp_servers(
    tool_manager: "ToolManager",
    user_id: str,
) -> int: ...
```

### Does NOT Exist

- ~~`rehydrate_user_mcp_servers(redis_client, tool_manager, user_id)`~~ — after TASK-805
  the signature is `(tool_manager, user_id)`. Using the old positional order would
  pass `redis_client` as `tool_manager` — a silent type bug.
- ~~`self.redis_client`~~ — the redis client is retrieved via `self.app.get("redis")`.

---

## Implementation Notes

### Target State (after this task)

```python
# wrapper.py — rehydration block AFTER this task:
user_tm = self._get_user_tool_manager(session)
redis_client = (
    self.app.get("redis") if self.app is not None else None
)
if user_tm is not None:
    try:
        from .mcp_commands import rehydrate_user_mcp_servers
        count = await rehydrate_user_mcp_servers(
            user_tm, str(session.telegram_id)
        )
        if count:
            self.logger.info(
                "Rehydrated %d MCP server(s) for tg:%s",
                count,
                session.telegram_id,
            )
    except Exception:  # noqa: BLE001
        self.logger.exception(
            "MCP rehydration failed for tg:%s (continuing)",
            session.telegram_id,
        )
```

Note: `redis_client` is fetched on the same line but no longer passed to the
rehydrate call. If `redis_client` is used elsewhere in `_initialize_user_context`
(e.g., jira post-auth), the variable stays. If it is ONLY used for this call,
it can be removed — but verify before touching it.

### Key Constraints

- Do NOT remove the outer `try/except` guard — the spec explicitly says to keep it.
- Do NOT touch any code outside the rehydration block (lines 963-983).
- Keep the `from .mcp_commands import rehydrate_user_mcp_servers` import style
  (inline, inside the `if` block) — this is the existing pattern.

---

## Acceptance Criteria

- [ ] `wrapper.py` no longer passes `redis_client` to `rehydrate_user_mcp_servers`.
- [ ] The rehydration call is `await rehydrate_user_mcp_servers(user_tm, str(session.telegram_id))`.
- [ ] The outer `try/except` block around the rehydration call is preserved.
- [ ] No other changes to `wrapper.py`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`

---

## Test Specification

This is a call-site change; the integration test in TASK-807
(`test_wrapper_rehydration_on_login`) covers it. Smoke check:

```bash
# Confirm the old 3-arg call no longer exists:
grep -n "rehydrate_user_mcp_servers" packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
# Expected: line with only 2 arguments (user_tm and str(session.telegram_id))
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-805 is completed** — `rehydrate_user_mcp_servers` must have the new 2-arg signature.
2. **Read** `wrapper.py` around lines 960-990 to see the current state.
3. **Check** if `redis_client` is used elsewhere in `_initialize_user_context` beyond the rehydration block:
   ```bash
   grep -n "redis_client" packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
   ```
4. **Implement** the minimal change: remove `redis_client` from the call and the condition guard.
5. Run `ruff check` on the file and fix any issues.
6. **Commit**: `git add packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
7. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
