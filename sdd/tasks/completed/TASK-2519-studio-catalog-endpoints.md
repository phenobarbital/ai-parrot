# TASK-2519: Catalog GET helpers — base classes, LLM clients, tools, vector stores

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2511
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11. The future UI needs reference catalogs: available agent
base classes (with public configurable attributes), supported LLM clients,
available tools, supported vector stores. All four reuse existing sources
of truth — no new registries.

---

## Scope

- Implement `handlers/studio/catalog.py` (GET-only, `StudioBaseView` or
  `BaseHandler`-style bare functions):
  - `GET /api/v1/astudio/catalog/base-classes` — from `parrot.bots`
    `__all__` (respect lazy exports): name, module, docstring first line,
    public configurable constructor params (introspected, `self`/private
    excluded).
  - `GET /api/v1/astudio/catalog/llm-clients` — from `SUPPORTED_CLIENTS`:
    provider key, resolved class name (resolve lazy-loader callables
    WITHOUT triggering heavy imports — call the loader lazily and guard
    ImportError → mark `available: false`).
  - `GET /api/v1/astudio/catalog/tools` — delegate to the existing
    `_build_catalog()` (process-wide cache included).
  - `GET /api/v1/astudio/catalog/vector-stores` — from
    `parrot.stores` supported-stores dispatch.
- Response caching mirroring `tools_catalog._CATALOG_CACHE`.
- Routes + tests.

**NOT in scope**: toolkit config schemas (TASK-2518); per-agent skills
listing (covered by TASK-2514 file list + TASK-2515 catalog).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py` | CREATE | four catalog GETs |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_catalogs.py` | CREATE | catalog shape tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import parrot.bots                                             # bots/__init__.py:9
from parrot.clients.factory import SUPPORTED_CLIENTS           # factory.py:106
from parrot.handlers.... import ...  # NO — tools catalog lives in the SERVER package:
from parrot.handlers.tools_catalog import _build_catalog  # (unverified — check module path
#   at implementation: packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py:44)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/__init__.py:9
__all__ = ("AbstractBot", "Agent", "BaseBot", "BasicAgent", "BasicBot",
           "Chatbot", "InfoAgent", "VoiceBot", "WebAgent", "WebSearchAgent")
# _LAZY_ATTRS = {"VoiceBot": ".voice", "InfoAgent": ".info"} — resolved via
#   module __getattr__; guard ImportError when resolving lazily

# packages/ai-parrot/src/parrot/clients/factory.py:106
SUPPORTED_CLIENTS = {...}  # values are classes OR zero-arg lazy-loader callables
#   (detect: callable(v) and not isinstance(v, type) → lazy loader; factory.py:191
#    resolves them the same way)

# packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py
def _build_catalog() -> List[Dict[str, Any]]: ...  # :44 — {slug, dotted_path,
#   description?, category?}; module-level _CATALOG_CACHE :41
class ToolCatalogHandler(BaseView): ...  # :85 — do NOT modify; import _build_catalog

# Vector stores: parrot/stores/ owns AbstractStore + dispatch
#   (supported_stores per .agent/CONTEXT.md) — grep
#   `grep -rn "supported_stores" packages/ai-parrot/src/parrot/stores/` at
#   implementation time for the exact symbol (unverified — check before use)
# Reference implementation: handlers/stores/helpers.py (VectorStoreHelper,
#   "public metadata endpoints for vector store configuration")
```

### Does NOT Exist
- ~~`parrot.clients.SUPPORTED_CLIENTS`~~ — import from
  `parrot.clients.factory`.
- ~~A base-classes catalog anywhere~~ — greenfield; do not invent a
  `BOT_CLASSES` registry, introspect `parrot.bots.__all__`.
- ~~`ToolkitRegistry` as tool source~~ — deprecated; the tool catalog is
  `_build_catalog()`/`discover_all()`.
- ~~`AnthropicClient.DEFAULT_MODEL`~~ — per-client default is the class
  attr `_default_model` (include it in the client catalog rows where
  present).

---

## Implementation Notes

### Pattern to Follow
`tools_catalog.py` end-to-end: module-level cache, best-effort imports
with swallowed failures, sorted stable output, `@is_authenticated()` +
`@user_session()`.

### Key Constraints
- NEVER trigger heavy imports eagerly at module import time — all
  resolution inside the request handler, cached after first success.
- Configurable-attribute introspection: `inspect.signature` on
  `cls.__init__`, keep params with defaults or annotations, drop `self`,
  `*args`, `**kwargs`, underscore-prefixed.
- Base-classes rows include `lazy: true` for `_LAZY_ATTRS` entries that
  fail to import (missing optional deps) instead of erroring.

### References in Codebase
- `handlers/stores/helpers.py` — vector-store metadata precedent.
- `bots/flows/authoring/catalog.py:403,482` — other discovery consumers.

---

## Acceptance Criteria

- [ ] Four catalogs served under `/api/v1/astudio/catalog/*`, authenticated.
- [ ] Base-classes rows expose configurable params; lazy/missing imports
      degrade gracefully (`available: false`), never 500.
- [ ] LLM catalog resolves lazy loaders without crashing on missing extras.
- [ ] Tools catalog output identical in shape to `/api/v1/tools/catalog`.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_catalogs.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_catalogs.py
class TestStudioCatalogs:
    async def test_base_classes_listed_with_params(self, studio_app): ...
    async def test_base_classes_lazy_import_graceful(self, studio_app, monkeypatch): ...
    async def test_llm_clients_from_supported_clients(self, studio_app): ...
    async def test_tools_catalog_shape(self, studio_app): ...
    async def test_vector_stores_listed(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2511 completed
3. **Verify the Codebase Contract** — resolve the two `(unverified)` items
   (`_build_catalog` import path from the server package; the
   supported-stores symbol in `parrot/stores/`) BEFORE writing code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- `StudioCatalogHandler` (single view, dynamic `{kind}` path segment)
  implemented in `handlers/studio/catalog.py`; one route
  (`/catalog/{kind}`) covers all four sub-catalogs
  (`base-classes`/`llm-clients`/`tools`/`vector-stores`).
- Resolved both `(unverified)` Codebase Contract items before writing
  code: `_build_catalog`/`_CATALOG_CACHE` confirmed at
  `handlers/tools_catalog.py:41,44`; the vector-store dispatch symbol
  confirmed as `parrot.stores.supported_stores` (a plain `{slug:
  class_name}` dict — `handlers/stores/helpers.py`'s
  `VectorStoreHelper.supported_stores()` is the existing precedent this
  task mirrors: no import-availability probing attempted there either,
  so the vector-stores catalog doesn't either).
- Base classes: introspects `parrot.bots.__all__` via plain `getattr()`
  (triggers the module's own lazy `__getattr__`/`_LAZY_ATTRS` resolution
  for `VoiceBot`/`InfoAgent`); a failing lazy import is caught and
  degrades to `{"available": false, "lazy": true, "error": ...}` instead
  of raising. Configurable params kept only when they carry a default OR
  a type annotation (per spec wording), dropping `self`/`*args`/
  `**kwargs`/underscore-prefixed.
- LLM clients: `SUPPORTED_CLIENTS` values that are `callable` and not
  themselves a `type` are treated as lazy loaders (same detection the
  factory itself uses) and called to resolve the real class; a raising
  loader (missing optional extra) degrades the same way. `_default_model`
  read via `getattr(cls, "_default_model", None)` per the contract's
  explicit correction (no `DEFAULT_MODEL` attr exists).
- Tools catalog deliberately reuses `tools_catalog_module._CATALOG_CACHE`
  itself (reading/writing the imported module's own global) rather than
  a Studio-local cache, so it never diverges from — and never rebuilds
  independently of — the existing `GET /api/v1/tools/catalog` endpoint.
- Tests (7, all passing): base-classes listing + lazy-import-failure
  degradation (via a fake `parrot.bots`-shaped module exercising the
  real `__getattr__` mechanism); LLM clients listing + lazy-loader
  failure degradation; tools catalog shape + shared-cache population
  (content-equality check, since JSON round-tripping the response body
  necessarily produces a fresh list — `is` was the wrong check and was
  corrected during iteration); vector-stores listing; unknown-kind 404.
  Full `packages/ai-parrot-server/tests/studio/` suite (143 tests)
  passes. `ruff check handlers/studio/` clean except the same pervasive
  pre-existing `BLE001` fail-open pattern used throughout every other
  file in this directory (two instances in this task's own lazy-import
  guards, which is the literal purpose of those `try/except`).

**Deviations from spec**: none
