# TASK-4197: `POST /forms/export` — NDJSON stream handler + route

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4196, TASK-4195
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 + §2 wire shapes (G4, AC6). The HTTP door over
`A2UIExportService`: `POST {tp}/forms/export` with
`{"dialect", "form_uids"?, "published_only"?, "locale"?}` streams one
`ExportedSurface` JSON object per line as `application/x-ndjson`. The route
tenant is authoritative (the body cannot override it). Depends on TASK-4195
because both edit `handlers.py`.

---

## Scope

- Add `FormAPIHandler.export_forms` (before `get_style`) streaming via `web.StreamResponse`.
- Register `POST {tp}/forms/export` right after the clone route in `routes.py` (tenant mode `required`).
- Tests in `tests/unit/api/test_export_forms.py`: NDJSON framing, `published_only`, `form_uids`, `dialect=json_schema`, 400 (bad body / unknown dialect), 415 (a2ui without renderer), body tenant ignored.

**NOT in scope**: CLI (TASK-4204), cross-tenant export.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `export_forms` handler |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | route registration |
| `packages/parrot-formdesigner/tests/unit/api/test_export_forms.py` | CREATE | handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from navigator.responses import JSONResponse                                        # api/handlers.py:19
from parrot_formdesigner.services.a2ui_export import A2UIExportService, ExportedSurface   # TASK-4196
from parrot_formdesigner.core import FormDialect                                    # TASK-4191
from parrot_formdesigner.api.render import get_renderer, supported_formats          # api/render.py:104, 109
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py — FormAPIHandler
    async def get_style(self, request: web.Request) -> web.Response            # line 916 — insert export_forms ABOVE it
    self._get_tenant(request) -> str                                             # used throughout (e.g. line 741)
    self.registry: FormRegistry
    body parse pattern (create_form 1147-1150): try: body = await request.json() except (json.JSONDecodeError, ValueError): return JSONResponse({"error": "Invalid JSON body"}, status=400)
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
    app.router.add_post(f"{tp}/forms/{{form_uid}}/clone", _wrap_auth(handler.clone_form))   # line 397 — anchor
    def _wrap_auth(handler, *, tenant: str = "required")                                        # line 84
    # sibling literal routes already exist: POST {tp}/forms/from-db (377), POST {tp}/forms/blank (381)
# packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py (TASK-4196)
class A2UIExportService: __init__(registry, *, renderer=None, dialect="a2ui", locale="en"); async def export_tenant(tenant, *, form_uids=None, published_only=False) -> AsyncIterator[ExportedSurface]
```

### Does NOT Exist
- ~~`GET /forms/export`~~ — POST only (body carries the filter).
- ~~a `tenant` field in the request body~~ — ignored if present; the route tenant wins.
- ~~a reserved-segment list for `form_uid`~~ — `export` as a literal sibling is the existing `/forms/blank` pattern; the FEAT-429 guard covers tenant slugs only.
- ~~`web.StreamResponse` helper in formdesigner~~ — none exists; use aiohttp directly as below.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_export_forms.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#_wrap_auth"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Validate everything **before** `resp.prepare()` — once the stream starts, status is fixed at 200.
- `form_uids` entries must parse as UUIDs (400 otherwise); `published_only` must be a bool.
- One `json.dumps(row.model_dump(mode="json")) + "\n"` per row; `await resp.write(...)`; `await resp.write_eof()`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the handler above `get_style` — *why*: keeps the contract endpoints (`schema`, `style`, `export`, `translate`) adjacent.
2. Register the route after the clone route — *why*: spec §6 Edit Sites anchor; literal sibling of `/forms/blank`.
3. Tests through `setup_form_api` wiring (same fixture approach as TASK-4194's tests).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def get_style(self, request: web.Request) -> web.Response:' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# BEFORE — insert ABOVE `    async def get_style(self, request: web.Request) -> web.Response:` (verified: api/handlers.py:916)
    async def export_forms(self, request: web.Request) -> web.Response:
        """POST /api/v1/{tenant}/forms/export — NDJSON stream of ExportedSurface rows (FEAT-650).

        Body ``{"dialect": "a2ui"|"json_schema", "form_uids": [..]?, "published_only": bool?, "locale": str?}``.
        The route tenant is authoritative. 400 on a malformed body / unknown dialect, 415 when ``a2ui`` is
        requested without the renderer. Each row is isolated: a render failure is an ``error`` row.
        """
        tenant = self._get_tenant(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be an object"}, status=400)
        raw_dialect = body.get("dialect", "a2ui")
        try:
            dialect = FormDialect(raw_dialect)
        except ValueError:
            return JSONResponse({"error": f"unknown dialect {raw_dialect!r}", "supported": [d.value for d in FormDialect]}, status=400)
        if dialect is FormDialect.A2UI and get_renderer("a2ui") is None:
            return JSONResponse({"supported": supported_formats()}, status=415)
        # FILL IN: parse body.get("form_uids") → list[uuid.UUID] | None (400 on a non-list or a non-UUID entry) and
        #          published_only = bool(body.get("published_only", False)); locale = body.get("locale", "en") — bounded by §2 wire shape
        from ..services.a2ui_export import A2UIExportService  # lazy: optional-extra module

        service = A2UIExportService(self.registry, dialect=dialect.value, locale=locale)
        resp = web.StreamResponse(status=200, headers={"Content-Type": "application/x-ndjson"})
        await resp.prepare(request)
        async for row in service.export_tenant(tenant, form_uids=form_uids, published_only=published_only):
            await resp.write((json.dumps(row.model_dump(mode="json")) + "\n").encode("utf-8"))
        await resp.write_eof()
        return resp
```
**Why this shape**: all 4xx decisions happen before `prepare()`; the service does the per-form isolation so the handler never catches render errors itself (spec §7 NDJSON pattern). `json` is already imported in `handlers.py` (used at line 1149). Add `FormDialect`/`get_renderer`/`supported_formats` imports only if TASK-4194/4195 did not already add them (check with `grep -n` first).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    app.router.add_post(f"{tp}/forms/{{form_uid}}/clone", _wrap_auth(handler.clone_form))' packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py)
# AFTER — insert below the clone route line (verified: api/routes.py:397)

    # FEAT-650 — bulk export (NDJSON). Literal sibling of /forms/blank; tenant "required".
    app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))
```
**Why**: `_wrap_auth` default tenant mode is `"required"` (routes.py:84) — export is never public.

### `packages/parrot-formdesigner/tests/unit/api/test_export_forms.py` (CREATE)
```python
"""POST /forms/export — FEAT-650 TASK-4197."""

from __future__ import annotations

import json

import pytest

# FILL IN: app/client fixture (same wiring as tests/unit/api/test_get_schema_dialect.py) with 3 forms in tenant
#          "navigator" (one published_version="1.0") and 1 form in tenant "other"; register a fake "a2ui" renderer
#          via api.render.register_renderer so the suite runs without ai-parrot — bounded by TASK-4194's fixture


async def _lines(resp):
    text = await resp.text()
    return [json.loads(line) for line in text.splitlines() if line]


async def test_ndjson_framing_and_tenant_isolation(client):
    resp = await client.post("/api/v1/navigator/forms/export", json={"dialect": "a2ui", "tenant": "other"})
    assert resp.status == 200 and resp.content_type == "application/x-ndjson"
    rows = await _lines(resp)
    assert len(rows) == 3 and all(r["dialect"] == "a2ui" and r["envelope"] for r in rows)


async def test_published_only_and_form_uids_filter(client):
    # FILL IN: {"published_only": true} → 1 row; {"form_uids": [<one uid>]} → 1 row; non-UUID entry → 400 — bounded by §2


async def test_json_schema_dialect(client):
    rows = await _lines(await client.post("/api/v1/navigator/forms/export", json={"dialect": "json_schema"}))
    assert rows and all(r["envelope"]["type"] == "object" for r in rows)


async def test_bad_body_unknown_dialect_and_missing_renderer(client):
    # FILL IN: non-object body → 400; {"dialect": "xml"} → 400 with supported; _RENDERERS without "a2ui" → 415 — bounded by AC3/AC6
```
**Why this shape**: the tenant-isolation test posts a foreign `tenant` in the body on purpose (spec: route tenant is authoritative).

### FILL IN checklist
- [ ] `handlers.py::export_forms` — `form_uids`/`published_only`/`locale` parsing with 400s; bounded by §2 wire shape.
- [ ] `test_export_forms.py` — fixtures + `FILL IN` bodies; bounded by AC6.

---

## Acceptance Criteria

- [ ] `POST /forms/export` streams `application/x-ndjson`, one row per form of the route tenant only (AC6).
- [ ] Filters and dialects behave per §2; 400/415 before any byte is streamed.
- [ ] Route registered with `tenant="required"`; `GET /forms/{uid}` routes unaffected (`test_route_tenant_coverage.py` passes).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_export_forms.py -v`; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_export_forms.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_route_tenant_coverage.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §2 wire shapes (`POST /forms/export`) and §3 M3
3. **Check dependencies** — TASK-4196 and TASK-4195 `"done"`
4. **Verify the Codebase Contract** — `grep -n 'async def get_style\|^import json' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`; `grep -n 'clone", _wrap_auth' packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the three files
9. **Close** with `scripts/sdd/close_task.sh TASK-4197 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

Implemented by codex gpt-5.6-terra; merged by sdd-worker orchestrator; merge-tier validation green (880 passed).

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-24
**Notes**:

**Deviations from spec**: none
