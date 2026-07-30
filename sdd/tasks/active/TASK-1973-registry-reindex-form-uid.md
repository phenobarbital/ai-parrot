# TASK-1973: Reindex FormRegistry on form_uid

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1972
**Assigned-to**: unassigned

---

## Context

The FormRegistry is the central in-memory store for all forms. Currently keyed
by `form_id` (a mutable slug), it must be re-keyed on `form_uid` (immutable UUID).
A secondary `_slug_index` keyed by `tenant_form_slug` (`{tenant}_{form_id}`)
provides slug-based lookups. Implements Module 2 from the spec.

---

## Scope

- Change `self._forms` dict key from `form_id` to `form_uid` (per-tenant).
- Add `self._slug_index: dict[str, str] = {}` keyed by `tenant_form_slug` → `form_uid`.
- Add static method `_make_slug_key(tenant, form_id) -> str` producing `"{tenant}_{form_id}"`.
- Update `register()`: store by `form.form_uid`, update slug index. Reject if
  `tenant_form_slug` already maps to a DIFFERENT `form_uid` (slug uniqueness enforcement).
- Update `get()`: parameter renamed from `form_id` to `form_uid`, lookup by UUID.
- Add `get_by_slug(form_id, tenant=)`: lookup via slug index → primary index.
- Update `unregister()`: parameter renamed from `form_id` to `form_uid`, clean both indexes.
- Update `contains()`: parameter renamed to `form_uid`.
- Update `clone_form()`: generate new `form_uid` for the clone, parameters renamed.
- Add `list_form_uids(tenant=)` method.
- Update `list_form_ids()` to use slug index or derive from primary index.

**NOT in scope**: Storage layer, API handlers, or route changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | Reindex, add slug index, new methods |
| `packages/parrot-formdesigner/tests/test_registry.py` | MODIFY | Update and add registry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema  # verified: core/__init__.py
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:146
```

### Existing Signatures to Use
```python
# services/registry.py:146
class FormRegistry:
    def __init__(self, storage=None, *, app=None,
                 default_tenant="navigator", require_tenant=True) -> None:  # line 175
    # self._forms: dict[str, dict[str, FormSchema]] = {}  # line 201 — KEY CHANGES HERE
    def _resolve_tenant(self, tenant, form=None) -> str:  # line 234
    async def register(self, form, *, persist=False, overwrite=True, tenant=None) -> None:  # line 265
        # stores at: self._forms[resolved_tenant][form.form_id] = form  # line 339
    async def unregister(self, form_id: str, *, tenant=None) -> bool:  # line 465
    async def clone_form(self, source_form_id, new_form_id, patch=None, *,
                         persist=True, tenant=None) -> FormSchema:  # line 512
    async def get(self, form_id: str, *, tenant=None) -> FormSchema | None:  # line 623
    async def list_forms(self, *, tenant=None) -> list[FormSchema]:  # line 639
    async def list_form_ids(self, *, tenant=None) -> list[str]:  # line 655
    async def contains(self, form_id: str, *, tenant=None) -> bool:  # line 668
```

### Does NOT Exist
- ~~`FormRegistry._slug_index`~~ — does not exist. Must be created.
- ~~`FormRegistry._make_slug_key()`~~ — does not exist. Must be created.
- ~~`FormRegistry.get_by_slug()`~~ — does not exist. Must be created.
- ~~`FormRegistry.get_by_uid()`~~ — does not exist. `get()` will be repurposed.
- ~~`FormRegistry.list_form_uids()`~~ — does not exist. Must be created.

---

## Implementation Notes

### Key Constraints
- All reads/writes must remain under `self._lock` (existing `asyncio.Lock`).
- `_resolve_tenant()` is unchanged — tenant resolution logic stays the same.
- `register()` with `overwrite=True` must update the slug index if `form_id` changed
  (remove old slug key, add new one).
- `register()` with `overwrite=False` must check BOTH `form_uid` collision AND
  `tenant_form_slug` collision.
- The `_on_register` / `_on_unregister` callbacks may need `form_uid` instead of
  `form_id` — check callers and update signatures accordingly.
- `clone_form()` must generate a new `form_uid` via `str(uuid.uuid4())` for the clone.

### Pattern: Slug Index Update in register()
```python
@staticmethod
def _make_slug_key(tenant: str, form_id: str) -> str:
    return f"{tenant}_{form_id}"

async def register(self, form, *, persist=False, overwrite=True, tenant=None):
    resolved = self._resolve_tenant(tenant, form)
    slug_key = self._make_slug_key(resolved, form.form_id)
    async with self._lock:
        existing_uid = self._slug_index.get(slug_key)
        if existing_uid and existing_uid != form.form_uid and not overwrite:
            raise ValueError(f"Slug '{form.form_id}' already in use by {existing_uid}")
        # ... store in _forms[resolved][form.form_uid]
        self._slug_index[slug_key] = form.form_uid
```

---

## Acceptance Criteria

- [ ] `_forms` keyed by `form_uid` (not `form_id`)
- [ ] `_slug_index` keyed by `tenant_form_slug` maps to `form_uid`
- [ ] `get(form_uid)` returns correct form
- [ ] `get_by_slug(form_id, tenant=)` resolves via slug index
- [ ] Duplicate slug in same tenant rejected on `register()`
- [ ] Same slug across different tenants allowed
- [ ] `unregister()` cleans both indexes
- [ ] `clone_form()` generates new `form_uid`
- [ ] `list_form_uids()` works
- [ ] All existing tests pass after adaptation

---

## Test Specification

```python
import uuid
import pytest
from parrot_formdesigner.core.schema import FormSchema, FormSection
from parrot_formdesigner.services.registry import FormRegistry

def _make_form(form_uid=None, form_id="test", title="Test"):
    return FormSchema(
        form_uid=form_uid or str(uuid.uuid4()),
        form_id=form_id,
        title=title,
        sections=[FormSection(section_id="s1", title="S1", fields=[])],
    )

class TestRegistryFormUid:
    @pytest.fixture
    def registry(self):
        return FormRegistry(require_tenant=False, default_tenant="test")

    async def test_index_by_form_uid(self, registry):
        form = _make_form()
        await registry.register(form)
        result = await registry.get(form.form_uid)
        assert result is not None
        assert result.form_uid == form.form_uid

    async def test_get_by_slug(self, registry):
        form = _make_form(form_id="my-slug")
        await registry.register(form)
        result = await registry.get_by_slug("my-slug")
        assert result is not None
        assert result.form_uid == form.form_uid

    async def test_slug_unique_per_tenant(self, registry):
        f1 = _make_form(form_id="dup")
        f2 = _make_form(form_id="dup")
        await registry.register(f1)
        with pytest.raises(ValueError, match="already in use"):
            await registry.register(f2, overwrite=False)

    async def test_slug_allowed_across_tenants(self):
        reg = FormRegistry(require_tenant=False, default_tenant="t1")
        f1 = _make_form(form_id="same")
        f1.tenant = "t1"
        f2 = _make_form(form_id="same")
        f2.tenant = "t2"
        await reg.register(f1, tenant="t1")
        await reg.register(f2, tenant="t2")
        assert await reg.get_by_slug("same", tenant="t1") is not None
        assert await reg.get_by_slug("same", tenant="t2") is not None

    async def test_unregister_cleans_both(self, registry):
        form = _make_form(form_id="clean")
        await registry.register(form)
        await registry.unregister(form.form_uid)
        assert await registry.get(form.form_uid) is None
        assert await registry.get_by_slug("clean") is None

    async def test_clone_new_uid(self, registry):
        form = _make_form(form_id="original")
        await registry.register(form)
        clone = await registry.clone_form(form.form_uid, "clone-slug")
        assert clone.form_uid != form.form_uid
        assert clone.form_id == "clone-slug"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-uid-stable-identity.spec.md` §2 and §3
2. **Verify TASK-1972 is completed** — `FormSchema.form_uid` must exist
3. **Verify the Codebase Contract** — read `services/registry.py` and confirm signatures
4. **Implement** all changes to FormRegistry
5. **Run tests**: `pytest packages/parrot-formdesigner/tests/ -v`
6. **Update status** and move file on completion

---

## Completion Note

*(Agent fills this in when done)*
