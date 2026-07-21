---
type: Wiki Overview
title: 'TASK-1161: Tenant-scoped callback registry'
id: doc:sdd-tasks-completed-task-1161-callback-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1 foundation service. `FieldType.REST` mode `callback` invokes a
relates_to:
- concept: mod:parrot.registry
  rel: mentions
---

# TASK-1161: Tenant-scoped callback registry

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 2)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Phase 1 foundation service. `FieldType.REST` mode `callback` invokes a
pre-registered Python coroutine; this module owns the registry. Per
the spec's Q3 refinement (§8), the registry is tenant-scoped with
**namespace-shadowing** semantics (per-tenant override of a globally
registered name) — this is a NEW pattern in `parrot-formdesigner`.
Authorization is NOT part of this module.

---

## Scope

- Implement `parrot_formdesigner/services/callback_registry.py` with:
  - `RestCallback` protocol/type alias: `Callable[..., Awaitable[RestCallbackOutput]]`.
    (The concrete `RestCallbackInput` / `RestCallbackOutput` models live
    in `rest_field_resolver.py` — TASK-1162; import lazily to avoid a
    circular dep, or accept `Any` here and rely on the resolver to
    construct the typed payload.)
  - `_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback]`
    module-level dict.
  - `@register_form_callback(name, *, tenant=None)` decorator.
  - `get_form_callback(name, *, tenant=None) -> RestCallback` with
    fallback to `(None, name)`.
  - `list_form_callbacks(tenant=None) -> list[tuple[str | None, str]]`.
- Duplicate `(tenant, name)` registration raises `ValueError`.
- A tenant slug equal to the literal string `"None"` is rejected at
  registration with `ValueError` (collision with the global-sentinel).
- Unit tests covering: register, duplicate-raises, tenant fallback,
  list-for-tenant, "None"-tenant-rejected.

**NOT in scope**: ACL / authorization, dotted-path resolution
(forbidden by spec), automatic introspection-based discovery.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/callback_registry.py` | CREATE | Module |
| `packages/parrot-formdesigner/tests/unit/services/test_callback_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from collections.abc import Awaitable, Callable
import logging
from typing import Any
```

### Existing Signatures (reference idiom — DO NOT import)

`parrot.registry.register_agent` (in the main `parrot/` package, not
formdesigner) is the *pattern* to mirror — a module-level dict +
decorator. DO NOT import it; the callback registry is a separate
domain and lives entirely inside `parrot-formdesigner`.

```python
# Existing precedent in parrot-formdesigner (name-only, no tenant):
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:67
_REGISTRY: dict[str, FieldControlMetadata] = {}
def register_field_control(field_type, *, ...): ...
# This is the SHAPE precedent; the new registry uses a composite key.
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.callback_registry`~~ — new.
- ~~`@register_form_callback` / `get_form_callback` /
  `list_form_callbacks`~~ — all new.
- ~~Dotted-path resolution (`callback: "myapp.callbacks.fn"`)~~ —
  rejected.
- ~~ACL-style `allowed_tenants={...}` argument~~ — not in this
  registry. ACLs live at the resolver/handler boundary.

---

## Implementation Notes

### Key (composite, sentinel-based)

```python
# Key is (tenant_slug_or_None, name).
# `None` is the literal Python sentinel.
# Lookup order: (tenant, name) -> (None, name) -> KeyError.

def register_form_callback(name: str, *, tenant: str | None = None):
    if tenant == "None":
        raise ValueError(
            "tenant slug 'None' (string) collides with the global "
            "sentinel; pick a different slug."
        )
    def decorator(fn):
        key = (tenant, name)
        if key in _CALLBACK_REGISTRY:
            raise ValueError(f"callback {key!r} already registered")
        _CALLBACK_REGISTRY[key] = fn
        return fn
    return decorator

def get_form_callback(name: str, *, tenant: str | None = None):
    if tenant is not None and (tenant, name) in _CALLBACK_REGISTRY:
        return _CALLBACK_REGISTRY[(tenant, name)]
    return _CALLBACK_REGISTRY[(None, name)]  # raises KeyError if absent
```

### Key constraints

- Module-level mutable state — provide a `_clear_registry_for_tests()`
  helper guarded by a docstring note ("test-only").
- `self.logger`? — this module is functions, not a class. Use a
  module-level `logger = logging.getLogger(__name__)`.

---

## Acceptance Criteria

- [ ] `@register_form_callback("x")` adds `(None, "x")` to registry.
- [ ] `@register_form_callback("x", tenant="acme")` adds `("acme", "x")`.
- [ ] Re-registering `("acme", "x")` raises `ValueError`.
- [ ] `get_form_callback("x", tenant="acme")` returns the tenant entry.
- [ ] `get_form_callback("x", tenant="other")` falls back to `(None, "x")`.
- [ ] `get_form_callback("missing")` raises `KeyError`.
- [ ] `register_form_callback("x", tenant="None")` raises `ValueError`.
- [ ] `list_form_callbacks(tenant="acme")` includes both tenant + global.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/services/test_callback_registry.py -v` passes.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.services.callback_registry import (
    register_form_callback, get_form_callback,
    list_form_callbacks, _CALLBACK_REGISTRY,
)

@pytest.fixture(autouse=True)
def clean_registry():
    _CALLBACK_REGISTRY.clear()
    yield
    _CALLBACK_REGISTRY.clear()

def test_register_global():
    @register_form_callback("compute")
    async def fn(payload): return None
    assert get_form_callback("compute") is fn

def test_register_tenant_and_fallback():
    @register_form_callback("compute")
    async def global_fn(payload): return None
    @register_form_callback("compute", tenant="acme")
    async def tenant_fn(payload): return None
    assert get_form_callback("compute", tenant="acme") is tenant_fn
    assert get_form_callback("compute", tenant="other") is global_fn

def test_duplicate_raises():
    @register_form_callback("x")
    async def fn(payload): return None
    with pytest.raises(ValueError, match="already registered"):
        register_form_callback("x")(fn)

def test_tenant_named_None_string_rejected():
    with pytest.raises(ValueError, match="collides"):
        register_form_callback("x", tenant="None")

def test_missing_callback_raises_keyerror():
    with pytest.raises(KeyError):
        get_form_callback("missing")

def test_list_includes_tenant_and_global():
    @register_form_callback("a")
    async def g(p): return None
    @register_form_callback("b", tenant="acme")
    async def t(p): return None
    listed = list_form_callbacks(tenant="acme")
    assert (None, "a") in listed and ("acme", "b") in listed
```

---

## Completion Note

*(Agent fills this in when done)*
