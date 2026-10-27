# TASK-4200: `POST /forms/translate` — stateless JSON Schema → A2UI handler + route

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4199, TASK-4197
**Assigned-to**: unassigned

---

## Context

Spec §2 wire shapes + §3 Module 4 (AC16, resolved §8). A stateless HTTP door
over `translate_jsonschema_to_a2ui`: body `{"schema", "form_id"?, "title"?,
"locale"?}` → the `createSurface` envelope (`application/a2ui+json`), route
tenant stamped, nothing persisted. Depends on TASK-4197 because both edit
`handlers.py` and `routes.py`.

---

## Scope

- Add `FormAPIHandler.translate_form` (next to `export_forms`, before `get_style`).
- Register `POST {tp}/forms/translate` after the export route.
- Tests `tests/unit/api/test_translate_forms.py`: 200 + tenant stamped, `with_meta`, 400 (no/invalid `schema`), 413, 415, registry untouched.

**NOT in scope**: persisting the translated form (use `POST /forms` import for that), CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `translate_form` handler |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | route registration |
| `packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py` | CREATE | handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.responses import JSONResponse                                   # api/handlers.py:19
from parrot_formdesigner.api import a2ui_wire                                  # api/handlers.py:30 (A2UI_MAX_BODY_BYTES :39, a2ui_response :275)
from parrot_formdesigner.api.render import get_renderer, supported_formats     # api/render.py:104, 109
from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui   # TASK-4199 (import lazily inside the handler)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
    async def export_forms(self, request) -> web.Response      # TASK-4197 — translate_form goes right after it (both before get_style, :916)
    self._get_tenant(request) -> str
    # body-size guard pattern (submit_data :1040-1048): if request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES: ... 413
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))   # line 39
def a2ui_response(envelopes: list[dict], *, status: int) -> web.Response                 # line 275
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
    app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))         # TASK-4197 — anchor for the translate route
# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py — with_meta shape (:215-235)
```

### Does NOT Exist
- ~~`GET /forms/translate`~~ — POST only.
- ~~persisting the translated form~~ — never (resolved §8); the handler must not touch `self.registry`.
- ~~a `tenant` field in the body~~ — ignored; route tenant wins.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#a2ui_response",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- 413 check first (`content_length`), then JSON parse, then `schema` must be a dict, then 415 renderer check, then translate; extractor/pydantic errors → 400 `{"error": "invalid schema", "details": str(exc)}`.
- Response = `a2ui_wire.a2ui_response([rendered.content], status=200)`; `?with_meta=true` → `web.json_response({"content", "content_type", "warnings", "metadata"})` like `handle_render`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the handler after `export_forms` — *why*: contract endpoints stay adjacent.
2. Register the route after the export route — *why*: spec §6 Edit Sites.
3. Tests through the TASK-4194 app fixture approach.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def get_style(self, request: web.Request) -> web.Response:' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# BEFORE — insert ABOVE `    async def get_style(...)` (verified: api/handlers.py:916; i.e. right after TASK-4197's export_forms)
    async def translate_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/{tenant}/forms/translate — stateless JSON Schema → A2UI (FEAT-650, resolved §8).

        Body ``{"schema": dict, "form_id"?, "title"?, "locale"?}``; answers the createSurface with the route
        tenant stamped. Never persists. 400 invalid body/schema, 413 over A2UI_MAX_BODY_BYTES, 415 no renderer.
        """
        tenant = self._get_tenant(request)
        if request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES:
            return JSONResponse({"error": "body too large", "max_bytes": a2ui_wire.A2UI_MAX_BODY_BYTES}, status=413)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)
        schema = body.get("schema") if isinstance(body, dict) else None
        if not isinstance(schema, dict):
            return JSONResponse({"error": "schema (object) is required"}, status=400)
        if get_renderer("a2ui") is None:
            return JSONResponse({"supported": supported_formats()}, status=415)
        from ..services.a2ui_translate import translate_jsonschema_to_a2ui  # lazy: optional-extra path

        try:
            rendered = await translate_jsonschema_to_a2ui(
                schema, form_id=body.get("form_id"), title=body.get("title"), tenant=tenant, locale=body.get("locale", "en")
            )
        except (ValidationError, ValueError) as exc:
            return JSONResponse({"error": "invalid schema", "details": str(exc)}, status=400)
        if request.query.get("with_meta", "").lower() in ("1", "true", "yes"):
            return web.json_response(
                {
                    "content": rendered.content,
                    "content_type": rendered.content_type,
                    "warnings": [w.model_dump(mode="json") for w in rendered.warnings],
                    "metadata": rendered.metadata,
                }
            )
        return a2ui_wire.a2ui_response([rendered.content], status=200)
```
**Why this shape**: order of guards = cheapest first and before any work; `ValidationError` is already imported in `handlers.py` (line 18), `json` at line 12.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified at task time: grep -c 'app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))' packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py — added by TASK-4197)
# AFTER — insert below the export route line
    # FEAT-650 — stateless JSON Schema → A2UI translation (never persists); tenant "required".
    app.router.add_post(f"{tp}/forms/translate", _wrap_auth(handler.translate_form))
```

### `packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py` (CREATE)
```python
"""POST /forms/translate — FEAT-650 TASK-4200."""

from __future__ import annotations

import pytest

# FILL IN: app/client fixture (same wiring as tests/unit/api/test_get_schema_dialect.py); register a fake "a2ui" renderer
#          that echoes form.tenant into content {"createSurface": {"surfaceId": "x", "tenant": form.tenant}} — bounded by TASK-4194 fixture

SCHEMA = {"type": "object", "title": "T", "properties": {"a": {"type": "string", "title": "A"}}, "required": ["a"]}


async def test_translate_stamps_route_tenant_and_never_persists(client, registry):
    before = len(await registry.list_forms(tenant="navigator"))
    resp = await client.post("/api/v1/navigator/forms/translate", json={"schema": SCHEMA, "tenant": "other"})
    assert resp.status == 200 and resp.content_type == "application/a2ui+json"
    assert (await resp.json())["createSurface"]["tenant"] == "navigator"
    assert len(await registry.list_forms(tenant="navigator")) == before


async def test_with_meta_wrapper(client):
    # FILL IN: ?with_meta=true → keys {"content","content_type","warnings","metadata"} — bounded by §2


async def test_400_413_415(client, monkeypatch):
    # FILL IN: {} → 400; {"schema": "x"} → 400; Content-Length > A2UI_MAX_BODY_BYTES (monkeypatch a2ui_wire.A2UI_MAX_BODY_BYTES=10) → 413;
    #          _RENDERERS without "a2ui" → 415 — bounded by §2 wire shape


async def test_real_renderer_validates():
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: with the real A2UIFormRenderer registered, POST SCHEMA → validate_envelope(deserialize(body).create_surface) passes — bounded by AC16
```

### FILL IN checklist
- [ ] `test_translate_forms.py` — fixtures + the three `FILL IN` tests; bounded by AC16.

---

## Acceptance Criteria

- [ ] `POST /forms/translate` returns a validating `createSurface`, stamps the route tenant, persists nothing, answers 400/413/415 per §2 (AC16).
- [ ] Route registered with `tenant="required"`; `test_route_tenant_coverage.py` passes.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py -v`; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_route_tenant_coverage.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_export_forms.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §2 wire shapes (`POST /forms/translate`) and §3 M4
3. **Check dependencies** — TASK-4199 and TASK-4197 `"done"`
4. **Verify the Codebase Contract** — `grep -n 'async def export_forms\|async def get_style\|^from pydantic import' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`; `grep -n 'forms/export' packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the three files
9. **Close** with `scripts/sdd/close_task.sh TASK-4200 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

Implemented by codex gpt-5.6-sol; merged by sdd-worker orchestrator; merge-tier validation green (884 passed).

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-24
**Notes**:

**Deviations from spec**: none
