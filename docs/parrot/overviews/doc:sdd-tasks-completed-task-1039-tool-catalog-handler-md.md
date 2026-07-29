---
type: Wiki Overview
title: 'TASK-1039: ToolCatalogHandler'
id: doc:sdd-tasks-completed-task-1039-tool-catalog-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot_tools import TOOL_REGISTRY # used in parrot/tools/__init__.py:184'
relates_to:
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.tools_catalog
  rel: mentions
- concept: mod:parrot_tools
  rel: mentions
---

# TASK-1039: ToolCatalogHandler

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> The frontend needs a read-only catalog of available tools so users can pick from
> `TOOL_REGISTRY` when configuring an ephemeral agent (spec §3 Module 7). This is a
> simple endpoint that exposes the registry as JSON.

---

## Scope

- Create `parrot/handlers/tools_catalog.py` with `ToolCatalogHandler(BaseView)`.
- Implement `GET /api/v1/tools/catalog` returning `TOOL_REGISTRY` entries as JSON.
- Response format: `[{slug, dotted_path, description?, category?}, ...]` sorted by slug.
- Enrich entries with description/category metadata from the tool classes where available.
- Requires standard session auth (same as other API endpoints).
- Write unit tests.

**NOT in scope**: Route registration (Module 5 / TASK-1041), modifying `TOOL_REGISTRY` itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/tools_catalog.py` | CREATE | ToolCatalogHandler |
| `tests/unit/test_tools_catalog.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools import TOOL_REGISTRY                               # used in parrot/tools/__init__.py:184
# TOOL_REGISTRY is a dict: {slug: dotted_path, ...}
```

### Existing Signatures to Use
```python
# parrot/tools/__init__.py:184
from parrot_tools import TOOL_REGISTRY
# TOOL_REGISTRY.get(name) → dotted_path string
# TOOL_REGISTRY.items() → [(slug, dotted_path), ...]

# BaseView pattern used by all handlers:
# from parrot.handlers.base import BaseView  (or similar)
# Verify the actual import path by checking existing handlers like UserAgentHandler
```

### Does NOT Exist
- ~~`parrot/handlers/tools_catalog.py`~~ — does not exist yet; this task creates it.
- ~~`TOOL_REGISTRY.descriptions`~~ — TOOL_REGISTRY is a simple dict of `{slug: dotted_path}`.
  Descriptions must be extracted from the tool classes themselves (import and inspect docstrings).
- ~~`GET /api/v1/tools/catalog`~~ — route does not exist yet; wired in TASK-1041.

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the pattern from existing handlers like UserAgentHandler
from aiohttp import web
from parrot_tools import TOOL_REGISTRY

class ToolCatalogHandler(BaseView):
    async def get(self) -> web.Response:
        catalog = []
        for slug, dotted_path in sorted(TOOL_REGISTRY.items()):
            entry = {"slug": slug, "dotted_path": dotted_path}
            # Optionally try to import and extract docstring for description
            catalog.append(entry)
        return self.json_response(catalog)
```

### Key Constraints
- Read-only — no mutations.
- Standard session auth (mirror what `UserAgentHandler` uses for GET).
- Sort output by `slug` for deterministic responses.
- If importing tool classes for descriptions is too slow, cache the catalog on first call.
- The spec notes (§8) that `TOOL_REGISTRY` metadata should be enriched — do a best-effort extraction of docstrings.

### References in Codebase
- `parrot/tools/__init__.py:184` — `TOOL_REGISTRY` import and usage
- `parrot/handlers/agents/users.py:161` — `UserAgentHandler` as a pattern for handler structure

---

## Acceptance Criteria

- [ ] `GET /api/v1/tools/catalog` returns JSON array of `{slug, dotted_path, description?}` entries.
- [ ] Output is sorted by `slug`.
- [ ] Same slugs as `TOOL_REGISTRY.keys()` are present in the response.
- [ ] Standard auth/session check is applied.
- [ ] All tests pass: `pytest tests/unit/test_tools_catalog.py -v`
- [ ] No linting errors: `ruff check parrot/handlers/tools_catalog.py`
- [ ] Import works: `from parrot.handlers.tools_catalog import ToolCatalogHandler`

---

## Test Specification

```python
# tests/unit/test_tools_catalog.py
import pytest
from unittest.mock import patch, MagicMock


class TestToolCatalogHandler:
    async def test_returns_registry_entries(self, aiohttp_client):
        # Mock TOOL_REGISTRY with known entries
        with patch("parrot.handlers.tools_catalog.TOOL_REGISTRY", {
            "weather": "parrot_tools.weather.WeatherTool",
            "search": "parrot_tools.search.SearchTool",
        }):
            resp = await client.get("/api/v1/tools/catalog")
            assert resp.status == 200
            data = await resp.json()
            slugs = [e["slug"] for e in data]
            assert slugs == ["search", "weather"]  # sorted

    async def test_empty_registry(self, aiohttp_client):
        with patch("parrot.handlers.tools_catalog.TOOL_REGISTRY", {}):
            resp = await client.get("/api/v1/tools/catalog")
            assert resp.status == 200
            data = await resp.json()
            assert data == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §3 Module 7.
2. **Check dependencies** — none for this task.
3. **Verify the Codebase Contract** — confirm `TOOL_REGISTRY` import path with `grep`.
4. **Check existing handler patterns** — read `UserAgentHandler` for BaseView usage, imports, auth.
5. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
6. **Implement** `ToolCatalogHandler`.
7. **Verify** all acceptance criteria are met.
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-07
**Notes**: `parrot/handlers/tools_catalog.py` created with `ToolCatalogHandler(BaseView)`. GET returns TOOL_REGISTRY sorted by slug. Docstring and category extracted via best-effort import. Catalog cached at module level after first request. Auth via `@is_authenticated()` / `@user_session()` decorators. 12 unit tests pass.

**Deviations from spec**: none
