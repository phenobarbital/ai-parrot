---
type: Wiki Overview
title: 'TASK-1209: Multi-toolkit runtime integration test'
id: doc:sdd-tasks-completed-task-1209-multi-toolkit-integration-test-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unit tests in TASK-1208 verify `_compute_active_tools` in
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
---

# TASK-1209: Multi-toolkit runtime integration test

**Feature**: FEAT-171 — Prefix-Aware Tool Resolution for DatabaseAgent
**Spec**: `sdd/specs/databaseagent-prefix-aware-tools.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1208
**Assigned-to**: unassigned

---

## Context

Unit tests in TASK-1208 verify `_compute_active_tools` in
isolation. This task adds the end-to-end integration test from
spec §4 that drives a `DatabaseAgent` with two distinct toolkits
through every `OutputComponent` flag combination and asserts the
merged tool surface contains both toolkits' tools.

Implements the **integration test** row from spec §4.

---

## Scope

- Add `test_databaseagent_multi_toolkit_runtime` in
  `packages/ai-parrot/tests/integration/bots/database/test_multi_toolkit.py`
  (CREATE).
- Reuse the `MockDatabaseToolkit` fixture introduced by TASK-1208.
- Test pattern:
  - Instantiate `DatabaseAgent` with two toolkits:
    `PostgresToolkit(tool_prefix="db")` (or another
    `MockDatabaseToolkit(tool_prefix="db")` to keep the test
    DB-free) and `MockDatabaseToolkit(tool_prefix="mk")`.
  - For each `OutputComponent` flag (and a few combinations like
    `SQL_QUERY | SCHEMA_CONTEXT`), call `_compute_active_tools`
    and assert the merged set contains the expected tool names
    from BOTH toolkits.
- Mark with `@pytest.mark.integration` if the project uses that
  marker (check `pyproject.toml` / `pytest.ini`); otherwise leave
  unmarked.

**NOT in scope**:
- Unit tests for `_compute_active_tools` (TASK-1208).
- Anything outside `tests/integration/bots/database/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/bots/database/test_multi_toolkit.py` | CREATE | Integration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent
from parrot.bots.database.toolkits.base import DatabaseToolkit
# MockDatabaseToolkit imported from conftest created by TASK-1208
```

### Existing Class Signatures (from TASK-1208)
```python
# packages/ai-parrot/tests/unit/bots/database/conftest.py
class MockDatabaseToolkit(DatabaseToolkit):
    database_type: str = "mock"
    primary_schema: str = "public"
    allowed_schemas: List[str] = ["public"]

    @tool
    async def search_schema(self, search_term: str, limit: int = 10):
        return []
```

### Does NOT Exist
- ~~`MockDatabaseToolkit.generate_query` / `validate_query` /
  `explain_query`~~ — the mock only exposes `search_schema`. Tests
  exercising other components must either (a) restrict assertions
  to `SCHEMA_CONTEXT` for the mock, or (b) extend
  `MockDatabaseToolkit` with extra `@tool` methods.

---

## Implementation Notes

### Reuse vs. extend the Mock
TASK-1208's `MockDatabaseToolkit` only exposes `search_schema`. To
exercise multiple `OutputComponent` flags meaningfully, this task
may need to extend it with additional stub methods
(`generate_query`, `validate_query`, `explain_query`). Either
extend the existing fixture in
`tests/unit/bots/database/conftest.py` or create a
`MockFullDatabaseToolkit` in
`tests/integration/bots/database/conftest.py`. Prefer extending
the existing fixture to avoid duplication.

### Component coverage matrix
```python
@pytest.mark.parametrize("components,expected_names", [
    (OutputComponent.SCHEMA_CONTEXT,
     {"db_search_schema", "mk_search_schema"}),
    (OutputComponent.SQL_QUERY,
     {"db_generate_query", "db_validate_query",
      "mk_generate_query", "mk_validate_query"}),
    (OutputComponent.EXECUTION_PLAN,
     {"db_explain_query", "mk_explain_query"}),
    (OutputComponent.SQL_QUERY | OutputComponent.SCHEMA_CONTEXT,
     {"db_search_schema", "mk_search_schema",
      "db_generate_query", "db_validate_query",
      "mk_generate_query", "mk_validate_query"}),
])
def test_databaseagent_multi_toolkit_runtime(
    agent_factory, mock_toolkit_factory, components, expected_names,
):
    agent = agent_factory(toolkits=[
        mock_toolkit_factory(tool_prefix="db"),
        mock_toolkit_factory(tool_prefix="mk"),
    ])
    tools = agent._compute_active_tools(components)
    names = {getattr(t, "name", None) for t in tools}
    assert expected_names.issubset(names), \
        f"Missing: {expected_names - names}"
```

### `@pytest.mark.integration` marker
Check the project marker config:
```bash
grep -n "markers" packages/ai-parrot/pyproject.toml || \
  grep -rn "markers" packages/ai-parrot/pytest.ini
```
If the `integration` marker is registered, use it. Otherwise, this
test is fast enough (in-memory mocks) that the marker is optional.

---

## Acceptance Criteria

- [ ] `test_databaseagent_multi_toolkit_runtime` exists under
      `tests/integration/bots/database/test_multi_toolkit.py`.
- [ ] The test parametrizes across at least four
      `OutputComponent` flag combinations.
- [ ] For each combination, both `db_*` AND `mk_*` tools appear in
      the resolved set (when the corresponding logical name is in
      `_TOOLKIT_TOOLS_BY_COMPONENT[component]`).
- [ ] Test passes:
      `pytest packages/ai-parrot/tests/integration/bots/database/test_multi_toolkit.py -v`.
- [ ] All previously-passing tests still pass.

---

## Test Specification

See "Implementation Notes" above for the parametrized skeleton.

---

## Agent Instructions

1. Confirm TASK-1208 is in `sdd/tasks/completed/`.
2. Decide whether to extend the existing `MockDatabaseToolkit`
   (preferred) or create a new richer mock.
3. Implement the test.
4. Run the test.
5. Move task file to `sdd/tasks/completed/` and update the
   per-spec index.
6. Fill in the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-05-15.

**Changes made:**
- Created `packages/ai-parrot/tests/integration/bots/database/test_multi_toolkit.py`
  with `test_databaseagent_multi_toolkit_runtime` parametrized across 4 component
  combinations: SCHEMA_CONTEXT, SQL_QUERY, EXECUTION_PLAN, SQL_QUERY|SCHEMA_CONTEXT.
- Inline `_MockToolkit` stub (self-contained, no external DB required).
- Defined `mock_toolkit_factory` and `agent_factory` fixtures directly in the test file.
- Added `__init__.py` to `tests/integration/bots/database/`.

**Tests:** 4/4 parametrized cases passed.
