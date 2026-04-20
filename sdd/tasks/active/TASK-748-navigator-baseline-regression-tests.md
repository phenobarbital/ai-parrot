# TASK-748: Baseline regression tests for `NavigatorToolkit`

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-747
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. Establishes the safety net
**before** any method body is migrated:

1. Snapshot the exact `get_tools()` tool-name list + tool-description
   strings (the LLM-facing contract). Every subsequent migration task
   must keep these byte-identical.
2. For every write tool (`create_*`, `update_*`, `clone_dashboard`,
   `assign_module_to_*`) prove that the `confirm_execution=False` branch
   returns `{"status": "confirm_execution", ...}` and makes **zero**
   calls to the underlying asyncdb connection.
3. Capture a mocked invocation of `create_program(confirm_execution=True)`
   to snapshot the target `insert_row` / `upsert_row` / `transaction`
   call arguments for later migration tasks.

---

## Scope

- Create `tests/unit/test_navigator_toolkit_baseline.py` with:
  - `test_get_tools_names_unchanged_post_migration` — 28-tool name snapshot.
  - `test_get_tools_descriptions_unchanged_post_migration` — description snapshot.
  - `test_<tool>_confirm_execution_false_returns_plan_dict` — one test per
    write tool asserting `{"status": "confirm_execution", …}` return and
    `AsyncMock.call_count == 0` on the connection.
- Add the `navigator_toolkit_factory` fixture to `tests/unit/conftest.py`
  (as specified in §4 Test Data / Fixtures).
- Pin the `upsert_row(update_cols=[])` SQL semantic (per Risk note in §7):
  add a unit test inspecting `_get_or_build_template("upsert", …,
  update_cols=())` so the semantic is frozen before Module 2 depends on it.

**NOT in scope**: modifying any NavigatorToolkit method body; rewriting
any SQL; any change outside `tests/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/unit/test_navigator_toolkit_baseline.py` | CREATE | Regression snapshots + per-tool confirm_execution tests |
| `packages/ai-parrot-tools/tests/unit/conftest.py` | MODIFY | Add `navigator_toolkit_factory` fixture |
| `packages/ai-parrot/tests/unit/test_postgres_toolkit.py` | MODIFY | Pin `upsert_row(update_cols=[])` semantic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.navigator.toolkit import NavigatorToolkit
# verified: packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(PostgresToolkit):
    tool_prefix: str = "nav"                                        # line 56
    def __init__(self, dsn="", default_client_id=1, user_id=None,
                 confirm_execution=False, **kw) -> None: ...        # line 75
    async def create_program(...) -> Dict[str, Any]: ...            # line 657
    async def create_module(...) -> Dict[str, Any]: ...             # line 850
    async def create_dashboard(...) -> Dict[str, Any]: ...          # line 1088
    async def create_widget(...) -> Dict[str, Any]: ...             # line 1332
    async def clone_dashboard(...) -> Dict[str, Any]: ...           # line 1244
    async def assign_module_to_client(...) -> Dict[str, Any]: ...   # line 1536
    async def assign_module_to_group(...) -> Dict[str, Any]: ...    # line 1551
```

### Does NOT Exist
- ~~A pre-existing `test_navigator_toolkit_baseline.py`~~ — this task creates it.
- ~~A `confirm_execution=True` bypass flag on the toolkit~~ — it is a
  per-method parameter, not a toolkit attribute.

---

## Implementation Notes

### Fixture
```python
# packages/ai-parrot-tools/tests/unit/conftest.py
@pytest.fixture
def navigator_toolkit_factory(mocker):
    def _factory(user_id=1, is_superuser=True, **kwargs):
        tk = NavigatorToolkit(dsn="postgres://stub", user_id=user_id, **kwargs)
        tk._is_superuser = is_superuser
        tk._user_programs = set()
        tk._user_groups = {1}
        tk._user_clients = set()
        tk._user_modules = set()
        for name in ("insert_row", "upsert_row", "update_row",
                     "delete_row", "select_rows", "execute_query"):
            setattr(tk, name, mocker.AsyncMock())
        tk.transaction = mocker.MagicMock(
            return_value=_AsyncContextManager(conn=mocker.AsyncMock())
        )
        return tk
    return _factory
```

### Snapshot Strategy
Use `syrupy` or a simple on-disk `.json` fixture committed alongside
the test file. The 28 tool names and descriptions are captured **once**
and every subsequent migration task re-asserts byte equality.

---

## Acceptance Criteria

- [ ] `test_get_tools_names_unchanged_post_migration` green on main branch (before migration).
- [ ] Every write tool has a `confirm_execution=False` test asserting plan-dict return and zero DB calls.
- [ ] `navigator_toolkit_factory` fixture usable by later tasks.
- [ ] `upsert_row(update_cols=[])` SQL shape pinned by a new test in `test_postgres_toolkit.py`.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_toolkit_baseline.py -v` passes.
- [ ] `ruff check packages/ai-parrot-tools/tests/unit/` clean.

---

## Agent Instructions

Standard: read spec §4, verify contract, implement, run tests, move to
`completed/`, update index. Do NOT modify any toolkit method body —
tests only.
