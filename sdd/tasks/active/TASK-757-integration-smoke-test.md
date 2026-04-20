# TASK-757: End-to-end integration smoke test against live Postgres

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-747, TASK-748, TASK-749, TASK-750, TASK-751, TASK-752, TASK-753, TASK-754, TASK-755, TASK-756
**Assigned-to**: unassigned

---

## Context

Implements **Module 10** of the spec. The unit tests mock the CRUD
primitives; this integration test drives the full `create_program →
create_module → create_dashboard → create_widget → update_widget →
clone_dashboard` chain against a real Postgres instance, proving row
counts, idempotency, and transactional rollback end-to-end.

---

## Scope

Create `tests/integration/test_navigator_toolkit_migration.py`:

- `pytest.skip` when `NAVIGATOR_DSN` env var is absent.
- Drive the full create chain on a scratch `program_slug`, asserting
  row counts in:
  - `auth.programs`, `auth.program_clients`, `auth.program_groups`
  - `navigator.modules`, `navigator.client_modules`, `navigator.modules_groups`
  - `navigator.dashboards`, `navigator.widgets`
- Idempotency: call `create_program` twice with the same slug; second
  call returns `already_existed=True`; no duplicate rows in
  `program_clients`, `program_groups`.
- Rollback: monkey-patch `PostgresToolkit.upsert_row` to raise after
  the first successful write inside `create_module`; assert program
  has no module row.
- Tear down by deleting the scratch program + cascade.

**NOT in scope**: any unit-test changes; any CI pipeline change; any
production-data touching.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/integration/test_navigator_toolkit_migration.py` | CREATE | End-to-end smoke test |
| `packages/ai-parrot-tools/tests/integration/conftest.py` | MODIFY (if exists) | Add `navigator_dsn` fixture |

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
class NavigatorToolkit(PostgresToolkit):
    _NAVIGATOR_TABLES: List[str] = [                                     # 59-73
        "auth.programs", "auth.program_clients", "auth.program_groups",
        "auth.clients", "auth.groups", "auth.user_groups",
        "navigator.modules", "navigator.client_modules",
        "navigator.modules_groups",
        "navigator.dashboards", "navigator.widgets",
        "navigator.widgets_templates", "navigator.widget_types",
    ]

    async def create_program(..., confirm_execution: bool = False): ...  # 657
    async def create_module(..., confirm_execution: bool = False): ...   # 850
    async def create_dashboard(..., confirm_execution=False): ...        # 1088
    async def create_widget(..., confirm_execution=False): ...           # 1332
    async def clone_dashboard(..., confirm_execution=False): ...         # 1244
    async def update_widget(widget_id, confirm_execution=False, **kw): ...  # 1440
```

### Does NOT Exist
- ~~A pre-existing integration harness for NavigatorToolkit~~ — this task creates it.
- ~~`NAVIGATOR_TEST_DSN` env var~~ — the fixture key is `NAVIGATOR_DSN`.

---

## Implementation Notes

### Fixture
```python
@pytest.fixture
def navigator_dsn():
    dsn = os.environ.get("NAVIGATOR_DSN")
    if not dsn:
        pytest.skip("NAVIGATOR_DSN not set; integration tests skipped.")
    return dsn
```

### Cleanup Strategy
Use a unique scratch slug per test run (e.g., prefixed with a UUID4
hex) so parallel test runs do not collide. Tear down via a `DELETE
FROM auth.programs WHERE program_slug LIKE 'feat107_%'` at teardown.

### Rollback Simulation
```python
async def test_transaction_rollback_on_mid_flow_failure(toolkit, monkeypatch):
    original = toolkit.upsert_row
    calls = {"n": 0}
    async def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # second write inside create_module
            raise RuntimeError("simulated failure")
        return await original(*args, **kwargs)
    monkeypatch.setattr(toolkit, "upsert_row", boom)
    with pytest.raises(RuntimeError):
        await toolkit.create_module(..., confirm_execution=True)
    # Assert no orphan row
    rows = await toolkit.select_rows("navigator.modules",
        where={"program_id": pid}, columns=["module_id"])
    assert rows == []
```

---

## Acceptance Criteria

- [ ] Test skips cleanly when `NAVIGATOR_DSN` is unset.
- [ ] `test_end_to_end_program_module_dashboard_widget` passes with correct row counts across 8 tables.
- [ ] `test_transaction_rollback_on_mid_flow_failure` passes — no orphan `navigator.modules` row after simulated failure.
- [ ] `test_confirm_execution_plan_then_confirm_materializes_rows` passes — plan-only call creates zero rows; `confirm_execution=True` materializes them.
- [ ] `test_update_dashboard_pk_enforcement_unchanged` passes — FEAT-106 PK-in-WHERE regression guard still green.
- [ ] Teardown leaves zero scratch rows in any of the 8 tables.
- [ ] `ruff check packages/ai-parrot-tools/tests/integration/` clean.

---

## Test Specification

All four tests from spec §4 "Integration Tests" table.

---

## Agent Instructions

Standard. If `NAVIGATOR_DSN` is unavailable locally, run the test file
with `pytest -v --tb=short` and confirm the `skip` markers print
cleanly. Document in the completion note which tests were actually
executed against live Postgres vs. skipped.
