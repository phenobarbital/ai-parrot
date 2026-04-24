# TASK-841: Integration tests — end-to-end pipeline against Postgres

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-835, TASK-838, TASK-839, TASK-840
**Assigned-to**: unassigned

---

## Context

End-to-end validation that the full submission pipeline works against a real Postgres (asyncpg
pool). Covers the success path, DLQ on failure, legacy-path parity, resolver warm-up, and
idempotent DDL migration. Spec §4 Integration Tests, §5 Acceptance Criteria.

---

## Scope

- Set up (or extend) an `asyncpg` pool fixture in `packages/parrot-formdesigner/tests/conftest.py`
  that provides an ephemeral Postgres DB (use the project's existing Postgres test infra — check
  `tests/conftest.py` first; if absent, document the DSN env var needed).
- Seed a minimal `FormRegistry` + `FormSchema` fixture (e.g., `form_id="db-form-test-01"`,
  `version="1.0"`, two fields).
- Write five integration tests (one per row in spec §4 Integration Tests):
  1. `test_end_to_end_pipeline_success_postgres` — POST valid payload, assert 200, assert DB row
     has metadata columns populated, assert NO DLQ row.
  2. `test_end_to_end_pipeline_failure_writes_dlq_postgres` — operator `post_validate` raises,
     assert 500 + `dlq_id`, assert NO row in `form_submissions`, assert exactly one row in
     `form_submissions_dlq` with the correct `stage` and error.
  3. `test_end_to_end_legacy_path_postgres` — wire routes without `operators` / `pydantic_resolver`,
     POST payload, assert today's response shape + flat JSONB row (new metadata cols NULL).
  4. `test_pydantic_resolver_warmup_against_real_registry` — load a couple of forms into the
     registry, run `resolver.warm_up(registry)`, assert every `(form_id, version)` resolves from
     cache without re-invoking codegen.
  5. `test_alter_table_migration_idempotent_postgres` — run `storage.initialize()` twice;
     assert no error; assert column set stable.

**NOT in scope**:
- Non-Postgres backends (spec §1 Non-Goals).
- Performance benchmarking.
- Load tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_submit_data_pipeline_e2e.py` | CREATE | Tests 1–3 |
| `packages/parrot-formdesigner/tests/integration/test_resolver_warmup_e2e.py` | CREATE | Test 4 |
| `packages/parrot-formdesigner/tests/integration/test_alter_migration_e2e.py` | CREATE | Test 5 |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | Add `pg_pool`, `form_registry`, `pg_form_submission_storage` fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All confirmed to resolve after TASKs 834–840 merge:
from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry
from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot.formdesigner.services.result_storage import FormResultStorage
from parrot.formdesigner.services.pydantic_resolver import PydanticModelResolver
from parrot.formdesigner.operators import FormOperator, OperatorContext, UserDetails
from parrot.formdesigner.core.schema import FormSchema
```

Runtime deps:

```python
import aiohttp  # for test client
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import asyncpg
import pytest
```

### Existing Signatures to Use

```python
# After TASK-835:
class FormSubmissionStorage(FormResultStorage):
    async def initialize(self) -> None: ...
    async def store(self, submission, *, conn=None) -> str: ...
    async def store_dlq(self, form_id, form_version, raw_payload, stage, error, traceback, correlation_id) -> str: ...

# After TASK-839:
class FormAPIHandler:
    def __init__(self, registry, client=None, submission_storage=None, forwarder=None, *, operators=None, pydantic_resolver=None): ...

# After TASK-840:
def setup_form_routes(app, *, registry=None, ..., operators=None, pydantic_resolver=None) -> None: ...
```

### Does NOT Exist
- ~~A bundled Postgres testcontainer fixture inside parrot-formdesigner~~ — before writing the
  fixture, grep repo-wide for existing fixtures (`grep -rn "asyncpg.*Pool" packages/parrot-formdesigner/tests`)
  and prefer reusing them. If none exist, require `PG_TEST_DSN` env var and `pytest.skip` when unset.
- ~~`aiohttp.test_utils.AioHTTPTestCase` pattern~~ — prefer `pytest-aiohttp`'s `aiohttp_client`
  fixture if the repo already uses it; otherwise build a `TestServer(app)` + `TestClient` by hand.
- ~~`pytest-postgresql`~~ — do not introduce as a new dep without checking current test deps.

---

## Implementation Notes

### Fixture sketch

```python
# packages/parrot-formdesigner/tests/conftest.py (add)
import os
import pytest
import asyncpg

@pytest.fixture
async def pg_pool():
    dsn = os.environ.get("PG_TEST_DSN")
    if not dsn:
        pytest.skip("PG_TEST_DSN not set")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    # clean tables at session start
    async with pool.acquire() as c:
        await c.execute("DROP TABLE IF EXISTS form_submissions_dlq;")
        await c.execute("DROP TABLE IF EXISTS form_submissions;")
    yield pool
    await pool.close()

@pytest.fixture
async def pg_form_submission_storage(pg_pool):
    from parrot.formdesigner.services.submissions import FormSubmissionStorage
    store = FormSubmissionStorage(pg_pool)
    await store.initialize()
    return store
```

### Test 1 — success path

```python
async def test_end_to_end_pipeline_success_postgres(
    pg_pool, pg_form_submission_storage, aiohttp_client,
):
    registry = FormRegistry()
    await registry.register(_sample_form_schema(), persist=False)

    app = web.Application()
    setup_form_routes(
        app,
        registry=registry,
        submission_storage=pg_form_submission_storage,
        operators=[UserDetails()],
    )
    client = await aiohttp_client(app)

    payload = {"name": "Alice", "age": 30}
    resp = await client.post("/api/v1/forms/db-form-test-01/data", json=payload)
    assert resp.status == 200
    body = await resp.json()
    assert body["is_valid"] is True
    assert "UserDetails" in body["operators_applied"]

    async with pg_pool.acquire() as c:
        row = await c.fetchrow(
            "SELECT * FROM form_submissions WHERE submission_id = $1",
            body["submission_id"],
        )
    assert row is not None
    # metadata columns populated (or None if no session — depends on fixture auth)
    dlq = await (pg_pool.fetchval("SELECT COUNT(*) FROM form_submissions_dlq"))
    assert dlq == 0
```

### Test 2 — DLQ on failure

Use a recording operator that raises in `post_validate`. Assert 500, `dlq_id` in body, zero rows
in `form_submissions`, exactly one row in `form_submissions_dlq` with `stage="post_validate"`.

### Test 3 — legacy parity

Wire `setup_form_routes(app, registry=..., submission_storage=...)` **without** operators and
resolver. POST the same payload. Assert response shape matches today's 200 body (no
`operators_applied` key, no `status` enrichment field).

### Test 4 — resolver warm-up

Load 2–3 FormSchemas, call `resolver.warm_up(registry)`, then call `resolver.resolve(...)` and
assert the class came from the cache (introspect `resolver._cache` or spy `_generate`).

### Test 5 — DDL idempotency

Call `storage.initialize()` twice against the same pool. Assert no error; assert the column set
of `form_submissions` matches the expected set after both runs.

### Key Constraints
- All integration tests MUST be skipped when `PG_TEST_DSN` is not set — never fail CI because
  Postgres is unavailable.
- Use `aiohttp_client` fixture from `pytest-aiohttp` if available; fall back to manual
  `TestServer`/`TestClient` otherwise.
- Clean up tables between tests (or use a per-test transaction that rolls back).
- No hard-coded DSN values; always read from env.

### References in Codebase
- Any existing `asyncpg` test fixtures in `packages/*/tests/conftest.py` — reuse if present.
- Spec §4 Integration Tests — the authoritative list.

---

## Acceptance Criteria

- [ ] All five integration tests implemented.
- [ ] Tests skip cleanly when `PG_TEST_DSN` is not set (no failure).
- [ ] Tests pass when `PG_TEST_DSN` points to an empty Postgres:
      `PG_TEST_DSN=postgres://... pytest packages/parrot-formdesigner/tests/integration/ -v`.
- [ ] No regressions in pre-existing unit tests.
- [ ] `ruff check packages/parrot-formdesigner/tests/integration/` clean.

---

## Test Specification

See the five tests described above. Each should follow the pattern:
1. Arrange fixtures (registry, storage, pool, app).
2. Act via `aiohttp_client.post(...)` or direct `storage.initialize()` calls.
3. Assert on response + DB state.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§4 Integration Tests, §5 AC).
2. **Check dependencies** — TASK-835, TASK-838, TASK-839, TASK-840 in `completed/`.
3. **Verify the Codebase Contract** — especially check for existing `pg_pool` fixtures in the
   repo before writing your own.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** fixtures + five integration tests.
6. **Verify** all acceptance criteria (run locally with `PG_TEST_DSN` set).
7. **Move this file** to `sdd/tasks/completed/TASK-841-integration-tests-postgres.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
