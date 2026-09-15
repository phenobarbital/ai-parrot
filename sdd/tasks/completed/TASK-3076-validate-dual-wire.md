# TASK-3076: Dual-wire `POST .../validate` (dry run) for A2UI action envelopes

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3074, TASK-3075
**Assigned-to**: unassigned
**Parallel**: false — Same file as TASK-3075 (handlers.py) — sequential after it to avoid merge conflicts.

---

## Context

Spec §3 Module 5, second endpoint. `FormAPIHandler.validate` accepts the same A2UI `action` wire (`form.validate` or `form.submit` name) and returns the 422 A2UI error shape or `200 {"messages": []}`, so an A2UI client can pre-flight a submission exactly like legacy clients do.

---

## Scope

- In `validate` (handlers.py:1022-1036): after the JSON parse, apply the same A2UI unwrap block as TASK-3075 (accept `form.validate` AND `form.submit` action names — `unwrap_action` already allows both).
- Response: when `a2ui_surface_id` is set → invalid: `a2ui_response(validation_errors(surface_id, errors), status=422)`; valid: `a2ui_response([], status=200)` (→ `{"messages": []}`). Legacy path unchanged (`{"is_valid", "errors"}`).
- Reuse the `_reply` helper introduced by TASK-3075 (factor it to a module-level `_a2ui_or_json_reply(a2ui_surface_id, payload, status)` if that is cleaner — then update `submit_data` to use it too).
- Update the `validate` docstring (1004-1010) with the FEAT-544 note.
- Tests in `tests/unit/api/test_validate_a2ui.py`: legacy unchanged; A2UI 422 shape; A2UI 200 `{"messages": []}`; `__unknown__` → `path == "/answers"`; surface mismatch 400.

**NOT in scope**: submit changes (TASK-3075); renderer; routes; docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | A2UI branch in validate (+ shared reply helper) |
| `packages/parrot-formdesigner/tests/unit/api/test_validate_a2ui.py` | CREATE | dual-wire validate tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from . import a2ui_wire            # packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py (TASK-3074)
from navigator.responses import JSONResponse                   # handlers.py:19
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
from navigator.responses import JSONResponse                # line 19 (the response class used throughout)
def extract_form_uid(request: web.Request) -> uuid.UUID     # 38
class FormAPIHandler:                                       # 109   (NOT `FormHandler`)
    registry: FormRegistry; validator: FormValidator; _partial_store
    def _get_tenant(self, request) -> str                    # 269
    def _assert_form_tenant(self, form, tenant) -> None      # 322
    def _build_auth_context(self, request) -> AuthContext    # 355
    def _extract_visit_context(self, form, body) -> tuple[dict, dict | None]   # 400 — splits reserved "visit_context" key off the answers
    async def validate(self, request) -> web.Response        # 1003-1040
        # 1022-1025: body = await request.json() / 400 "Invalid JSON body"
        # 1026: data, visit_context = self._extract_visit_context(form, body)
        # 1027-1036: result = await self.validator.validate(form, data, visit_context=visit_context); errors["__unknown__"] for REJECT; return JSONResponse({"is_valid", "errors"}, status=200|422)
    async def submit_data(self, request) -> web.Response     # 1464
        # 1522-1525: body = await request.json() / 400 "Invalid JSON body"
        # 1530: data, visit_context = self._extract_visit_context(form, body)
        # 1610-1615: return JSONResponse({"is_valid": False, "errors": result.errors}, status=422)
        # 1638-1641: return JSONResponse({"is_valid": False, "errors": {"__unknown__": sorted(result.extra_data)}}, status=422)
        # 1842-1850: return JSONResponse({"submission_id", "is_valid": True, "forwarded", "forward_status", "forward_error"})   (200)
# packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py: declared_tenant(request) -> str (166); enforce_membership_unless_public(request, form, tenant) (189)
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py: class ValidationResult (159: is_valid, errors: dict[str, list[str]], sanitized_data, extra_data); FormValidator.validate(form, data, *, locale="en", auth_context=None, location_vars=None, visit_context=None) -> ValidationResult (220-229)
```

### Does NOT Exist
- ~~`parrot_formdesigner.api.a2ui_wire`~~ — does not exist yet (TASK-3074 creates it)
- ~~`A2UIErrorCode.VALIDATION_FAILED`~~ — NOT an enum member; build `ErrorMessage(code="VALIDATION_FAILED", surface_id=..., path=..., message=...)` directly and `serialize()` it; never pass it to `error_envelope()`
- ~~`error_envelope(..., surface_id=..., path=...)` for validation errors~~ — `error_envelope` takes an `A2UIErrorCode`; validation errors bypass it
- ~~`POST /api/v1/{tenant}/forms/{form_uid}/a2ui`~~ — no such route; dual-wire lives on `/data` and `/validate`
- ~~`A2UIRuntime`~~ / ~~`A2UIHandler`~~ involvement — the runtime routes actions to LLM turns; NOT used here
- ~~`ActionMessage.answers`~~ — answers live in `data_model["answers"]` (preferred) or `context["answers"]`
- ~~`request.content_type == "application/a2ui+json"` being the ONLY detection~~ — body shape `{"version": "v1.0", "action": {...}}` must also be detected (aiohttp clients often send application/json)
- ~~`class FormHandler`~~ — the class is `FormAPIHandler` (handlers.py:109)
- ~~a `/validate/a2ui` route~~ — no new route

---

## Implementation Notes

### Pattern to Follow
```python
# handlers.py:1022-1036 — validate body: same insertion point as submit_data (after JSON parse, before _extract_visit_context)
```
- Existing `tests/unit/api/test_validate_endpoint_unknown_fields.py` must pass unchanged.

### References in Codebase
- `packages/parrot-formdesigner/tests/unit/api/test_validate_endpoint_unknown_fields.py` — harness to copy

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] Legacy `/validate` responses unchanged (`test_validate_endpoint_unknown_fields.py` passes).
- [ ] A2UI action → 422 with `VALIDATION_FAILED` errors per field + `updateDataModel(/errors)`; valid → 200 `{"messages": []}`; `__unknown__` under REJECT → `path == "/answers"`.
- [ ] Surface mismatch → 400 generic `error` envelope.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/api/test_validate_a2ui.py packages/parrot-formdesigner/tests/unit/api/test_validate_endpoint_unknown_fields.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_validate_a2ui.py
import pytest
pytest.importorskip("parrot.outputs.a2ui")

async def test_validate_legacy_unchanged(handler, request_factory): ...
async def test_validate_a2ui_422_errors(handler, request_factory): ...
async def test_validate_a2ui_200_empty_messages(handler, request_factory): ...
async def test_validate_a2ui_unknown_fields_reject(handler, request_factory): ...
async def test_validate_a2ui_surface_mismatch_400(handler, request_factory): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2ui-form-output-renderer.spec.md` (§2 Overview, §3 Module Breakdown, §6 Codebase Contract, §7 mapping table).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code confirm every import/signature above still exists (`grep`/`read`); update the contract FIRST if anything drifted.
4. **Update status** in `sdd/tasks/index/a2ui-form-output-renderer.json` → `"in-progress"` with your session ID.
5. **Implement** following the scope, contract and notes. Write the tests first (TDD).
6. **Verify** all acceptance criteria; run the listed pytest commands and `ruff check`.
7. **Move this file** to `sdd/tasks/completed/TASK-3076-validate-dual-wire.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: Added the same A2UI unwrap block as `submit_data` (detection,
`A2UI_MAX_BODY_BYTES` 413 guard, `unwrap_action` 400-on-`A2UIWireError`) to
`validate`, right after the JSON parse and before `_extract_visit_context`.
The final reply branches explicitly on `a2ui_surface_id`/`is_valid`: valid
→ `a2ui_response([], status=200)` (`{"messages": []}`); invalid →
`a2ui_response(validation_errors(surface_id, errors), status=422)`
(one `VALIDATION_FAILED` envelope per field + a trailing
`updateDataModel(/errors)`); legacy path is the original
`JSONResponse({"is_valid", "errors"}, ...)`, untouched. `unwrap_action`
already accepts both `form.validate` and `form.submit` action names, so no
extra logic was needed for that AC bullet — verified with a dedicated
test. 6 new tests in `test_validate_a2ui.py` pass; the pre-existing
`test_validate_endpoint_unknown_fields.py` suite (8 tests) passes
unchanged; `ruff check` clean. Ran the wider `tests/unit/api` +
`tests/unit/renderers` suites — only the same pre-existing, unrelated
`test_form_controls_payload_shape` failure remains (already noted in
TASK-3073/3074's Completion Notes).

**Deviations from spec**: did NOT factor a shared module-level
`_a2ui_or_json_reply(a2ui_surface_id, payload, status)` helper reused by
both `submit_data` and `validate`, though the Scope text offered that as
an option ("if that is cleaner"). `submit_data`'s `_reply` dispatches on
whether `"errors"` is a KEY in the payload dict (present only on the
failure paths there); `validate`'s payload always carries an `"errors"`
key (`{}` when valid), so the same key-presence heuristic would
mis-classify a *valid* dry-run as a validation failure and wrongly emit a
trailing `updateDataModel(/errors)` for the 200 case. Reusing `_reply`
would need an explicit `is_valid` branch bolted onto it anyway, at which
point it stops being the same generic helper — so `validate` inlines its
own two-line `if a2ui_surface_id is not None: ...` branch instead. Judged
correctness-over-DRY given the acceptance criteria are explicit about the
200 `{"messages": []}` shape.
