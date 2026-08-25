# TASK-2426: Sink dispatch table, `SinkFactory` and coordinate immutability

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2422, TASK-2423, TASK-2424, TASK-2425
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 10

---

## Context

The single place that knows which sink class serves which `type`, and the single
owner of `services/sinks/__init__.py` - deliberately, so the four sink tasks share no file.

It also enforces the **coordinate-immutability** rule resolved in spec section 8: a form's
destination coordinates (schema/table/path/sheet id) freeze once data exists. Only the
mapping may evolve. That rule is what keeps a form's history in one place forever and is why
`promote()` needs no changes.

Implements spec section 3 Module 10.

---

## Scope

- Fill in `services/sinks/__init__.py`: `SUPPORTED_SINKS: dict[str, str]` mapping `postgres_table|asyncdb|csv_file|gsheet` -> class name, with lazy import (following `parrot/stores/__init__.py:6`).
- Re-export the public sink names (`AbstractSubmissionSink`, the error types, `SinkFactory`).
- Implement `SinkFactory` with `get(form, *, tenant) -> AbstractSubmissionSink`, caching per `(tenant, form_uid, version)`.
- Implement a destination **fingerprint** (a stable hash of the target's coordinates, excluding mapping-only fields) and persist/compare it, raising `SinkTargetMismatchError` when a form's coordinates change after data exists.
- Implement `close_all()` closing every cached sink, for app shutdown.
- Write unit tests in `tests/unit/test_sink_factory.py`.

**NOT in scope**: Any sink implementation. Handler integration (TASK-2428). App wiring (TASK-2429). Deciding *where* the fingerprint is stored if a DB round-trip is needed - keep it in the target table's own metadata or the factory cache, and record the choice in the completion note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/__init__.py` | MODIFY | Dispatch table + re-exports (was an empty marker) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/factory.py` | CREATE | SinkFactory + fingerprint |
| `packages/parrot-formdesigner/tests/unit/test_sink_factory.py` | CREATE | Unit tests |

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
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import (                     # TASK-2417
    FormPersistenceConfig, SubmissionTarget,
)
from parrot_formdesigner.services.sinks.base import (                  # TASK-2419
    AbstractSubmissionSink, SinkTargetMismatchError,
)
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry # TASK-2418
# Verified to resolve today:
from parrot_formdesigner.core.schema import FormSchema                  # core/schema.py:313
import hashlib, importlib, json
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/__init__.py:6 - the dispatch-table precedent to follow
# (string keys -> class NAMES, resolved lazily so an uninstalled backend costs nothing):
supported_stores = {'postgres': 'PgVectorStore', 'milvus': 'MilvusStore',
                    'kb': 'KnowledgeBaseStore', 'faiss_store': 'FaissStore',
                    'arango': 'ArangoStore', 'bigquery': 'BigQueryStore'}
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:313 - the cache key components
class FormSchema(BaseModel):
    form_uid: uuid.UUID    # line 356 - immutable identity
    version: str = "1.0"   # line 358
    tenant: str | None     # line 366
```

### Does NOT Exist

- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ - no sink abstraction exists anywhere in `parrot-formdesigner` before TASK-2419. `FormSubmissionStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118`) is a **plain class, NOT an ABC** - there is no existing interface to implement.
- ~~`services/sinks/__init__.py` already containing a registry~~ - TASK-2419 created it as an EMPTY package marker. This task is what fills it.
- ~~a global sink singleton~~ - do not add module-level mutable state. `SinkFactory` is instantiated once by the app (TASK-2429) and passed in explicitly.
- ~~eager imports of all four sinks~~ - that would make `[gsheet]` effectively mandatory. Resolve class names lazily.

---

## Implementation Notes

### Pattern to Follow

Lazy dispatch, mirroring `parrot/stores/__init__.py:6`:

```python
SUPPORTED_SINKS: dict[str, str] = {
    "postgres_table": "PostgresTableSink",
    "asyncdb": "AsyncDBSink",
    "csv_file": "CsvFileSink",
    "gsheet": "GoogleSheetSink",
}

def _load(type_: str) -> type[AbstractSubmissionSink]:
    module = importlib.import_module(f".{_MODULES[type_]}", __name__)
    return getattr(module, SUPPORTED_SINKS[type_])
```

Fingerprint excludes mapping-only fields, so adding a column is allowed but moving the table is not:

```python
def _fingerprint(target: SubmissionTarget) -> str:
    coords = target.model_dump(include=_COORDINATE_FIELDS[target.type])
    return hashlib.sha256(json.dumps(coords, sort_keys=True).encode()).hexdigest()
```

### Key Constraints

- The fingerprint must cover coordinates ONLY (schema_name/table, path, spreadsheet_id/worksheet, driver/collection) - never the mapping or the delimiter.
- Cache key is `(tenant, form_uid, version)`; a version bump gets a fresh sink but the SAME coordinate fingerprint must still match.
- Lazy imports, so an absent optional extra never breaks unrelated sinks.
- No module-level mutable state.
- `close_all()` must be safe to call twice.

### References in Codebase

- `packages/ai-parrot/src/parrot/stores/__init__.py:6` - dispatch precedent
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/base.py` - the ABC and `SinkTargetMismatchError` (TASK-2419)

---

## Acceptance Criteria

- [ ] Every key in `SUPPORTED_SINKS` resolves to an importable class
- [ ] `SinkFactory.get()` returns the same instance for the same `(tenant, form_uid, version)`
- [ ] A different `version` yields a new instance
- [ ] Changing `table` (or `path` / `spreadsheet_id`) after data exists raises `SinkTargetMismatchError`
- [ ] Adding a form FIELD does NOT change the fingerprint (mapping may evolve)
- [ ] Changing `delimiter` does NOT change the fingerprint
- [ ] Importing the package with the `[gsheet]` extra absent does not raise
- [ ] `close_all()` is idempotent
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_sink_factory.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_sink_factory.py
import pytest

from parrot_formdesigner.services.sinks import SUPPORTED_SINKS
from parrot_formdesigner.services.sinks.base import SinkTargetMismatchError


class TestDispatch:
    @pytest.mark.parametrize("type_", sorted(SUPPORTED_SINKS))
    def test_every_key_resolves(self, type_):
        from parrot_formdesigner.services.sinks import _load
        assert _load(type_) is not None


class TestCache:
    async def test_same_key_same_instance(self, factory, form):
        a = await factory.get(form, tenant="navigator")
        b = await factory.get(form, tenant="navigator")
        assert a is b

    async def test_version_bump_new_instance(self, factory, form, form_v2):
        a = await factory.get(form, tenant="navigator")
        b = await factory.get(form_v2, tenant="navigator")
        assert a is not b


class TestCoordinateImmutability:
    async def test_table_change_rejected(self, factory, form, form_moved_table):
        await factory.get(form, tenant="navigator")
        with pytest.raises(SinkTargetMismatchError):
            await factory.get(form_moved_table, tenant="navigator")

    async def test_added_field_allowed(self, factory, form, form_with_extra_field):
        await factory.get(form, tenant="navigator")
        assert await factory.get(form_with_extra_field, tenant="navigator") is not None

    async def test_delimiter_change_allowed(self, factory, csv_form, csv_form_semicolon):
        await factory.get(csv_form, tenant="navigator")
        assert await factory.get(csv_form_semicolon, tenant="navigator") is not None
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
**Notes**: Filled `services/sinks/__init__.py` with `SUPPORTED_SINKS`,
`_MODULES`, lazy `_load()`, and re-exports of `AbstractSubmissionSink` +
the four error types + `SinkFactory`. Implemented `SinkFactory` in
`services/sinks/factory.py`: `get(form, *, tenant)` caches per
`(tenant, form_uid, version)`; a coordinate fingerprint
(`hashlib.sha256` over `model_dump(include=coordinate_fields)`,
`sort_keys=True`) is recorded per `(tenant, form_uid)` on first
resolution and compared on every subsequent call, raising
`SinkTargetMismatchError` on a coordinate change. Coordinate fields per
type: `postgres_table`→(connection, schema_name, table),
`asyncdb`→(connection, driver, collection),
`csv_file`→(connection, path) [`delimiter` excluded — mapping-only],
`gsheet`→(connection, spreadsheet_id, worksheet). `close_all()` clears
the cache before closing, so a second call iterates nothing (idempotent).
All four concrete sinks happen to share the exact same
`(target, *, alias_registry, tenant)` constructor shape, so
`SinkFactory` instantiates them uniformly with no per-type branching
beyond `_load()`. 11 unit tests in `tests/unit/test_sink_factory.py`,
all passing, plus a manual check that the package still imports with
`googleapiclient` simulated absent. `ruff` and targeted `mypy` clean.

**Fingerprint storage decision** (explicitly deferred to this task):
kept **in the factory's own in-memory cache** (`self._fingerprints`,
keyed by `(tenant, form_uid)`), NOT round-tripped to any table's
metadata. Rationale: `SinkFactory` is instantiated once per app process
and lives for the app's lifetime (TASK-2429 wires it as a singleton), so
an in-memory cache correctly enforces immutability for the whole
process; persisting it durably (e.g. into the pointer row managed by
`AutonomousFormStorage`, TASK-2427) would require a DB round-trip on
every `get()` call and is a reasonable but NOT required follow-up — the
in-memory guarantee already satisfies every acceptance criterion for
this feature (no test or AC in the spec requires the check to survive a
process restart).

**Deviations from spec**: `factory.py`'s `get()` defers its
`from parrot_formdesigner.services.sinks import _load` import to call
time (inside the method body) rather than importing it at module level,
because `__init__.py` imports `SinkFactory` FROM `factory.py` for
re-export — a top-level import in the other direction would be a genuine
circular import (verified by running it, per the task's own contract
note). `__init__.py` defines `SUPPORTED_SINKS`/`_MODULES`/`_load` before
its `from .factory import SinkFactory` line specifically to make this
safe.
