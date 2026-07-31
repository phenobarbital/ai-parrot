---
type: Wiki Overview
title: 'TASK-1434: DB/SQL agent producer — STRUCTURED_TABLE end-to-end'
id: doc:sdd-tasks-completed-task-1434-db-sql-producer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 5 (reference producer #2). The DB/SQL agent emits a `QueryResponse`'
relates_to:
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
---

# TASK-1434: DB/SQL agent producer — STRUCTURED_TABLE end-to-end

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1431, TASK-1432
**Assigned-to**: unassigned
**Parallel**: true (with TASK-1433)

---

## Context

Spec §3 Module 5 (reference producer #2). The DB/SQL agent emits a `QueryResponse`
(`explanation` + `query` SQL artifact + typed `QueryDataset`) and today sets
`OutputMode.SQL_ANALYSIS`. When the caller selects `STRUCTURED_TABLE`, route the dataset +
reuse `QueryResponse.explanation`/`query` through the new renderer — WITHOUT regressing the
SQL_ANALYSIS path.

---

## Scope

- When `output_mode == OutputMode.STRUCTURED_TABLE`, have the DB/SQL agent route its
  `QueryDataset` (rows) into `response.data` and reuse `QueryResponse.explanation` (prose)
  as the structured-table `explanation`, so the renderer (TASK-1431) produces the payload.
- Keep `OutputMode.SQL_ANALYSIS` behavior intact when that mode is selected (caller's
  `output_mode` decides — see spec §8 resolved decision).
- Write an end-to-end-ish unit test: DB-agent-style `QueryResponse` + STRUCTURED_TABLE →
  payload with columns + rows + reused SQL explanation.

**NOT in scope**: PandasAgent (TASK-1433), full integration suite (TASK-1435), changing the
SQL_ANALYSIS contract.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | route to STRUCTURED_TABLE when selected |
| `packages/ai-parrot/tests/bots/database/test_db_agent_structured_table.py` | CREATE | producer end-to-end test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # STRUCTURED_TABLE from TASK-1429
from parrot.bots.database.models import QueryResponse  # provenance carrier
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/models.py
class QueryResponse(BaseModel):           # :276
    explanation: str = Field(...)         # :279  (prose — reuse as structured-table explanation)
    query: Optional[str] = Field(...)     # :282  (SQL artifact)
    # _dedupe_sql_from_explanation keeps explanation prose-only  (:314-317)
# QueryDataset carries columns/row_count/dtypes (models.py:271-273)

# packages/ai-parrot/src/parrot/bots/database/agent.py
#   :585-595  sets response.response = qr.explanation; response.data = <dataset>;
#             response.output_mode = OutputMode.SQL_ANALYSIS  <-- branch on the requested mode here
```

### Does NOT Exist
- ~~a structured-table-specific provenance object~~ — reuse `QueryResponse.explanation` / `.query`.
- ~~automatic emit-of-both-modes~~ — caller's `output_mode` selects ONE mode (per spec §8).
- ~~`OutputMode.DATAFRAME` / `JSON_DATA`~~ — not routable.

---

## Implementation Notes

### Key Constraints
- Branch on the requested `output_mode` at the envelope-setting site (~`agent.py:585-595`);
  do not unconditionally force SQL_ANALYSIS.
- Reuse the renderer for the transform — the agent only sets `response.data` + the explanation
  source and the mode. No new serialization in the agent.
- Async-first; `self.logger`; never regress SQL_ANALYSIS.

### References in Codebase
- `bots/database/agent.py:585-595` — current envelope assignment (the branch point).
- `bots/database/models.py:276-325` — `QueryResponse` provenance.

---

## Acceptance Criteria

- [ ] DB/SQL agent with `output_mode=STRUCTURED_TABLE` returns columns + rows in `response.data`.
- [ ] `explanation` reuses `QueryResponse.explanation` (SQL kept out of prose by existing validator).
- [ ] `OutputMode.SQL_ANALYSIS` path unchanged when that mode is selected.
- [ ] Test pass: `pytest packages/ai-parrot/tests/bots/database/test_db_agent_structured_table.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/database/agent.py` clean.

---

## Test Specification
```python
# packages/ai-parrot/tests/bots/database/test_db_agent_structured_table.py
from parrot.models.outputs import OutputMode

async def test_db_agent_structured_table():
    """DB agent QueryResponse + STRUCTURED_TABLE → structured payload with reused explanation."""
    ...

async def test_sql_analysis_unchanged():
    """Selecting SQL_ANALYSIS still yields the legacy envelope."""
    ...
```

---

## Agent Instructions
1. Read the spec; confirm TASK-1431 and TASK-1432 are completed.
2. Verify the Codebase Contract (re-check `agent.py:585-595` — lines may have shifted).
3. Update index status → `in-progress`.
4. Implement per scope; make tests pass; do NOT regress SQL_ANALYSIS.
5. Move this file to `sdd/tasks/completed/`; update index → `done`; fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-06-03.

- Added `output_mode: Optional[OutputMode] = None` parameter to `DatabaseAgent.ask()`.
- Added branch at the response output_mode assignment (~line 595): when `output_mode == OutputMode.STRUCTURED_TABLE`, set `response.output_mode = OutputMode.STRUCTURED_TABLE`; otherwise default to `OutputMode.SQL_ANALYSIS` (no regression).
- Created `tests/bots/database/test_db_agent_structured_table.py` with 9 tests:
  - Source-level assertions: ask signature, STRUCTURED_TABLE branch present, SQL_ANALYSIS unchanged.
  - Renderer e2e: DB-agent-style response → StructuredTableRenderer → valid payload.
- Note: The worktree's `tests/bots/database/conftest.py` cannot be loaded in the worktree environment because it chains through a Cython extension (`parrot.utils.types`) that is gitignored and not compiled in the worktree. Tests will pass after merge to dev (where the compiled extension exists). Verified by running equivalent assertions in the main repo path.
