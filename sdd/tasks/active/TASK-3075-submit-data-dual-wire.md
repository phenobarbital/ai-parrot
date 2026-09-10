# TASK-3075: Dual-wire `POST .../data`: accept A2UI action envelopes, reply with A2UI envelopes

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3074
**Assigned-to**: unassigned
**Parallel**: false — Edits handlers.py; TASK-3076 edits the same file — run sequentially (3075 then 3076).

---

## Context

Spec §3 Module 5 (decisions U1/U2). `FormAPIHandler.submit_data` gains an A2UI branch: when the body is an A2UI `action` envelope, unwrap it into plain field_id answers BEFORE `_extract_visit_context`, run the untouched validate → lifecycle → persist → forward pipeline, and translate the three existing outcomes (422 field errors, 422 `__unknown__`/extras-cap, 200 composite) into A2UI envelopes. Legacy JSON callers must observe byte-identical behaviour.

---

## Scope

- In `submit_data` (handlers.py:1522-1530): after `body = await request.json()` and BEFORE `data, visit_context = self._extract_visit_context(form, body)`, add:
  ```python
  a2ui_surface_id: str | None = None
  if a2ui_wire.is_a2ui_request(request, body):
      try:
          submission_in = a2ui_wire.unwrap_action(form, body)
      except a2ui_wire.A2UIWireError as exc:
          return a2ui_wire.a2ui_response([exc.envelope], status=exc.status)
      a2ui_surface_id = submission_in.surface_id
      body = submission_in.answers
  ```
  (`import` the module at top: `from . import a2ui_wire` — it is import-safe without ai-parrot.)
- Add a body-size guard for the A2UI branch: if `request.content_length` (or `len(raw)`) exceeds `a2ui_wire.A2UI_MAX_BODY_BYTES` → 413 with a generic `error` envelope (`A2UIErrorCode.INTERNAL`, "The submitted data model exceeds the maximum allowed size.").
- Wrap the existing returns when `a2ui_surface_id` is set (do not restructure the legacy branches):
  - 1610-1615 (`{"is_valid": False, "errors": result.errors}`) → `a2ui_wire.a2ui_response(a2ui_wire.validation_errors(a2ui_surface_id, result.errors), status=422)`
  - 1638-1641 (`__unknown__`) and the extras-cap 422 → same helper with `{"__unknown__": [...]}` / the cap error dict
  - `_metadata` 422 (≈1720) → `validation_errors(surface_id, {"_metadata": [str(exc)]})`
  - 1842-1850 (200 composite) → `a2ui_wire.a2ui_response(a2ui_wire.confirmation(a2ui_surface_id, <the same dict>), status=200)`
  - sink 503/422/501 `{"error": ...}` paths → generic `error_envelope(A2UIErrorCode.INTERNAL, ..., surface_id=...)` via `a2ui_response` with the same status.
  Implement this as a small local helper `_reply(payload: dict, status: int) -> web.Response` selected once, so each existing `return JSONResponse(...)` becomes `return _reply(...)` with the legacy branch returning `JSONResponse(payload, status=status)` unchanged.
- `merge_partials`, lifecycle hooks (`onBeforeSubmit`/`onAfterSubmit`/`onError`), `visit_context`, persistence and forwarding are NOT modified — the A2UI branch only changes `body` before and the response shape after.
- Update the `submit_data` docstring (1465-1495) with a step "1a. A2UI wire (FEAT-544)".
- Tests: `tests/unit/api/test_submit_a2ui.py` using the same handler harness as `tests/unit/api/test_submit_unknown_fields.py` (mocked registry/validator/storage): legacy body unchanged; A2UI 422; A2UI 200; surface mismatch 400; oversized 413; hooks dispatched once; nothing persisted on 422.

**NOT in scope**: the `validate` endpoint (TASK-3076); routes; renderer; partial saves; changing any legacy status code or payload.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | A2UI branch in submit_data + `_reply` helper + docstring |
| `packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py` | CREATE | dual-wire submit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from . import a2ui_wire            # packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py — created by TASK-3074 (import-safe without ai-parrot)
from navigator.responses import JSONResponse                   # handlers.py:19
from .tenant import enforce_membership_unless_public           # handlers.py:31-37 import block; tenant.py:189
from ..services.validators import FormValidator                # handlers.py:29
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

# api/a2ui_wire.py (TASK-3074): is_a2ui_request(request, body) -> bool; unwrap_action(form, body) -> A2UIActionSubmission(.surface_id, .answers, .action_name); A2UIWireError(.status, .envelope); validation_errors(surface_id, errors) -> list[dict]; confirmation(surface_id, result) -> list[dict]; a2ui_response(envelopes, *, status) -> web.Response; A2UI_MAX_BODY_BYTES
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
- ~~a new `submit_a2ui()` method / new route~~ — the A2UI branch lives INSIDE `submit_data`
- ~~changing `_extract_visit_context`~~ — feed it the unwrapped answers dict; do not modify it

---

## Implementation Notes

### Pattern to Follow
```python
# handlers.py:1522-1530 — insertion point
try:
    body = await request.json()
except (json.JSONDecodeError, ValueError):
    return JSONResponse({"error": "Invalid JSON body"}, status=400)
# >>> A2UI unwrap goes HERE (body becomes the plain answers dict) <<<
data, visit_context = self._extract_visit_context(form, body)
```
- Keep the diff surgical: one insertion block, one `_reply` helper, and `return JSONResponse(...)` → `return _reply(...)` on the enumerated lines only.
- Existing tests `tests/unit/api/test_submit_unknown_fields.py`, `tests/unit/test_submit_path_branch.py`, `tests/integration/test_unknown_fields_e2e.py` MUST pass unchanged — run them first (baseline) and after.

### References in Codebase
- `packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py` — handler test harness to copy
- `packages/parrot-formdesigner/docs/lifecycle-events.md` — hook semantics that must be preserved

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] Legacy JSON submissions produce byte-identical responses: the three existing suites listed above pass unchanged.
- [ ] A2UI action with an invalid form → 422; body is `{"messages": [error…, updateDataModel]}` (or a single envelope with `application/a2ui+json`); one `VALIDATION_FAILED` error per field with `path == "/answers/<field_id>"`; nothing persisted; `onError` dispatched exactly as the legacy 422 path does.
- [ ] A2UI action with a valid form → 200; `updateDataModel.value.submission_id` equals the stored submission id; `updateComponents` targets `root-status`; `onBeforeSubmit`/`onAfterSubmit` dispatched once.
- [ ] Surface mismatch / wrong action name → 400 generic `error` envelope; oversized body → 413 generic `error`; nothing persisted in either case.
- [ ] `?merge_partials=true` still merges cached partials into A2UI-unwrapped answers.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py packages/parrot-formdesigner/tests/unit/test_submit_path_branch.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py
import pytest
pytest.importorskip("parrot.outputs.a2ui")
# reuse the FormAPIHandler harness/fixtures from test_submit_unknown_fields.py (mock registry/validator/submission_storage)

async def test_submit_legacy_json_unchanged(handler, request_factory): ...
async def test_submit_a2ui_422_returns_error_envelopes_and_persists_nothing(handler, request_factory): ...
async def test_submit_a2ui_200_returns_confirmation(handler, request_factory): ...
async def test_submit_a2ui_surface_mismatch_400(handler, request_factory): ...
async def test_submit_a2ui_oversized_413(handler, request_factory): ...
async def test_submit_a2ui_unknown_fields_reject_policy_path_is_answers(handler, request_factory): ...
async def test_submit_a2ui_dispatches_lifecycle_hooks_once(handler, request_factory, hook_spy): ...
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
7. **Move this file** to `sdd/tasks/completed/TASK-3075-submit-data-dual-wire.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
