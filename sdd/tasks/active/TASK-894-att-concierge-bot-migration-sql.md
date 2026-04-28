# TASK-894: Write SQL migration to insert att_concierge bot record

**Feature**: att-concierge-bot-record
**Feature ID**: FEAT-131
**Spec**: sdd/specs/att-concierge-bot-record.spec.md
**Status**: [ ] pending
**Priority**: high
**Effort**: S
**Depends-on**: none
**Parallel**: false
**Assigned-to**: unassigned

## Context

The AT&T concierge RAG chatbot exists as a Python class but has no entry in the
`navigator.ai_bots` PostgreSQL table. The bot manager cannot discover or load it
dynamically without this record. This task creates the idempotent SQL migration.

## Scope

Create the file `sdd/migrations/FEAT-131-att-concierge-bot-record.sql` containing
an `INSERT ... ON CONFLICT (name) DO NOTHING` statement for the `att_concierge`
bot record in `navigator.ai_bots`.

The INSERT must set:
- `name = 'att_concierge'`
- `description = 'AT&T concierge RAG chatbot for product, plan, and service queries'`
- `role = 'AT&T Concierge'`
- `goal = 'Help AT&T retail staff and customers find accurate information about AT&T products, plans, and services using a curated knowledge base.'`
- `backstory = 'I am the AT&T concierge assistant, trained on AT&T product catalogs, service plans, and customer service documents. I retrieve relevant information from the AT&T knowledge base to answer questions accurately.'`
- `rationale = 'I maintain a professional, helpful tone. I only answer questions that can be addressed using the AT&T knowledge base. For out-of-scope questions I politely redirect the user.'`
- `capabilities = 'I can answer questions about AT&T products, plans, services, and promotions using retrieval-augmented generation from the AT&T concierge knowledge base.'`
- `operation_mode = 'adaptive'`
- `use_vector = TRUE`
- `vector_store_config = '{"schema": "att", "table": "concierge", "dimension": 768, "metric_type": "EUCLIDEAN_DISTANCE", "vector_store": "postgres"}'::JSONB`
- `embedding_model = '{"model_name": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}'::JSONB`
- `context_search_limit = 10`
- `context_score_threshold = 0.7`
- `llm = 'google'`
- `model_name = 'gemini-2.5-flash'`
- `temperature = 0.1`
- `max_tokens = 1024`
- `tools_enabled = FALSE`
- `auto_tool_detection = FALSE`
- `language = 'en'`
- `enabled = TRUE`

## Files to Create/Modify

- `sdd/migrations/FEAT-131-att-concierge-bot-record.sql` — CREATE: idempotent INSERT migration

## Test Criteria

After applying the migration, execute:

```sql
SELECT name, use_vector, operation_mode, enabled, llm, model_name
FROM navigator.ai_bots
WHERE name = 'att_concierge';
```

Expected: 1 row returned with `use_vector=true`, `operation_mode='adaptive'`, `enabled=true`.

Run migration twice and verify `SELECT COUNT(*) FROM navigator.ai_bots WHERE name = 'att_concierge'` returns `1` (idempotency check).

## Implementation Notes

- Reference the table DDL in `packages/ai-parrot/src/parrot/handlers/creation.sql`
  to confirm column names match exactly (e.g., `use_vector` not `use_vector_context`).
- The UNIQUE constraint is on `name` column (`unq_navigator_ai_bots_name`), so use
  `ON CONFLICT (name) DO NOTHING`.
- Do NOT use `ON CONFLICT DO UPDATE` — a no-op is sufficient and safest.
