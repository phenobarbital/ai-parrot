---
type: Wiki Overview
title: 'TASK-1211: SQL Analyst no-regression integration test'
id: doc:sdd-tasks-completed-task-1211-sql-analyst-no-regression-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The validation logic added by TASK-1210 is defensive — it must not
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
---

# TASK-1211: SQL Analyst no-regression integration test

**Feature**: FEAT-172 — Mandatory `tool_prefix` + Eager Collision Detection
**Spec**: `sdd/specs/databaseagent-mandatory-prefix-collision.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1210
**Assigned-to**: unassigned

---

## Context

The validation logic added by TASK-1210 is defensive — it must not
break the canonical `sql_analyst` runtime config (one
`PostgresToolkit` with `tool_prefix="db"`). This task pins that
invariant with an integration smoke test.

Implements the **integration test** row from spec §4.

---

## Scope

- Add `test_sql_analyst_unchanged_after_feat_172` under
  `packages/ai-parrot/tests/integration/bots/database/test_feat_172_no_regression.py`
  (CREATE).
- Test flow:
  - Instantiate `DatabaseAgent` with a single `PostgresToolkit`
    (or a fully-stubbed mock that inherits from `DatabaseToolkit`
    with `tool_prefix="db"` if a live PG is not available).
  - Call `await agent.configure()` and assert it returns without
    raising.
  - Assert `agent._internal_toolkit is not None` after
    `configure()`.
  - Call `agent._compute_active_tools(OutputComponent.SQL_QUERY |
    OutputComponent.SCHEMA_CONTEXT | OutputComponent.EXECUTION_PLAN)`
    and assert the canonical surface is present:
    `{db_search_schema, db_generate_query, db_validate_query,
    db_explain_query}`.
  - Assert that **no `logger.warning`** is emitted by
    `_compute_active_tools` during normal operation (no
    collision, no `tool_prefix=None` deprecation).
- Mark with `@pytest.mark.integration` if the marker is
  registered.

**NOT in scope**:
- Unit tests for the validation passes (TASK-1210).
- Anything touching `agent.py` source.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/bots/database/test_feat_172_no_regression.py` | CREATE | Integration smoke test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import logging
import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# OR the MockDatabaseToolkit fixture if a live PG is not available.
```

### Existing Signatures (from earlier tasks)
```python
# From TASK-1208 (FEAT-171):
#   packages/ai-parrot/tests/unit/bots/database/conftest.py
#   class MockDatabaseToolkit(DatabaseToolkit): ...
#   mock_toolkit_factory(tool_prefix=..., method_name=...) → toolkit

# From TASK-1210 (FEAT-172):
#   DatabaseAgent.configure() raises ValueError on bad prefix /
#   collision; sets self._internal_toolkit on success.
```

### Does NOT Exist
- ~~A pre-baked `sql_analyst_agent` fixture~~ — does not exist as
  a shared fixture. Build it inline in this test.

---

## Implementation Notes

### Choosing live PG vs. mock
Two reasonable approaches:
1. **Mock-only**: use `MockDatabaseToolkit(tool_prefix="db",
   methods=["search_schema", "generate_query", "validate_query",
   "explain_query"])`. Fast, no infra. Sufficient because this
   test pins the **agent's** behaviour, not PG-specific code
   paths.
2. **Live PG**: use `PostgresToolkit` against a test DB. Catches
   regressions where the real toolkit changes its tool surface.
   Slower; requires the test DB fixture.

Prefer **mock-only** for this test — its job is to pin the agent's
no-regression behaviour, not to validate `PostgresToolkit`. The
canonical surface is well-defined; if `PostgresToolkit` ever drops
one of those tools, the broader test suite will catch it.

### Test skeleton
```python
import logging
import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent


async def test_sql_analyst_unchanged_after_feat_172(
    mock_toolkit_factory, caplog,
):
    """Canonical sql_analyst config:
    one PostgresToolkit(tool_prefix='db'). configure() succeeds,
    expected tool surface is exposed, no warnings on the request
    path."""
    tk = mock_toolkit_factory(
        tool_prefix="db",
        methods=[
            "search_schema", "generate_query",
            "validate_query", "explain_query",
        ],
    )
    agent = DatabaseAgent(name="sql_analyst", toolkits=[tk])

    await agent.configure()
    assert agent._internal_toolkit is not None

    with caplog.at_level(logging.WARNING):
        tools = agent._compute_active_tools(
            OutputComponent.SQL_QUERY
            | OutputComponent.SCHEMA_CONTEXT
            | OutputComponent.EXECUTION_PLAN,
        )

    names = {getattr(t, "name", None) for t in tools}
    assert {
        "db_search_schema", "db_generate_query",
        "db_validate_query", "db_explain_query",
    }.issubset(names)

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "collision" in r.getMessage()
    ]
    assert warnings == [], f"Unexpected warnings: {warnings}"
```

### Mock factory extension
TASK-1210 already extends the FEAT-171 `mock_toolkit_factory` to
accept arbitrary `tool_prefix` values. If `methods=` is not yet a
parameter, extend the factory to accept a list of method names
and dynamically declare `@tool`-decorated stubs for each. Keep
the change in the conftest, not in this test file.

---

## Acceptance Criteria

- [ ] `test_sql_analyst_unchanged_after_feat_172` exists at the
      documented path.
- [ ] `configure()` succeeds without raising.
- [ ] `agent._internal_toolkit is not None` after `configure()`.
- [ ] The merged surface contains
      `{db_search_schema, db_generate_query, db_validate_query,
      db_explain_query}`.
- [ ] No collision warning fires on the request path.
- [ ] Test passes:
      `pytest packages/ai-parrot/tests/integration/bots/database/test_feat_172_no_regression.py -v`.
- [ ] Previously-passing tests still pass.

---

## Test Specification

See "Implementation Notes" above for the full skeleton.

---

## Agent Instructions

1. Confirm TASK-1210 is in `sdd/tasks/completed/`.
2. Confirm the `mock_toolkit_factory` accepts the parameters used
   here (`tool_prefix`, `methods`). Extend the FEAT-171 conftest
   if needed.
3. Implement the test.
4. Run the test.
5. Move task file to `sdd/tasks/completed/` and update the
   per-spec index.
6. Fill in the Completion Note.

---

## Completion Note

**Status**: done  
**Completed**: 2026-05-15  
**Agent**: sdd-worker

### What was implemented

Created `packages/ai-parrot/tests/integration/bots/database/test_feat_172_no_regression.py`
with a fully self-contained integration test `test_sql_analyst_unchanged_after_feat_172`.

Following the same pattern as the existing `test_multi_toolkit.py`, the test defines an
inline `_SqlAnalystMockToolkit` class (inheriting from `DatabaseToolkit` with
`tool_prefix="db"`) that exposes exactly the four canonical tools:
`search_schema`, `generate_query`, `validate_query`, `explain_query`.

The test verifies:
1. `configure()` succeeds without raising (FEAT-172 validation passes with `tool_prefix="db"`).
2. `_internal_toolkit is not None` after `configure()`.
3. The canonical surface `{db_search_schema, db_generate_query, db_validate_query,
   db_explain_query}` is present in `_compute_active_tools()` output.
4. No collision warning fires on the clean request path.

### Test results
- `test_sql_analyst_unchanged_after_feat_172` — PASSED.
- All 30 database tests (unit + integration) — PASSED.
- `ruff check` — clean.

### Note on mock_toolkit_factory
Per the task spec, the test could use `mock_toolkit_factory`. However, since pytest
conftest fixtures from `tests/unit/bots/database/conftest.py` are not automatically
available in `tests/integration/bots/database/`, the test uses an inline mock class
consistent with the existing integration test pattern in `test_multi_toolkit.py`.
This avoids cross-directory conftest coupling while achieving the same coverage goal.
