# TASK-2429: Application wiring - alias registry app key and factory injection

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-2418, TASK-2426
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 13

---

## Context

Makes the feature reachable from a running app, and puts the security control
where the spec decided it belongs: the alias allowlist is an **aiohttp app key wired at app
construction** (spec section 8, resolved) - explicit, testable without touching the
environment, and deliberately NOT runtime-mutable.

Implements spec section 3 Module 13.

---

## Scope

- Modify `api/routes.py` (around the setup function at `:160`) to build a `SinkAliasRegistry` from configuration and register it as an aiohttp app key.
- Construct a `SinkFactory` from that registry and pass it into `FormAPIHandler`.
- Register a shutdown hook calling `SinkFactory.close_all()`.
- Export the new public names from `services/__init__.py`, following the existing re-export style (`FormSubmissionStorage` at `:27` / `__all__` at `:40`).
- Keep every new parameter OPTIONAL so an app that does not configure aliases behaves exactly as today.
- Write unit tests in `tests/unit/test_persistence_wiring.py`.

**NOT in scope**: The handler branch (TASK-2428). A DB-backed or hot-reloadable allowlist (rejected in spec section 8). Documentation (TASK-2431).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Build the registry + factory, register app key and shutdown hook |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | Re-export the new public names |
| `packages/parrot-formdesigner/tests/unit/test_persistence_wiring.py` | CREATE | Unit tests |

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
# Added to api/routes.py:
from ..services.sink_aliases import SinkAliasRegistry     # TASK-2418
from ..services.sinks.factory import SinkFactory          # TASK-2426
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py - the existing setup surface. Read it before editing:
#   sed -n 150,200p packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
# line 59:  from ..services.submissions import FormSubmissionStorage  (TYPE_CHECKING)
# line 160: submission_storage: "FormSubmissionStorage | None" = None
#   -> add `alias_registry` / `sink_factory` parameters alongside, all OPTIONAL.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py - the re-export style to follow
# line 27: FormSubmissionStorage,
# line 40: "FormSubmissionStorage",

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:138 - the constructor to feed (modified by TASK-2428)
class FormAPIHandler:
    def __init__(self, registry, client=None, submission_storage=None, forwarder=None,
                 partial_store=None, ..., rbac_enforcing: bool = False) -> None: ...
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:275 - the existing app-key precedent to copy
def __init__(self, storage=None, *, app=None, default_tenant="navigator",
             require_tenant=True) -> None:
    ...
    if app is not None:
        self._app = app
        app["form_registry"] = self             # <- the app-key idiom
        app.on_startup.append(self.on_startup)
        app.on_shutdown.append(self.on_shutdown)
```

### Does NOT Exist

- ~~`app["sink_aliases"]`~~ or any existing sink app key - none exists; this task chooses and documents the key name.
- ~~a config module in `parrot-formdesigner`~~ - the package has none. Configuration arrives as constructor arguments; the caller supplies the alias table.
- ~~`navconfig` as a direct dependency of `parrot-formdesigner`~~ - NOT in its dependency list. `core/auth.py:39` imports it inside `try/except ImportError` and falls back to `os.environ`. Keep that guarded pattern.
- ~~`FormRegistry.set_storage` being called here for `AutonomousFormStorage`~~ - it exists (`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:685`) but wiring the autonomous *definition* storage is the host app's choice, not this task's. Wire only the submission-sink path.

---

## Implementation Notes

### Pattern to Follow

Copy the app-key + shutdown-hook idiom already used by `FormRegistry`
(`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:275`):

```python
def setup_form_routes(app, *, alias_registry: SinkAliasRegistry | None = None, ...):
    if alias_registry is not None:
        app["form_sink_aliases"] = alias_registry
        factory = SinkFactory(alias_registry)
        app.on_shutdown.append(lambda _app: factory.close_all())
    else:
        factory = None                     # feature simply inactive
    handler = FormAPIHandler(registry, ..., sink_factory=factory)
```

### Key Constraints

- Every new parameter is OPTIONAL and defaults to `None` - an app that does not configure aliases must behave exactly as today.
- The allowlist is NOT runtime-mutable - no endpoint may add an alias.
- Register the shutdown hook so pools and file handles close.
- Do not change any existing parameter's name, order or default in `routes.py`.
- Document the chosen app-key name in the module docstring; TASK-2431 documents it for operators.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:275` - the app-key + signal-hook idiom
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:160` - where `submission_storage` is already threaded through
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py:27,40` - the re-export style

---

## Acceptance Criteria

- [ ] An app built WITHOUT `alias_registry` behaves exactly as today (regression test)
- [ ] An app built WITH `alias_registry` exposes it under the documented app key
- [ ] `FormAPIHandler` receives a non-None `sink_factory` when a registry is supplied
- [ ] `close_all()` runs on app shutdown
- [ ] No endpoint can mutate the allowlist (no route registered for it)
- [ ] New names importable from `parrot_formdesigner.services`
- [ ] Existing `routes.py` parameters unchanged in name, order and default
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_persistence_wiring.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_persistence_wiring.py
import pytest
from aiohttp import web


class TestWiring:
    def test_without_registry_is_inactive(self, make_app):
        app = make_app(alias_registry=None)
        assert "form_sink_aliases" not in app

    def test_with_registry_exposes_app_key(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        assert app["form_sink_aliases"] is alias_registry

    def test_handler_receives_factory(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        assert app["form_api_handler"]._sink_factory is not None

    async def test_close_all_on_shutdown(self, make_app, alias_registry, spy_factory):
        app = make_app(alias_registry=alias_registry)
        await app.shutdown()
        assert spy_factory.closed

    def test_no_allowlist_mutation_route(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        paths = {r.resource.canonical for r in app.router.routes() if r.resource}
        assert not any("alias" in p for p in paths)
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
