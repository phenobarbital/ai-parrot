# TASK-348: Eager Vector Store Provisioning at Bot Creation

**Feature**: API Bot Creation — Normalization & Provisioning
**Feature ID**: FEAT-049
**Spec**: `sdd/specs/new-api-bot-creation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-347
**Assigned-to**: unassigned

---

## Context

> Final task for FEAT-049. Adds eager PgVector table creation when a user provides `table` and `schema` in the vector store config during bot creation.
> Implements spec Section 3 — Module 2, change #2 (`_provision_vector_store`).

---

## Scope

### 1. New `_provision_vector_store()` method in `ChatbotHandler`

Add a private async method:

```python
async def _provision_vector_store(
    self,
    bot: AbstractBot,
    vector_store_config: dict
) -> dict:
```

**Logic:**
1. Extract `table = vector_store_config.get('table')` and `schema = vector_store_config.get('schema')`.
2. If either `table` or `schema` is missing/falsy: return `{"status": "none"}`.
3. Extract store type: `store_type = vector_store_config.get('name', 'postgres')` (the vector store driver).
4. Extract `dimension = vector_store_config.get('dimension', 384)`.
5. Extract `embedding_model` from config if present.
6. Build store kwargs: `table`, `schema`, `dimension`, `embedding_model`, plus any other relevant config keys.
7. Try:
   - Call `bot.define_store(vector_store=store_type, **store_kwargs)`.
   - Call `bot.configure_store()`.
   - Call `await bot.store.connection()`.
   - Call `await bot.store.create_collection(table=table, schema=schema, dimension=dimension)`.
   - Return `{"status": "ready"}`.
8. Except Exception as e:
   - Log: `self.logger.error(f"Vector store provisioning failed for {bot.name}: {e}")`.
   - Return `{"status": "pending", "error": str(e)}`.

### 2. Integration into `_put_database()`

After bot creation and BotManager registration (the step added by TASK-347), add:

```python
# Provision vector store if configured
vs_config = payload.get('vector_store_config') or {}
vs_result = await self._provision_vector_store(bot_instance, vs_config)
```

Include `vs_result` fields in the response:
- `"vector_store_status": vs_result["status"]`
- `"vector_store_error": vs_result.get("error")` (only if status is `"pending"`)

**NOT in scope**: Naming utilities (TASK-345), registry cleanup (TASK-346), name normalization (TASK-347).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/bots.py` | MODIFY | Add `_provision_vector_store()` method; call it from `_put_database()` |

---

## Implementation Notes

- `bot.define_store()` is from `VectorInterface` mixin (`parrot/interfaces/vector.py:98-108`). It sets `self._vector_store` as a dict and `self._use_vector = True`.
- `bot.configure_store()` is from `VectorInterface` (`parrot/interfaces/vector.py:77-96`). It instantiates the store class and assigns to `self.store`.
- `bot.store.connection()` creates the SQLAlchemy engine + connection pool.
- `bot.store.create_collection()` is at `parrot/stores/postgres.py:2800-2868`. It checks if the table exists first, then creates it with vector columns and indexes.
- The `define_store` → `configure_store` → `connection` → `create_collection` chain matches the pattern already used in `BotManagement.put()` (`parrot/handlers/chat.py:780-790`).
- All exceptions from the chain must be caught — a failed provisioning must NOT prevent the bot from being created.

---

## Acceptance Criteria

- [x] `PUT /api/v1/bots` with `vector_store_config` containing `table` and `schema` returns `vector_store_status: "ready"`.
- [x] The PgVector table actually exists in the database after the PUT returns.
- [x] `PUT /api/v1/bots` with `vector_store_config` missing `table` returns `vector_store_status: "none"`.
- [x] `PUT /api/v1/bots` with `vector_store_config` but PgVector unreachable returns `vector_store_status: "pending"` with `vector_store_error` explaining the failure.
- [x] The bot is created in the database regardless of vector store provisioning outcome.
- [x] Error is logged with `self.logger.error(...)` on provisioning failure.
