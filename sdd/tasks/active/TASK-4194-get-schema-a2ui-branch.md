# TASK-4194: `GET /forms/{uid}/schema` A2UI branch + legacy golden test

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4193
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (G2, G3, AC2, AC3, AC4, AC15). `FormAPIHandler.get_schema`
(`api/handlers.py:884-914`) renders the JSON-Schema body, dispatches
`onSchemaLoaded`, applies `schema_overrides` and returns JSON. This task adds
the A2UI branch **after** `enforce_membership_unless_public` and after the
`onSchemaLoaded` dispatch (codex S2/S10): when `resolve_dialect()` says
`A2UI`, answer `render_a2ui_schema()` framed by `a2ui_wire.a2ui_response`,
mirroring `handle_render`'s `?with_meta=true`. The legacy path must stay
byte-identical — proven by a golden fixture captured **before** the branch is
added (red/green, spec §7 Known Risks).

---

## Scope

- Capture a golden JSON of today's `GET /schema` body for a fixture form into `tests/unit/api/fixtures/golden_schema_legacy.json` (first commit of the task, before touching the handler).
- Add the A2UI branch to `get_schema`: `DialectError` → `JSONResponse(payload, status)`; A2UI → envelopes via `render_a2ui_schema(form, locale=…, overrides=resolution.schema_overrides)`; single envelope → `a2ui_wire.a2ui_response([env], status=200)`; several → `a2ui_wire.a2ui_response(envelopes, status=200)` (`{"messages": [...]}`); `?with_meta=true` → `web.json_response({"content": envelopes[0] if len==1 else {"messages": envelopes}, "content_type", "warnings", "metadata"})`.
- Tests: legacy golden unchanged; a2ui single envelope; a2ui + overrides → messages; 400; 415; private form membership under `?dialect=a2ui`; `onSchemaLoaded` abort → JSON error under both dialects.

**NOT in scope**: `list_forms` (TASK-4195), `get_form` (never changes), docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | A2UI branch in `get_schema` + `dialect` import |
| `packages/parrot-formdesigner/tests/unit/api/fixtures/golden_schema_legacy.json` | CREATE | pre-feature `GET /schema` body |
| `packages/parrot-formdesigner/tests/unit/api/test_get_schema_dialect.py` | CREATE | golden + a2ui + lifecycle/auth tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.responses import JSONResponse                                        # api/handlers.py:19
from parrot_formdesigner.api import a2ui_wire                                       # api/handlers.py:30
from parrot_formdesigner.api.dialect import DialectError, resolve_dialect, render_a2ui_schema, A2UI_MEDIA_TYPE   # TASK-4192/4193
from parrot_formdesigner.core import FormDialect                                    # TASK-4191
from parrot_formdesigner.services.event_dispatcher import apply_schema_overrides, dispatch   # api/handlers.py:27
from parrot_formdesigner.core.events import FormEventAbort                          # api/handlers.py:20
from parrot_formdesigner.api.routes import setup_form_api                           # api/routes.py:192
from parrot_formdesigner.services.registry import FormRegistry                      # services/registry.py:240
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py — class FormAPIHandler
    async def get_schema(self, request: web.Request) -> web.Response:               # line 884
        # 885-893: form_uid/tenant/registry.get/404/_assert_form_tenant/enforce_membership_unless_public
        # 895: rendered: RenderedForm = await self.schema_renderer.render(form)
        # 898-910: resolution = await dispatch("onSchemaLoaded", form=form, request=request, tenant=tenant,
        #          auth_context=self._build_auth_context(request), schema_dump=rendered.content)  (FormEventAbort → JSONResponse error)
        # 911-913: content = rendered.content; if resolution.schema_overrides: content = apply_schema_overrides(content, dict(...))
        # 914: return JSONResponse(content)          ← the anchor; the A2UI branch goes BEFORE line 911
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response   # line 275 — 1 → application/a2ui+json; else {"messages": [...]} application/json
# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py — with_meta shape (lines 215-235):
#   if request.query.get("with_meta", "").lower() in ("1", "true", "yes"): web.json_response({"content": ..., "content_type": ..., "warnings": [...], "metadata": ...})
# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
class EventResolution(BaseModel): schema_overrides: Mapping[str, Any] | None = None   # line 182, 203
# tests: app wiring pattern — tests/unit/api/test_reserved_segment_guard.py (TestServer/TestClient with navigator-auth decorators monkeypatched to pass-through) and tests/unit/api/test_submit_a2ui.py (A2UI handler tests)
```

### Does NOT Exist
- ~~a `dialect` branch in `get_form`~~ — must NOT be added (resolved §8: raw FormSchema always).
- ~~A2UI `error` envelopes for lifecycle aborts / 404 / membership failures~~ — those keep the JSON error bodies (they occur before negotiation).
- ~~`request.query["dialect"]` parsing inside handlers~~ — only `resolve_dialect` parses it.
- ~~`FormAPIHandler.a2ui_renderer`~~ — no attribute; `render_a2ui_schema` resolves the renderer via `get_renderer("a2ui")`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/fixtures/golden_schema_legacy.json", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_get_schema_dialect.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#a2ui_response",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py#dispatch",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py#EventResolution"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Golden first: write the fixture + the golden test and see it pass on the untouched handler, commit, then add the branch (AC2).
- The branch is inserted between the `onSchemaLoaded` dispatch and the `apply_schema_overrides` line, so JSON callers run exactly the same statements as today.
- `DialectError` is caught right after `enforce_membership_unless_public` and before rendering — a 400/415 must not trigger a JSON-Schema render nor the lifecycle hook? **Decision**: resolve the dialect *after* the hook so `onSchemaLoaded` semantics are identical under both dialects (AC15); a 400 for `?dialect=xml` therefore still runs the hook — acceptable and simpler.

---

## Implementation Blueprint

### Steps (in order)
1. Build the golden fixture by running the existing handler on a fixture form (2 sections, TEXT/SELECT/NUMBER/BOOLEAN) and dumping `resp.json()` to the fixture file — *why*: AC2's byte-level guarantee needs a pre-change capture.
2. Add the import line and the branch — *why*: see constraints.
3. Tests for every row of AC3/AC4/AC15.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from \. import a2ui_wire$' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `from . import a2ui_wire` (verified: api/handlers.py:30)
from .dialect import DialectError, render_a2ui_schema, resolve_dialect
from ..core import FormDialect
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — branch)
```python
# occurrences: 1 (verified: grep -c '        return JSONResponse(content)$' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# BEFORE — insert ABOVE the two lines
#     content = rendered.content
#     if resolution.schema_overrides:
# that precede `        return JSONResponse(content)` (verified: api/handlers.py:911-914), i.e. right after the
# `except FormEventAbort as exc: ... return JSONResponse(...)` block of the onSchemaLoaded dispatch (line 904-910):
        # FEAT-650 — A2UI dialect (resolved AFTER membership + onSchemaLoaded so lifecycle semantics are identical)
        try:
            dialect = resolve_dialect(request, form)
        except DialectError as exc:
            return JSONResponse(exc.payload, status=exc.status)
        if dialect is FormDialect.A2UI:
            locale = request.query.get("locale", "en")
            envelopes, a2ui_rendered, a2ui_warnings = await render_a2ui_schema(
                form, locale=locale, overrides=resolution.schema_overrides
            )
            if request.query.get("with_meta", "").lower() in ("1", "true", "yes"):
                return web.json_response(
                    {
                        "content": envelopes[0] if len(envelopes) == 1 else {"messages": envelopes},
                        "content_type": a2ui_rendered.content_type,
                        "warnings": [w.model_dump(mode="json") for w in a2ui_rendered.warnings] + a2ui_warnings,
                        "metadata": a2ui_rendered.metadata,
                    }
                )
            return a2ui_wire.a2ui_response(envelopes, status=200)
```
**Why this shape**: statement-for-statement the JSON path is untouched (AC2); the framing reuses `a2ui_wire.a2ui_response` so `/schema` and `/data` speak the same wire (spec §2); `with_meta` mirrors `handle_render` (`api/render.py:215-235`). Also update the `get_schema` docstring to mention the dialect negotiation.

### `packages/parrot-formdesigner/tests/unit/api/test_get_schema_dialect.py` (CREATE)
```python
"""GET /forms/{uid}/schema dialect negotiation — FEAT-650 TASK-4194."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "fixtures" / "golden_schema_legacy.json"

# FILL IN: app/client fixture — copy the TestServer/TestClient + navigator-auth pass-through pattern from
#          tests/unit/api/test_reserved_segment_guard.py; register the fixture form (is_public=True, tenant="navigator")
#          in a FormRegistry and call setup_form_api(app, registry) — bounded by that test's proven wiring


async def test_legacy_body_is_golden(client, form):
    resp = await client.get(f"/api/v1/navigator/forms/{form.form_uid}/schema")
    assert resp.status == 200
    assert await resp.json() == json.loads(GOLDEN.read_text())


async def test_forced_json_schema_on_a2ui_form_is_golden(client, form_a2ui):
    # FILL IN: same body as golden for ?dialect=json_schema on a form stored with dialect="a2ui" — bounded by AC3


async def test_a2ui_single_envelope(client, form):
    pytest.importorskip("parrot.outputs.a2ui")
    resp = await client.get(f"/api/v1/navigator/forms/{form.form_uid}/schema?dialect=a2ui")
    assert resp.status == 200 and resp.content_type == "application/a2ui+json"
    body = await resp.json()
    assert body["createSurface"]["surfaceId"] == f"form-{form.form_uid}"


async def test_a2ui_with_overrides_is_messages(client, form):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: bind an onSchemaLoaded handler returning schema_overrides={"title": "X"} (see tests/integration/test_lifecycle_events_get.py
    #          for how events are bound) → body == {"messages": [createSurface, updateComponents]} and content_type application/json — bounded by AC4/G3


async def test_unknown_dialect_400_and_missing_extra_415(client, form):
    # FILL IN: ?dialect=xml → 400 with "supported"; with api.render._RENDERERS emptied of "a2ui" → ?dialect=a2ui → 415 {"supported": [...]} — bounded by AC3


async def test_private_form_requires_membership_under_a2ui(client, private_form):
    # FILL IN: without session/programs → same status as today's JSON path (403/401 per enforce_membership_unless_public) — bounded by AC15


async def test_onschemaloaded_abort_is_json_under_both_dialects(client, form):
    # FILL IN: bind an aborting handler → both ?dialect=a2ui and default return JSON {"error","reason"} with exc.status_code — bounded by AC15
```
**Why this shape**: AC2, AC3, AC4, AC15 each get a named test; the golden test is the only guard against a silent legacy change.

### FILL IN checklist
- [ ] `test_get_schema_dialect.py` — app/client fixtures; bounded by `test_reserved_segment_guard.py`'s wiring.
- [ ] `test_get_schema_dialect.py` — bodies of the five `FILL IN` tests; bounded by AC3/AC4/AC15.
- [ ] `fixtures/golden_schema_legacy.json` — captured from the untouched handler; bounded by AC2.

---

## Acceptance Criteria

- [ ] Golden test passes before and after the branch; `?dialect=json_schema` on an `a2ui` form returns the golden body (AC2/AC3).
- [ ] `?dialect=a2ui` → single `createSurface` with `application/a2ui+json`; with overrides → `{"messages": [...]}`; every envelope validates (AC4).
- [ ] 400 / 415 payloads per §7; membership and `onSchemaLoaded` abort behave identically under both dialects (AC15).
- [ ] `get_form` is untouched (`git diff` shows no change between lines 847-882).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_get_schema_dialect.py -v`; `ruff check` clean on `handlers.py`.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_get_schema_dialect.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_handler_tenant_split.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_lifecycle_events_get.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M2, §7 Known Risks (golden), codex S2/S10 in §9
3. **Check dependencies** — TASK-4193 `"done"` (which implies 4191/4192)
4. **Verify the Codebase Contract** — `grep -n 'return JSONResponse(content)$\|async def get_schema\|from . import a2ui_wire' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** golden first, then the branch; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the three files
9. **Close** with `scripts/sdd/close_task.sh TASK-4194 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
