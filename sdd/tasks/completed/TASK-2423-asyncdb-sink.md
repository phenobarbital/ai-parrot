# TASK-2423: `AsyncDBSink` - Mongo / Arango (nested) and BigQuery (tabular)

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2418, TASK-2419, TASK-2420
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 7

---

## Context

Reaches the rest of the stores the workspace already talks to, at almost no
dependency cost - `asyncdb>=2.0` is already a direct dependency of this package
(`packages/parrot-formdesigner/pyproject.toml:36`).

The mapping mode is driver-dependent (spec section 8, resolved): document drivers store `data`
**nested**; tabular drivers flatten.

Implements spec section 3 Module 7.

---

## Scope

- Create `services/sinks/asyncdb_store.py` with `AsyncDBSink(AbstractSubmissionSink)`.
- Classify the configured `driver` as document (`mongo`, `arango`) or tabular (`bigquery`), and select `nest_submission` or `flatten_submission` accordingly.
- Compute `capabilities` per driver - document drivers get `{WRITE, READ, LIST, PROVISION}`; declare `EXTEND` only where the driver genuinely supports additive schema change.
- Implement `ensure_target(form)` per driver (create collection / dataset table when absent).
- Implement `write`, and `read` / `list_revisions` where the driver supports them.
- Resolve credentials via `SinkAliasRegistry`; map driver/transport failures to `SinkUnavailableError`.
- Guard the `asyncdb` driver imports so an uninstalled extra yields a clear error rather than an ImportError at module import.
- Write unit tests in `tests/unit/test_asyncdb_sink.py` with a fake asyncdb driver.

**NOT in scope**: Registration in the dispatch table (TASK-2426). Postgres - that is TASK-2422 via asyncpg directly. Adding new asyncdb extras to `pyproject.toml`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/asyncdb_store.py` | CREATE | asyncdb-backed sink |
| `packages/parrot-formdesigner/tests/unit/test_asyncdb_sink.py` | CREATE | Unit tests with a fake driver |

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
# Verified to resolve today (asyncdb is a DIRECT dependency: pyproject.toml:36):
from asyncdb import AsyncDB          # verify the exact symbol with:
                                     #   python -c "import asyncdb; print(dir(asyncdb))"
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.submissions import FormSubmission
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import SinkCapability, AsyncDBTarget       # TASK-2417
from parrot_formdesigner.services.sinks.base import (                                # TASK-2419
    AbstractSubmissionSink, SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import (                              # TASK-2420
    flatten_submission, nest_submission, column_names_for,
)
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry              # TASK-2418
```

> WARNING: **Verify the `asyncdb` API surface before writing code.** This spec did not pin
> `AsyncDB`'s constructor or method names. Run the `python -c` above and read the installed
> package; do not assume `AsyncDB(driver, dsn=...)` or `.insert()` exist.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/__init__.py:6 - the driver-name vocabulary used
# elsewhere in this workspace (mirror these keys where they overlap):
supported_stores = {'postgres': 'PgVectorStore', 'milvus': 'MilvusStore',
                    'kb': 'KnowledgeBaseStore', 'faiss_store': 'FaissStore',
                    'arango': 'ArangoStore', 'bigquery': 'BigQueryStore'}
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str          # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID         # REQUIRED (FEAT-389 / TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime        # default_factory -> datetime.now(timezone.utc)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None
```

### Does NOT Exist

- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ - no sink abstraction exists anywhere in `parrot-formdesigner` before TASK-2419. `FormSubmissionStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118`) is a **plain class, NOT an ABC** - there is no existing interface to implement.
- ~~a formdesigner-side asyncdb wrapper~~ - nothing in `parrot-formdesigner` wraps `asyncdb` today. `pyproject.toml:36` declares the dependency but grep finds no usage in `services/`; verify with `grep -rn asyncdb packages/parrot-formdesigner/src/parrot_formdesigner` before assuming a helper exists.
- ~~`parrot.stores.AbstractStore`~~ - that lives in the `ai-parrot` distribution, which is an OPTIONAL extra of this package (`pyproject.toml:50-52`). Do NOT import it; this sink must work with `parrot-formdesigner` installed alone.
- ~~`python-datamodel`~~ - not a dependency of `parrot-formdesigner` (it belongs to `ai-parrot`). Do not reach for dynamic model generation.

---

## Implementation Notes

### Pattern to Follow

Driver classification decides the mapping mode - this is the whole point of the task:

```python
DOCUMENT_DRIVERS = frozenset({"mongo", "arango"})
TABULAR_DRIVERS = frozenset({"bigquery"})

def _payload(self, form, submission):
    if self._target.driver in DOCUMENT_DRIVERS:
        return nest_submission(form, submission)      # data stays nested
    return flatten_submission(form, submission)       # parent__child, ARRAY as JSON
```

### Key Constraints

- Document drivers must NOT flatten - that is an explicit product decision (spec section 8).
- `capabilities` is computed per driver, not hardcoded for the class.
- Driver imports guarded; a missing extra produces an actionable message naming the extra.
- All credentials via `SinkAliasRegistry` - never a DSN from the target model.
- Async throughout; close driver connections in `close()`.
- Verify every `asyncdb` symbol against the installed package before use.

### References in Codebase

- `packages/ai-parrot/src/parrot/stores/__init__.py:6` - driver-name vocabulary
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/postgres_table.py` - sibling sink written in TASK-2422; match its shape
- `packages/parrot-formdesigner/pyproject.toml:36` - `asyncdb>=2.0` is already available

---

## Acceptance Criteria

- [ ] `capabilities` differs between a document driver and a tabular driver
- [ ] A `mongo` target stores `data` nested (asserted on the payload handed to the driver)
- [ ] A `bigquery` target stores a flattened row
- [ ] A simulated driver failure raises `SinkUnavailableError`
- [ ] Importing the module with the driver extra absent does not raise
- [ ] Every `asyncdb` symbol used is confirmed to exist in the installed package
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_asyncdb_sink.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_asyncdb_sink.py
import pytest

from parrot_formdesigner.core.persistence import SinkCapability
from parrot_formdesigner.services.sinks.base import SinkUnavailableError


class TestMappingMode:
    async def test_document_driver_nests(self, mongo_sink, fake_driver, form, submission):
        await mongo_sink.write(submission, None)
        payload = fake_driver.written[-1]
        assert payload["data"] == submission.data
        assert not any("__" in k for k in payload)

    async def test_tabular_driver_flattens(self, bigquery_sink, fake_driver, form_with_group, submission):
        await bigquery_sink.write(submission, None)
        assert any("__" in k for k in fake_driver.written[-1])


class TestCapabilities:
    def test_document_driver_capability_set(self, mongo_sink):
        assert SinkCapability.WRITE in mongo_sink.capabilities
        assert SinkCapability.EXTEND not in mongo_sink.capabilities


class TestFailure:
    async def test_driver_error_maps_unavailable(self, broken_sink, submission):
        with pytest.raises(SinkUnavailableError):
            await broken_sink.write(submission, None)
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
**Notes**: Verified the installed `asyncdb` API surface directly (per the
task's explicit warning) before writing any code:
`asyncdb.AsyncDB(driver=..., dsn=...)` factory `__new__`; real per-driver
methods `mongo.insert`/`list_collections`/`create_collection`/`fetch_one`;
`arangodb.insert_document`/`collection_exists`/`create_collection`/`query`;
`bigquery.write`/`create_table`/`query`. Implemented `AsyncDBSink` with
driver classification (`DOCUMENT_DRIVERS = {mongo, arango}`,
`TABULAR_DRIVERS = {bigquery}`), capabilities computed per driver
(`{WRITE,READ,LIST,PROVISION}` + `EXTEND` only for bigquery),
`ensure_target`/`write`/`read`/`list_revisions` dispatching to each
driver's real method names, guarded lazy imports (`asyncdb`,
`google.cloud.bigquery`) mapping failures to `SinkUnavailableError`.
`write()` computes its own payload via `nest_submission`/
`flatten_submission` when called with `payload=None` (per the task's
"Pattern to Follow"), using a form cached from the most recent
`ensure_target()` call (or supplied via an optional constructor kwarg for
convenience/tests). 8 unit tests in `tests/unit/test_asyncdb_sink.py`
using a fake driver double implementing the verified real method names,
covering: document nesting, tabular flattening, per-driver capability
sets, driver-failure mapping, and clean module import. `ruff` and
targeted `mypy` clean.

**Deviations from spec**: `AsyncDBTarget.collection` is validated via
`validate_identifier()` at construction (TASK-2417 — no dots allowed),
which contradicts the spec's own docstring sketch of
`"<dataset_id>.<table_id>"` for BigQuery. Resolved by using the tenant as
the BigQuery dataset id (`dataset_id = tenant`) and `collection` as the
table id — consistent with how tenant already scopes the Postgres schema
elsewhere in this package. Documented in the module docstring and
`_split_bigquery_collection()`. Did not modify `core/persistence.py`
(TASK-2417) since a single validated identifier field is the more
conservative, already-locked-in contract.
