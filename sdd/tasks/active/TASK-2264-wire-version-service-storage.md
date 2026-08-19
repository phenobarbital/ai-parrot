# TASK-2264: Wire the storage backend into FormVersionService

**Feature**: FEAT-433 — Form Version History — repair the read path
**Spec**: `sdd/specs/form-version-history-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 1. `_get_version_service()` builds the service with no
`storage=` argument, so `_storage is None` and every publish lands in an
in-process dict instead of Postgres. This is the root of both dead
endpoints: `POST /publish` loses its snapshot on process exit, and
`list_versions` never reaches storage at all.

Necessary but **not sufficient** on its own — verified in the brainstorm's
reproduction, the endpoint still returns `[]` after this task alone. It is
sequenced first because TASK-2265 and TASK-2269 both need a real backend
to exist.

---

## Scope

- Pass `storage=self.registry.storage` when constructing
  `FormVersionService` in `_get_version_service()`.
- Add a unit test asserting the constructed service has a non-None
  `_storage` when the registry has a backend attached.
- Add a unit test asserting a published snapshot survives discarding and
  rebuilding the service (the restart case).

**NOT in scope**: the `published_version` filter (TASK-2266), the
`list_versions` query (TASK-2265), the immutability guard this task makes
reachable (TASK-2269 — do not fix it here, but do not pretend it is fine
either).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `_get_version_service()` passes `storage=` |
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | MODIFY | the two tests above |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.form_version import FormVersionService
from parrot_formdesigner.services.registry import FormRegistry
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
    def _get_version_service(self) -> "FormVersionService":   # line 1801
        if self._version_service is None:
            from ..services.form_version import FormVersionService
            self._version_service = FormVersionService(self.registry)   # line 1809

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    @property
    def storage(self) -> "FormStorage | None": ...            # line 1307
    def set_storage(self, storage: FormStorage) -> None: ...  # line 604

# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
class FormVersionService:
    def __init__(self, registry, storage=None, *, has_responses=None) -> None: ...
```

### Does NOT Exist
- ~~`FormDesignerHandler.storage`~~ — the backend is reached through
  `self.registry.storage`, not off the handler
- ~~`FormVersionService.set_storage()`~~ — storage is constructor-only

---

## Implementation Notes

### Key Constraints
- `FormRegistry.storage` may legitimately be `None` (in-memory
  deployments and most unit tests). Passing `None` through is the current
  behaviour and must keep working — do not raise when there is no backend.
- The service is cached on the handler (`self._version_service`); the
  storage is read at construction time, so a `set_storage()` call made
  after the first version request will not be picked up. Acceptable
  today; note it in the docstring rather than adding invalidation.

### References in Codebase
- `api/handlers.py:1828` — `_make_question_bank` already does exactly
  this (`storage=self.registry.storage`); follow that shape.

---

## Acceptance Criteria

- [ ] `_get_version_service()` passes `storage=self.registry.storage`
- [ ] A service built from a registry with a backend has `_storage is not None`
- [ ] A published snapshot is loadable from storage after the service
      object is discarded and rebuilt
- [ ] Registries without a backend still work (no raise, in-memory path intact)
- [ ] `pytest packages/parrot-formdesigner/tests/unit/ -v` passes
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`

---

## Test Specification

```python
async def test_version_service_receives_storage(handler_with_pg_registry):
    svc = handler_with_pg_registry._get_version_service()
    assert svc._storage is not None

async def test_publish_persists_across_service_instances(registry, pg_storage, form):
    svc = FormVersionService(registry, storage=pg_storage)
    tag = await svc.publish(form.form_uid, tenant="t1")
    del svc
    assert await pg_storage.load(form.form_uid, version=tag, tenant="t1") is not None
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
