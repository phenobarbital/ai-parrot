# TASK-2427: `AutonomousFormStorage` - pointer-indexed form definitions

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L
**Depends-on**: TASK-2417, TASK-2418
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 11

---

## Context

The second half of "autonomous": the form's *definition body* lives in its own
store, while the registry still indexes a pointer so listing, RBAC and multi-tenancy keep
working (spec section 8, resolved).

Implemented as a **decorator** over the existing `FormStorage`, not a new registry - because
satisfying the same interface means `FormRegistry._read_through`
(`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:1035`) needs no changes at all.

WARNING: **The single biggest trap in this feature lives here** - see "Does NOT Exist".

Implements spec section 3 Module 11.

---

## Scope

- Create `services/autonomous_storage.py` with `AutonomousFormStorage(FormStorage)` wrapping an inner `FormStorage`.
- Implement `save()`: write the schema BODY to the definition target, and a pointer row (identity + persistence block + `source_ref`) through the inner storage.
- Implement `load()` (by `form_uid`, matching the concrete contract - see below) and **`load_by_slug()`**: read the pointer via the inner storage, then hydrate the body from the definition target.
- Delegate `delete()`, `list_forms()`, `list_versions()`, `promote()`, `close()` to the inner storage, removing the body from the definition target on delete.
- Forms WITHOUT a `persistence.definition` block must pass straight through to the inner storage, unchanged.
- Resolve the definition target's location via `SinkAliasRegistry.contain(...)`.
- Write unit tests in `tests/unit/test_autonomous_form_storage.py`.

**NOT in scope**: Submission sinks. Registry changes - `FormRegistry` must NOT be modified. Changing the `FormStorage` ABC. `clone_form()` behaviour (spec section 8, still open).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/autonomous_storage.py` | CREATE | FormStorage decorator |
| `packages/parrot-formdesigner/tests/unit/test_autonomous_form_storage.py` | CREATE | Unit tests |

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
from parrot_formdesigner.services.registry import FormStorage   # services/registry.py:63
from parrot_formdesigner.core.schema import FormSchema          # core/schema.py:313
from parrot_formdesigner.core.style import StyleSchema          # used in FormStorage.save signature
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import FileDefinitionTarget   # TASK-2417
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry # TASK-2418
import uuid
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:63 - the ABC to satisfy
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *,
                   tenant: str | None = None) -> str: ...                     # line 73
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...       # line 95
    @abstractmethod
    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool: ...  # line 116
    @abstractmethod
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 130
    async def list_versions(self, form_uid: uuid.UUID, *,
                            tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 149
    async def promote(self, form_uid: uuid.UUID, version: str, schema_json: str, *,
                      tenant: str | None = None) -> bool: ...                 # line 180
    async def close(self) -> None: ...                                        # line 230

# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:69 - the concrete impl being wrapped. NOTE the signature
# divergence from the ABC (see "Does NOT Exist"):
class PostgresFormStorage(FormStorage):
    async def load(self, form_uid: uuid.UUID, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...  # line 496
    async def load_by_slug(...)                                          # line 555

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:1035 - the caller you must stay compatible with.
# DO NOT MODIFY THIS METHOD.
async def _read_through(self, resolved, *, form_uid=None, form_id=None) -> FormSchema | None:
    ...
    loaded = await self._storage.load(form_uid, tenant=resolved)      # line 1073
    ...
    loaded = await self._storage.load_by_slug(form_id, resolved)      # line 1075
    # lines 1070-1082: fail-soft - storage faults are logged and return None
```

### Does NOT Exist

- ~~`FormStorage.load_by_slug`~~ - **NOT declared on the ABC** (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:63-238` declares only `save`, `load`, `delete`, `list_forms`, `list_versions`, `promote`, `close`) - yet `FormRegistry` **calls it** at `services/registry.py:418` and `:1075`. Any `FormStorage` implementation MUST provide it or read-through lookups raise `AttributeError`.
- **ABC/impl signature divergence** - `FormStorage.load()` is DECLARED `load(form_id: str, ...)` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:95`) but `PostgresFormStorage.load()` takes `form_uid: uuid.UUID` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:496`), and `FormRegistry` calls it with a UUID (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:1073`). **Follow the concrete/caller contract (UUID), NOT the ABC docstring.**
- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~`FormSubmissionStorage.DEFAULT_SCHEMA`~~ / ~~`PostgresFormStorage.DEFAULT_SCHEMA`~~ as **class attributes** - they are **module-level** constants (`services/submissions.py:31-32`, `services/storage.py:65-66`), despite the dotted form used in the `FormRegistry.__init__` docstring (`services/registry.py:293`).
- ~~a `source_ref` column on the existing table~~ - `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:159` `_create_table_sql` has NO such column. The pointer must fit the existing columns (`schema_json` is the natural home for the pointer envelope) or the DDL must be extended additively. Read that DDL before deciding.
- ~~`FormRegistry.set_storage` as the wiring point~~ - it exists (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:685`) but app wiring belongs to TASK-2429; this task only delivers the class.

---

## Implementation Notes

### Pattern to Follow

Decorate, delegate, and hydrate - never modify the registry:

```python
class AutonomousFormStorage(FormStorage):
    def __init__(self, inner: FormStorage, aliases: SinkAliasRegistry) -> None:
        self._inner = inner
        self._aliases = aliases

    async def load(self, form_uid: uuid.UUID, version=None, *, tenant=None):
        pointer = await self._inner.load(form_uid, version, tenant=tenant)
        if pointer is None or not _is_pointer(pointer):
            return pointer                      # pass-through for ordinary forms
        return await self._hydrate(pointer, tenant=tenant)

    async def load_by_slug(self, form_id: str, tenant: str | None = None):
        # REQUIRED even though the ABC omits it - registry.py:1075 calls it.
        pointer = await self._inner.load_by_slug(form_id, tenant)
        ...
```

### Key Constraints

- `load_by_slug` is MANDATORY - the ABC omits it but `FormRegistry` calls it. Its absence is an `AttributeError` at runtime, not a type error at build time.
- `load` takes a `uuid.UUID`, per the concrete/caller contract.
- Pass-through must be exact for forms without a `definition` block - no behaviour change.
- Never modify `services/registry.py`.
- A definition-target read failure must propagate as an exception the registry can fail-soft on (it already catches broadly at `registry.py:1070-1082`), so the form 404s rather than 500s.
- Async throughout; `self.logger` on hydrate and on pointer-mismatch.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:63` - the ABC
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:1035` - the caller to stay compatible with
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:496,555` - the concrete `load` / `load_by_slug` contracts
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py:159` - the existing DDL (pointer must fit it)
- `packages/parrot-formdesigner/tests/test_registry_read_through.py` - existing read-through test doubles to model on

---

## Acceptance Criteria

- [ ] `AutonomousFormStorage` instantiates (all abstract methods implemented)
- [ ] `load_by_slug` EXISTS and hydrates a pointer (explicit test)
- [ ] `load` accepts a `uuid.UUID` and hydrates a pointer
- [ ] A form with no `persistence.definition` passes through byte-identically
- [ ] `save()` -> `load()` round-trips an identical `FormSchema`
- [ ] `delete()` removes both the pointer and the body
- [ ] `list_forms()` includes pointer-indexed forms
- [ ] `FormRegistry` is NOT modified (`git diff` on `services/registry.py` is empty)
- [ ] A definition-target read failure does not raise past the registry's fail-soft boundary
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_autonomous_form_storage.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_autonomous_form_storage.py
import uuid
import pytest

from parrot_formdesigner.services.autonomous_storage import AutonomousFormStorage


class TestABCCompliance:
    def test_instantiates(self, inner_storage, alias_registry):
        assert AutonomousFormStorage(inner_storage, alias_registry) is not None

    def test_load_by_slug_exists(self, autonomous_storage):
        # The ABC omits it, but FormRegistry calls it at registry.py:1075.
        assert callable(getattr(autonomous_storage, "load_by_slug", None))


class TestRoundtrip:
    async def test_save_then_load_by_uid(self, autonomous_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        got = await autonomous_storage.load(autonomous_form.form_uid, tenant="navigator")
        assert got == autonomous_form

    async def test_save_then_load_by_slug(self, autonomous_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        got = await autonomous_storage.load_by_slug(autonomous_form.form_id, "navigator")
        assert got == autonomous_form

    async def test_delete_removes_body(self, autonomous_storage, autonomous_form, definition_path):
        await autonomous_storage.save(autonomous_form)
        await autonomous_storage.delete(autonomous_form.form_uid, tenant="navigator")
        assert not definition_path.exists()


class TestPassThrough:
    async def test_ordinary_form_untouched(self, autonomous_storage, plain_form):
        await autonomous_storage.save(plain_form)
        got = await autonomous_storage.load(plain_form.form_uid, tenant="navigator")
        assert got == plain_form

    async def test_list_forms_includes_pointer(self, autonomous_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        ids = [r["form_id"] for r in await autonomous_storage.list_forms(tenant="navigator")]
        assert autonomous_form.form_id in ids
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

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
