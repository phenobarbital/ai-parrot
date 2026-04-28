# Feature Specification: AT&T Concierge Bot Record

**Feature ID**: FEAT-131
**Jira**: NAV-8248
**Date**: 2026-04-28
**Author**: flow-bot (research phase)
**Reporter**: jesuslarag@gmail.com
**Assignee**: flow-bot
**Status**: approved
**Target version**: next patch release

---

## 1. Motivation & Business Requirements

### Problem Statement

The AT&T concierge RAG chatbot is implemented in code (`examples/chatbots/att/bot.py`)
and connects to the `att.concierge` vector store in PostgreSQL, but it lacks a
corresponding record in the `navigator.ai_bots` database table. Without this
record, the bot cannot be discovered or loaded by the bot manager infrastructure,
and the acceptance criterion of confirming the agent named `att_concierge` in
`navigator.ai_bots` cannot be satisfied.

### Business Impact

- The AT&T concierge RAG chatbot is not discoverable via the standard bot registry.
- Bot manager components that query `navigator.ai_bots` cannot load or instantiate
  the AT&T concierge bot dynamically.
- Without the DB record, any API or UI that lists available bots will not show
  the AT&T concierge, preventing end-users from accessing it.

---

## 2. Scope

### In-scope

1. Create a SQL migration file `sdd/migrations/FEAT-131-att-concierge-bot-record.sql`
   that performs an idempotent `INSERT ... ON CONFLICT (name) DO NOTHING` into
   `navigator.ai_bots` for the AT&T concierge bot with:
   - `name = 'att_concierge'`
   - `description`: descriptive text for the AT&T RAG concierge
   - `role = 'AT&T Concierge'`
   - `goal`: help AT&T retail staff and customers with product, plan, and service queries
   - `backstory`: trained on AT&T product catalog and concierge documents
   - `operation_mode = 'adaptive'`
   - `use_vector = TRUE`
   - `vector_store_config`: JSON pointing to `schema='att'`, `table='concierge'`
   - `embedding_model`: `sentence-transformers/all-mpnet-base-v2` / `huggingface`
   - `context_search_limit = 10`
   - `context_score_threshold = 0.7`
   - `llm = 'google'`, `model_name = 'gemini-2.5-flash'`
   - `tools_enabled = FALSE` (pure RAG, no tool calls)
   - `language = 'en'`
   - `enabled = TRUE`

2. Verify the migration executes without error against the target PostgreSQL instance
   (dev/staging) and that the row can be queried back.

### Out-of-scope

- Changes to the AT&T concierge Python bot code.
- Creating or modifying the `att.concierge` vector store table.
- UI/frontend changes.
- Backfilling historical conversation data.

---

## 3. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-1 | A row with `name = 'att_concierge'` exists in `navigator.ai_bots` | `SELECT name FROM navigator.ai_bots WHERE name = 'att_concierge';` returns 1 row |
| AC-2 | `use_vector = TRUE` and `vector_store_config` references `att.concierge` | SQL check on returned row |
| AC-3 | `enabled = TRUE` and `operation_mode = 'adaptive'` | SQL check on returned row |
| AC-4 | Migration is idempotent — running it twice does not error or duplicate the row | Run migration twice; `SELECT COUNT(*) ... WHERE name = 'att_concierge'` returns 1 |

---

## 4. Technical Design

### 4.1 Table Schema Reference

The `navigator.ai_bots` table is defined in
`packages/ai-parrot/src/parrot/handlers/creation.sql` and modeled by
`BotModel` in `packages/ai-parrot/src/parrot/handlers/models/bots.py`.

Key columns relevant to this feature:

| Column | Type | Notes |
|--------|------|-------|
| `name` | `VARCHAR NOT NULL UNIQUE` | Bot identifier — `att_concierge` |
| `use_vector` | `BOOLEAN` | Must be `TRUE` for RAG |
| `vector_store_config` | `JSONB` | Contains `schema`, `table`, `metric_type` |
| `embedding_model` | `JSONB` | HuggingFace model config |
| `operation_mode` | `VARCHAR` | `'adaptive'` |
| `tools_enabled` | `BOOLEAN` | `FALSE` (pure RAG) |
| `llm` | `VARCHAR` | `'google'` |
| `model_name` | `VARCHAR` | `'gemini-2.5-flash'` |

### 4.2 Migration File

Location: `sdd/migrations/FEAT-131-att-concierge-bot-record.sql`

The SQL will use `INSERT INTO navigator.ai_bots (...) VALUES (...) ON CONFLICT (name) DO NOTHING`
to guarantee idempotency. The `vector_store_config` JSON will include:

```json
{
  "schema": "att",
  "table": "concierge",
  "dimension": 768,
  "metric_type": "EUCLIDEAN_DISTANCE",
  "vector_store": "postgres"
}
```

### 4.3 Verification Query

```sql
SELECT
    chatbot_id,
    name,
    use_vector,
    vector_store_config,
    operation_mode,
    enabled
FROM navigator.ai_bots
WHERE name = 'att_concierge';
```

---

## 5. Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `sdd/migrations/FEAT-131-att-concierge-bot-record.sql` | CREATE | Idempotent INSERT for att_concierge bot record |

---

## 6. Dependencies

- PostgreSQL `navigator` schema with `ai_bots` table already created (pre-existing).
- `uuid-ossp` extension enabled (pre-existing — used by `DEFAULT uuid_generate_v4()`).
- Access to the target database environment (dev/staging credentials).

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `att.concierge` vector table does not exist in target env | Medium | Medium | Migration only inserts metadata; bot will gracefully fail at query time if table is absent |
| `unq_navigator_ai_bots_name` constraint violated on re-run | Low | None | `ON CONFLICT (name) DO NOTHING` guarantees idempotency |
| Column name mismatch between `BotModel` and DDL | Low | Low | Verified against `creation.sql` and `models/bots.py` before writing migration |
