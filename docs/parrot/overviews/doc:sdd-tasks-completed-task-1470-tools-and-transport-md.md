---
type: Wiki Overview
title: 'TASK-1470: LLM Tools + HTTP/AgenTalk Transport'
id: doc:sdd-tasks-completed-task-1470-tools-and-transport-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 7** — the surfaces. Exposes the filtering API to (a)
  the LLM
relates_to:
- concept: mod:parrot.handlers.dataset_filter_handler
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1470: LLM Tools + HTTP/AgenTalk Transport

**Feature**: FEAT-225 — DatasetManager Common-Field Filtering
**Spec**: `sdd/specs/datasetmanager-filtering.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1467, TASK-1468, TASK-1469
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** — the surfaces. Exposes the filtering API to (a) the LLM
agent via `AbstractToolkit` tools and (b) the frontend via an aiohttp handler +
AgenTalk envelope, modeled on the existing `spatial_filter_handler.py`.

---

## Scope

- Register `AbstractToolkit` tools on `DatasetManager` (via its `get_tools`):
  `define_filters`, `apply_filters`, `list_filters` (schema), `get_filter_values`.
  Each with a clear docstring (becomes the LLM tool description).
- Implement `parrot/handlers/dataset_filter_handler.py`:
  - `GET  .../filters/schema` → `get_filter_schema()`
  - `GET  .../filters/{name}/values` → `get_filter_values(name)`
  - `POST .../filters` → `apply_filters(request, persist=...)` (spatial returns
    the existing `SpatialResult`/GeoJSON shape)
  - An AgenTalk typed pass-through envelope mirroring `SpatialFilterEnvelope`.
- Integration tests for schema/values/apply over HTTP.

**NOT in scope**: the underlying methods (TASK-1467/1468/1469) — only wiring/transport.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | register filter `@tool`s in `get_tools` |
| `packages/ai-parrot/src/parrot/handlers/dataset_filter_handler.py` | CREATE | aiohttp handler + AgenTalk envelope |
| `packages/ai-parrot/tests/integration/test_dataset_filter_handler.py` | CREATE | schema / values / apply over HTTP |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from pydantic import BaseModel, Field
# Lazy import at runtime to avoid circular deps (mirror spatial handler):
#   from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.filtering import FilterDefinition, FilterResult  # TASK-1464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/handlers/spatial_filter_handler.py  (pattern to mirror)
class SpatialFilterHandler(web.View): ...   # aiohttp handler; lazy-imports DatasetManager
class SpatialFilterEnvelope(BaseModel):     # AgenTalk typed pass-through
    spec: SpatialFilterSpec; agent_id: str
    async def forward(self, dataset_manager) -> SpatialResult: ...
# Routes registered as:
#   app.router.add_route("*", "/api/v1/spatial/{agent_id}", SpatialFilterHandler)
#   app.router.add_route("*", "/api/v1/spatial/{agent_id}/manifest", SpatialFilterHandler)

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                 # line 500
    def get_tools(self) -> List[...]                   # AbstractToolkit tool exposure
    async def apply_filters(self, request, *, persist=False) -> FilterResult  # TASK-1467
    def get_filter_schema(self) -> List[Dict[str, Any]]                       # TASK-1469
    async def get_filter_values(self, name: str) -> List[Any]                 # TASK-1468
    def define_filters(self, definitions: List[FilterDefinition]) -> None     # TASK-1465
```

### Does NOT Exist
- ~~`parrot.handlers.dataset_filter_handler`~~ — created here.
- ~~A non-spatial filter route~~ — only `spatial_filter_handler.py` exists today.
- ~~`AbstractBot.run()` coupling for filtering~~ — like spatial, the envelope does
  NOT invoke the agent loop; it forwards directly to the manager.

---

## Implementation Notes

### Pattern to Follow
Copy the structure of `spatial_filter_handler.py` verbatim where possible:
two transport paths (direct + AgenTalk envelope), lazy `DatasetManager` import,
data-only responses. Register `@tool`s the same way the manager exposes its other
toolkit tools (inspect existing `get_tools` usage in `tool.py`).

### Key Constraints
- Async; data-only responses (no bidirectional chat↔UI coupling).
- `@tool` docstrings are the LLM-facing descriptions — make them precise.
- Reuse `FilterResult` / `SpatialResult` serialization; do not invent new envelopes
  beyond the AgenTalk pass-through.

---

## Acceptance Criteria

- [ ] `DatasetManager.get_tools()` includes the new filter tools with docstrings.
- [ ] `GET filters/schema`, `GET filters/{name}/values`, `POST filters` return expected payloads.
- [ ] Spatial filter requests over HTTP return the existing `SpatialResult` shape.
- [ ] AgenTalk envelope forwards to the manager without invoking the agent loop.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integration/test_dataset_filter_handler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/dataset_filter_handler.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_dataset_filter_handler.py
import pytest


async def test_get_schema(aiohttp_client, app_with_filter_handler):
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.get("/api/v1/filters/my-agent/schema")
    assert resp.status == 200
    body = await resp.json()
    assert any(e["name"] == "region" for e in body)


async def test_post_apply(aiohttp_client, app_with_filter_handler):
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.post("/api/v1/filters/my-agent",
                             json={"request": {"region": ["North"]}})
    assert resp.status == 200
```

---

## Agent Instructions

Standard SDD agent loop. Read `spatial_filter_handler.py` in full before writing
the new handler — replicate its envelope/transport conventions. Confirm the route
registration convention used by the server package.

---

## Completion Note

Implemented as specified. Added async LLM-facing tool wrappers `list_filters()` and
`set_filters()` to DatasetManager (auto-exposed via AbstractToolkit.get_tools() for
async public methods; `apply_filters` and `get_filter_values` already auto-exposed).
Created `handlers/dataset_filter_handler.py` with `DatasetFilterEnvelope` (AgenTalk
pass-through) and `DatasetFilterHandler` class (GET schema, GET values, POST apply
endpoints). 10 integration tests + 2 envelope tests pass. No linting errors.
