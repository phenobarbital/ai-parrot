---
id: FC-040
query_id: Q026-F4
type: read
intent: "Follow-up: read parrot/auth/oauth2/persistence.py — users_integrations / user_agent_toolkits storage."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-007
depth: 1
---

# FC-040 — persistence.py upserts connection METADATA (not tokens) into DocumentDB `users_integrations` keyed (user_id, provider) and `user_agent_toolkits` keyed (user_id, agent_id, toolkit_id)

## Summary

191 lines. `upsert_users_integration(row)` `$set`/`$setOnInsert` on `{user_id, provider}`; `get_users_integration(user_id, provider)`; `delete_users_integration`; `upsert_user_agent_toolkit(row)` on `(user_id, agent_id, toolkit_id)`; `list_user_agent_toolkits(user_id, agent_id)`; `delete_user_agent_toolkits_by_provider(user_id, provider)` cascade.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py`
  lines: 42-64
  symbol: `upsert_users_integration`
  excerpt: |
    query = {"user_id": row.user_id, "provider": row.provider}
    "$set": row.model_dump(exclude={"user_id", "provider"}), "$setOnInsert": {...}
- path: `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py`
  lines: 113-146
  symbol: `upsert_user_agent_toolkit`
  excerpt: |
    composite key (user_id, agent_id, toolkit_id)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py`
  lines: 171-191
  symbol: `delete_user_agent_toolkits_by_provider`
  excerpt: |
    Cascade-delete all enablement records for (user_id, provider)

## Notes

Connection metadata is already principal-keyed `(user_id, provider)`; one row per provider (no multi-account), matching the brainstorm's v1 'one account per provider'.
