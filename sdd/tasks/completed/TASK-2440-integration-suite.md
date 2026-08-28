# TASK-2440: End-to-end integration suite for the unknown-fields policy

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2436, TASK-2437, TASK-2438, TASK-2439
**Assigned-to**: unassigned
**Implements**: Spec section 4 Integration Tests

---

## Context

The unit tests in TASK-2432…2439 each prove one layer. This task proves the
claims that only hold when the layers are assembled — above all the two that are
the feature's whole justification:

- **`drop` is byte-identical to pre-FEAT-458** (spec AC1). Everything else in this
  feature is worthless if the default silently changed behaviour.
- **A `persistence:` form captures extras too** (spec AC14). This is the
  half-working failure mode FEAT-458 exists to avoid, and it can only be observed
  end-to-end because the exclusivity branch lives in the handler.

Also the one that a mocked unit test structurally cannot catch: the
codec-registered-pool JSONB round trip (spec AC13), which is how a real deployment
differs from a test double.

Implements spec section 4 Integration Tests.

---

## Scope

- Create `packages/parrot-formdesigner/tests/integration/test_unknown_fields_e2e.py`
  covering the eight integration tests named in the spec:
  `test_e2e_keep_stores_and_forwards`, `test_e2e_drop_is_byte_identical_to_baseline`,
  `test_e2e_legacy_table_gains_column_on_initialize`, `test_e2e_reject_blocks_submission`,
  `test_e2e_persistence_form_captures_extras`, `test_e2e_partial_then_merge_partials_submit`,
  `test_e2e_codec_registered_pool_roundtrip`, `test_e2e_audio_ws_submission_unaffected`.
- Run against a real Postgres table (follow whatever fixture the package's existing
  `tests/integration/` suite uses to provision one — do NOT invent a new harness)
  and a stub HTTP endpoint for the forwarder.
- For `test_e2e_legacy_table_gains_column_on_initialize`: create the table WITHOUT
  `extra_data` (simulate a pre-FEAT-458 schema), insert a row, run `initialize()`,
  then assert the column exists, the legacy row reads back with `extra_data is None`,
  and no data was lost.
- For `test_e2e_codec_registered_pool_roundtrip`: register a json codec on the pool
  (the condition that caused the 2026-08-14 defect recorded at
  `services/submissions.py:255-273`) and assert
  `jsonb_typeof(extra_data) = 'object'` in SQL and a `dict` from
  `_row_to_submission`.
- For `test_e2e_persistence_form_captures_extras`: parametrize over a tabular and a
  document sink driver, asserting extras land in the sink and that
  `navigator.form_data` has **no** row for that submission.
- Add a short `README`-style module docstring stating which spec ACs each test
  covers, so a future reader can map a failure to a requirement.

**NOT in scope**: Any production-code change. If a test fails because of a
defect, fix it in the owning task's file and note it in that task's Completion
Note — do not patch production code from this task. New unit tests (they belong to
their module's task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_unknown_fields_e2e.py` | CREATE | The eight end-to-end tests |
| `packages/parrot-formdesigner/tests/integration/conftest.py` | MODIFY | Add only fixtures the suite needs, reusing existing ones |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import, fixture, or harness.

### Verified Imports

```python
# All landed by the time this task runs (TASK-2432/2433/2434/2435):
from parrot_formdesigner.core.schema import FormSchema, UnknownFieldsPolicy
from parrot_formdesigner.services.submissions import (
    DEFAULT_SCHEMA, DEFAULT_TABLE, FormSubmission, FormSubmissionStorage,
)
from parrot_formdesigner.services.unknown_fields import MAX_EXTRA_KEYS, MAX_EXTRA_BYTES
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

# PLANNED — FEAT-457. Verify before importing:
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission
```

### Existing Signatures to Use

```python
# services/submissions.py:31-32
DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "form_data"

# services/submissions.py:118
class FormSubmissionStorage:
    def __init__(self, pool: Any, *, schema: str = DEFAULT_SCHEMA,
                 table_name: str = DEFAULT_TABLE, tenant: str | None = None): ...
    async def initialize(self, *, tenant: str | None = None) -> None: ...   # line 289
    #   Runs _create_table_sql THEN _alter_table_sql (:301-303) — this is the
    #   entire migration path; the legacy-table test drives THIS method.
    async def store(self, submission: FormSubmission, *,
                    tenant: str | None = None) -> str: ...                 # line 308
    _SELECT_COLUMNS: str                                                   # line 372
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...                # line 380
    #   Read paths using _SELECT_COLUMNS: :435 (by submission_id), :464 (list)

# The reason test_e2e_codec_registered_pool_roundtrip exists — verbatim from
# services/submissions.py:255-273:
#   "`$n::text::jsonb`, NOT a bare `$n`: ... a HOST-provided pool may register a
#    json/jsonb codec (encoder=json.dumps) — which then re-encodes the value,
#    storing a double-encoded jsonb STRING instead of an object
#    (`jsonb_typeof = 'string'`) ... Measured 2026-08-14 against a FieldSync
#    (codec-registered) pool: both live submissions stored `data` and `context`
#    as strings, and `get_submission` then raised `ValidationError` reading back
#    its own rows."

# api/handlers.py — the routes under test
async def submit_data(self, request) -> web.Response: ...   # line 1440
async def validate(self, request) -> web.Response: ...      # line 993
async def save_partial(self, request) -> web.Response: ...  # line 530
#   merge_partials is a QUERY PARAM: ?merge_partials=true (:1502)
#   Partial storage is field_uid-keyed (TASK-2003); the handler remaps to
#   field_ids via self._remap_partial_to_field_ids before merging (:1514)

# api/audio_ws.py:1115 — the path that must stay unaffected
async def _finish_session(self, ws, session) -> None: ...
#   Builds data={fid: a.value for fid, a in session.answers.items()} (:1143)
#   from MANIFEST-keyed answers, never a client payload, then store() at :1149.
#   Therefore extra_data is correctly None with no code change.
```

### Does NOT Exist

- ~~A FEAT-458-specific DB fixture~~ — reuse the package's existing
  `tests/integration/` Postgres fixture. `grep` `tests/integration/conftest.py`
  first; do not stand up a new container harness.
- ~~A revision-insert path~~ — only `store()` writes rows. Only two callers:
  `api/handlers.py:1617` and `api/audio_ws.py:1149`.
- ~~A standalone migration script for `form_data`~~ — `initialize()` is the
  migration path.
- ~~`extra_data` on the audio path~~ — it stays `None`; assert that, do not add it.
- ~~A per-form cap override to exercise~~ — caps are module-level constants.

---

## Implementation Notes

### Pattern to Follow

```python
# The baseline test is the most important one in this file. Capture the row and the
# response for a DEFAULT (drop) form and assert nothing moved (spec AC1).
async def test_e2e_drop_is_byte_identical_to_baseline(client, drop_form, db):
    payload = {"name": "Ana", "junk": 1, "_client_ms": 1180}
    resp = await client.post(f"/api/v1/forms/{drop_form.form_uid}/submit", json=payload)
    body = await resp.json()

    row = await db.fetchrow(
        "SELECT data, extra_data FROM navigator.form_data WHERE submission_id = $1",
        body["submission_id"],
    )
    assert resp.status == 200
    assert set(body) == {"submission_id", "is_valid", "forwarded",
                         "forward_status", "forward_error"}   # response shape unchanged
    assert json.loads(row["data"]) == {"name": "Ana"}         # extras absent from data
    assert row["extra_data"] is None                          # and not captured
```

### Key Constraints

- **Assert on the DB, not only on the API response.** The bug this feature fixes is
  invisible from the response — that is the entire point.
- The legacy-table test must build the table without `extra_data` explicitly
  (e.g. run `_create_table_sql` output with the column stripped, or a hand-written
  CREATE), so it genuinely exercises `ADD COLUMN IF NOT EXISTS`.
- Use `MAX_EXTRA_KEYS` / `MAX_EXTRA_BYTES` from the module — never hardcode 256 in
  a test, or the suite will silently stop testing the real boundary if the constant
  changes.
- Mark tests requiring Postgres with whatever skip/marker the existing integration
  suite uses, so a developer without a database still gets a green unit run.
- `pytest-asyncio` throughout; no blocking I/O in an async test.

### References in Codebase

- `packages/parrot-formdesigner/tests/integration/` — the existing suite; copy its
  fixture and marker conventions.
- `packages/parrot-formdesigner/tests/integration/test_upload_rest.py` — a
  substantial existing integration test to model structure on.
- `services/submissions.py:255-273` — why the codec test exists.

---

## Acceptance Criteria

- [ ] All eight named tests exist and pass.
- [ ] `test_e2e_drop_is_byte_identical_to_baseline` asserts the stored `data`, the
      `extra_data` NULL, AND the response body shape (spec AC1).
- [ ] `test_e2e_keep_stores_and_forwards` asserts extras in `extra_data`, `data`
      free of undeclared keys, and the forwarded body flat-merged (spec AC4, AC12).
- [ ] `test_e2e_legacy_table_gains_column_on_initialize` starts from a table with no
      `extra_data`, and after `initialize()` the column exists and the pre-existing
      row reads back with `extra_data is None` (spec AC3).
- [ ] `test_e2e_reject_blocks_submission` asserts `422`, `errors["__unknown__"]`,
      `onError` fired, and zero rows written (spec AC7).
- [ ] `test_e2e_persistence_form_captures_extras` is parametrized over a tabular and
      a document driver, and asserts `navigator.form_data` has no row (spec AC14).
- [ ] `test_e2e_codec_registered_pool_roundtrip` asserts
      `jsonb_typeof(extra_data) = 'object'` and a `dict` from the read path (spec AC13).
- [ ] `test_e2e_partial_then_merge_partials_submit` asserts `/partial` still rejects
      unknown `field_id`s while `/submit?merge_partials=true` captures extras (spec AC17).
- [ ] `test_e2e_audio_ws_submission_unaffected` asserts `extra_data IS NULL` for a
      WebSocket submission (spec AC18).
- [ ] Cap boundaries are asserted via the imported constants, not literals.
- [ ] Suite passes: `pytest packages/parrot-formdesigner/tests/integration/test_unknown_fields_e2e.py -v`
- [ ] Full suite green: `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/tests/integration/test_unknown_fields_e2e.py`

---

## Test Specification

> The eight tests ARE this task's deliverable; their names and assertions are
> enumerated in Scope and Acceptance Criteria above. Structure the module as:

```python
"""End-to-end tests for the FEAT-458 unknown-fields policy.

Spec AC coverage:
  AC1  test_e2e_drop_is_byte_identical_to_baseline
  AC3  test_e2e_legacy_table_gains_column_on_initialize
  AC4  test_e2e_keep_stores_and_forwards
  AC7  test_e2e_reject_blocks_submission
  AC12 test_e2e_keep_stores_and_forwards
  AC13 test_e2e_codec_registered_pool_roundtrip
  AC14 test_e2e_persistence_form_captures_extras
  AC17 test_e2e_partial_then_merge_partials_submit
  AC18 test_e2e_audio_ws_submission_unaffected
"""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-26
**Notes**: Corrected a stale Codebase Contract assumption FIRST (per Agent
Instructions step 3): `tests/integration/` in this package tests WITHOUT a
live database throughout (verified by inspection — `conftest.py` only
re-exports fake-pool fixtures from `tests/fixtures/persistence.py`, and
every existing file in that directory, e.g. `test_autonomous_persistence.py`,
explicitly documents "Postgres scenarios use a fake asyncpg-pool"). The
package's actual real-Postgres convention (`SCRATCH_DSN` env var +
`pytest.mark.skipif`, dedicated disposable schema, drop-on-teardown) lives
in top-level `tests/` (`test_submission_jsonb_shape.py`,
`test_jsonb_object_storage.py`) — the exact precedent this task's own
References section points at for the codec hazard. Followed that
precedent instead (module-level skip, schema `pfd_unknown_fields_e2e_test`,
create/drop-cascade per test via a `pool` fixture), placing the file at
the path the Files table specifies.

Implemented all 8 named tests plus 2 extra cap-boundary tests (over/at
`MAX_EXTRA_KEYS`, imported from `services.unknown_fields`, never
hardcoded). Called `submit_data`/`validate`/`save_partial` directly on a
`FormAPIHandler` built with a real (unmocked) `FormValidator` (its default
per `__init__`), a real `FormSubmissionStorage` against the scratch
schema, a real `SubmissionForwarder` against a stub `aiohttp_server`
(pytest-aiohttp, already a project dependency — confirmed by the
`aiohttp-1.1.1` plugin already active in the suite's own pytest output),
and a real `PostgresTableSink` (pool passed directly, bypassing DSN/alias
resolution) for the tabular leg of the persistence-sink test. For the
document leg, used a fake `AbstractSubmissionSink` double (matching
FEAT-457's own `_FakeSink` pattern from `test_submit_path_branch.py`) —
no live Mongo/Arango container exists in this repo's test infra (verified:
only Postgres and Redis containers running locally), and the property
under test (exclusivity: nothing written to `form_data`) is independent
of which document driver receives the write. For the partial+merge test,
reused FEAT-393's own `InMemoryPartialStore` pattern (a real
`PartialSaveStore` subclass backed by an in-memory fake Redis client,
copied from `tests/unit/api/test_partial_saves_uid.py`) — exercises the
real save/merge logic without a live Redis dependency. For the audio-path
test, called `AudioFormWSHandler._finish_session` directly (bypassing WS
protocol framing) against a real `FormSubmissionStorage`.

**Verification**: ran the full suite against the locally running
`docker-postgres-1` container (`SCRATCH_DSN=postgresql://postgres:***@
localhost:5432/postgres`, disposable schema, confirmed dropped after the
run via `\dn` — no trace left in the shared dev database) — all 11 tests
passed for real, not just skipped. Also ran without `SCRATCH_DSN` — all
11 skip cleanly (`11 skipped`), satisfying "a developer without a
database still gets a green unit run." One production-adjacent bug was
found in my OWN test fixture, not production code (`test_e2e_
legacy_table_gains_column_on_initialize`'s hand-written legacy DDL was
missing several columns `_create_table_sql`'s trailing `CREATE INDEX`
statements reference), fixed in the test file per this task's own "fix
test bugs here, production defects in the owning task" rule — no
production code was touched by this task. Full-suite regression
(`git stash` diff, without `SCRATCH_DSN`): zero new failures. `ruff
check`: clean (0 findings after `--fix` on import ordering/`datetime.UTC`,
matching the file's own new-code style, not touching any other file).

**Deviations from spec**: `tests/integration/conftest.py` was NOT
modified. The Files table listed it for "fixtures the suite needs,
reusing existing ones," but nothing in `conftest.py` (fake-pool-only
fixtures) is relevant to a real-DB suite, and no other file in
`tests/integration/` shares this suite's real-Postgres concern to
justify a shared fixture — the closest actual precedent
(`test_submission_jsonb_shape.py`) keeps its `pool` fixture entirely
local to itself for the same reason. Kept `pool`/`storage` local to
`test_unknown_fields_e2e.py` instead of adding an unused shared fixture
to `conftest.py`.
