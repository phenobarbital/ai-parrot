# TASK-2430: End-to-end integration suite for autonomous persistence

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2428, TASK-2429, TASK-2427
**Assigned-to**: unassigned
**Implements**: Spec section 4 Integration Tests

---

## Context

Proves the feature end to end, and in particular proves the guarantees that unit
tests structurally cannot: **exclusivity** (nothing lands in the generic table), **backwards
compatibility** (a form without `persistence` is unchanged), and the **fail-5xx** semantics
(nothing persisted anywhere on sink outage).

Implements the integration table in spec section 4.

---

## Scope

- Create `tests/integration/test_autonomous_persistence.py` covering all 13 scenarios from spec section 4: submit to own Postgres table; generic storage skipped; submit without persistence unchanged; CSV append; sink down -> 503; read on CSV form -> 501; read on Postgres form -> 200; new field adds column; removed field leaves column; merge_partials then sink write; autonomous form still listed; unknown alias rejected at registration; forwarder still runs alongside a sink write.
- Create shared fixtures in `tests/fixtures/persistence.py`: `alias_registry` (one DSN alias + one tmp_path base-dir alias), `survey_form_postgres` (with a GROUP and an ARRAY field), `survey_form_csv`, and `fake_pool` recording executed SQL.
- Assert exclusivity with a mock/spy on `FormSubmissionStorage.store`, not by observing an empty table.
- Mark tests needing a live Postgres appropriately (follow the existing suite's markers) so the suite stays runnable without a database.

**NOT in scope**: New production code - if a test cannot pass without a production change, that is a defect in the corresponding task; report it rather than patching production here. Performance benchmarks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_autonomous_persistence.py` | CREATE | 13 end-to-end scenarios |
| `packages/parrot-formdesigner/tests/fixtures/persistence.py` | CREATE | Shared fixtures |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today:
from parrot_formdesigner.services.registry import FormRegistry          # services/registry.py:240
from parrot_formdesigner.services.submissions import FormSubmissionStorage  # services/submissions.py:118
from parrot_formdesigner.api.handlers import FormAPIHandler             # api/handlers.py:108
from parrot_formdesigner.core.schema import FormSchema                  # core/schema.py:313
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import FormPersistenceConfig  # TASK-2417
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry # TASK-2418
from parrot_formdesigner.services.sinks.factory import SinkFactory      # TASK-2426
```

### Existing Signatures to Use

```python
# Existing test conventions in this package - READ THESE FIRST and match their style:
#   packages/parrot-formdesigner/tests/test_registry_read_through.py      - storage doubles for read-through
#   packages/parrot-formdesigner/tests/test_submission_jsonb_shape.py     - JSONB / codec assertions
#   packages/parrot-formdesigner/tests/test_submit_merge.py               - the ?merge_partials=true submit path
#   packages/parrot-formdesigner/tests/conftest.py                        - existing shared fixtures
#   packages/parrot-formdesigner/tests/integration/                       - where integration tests already live
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py:24 - partials are Redis-backed and keyed by
# (form_id, session_id), independent of the submissions table. The merge happens
# BEFORE the sink write.
class PartialSaveStore:
    def _redis_key(self, form_id: str, session_id: str) -> str: ...   # line 178
```

### Does NOT Exist

- ~~an existing integration test for persistence~~ - none exists; this task creates the file.
- ~~`tests/fixtures/persistence.py`~~ - does not exist yet. `packages/parrot-formdesigner/tests/fixtures/` DOES exist; add the module there.
- ~~a live Postgres in CI~~ - do not assume one. Gate DB-dependent tests behind the suite's existing marker convention (inspect `packages/parrot-formdesigner/tests/conftest.py` and `packages/parrot-formdesigner/pyproject.toml` for markers).
- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.

---

## Implementation Notes

### Pattern to Follow

Exclusivity must be asserted on the call, not inferred from state:

```python
async def test_submit_skips_generic_storage(handler, autonomous_form, post):
    handler._submission_storage.store = AsyncMock()
    resp = await handler.submit_data(post(autonomous_form))
    assert resp.status == 200
    handler._submission_storage.store.assert_not_called()   # <- the guarantee
```

Backwards compatibility is a regression assertion, not a smoke test:

```python
async def test_submit_without_persistence_unchanged(handler, plain_form, post):
    handler._submission_storage.store = AsyncMock()
    await handler.submit_data(post(plain_form))
    handler._submission_storage.store.assert_awaited_once()
```

### Key Constraints

- Exclusivity, backwards compatibility and fail-5xx are the three tests that must not be weakened - they encode the feature's contract.
- The suite must run green WITHOUT a live database; DB-dependent tests are marked.
- Reuse existing fixtures from `conftest.py` rather than duplicating them.
- No production code changes in this task.
- Use `tmp_path` for every CSV scenario - never write into the repo.

### References in Codebase

- `packages/parrot-formdesigner/tests/test_submit_merge.py` - the submit-path integration style to follow
- `packages/parrot-formdesigner/tests/test_registry_read_through.py` - storage doubles
- `packages/parrot-formdesigner/tests/test_submission_jsonb_shape.py` - JSONB assertions
- spec section 4 - the authoritative list of 13 scenarios

---

## Acceptance Criteria

- [ ] All 13 scenarios from spec section 4 are implemented as named tests
- [ ] `test_submit_skips_generic_storage` asserts `store` was NOT called
- [ ] `test_submit_without_persistence_unchanged` asserts `store` WAS called once
- [ ] `test_sink_down_returns_503` asserts 503 AND that nothing was persisted anywhere
- [ ] `test_new_field_adds_column` and `test_removed_field_leaves_column` both pass
- [ ] `test_merge_partials_then_sink_write` proves the merge happens before the write
- [ ] `test_autonomous_form_still_listed` proves listing and slug resolution still work
- [ ] `test_unknown_alias_rejected_at_registration` asserts 422 at registration, not at submit
- [ ] `test_forwarder_still_runs_with_persistence` proves both the forward and the sink write happen
- [ ] The full suite passes with no database available (DB tests skipped via marker)
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` fully green
- [ ] `ruff` clean on the new test files

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/integration/test_autonomous_persistence.py - scenario names are normative
class TestExclusivity:
    async def test_submit_to_own_postgres_table(...): ...
    async def test_submit_skips_generic_storage(...): ...
    async def test_submit_without_persistence_unchanged(...): ...

class TestCsvSink:
    async def test_submit_to_csv_appends_row(...): ...

class TestFailureSemantics:
    async def test_sink_down_returns_503(...): ...

class TestCapabilityGating:
    async def test_read_on_csv_form_returns_501(...): ...
    async def test_read_on_postgres_form_returns_200(...): ...

class TestProvisioning:
    async def test_new_field_adds_column(...): ...
    async def test_removed_field_leaves_column(...): ...

class TestInteractions:
    async def test_merge_partials_then_sink_write(...): ...
    async def test_autonomous_form_still_listed(...): ...
    async def test_unknown_alias_rejected_at_registration(...): ...
    async def test_forwarder_still_runs_with_persistence(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24
**Notes**: Created `tests/fixtures/persistence.py` (`alias_registry`,
`survey_form_postgres` with a GROUP and an ARRAY field,
`survey_form_csv`, `fake_pool` recording executed SQL — mirroring
TASK-2422's own fake-pool double) plus a `tests/integration/conftest.py`
re-exporting them (avoids a ruff F811 false-positive that direct
per-test-module imports of same-named fixtures trigger). Implemented all
13 named scenarios from spec section 4 in
`tests/integration/test_autonomous_persistence.py`, running entirely
without a live database: Postgres scenarios use a REAL
`PostgresTableSink` wired to `fake_pool`; CSV scenarios use a REAL
`CsvFileSink` writing into `tmp_path`; the submit-path is exercised
through the REAL `FormAPIHandler.submit_data()` (mocked registry/
validator only, per `test_submit_merge.py`'s established style) — a
`_SingleSinkFactory` test double stands in for the real `SinkFactory`
only because the real factory offers no pool-injection hook (out of
scope to add). Exclusivity and backwards-compatibility are asserted on
the `FormSubmissionStorage.store` mock call itself, never inferred from
state, per the task's own key constraint. `test_new_field_adds_column`/
`test_removed_field_leaves_column` reuse the SAME cached sink across two
`submit_data()` calls with different form field sets, proving additive
`ensure_target()` re-evaluation on a live submit path (not just a direct
sink unit test). `test_autonomous_form_still_listed` exercises
`FormRegistry` + `AutonomousFormStorage` + an in-memory `FormStorage`
double together. `test_forwarder_still_runs_with_persistence` proves
both the forward call and the sink write happen. Full package suite
re-run: still exactly the same 40 pre-existing failures before and after
(10 new passed + 3 new xfailed, zero regressions). `ruff` clean on all
three new files; `mypy` clean.

**Deviations from spec** (both explicitly sanctioned by the task's own
"NOT in scope: New production code — ... report it rather than patching
production here" instruction; no production code was touched):
1. **`test_read_on_csv_form_returns_501` / `test_read_on_postgres_form_returns_200`**
   marked `xfail(strict=True)`. Confirmed via `grep` (again, independently
   of TASK-2428's own finding): `FormAPIHandler` has NO `get_submission`/
   `list_revisions` HTTP endpoint anywhere in this codebase. There is
   nothing to call or gate on capabilities. A follow-up task must add
   these endpoints before this scenario pair can be implemented for real.
2. **`test_unknown_alias_rejected_at_registration`** marked
   `xfail(strict=True)`. Confirmed via `grep`/read: no production code
   path — not `FormSchema` validation (TASK-2421 only checks reserved-
   column collisions and identifier validity, never alias existence), not
   `FormRegistry.register()`, not anywhere else — validates a
   `persistence.data.connection` alias against the `SinkAliasRegistry`
   allowlist at registration time. The test asserts the DESIRED behavior
   (`pytest.raises(ValueError)`) and genuinely fails today, confirming the
   gap; it will need a small, separately-scoped production task (most
   naturally as a `FormSchema`/`FormRegistry.register()` validation hook)
   to close.

All three gaps are pre-existing holes in the task chain (present before
this task started), not introduced by this task, and are now precisely
documented with failing (`xfail`) tests rather than silently skipped or
worked around with new production code.
