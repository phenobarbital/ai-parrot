# TASK-4203: Dual-wire `POST /forms` — import an A2UI surface (`is_a2ui_surface_body`, `_import_a2ui_surface`)

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4202, TASK-4200
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G6, AC11; codex S5; resolved §8 conflict policy).
`POST /forms` today is LLM-prompt only (`body["prompt"]`, 503 without a
client). This task adds a surface branch **before** the LLM-client guard:
`a2ui_wire.is_a2ui_surface_body()` detects `Content-Type:
application/a2ui+json` or `{"version": "v1.0", "createSurface": {...}}`;
`_import_a2ui_surface` validates (`validate_envelope`, S5), extracts through
`A2UIExtractor`, stamps the route tenant, applies the 409-unless-`overwrite`
policy and registers with `persist=True`. Depends on TASK-4200 because both
edit `handlers.py`.

---

## Scope

- `a2ui_wire.is_a2ui_surface_body(request, body)` next to `is_a2ui_request` (no `parrot.*` import).
- `create_form`: after `_rbac_shadow_gate`, parse the body first (moving the parse above the 503 guard), branch on the predicate, else the legacy prompt path unchanged.
- `_import_a2ui_surface`: 413 (`A2UI_MAX_BODY_BYTES`, A2UI error envelope like `submit_data`), extract (ValueError → 422 `{"error": "invalid surface", "details"}`), tenant stamp, conflict check (`registry.get` exists and `?overwrite` not truthy → 409; `FormAlreadyExistsError` → 409), bump version on overwrite, `register(persist=True, overwrite=True, tenant=tenant)`, 201 payload with `import` report.
- Tests `tests/unit/api/test_import_a2ui.py`.

**NOT in scope**: CLI import (TASK-4204), heuristic rules (TASK-4202).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` | MODIFY | `is_a2ui_surface_body` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `create_form` branch + `_import_a2ui_surface` |
| `packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py` | CREATE | import tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.responses import JSONResponse                                   # api/handlers.py:19
from parrot_formdesigner.api import a2ui_wire                                  # api/handlers.py:30
from parrot_formdesigner.api._utils import _bump_version                       # api/handlers.py:31 (api/_utils.py:61)
from parrot_formdesigner.services.registry import FormAlreadyExistsError, FormRegistry   # api/handlers.py:28 (registry.py:51, 240)
from parrot_formdesigner.extractors import A2UIExtractor                       # TASK-4201 (lazy inside the handler — optional extra)
from parrot_formdesigner.core import FormDialect                               # TASK-4191
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
A2UI_MAX_BODY_BYTES                                                       # line 39
def is_a2ui_request(request: web.Request, body: Any) -> bool              # line 122 — anchor; detects Content-Type OR {"version":"v1.0","action":...}; MUST NOT import parrot.* (lines 14-16)
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py — FormAPIHandler.create_form (line 1135)
#   1138: await self._rbac_shadow_gate(request, "create_form")
#   1142-1146: if self._create_tool.client is None: return JSONResponse({"error": "No LLM client configured for form creation"}, status=503)
#   1147-1150: try: body = await request.json() except (json.JSONDecodeError, ValueError): 400
#   1152-1154: prompt = body.get("prompt"); if not prompt: 400
#   1155: tenant = self._get_tenant(request)
#   1181-1190: success payload {"form_uid", "form_id", "title", "url": f"{prefix}/{tenant}/forms/{form_uid}"} with prefix = request.app.get("_form_prefix", "")
# submit_data 413 pattern (1040-1048): from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope → a2ui_wire.a2ui_response([envelope], status=413)
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def register(self, form, *, persist=False, overwrite=True, tenant=None) -> None   # 466 — FormAlreadyExistsError on slug clash with a DIFFERENT form_uid
    async def get(self, form_uid, *, tenant=None) -> FormSchema | None                     # 976
# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py (TASK-4201/4202)
class A2UIExtractor: def extract(self, surface, *, form_id=None, title=None, tenant=None) -> ExtractedForm   # raises ValueError (invalid/non-surface/limits)
class ExtractedForm: form; mode; warnings; dropped: list[DroppedComponent]
```

### Does NOT Exist
- ~~`POST /forms/import`~~ — rejected; `POST /forms` is dual-wire.
- ~~trusting `parrot_tenant` / `parrot_submit_url` from the surface~~ — tenant comes from the route (spec §7 "Tenant stamping"); the extractor already ignores `parrot_tenant`.
- ~~minting a new `form_uid` on conflict~~ — rejected (resolved §8: 409 unless `?overwrite=true`).
- ~~`is_a2ui_request` detecting `createSurface`~~ — it only detects `action`; hence the new predicate.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#is_a2ui_request",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormAlreadyExistsError",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py#_bump_version"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Body parse must move **above** the LLM 503 guard (S5), so an import works on a server with no LLM client; the prompt path then checks the client exactly as before.
- `?overwrite=true` (`"1"|"true"|"yes"`, case-insensitive). On overwrite: `form.version = _bump_version(existing.version)` before `register`.
- 201 payload: `{"form_uid", "form_id", "url", "dialect", "import": {"mode", "warnings", "dropped": [DroppedComponent dumps]}}`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the predicate in `a2ui_wire.py` — *why*: detection must work without ai-parrot (same rule as `is_a2ui_request`).
2. Reorder `create_form` (parse → branch → 503 guard → prompt) — *why*: S5.
3. Add `_import_a2ui_surface` right after `create_form` — *why*: keeps the import logic out of the LLM path.
4. Tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def is_a2ui_request(request: web.Request, body: Any) -> bool:' packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py)
# BEFORE — insert ABOVE `def is_a2ui_request(request: web.Request, body: Any) -> bool:` (verified: api/a2ui_wire.py:122)
def is_a2ui_surface_body(request: web.Request, body: Any) -> bool:
    """True when the body is an agent→renderer ``createSurface`` envelope (FEAT-650 import).

    ``Content-Type: application/a2ui+json`` OR a JSON object with ``version == "v1.0"``
    and a ``createSurface`` object. Never imports ``parrot.outputs.a2ui`` (same rule as
    :func:`is_a2ui_request`): ``POST /forms`` must keep working without the extra.
    """
    if request.content_type == "application/a2ui+json":
        return True
    return isinstance(body, dict) and body.get("version") == "v1.0" and isinstance(body.get("createSurface"), dict)
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — `create_form` reorder)
```python
# occurrences: 2 (verified: grep -c '        if self._create_tool.client is None:' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# FILL IN: disambiguate — the FIRST occurrence, inside create_form (api/handlers.py:1142), directly preceded by the comment
#   `# _create_tool was initialised with the client available at construction` ... `# again, so the guard accurately reflects the tool's actual state.`;
#   the second occurrence is inside edit_form (~:1199) and MUST NOT be touched.
# REORDER inside create_form (verified: api/handlers.py:1138-1155): move the existing
#     try: body = await request.json() except (json.JSONDecodeError, ValueError): return JSONResponse({"error": "Invalid JSON body"}, status=400)
# block (:1147-1150) and `tenant = self._get_tenant(request)` (:1155) to directly AFTER `await self._rbac_shadow_gate(request, "create_form")`,
# then insert, BEFORE `        if self._create_tool.client is None:`:
        # FEAT-650 — dual-wire: an A2UI createSurface body is an import, not a prompt (S5: before the LLM guard)
        if a2ui_wire.is_a2ui_surface_body(request, body):
            return await self._import_a2ui_surface(request, body, tenant=tenant)
# (the prompt path below is otherwise untouched — only the already-moved lines are removed from their old position)
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — importer)
```python
# occurrences: 1 (verified: grep -c '    async def edit_form(self, request: web.Request) -> web.Response:' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# BEFORE — insert ABOVE `    async def edit_form(self, request: web.Request) -> web.Response:` (verified: api/handlers.py:1190)
    async def _import_a2ui_surface(self, request: web.Request, body: dict[str, Any], *, tenant: str) -> web.Response:
        """Import a createSurface as a new form (FEAT-650 §3 M6): 413 / 422 / 409-unless-overwrite / 201."""
        if request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES:
            from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope

            return a2ui_wire.a2ui_response([error_envelope(A2UIErrorCode.PAYLOAD_TOO_LARGE, "body too large")], status=413)
            # FILL IN: verify the A2UIErrorCode member name used by submit_data at :1041-1048 and reuse it — bounded by that code
        from ..extractors import A2UIExtractor  # lazy: optional extra

        try:
            result = A2UIExtractor().extract(body, tenant=tenant)
        except RuntimeError as exc:  # extra missing
            return JSONResponse({"error": str(exc)}, status=415)
        except ValueError as exc:
            return JSONResponse({"error": "invalid surface", "details": str(exc)}, status=422)
        form = result.form.model_copy(update={"tenant": tenant})
        overwrite = request.query.get("overwrite", "").lower() in ("1", "true", "yes")
        existing = await self.registry.get(form.form_uid, tenant=tenant)
        if existing is not None:
            if not overwrite:
                return JSONResponse({"error": "form already exists", "form_uid": str(form.form_uid)}, status=409)
            form = form.model_copy(update={"version": _bump_version(existing.version)})
        try:
            await self.registry.register(form, persist=True, overwrite=True, tenant=tenant)
        except FormAlreadyExistsError as exc:
            return JSONResponse({"error": str(exc), "form_id": form.form_id}, status=409)
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse(
            {
                "form_uid": str(form.form_uid),
                "form_id": form.form_id,
                "url": f"{prefix}/{tenant}/forms/{form.form_uid}",
                "dialect": form.dialect.value,
                "import": {"mode": result.mode.value, "warnings": result.warnings, "dropped": [d.model_dump() for d in result.dropped]},
            },
            status=201,
        )
```
**Why this shape**: the extractor already runs `validate_envelope` before walking (TASK-4201), so a 422 here covers S5's "validate with catalog rules"; the conflict policy is the resolved §8 contract and reuses `_bump_version` like `update_form` (:1358).

### `packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py` (CREATE)
```python
"""POST /forms dual-wire import — FEAT-650 TASK-4203."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot_formdesigner.api.a2ui_wire import is_a2ui_surface_body


def test_predicate_without_extra():
    req = make_mocked_request("POST", "/x", headers={"Content-Type": "application/json"})
    assert is_a2ui_surface_body(req, {"version": "v1.0", "createSurface": {"surfaceId": "s"}})
    assert not is_a2ui_surface_body(req, {"version": "v1.0", "action": {}})
    assert not is_a2ui_surface_body(req, {"prompt": "hi"})
    assert is_a2ui_surface_body(make_mocked_request("POST", "/x", headers={"Content-Type": "application/a2ui+json"}), None)


# FILL IN: handler fixture — build FormAPIHandler like tests/integration/test_a2ui_form_cycle.py:26-60 (FormRegistry + mocks) with
#          _create_tool.client = None (NO LLM client) to prove S5; a rendered surface fixture from A2UIFormRenderer — importorskip


async def test_import_creates_form_without_llm_client(handler, surface):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: POST surface → 201; payload keys form_uid/form_id/url/dialect/import; registry.get(uid) is not None; tenant == route tenant
    #          even though the surface's parrot_tenant says "other" — bounded by AC11


async def test_conflict_409_then_overwrite_bumps_version(handler, surface):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: second POST → 409 {"form_uid"}; with ?overwrite=true → 201 and version bumped — bounded by resolved §8


async def test_invalid_surface_422_and_413(handler):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: surface with duplicate ids → 422 {"error": "invalid surface"}; Content-Length > A2UI_MAX_BODY_BYTES → 413 — bounded by AC11


async def test_prompt_body_still_hits_llm_path(handler):
    # FILL IN: {"prompt": "x"} with client None → 503 (unchanged behaviour) — bounded by AC11
```
**Why this shape**: the predicate test runs without ai-parrot (AC12); the no-LLM-client fixture is the direct proof of codex S5; the 409/overwrite pair pins the resolved policy.

### FILL IN checklist
- [ ] `handlers.py::_import_a2ui_surface` — exact `A2UIErrorCode` member for 413 (copy from `submit_data`); bounded by `handlers.py:1041-1048`.
- [ ] `test_import_a2ui.py` — fixtures + `FILL IN` bodies; bounded by AC11.

---

## Acceptance Criteria

- [ ] A surface body is imported (201 + `import` report) with the route tenant; existing `parrot_form_uid` → 409 unless `?overwrite=true` (version bumped); invalid surface → 422; oversize → 413; legacy `{"prompt"}` unchanged incl. its 503 (AC11).
- [ ] Import works with no LLM client configured (S5).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py -v`; existing `test_a2ui_wire.py` and `test_submit_a2ui.py` still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_a2ui_wire.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_create_form_tool.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M6, §7 "Tenant stamping", §9 S5
3. **Check dependencies** — TASK-4202 and TASK-4200 `"done"`
4. **Verify the Codebase Contract** — `grep -n 'async def create_form\|_create_tool.client is None\|async def edit_form\|A2UIErrorCode' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`; `grep -n '^def is_a2ui_request' packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the three files
9. **Close** with `scripts/sdd/close_task.sh TASK-4203 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

Implemented by codex gpt-5.6-luna; merged by sdd-worker orchestrator; merge-tier validation green (696 passed).

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-24
**Notes**:

**Deviations from spec**: none
