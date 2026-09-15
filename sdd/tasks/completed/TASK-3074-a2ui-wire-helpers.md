# TASK-3074: api/a2ui_wire.py: detect, unwrap, and shape A2UI envelopes for the form endpoints

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3071
**Assigned-to**: unassigned
**Parallel**: true — New file; only shares the pointer helpers from TASK-3071. No overlap with TASK-3072/3073 — safe in a parallel worktree.

---

## Context

Spec §3 Module 4 (decisions U1 dual-wire and U2 full A2UI cycle). Pure helper module the handlers (TASK-3075/3076) call: detect an inbound A2UI renderer→agent `action` envelope, unwrap it into field_id-keyed answers, and build the outbound A2UI replies (per-field `error` envelopes + `updateDataModel` on 422; `updateDataModel` + `updateComponents` confirmation on 200) with the same framing as `A2UIHandler`. Keeps `handlers.py` changes minimal and testable in isolation.

---

## Scope

- Create `api/a2ui_wire.py` with: constants `A2UI_SUBMIT_ACTION = "form.submit"`, `A2UI_VALIDATE_ACTION = "form.validate"`, `A2UI_CANCEL_ACTION = "form.cancel"`, `A2UI_MAX_BODY_BYTES` (default 1 MiB, env `A2UI_MAX_DATA_MODEL_BYTES` like the runtime).
- `class A2UIActionSubmission(BaseModel)`: `surface_id: str`, `action_name: str`, `source_component_id: str`, `answers: dict[str, Any]`, `raw_context: dict[str, Any]`.
- `class A2UIWireError(Exception)`: carries `status: int` and `envelope: dict` (a generic `error` built with `error_envelope(A2UIErrorCode.INVALID_FUNCTION_CALL | NOT_FOUND | FORBIDDEN, msg, surface_id=...)`).
- `def is_a2ui_request(request: web.Request, body: Any) -> bool`: True when `request.content_type == A2UI_MEDIA_TYPE` OR (`isinstance(body, dict)` and `body.get("version") == "v1.0"` and `"action" in body`). Returns False (never raises) when `parrot.outputs.a2ui` cannot be imported.
- `def unwrap_action(form: FormSchema, body: dict[str, Any]) -> A2UIActionSubmission`: `msg = deserialize(body)`; require `isinstance(msg, A2UIRendererMessage) and msg.action is not None` else `A2UIWireError(400)`; require `msg.action.surface_id == f"form-{form.form_uid}"` else `A2UIWireError(400)`; require `name in {A2UI_SUBMIT_ACTION, A2UI_VALIDATE_ACTION}` else `A2UIWireError(400)`; answers = `msg.action.data_model["answers"]` if `data_model` and `"answers" in data_model` else `msg.action.context.get("answers", {})` (must be a dict, else 400); keys → `field_id_from_pointer_token()`; drop `None`-valued keys only if the field is not declared (keep declared fields so `required` validation triggers).
- `def validation_errors(surface_id: str, errors: dict[str, list[str] | str]) -> list[dict]`: for each field → `serialize(ErrorMessage(code="VALIDATION_FAILED", surface_id=surface_id, path=field_pointer(field_id), message="; ".join(msgs)))`; the reserved `__unknown__` key → `path="/answers"`; `_metadata` key → `path="/answers"`; append `serialize(UpdateDataModel(surface_id=surface_id, path="/errors", value=errors))`.
- `def confirmation(surface_id: str, result: dict[str, Any], *, message: str = "Form submitted.") -> list[dict]`: `serialize(UpdateDataModel(surface_id, path="/submission", value={k: result.get(k) for k in ("submission_id","is_valid","forwarded","forward_status")}))` + `serialize(UpdateComponents(surface_id, components=[Component(id="root-status", component="Text", text=message, metadata=ComponentMetadata(extensions=Extensions({"parrot_role": "status", "parrot_state": "submitted"})))]))`.
- `def a2ui_response(envelopes: list[dict], *, status: int) -> web.Response`: one envelope → `web.json_response(envelopes[0], status=status, content_type=A2UI_MEDIA_TYPE)`; several → `web.json_response({"messages": envelopes}, status=status)`; zero → `{"messages": []}`.
- Unit tests in `tests/unit/api/test_a2ui_wire.py`, including `validate_message()` on every produced envelope.

**NOT in scope**: editing `handlers.py` (TASK-3075/3076); renderer work; any route addition; partial saves.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` | CREATE | detection, unwrap, error/confirmation shaping, response framing |
| `packages/parrot-formdesigner/tests/unit/api/test_a2ui_wire.py` | CREATE | unit tests incl. validate_message conformance |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema                        # packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:401
from parrot_formdesigner.renderers.a2ui import field_pointer, field_id_from_pointer_token   # created by TASK-3071
# ai-parrot core — import LAZILY (optional extra); if ImportError, is_a2ui_request() must return False
from parrot.outputs.a2ui.models import ActionMessage, ErrorMessage, UpdateComponents, UpdateDataModel, Component, ComponentMetadata, Extensions, A2UIRendererMessage   # models.py:585 / :648 / :473 / :490 / :400 / :364 / :341 / :740
from parrot.outputs.a2ui.serialization import serialize, deserialize   # serialization.py:104 / :155
from parrot.outputs.a2ui.catalog import validate_message               # catalog/__init__.py:455 (tests only)
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope   # runtime/models.py:45 / :172 (generic errors ONLY)
from parrot.a2a.models import A2UI_MEDIA_TYPE                           # a2a/models.py:336
from aiohttp import web
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class ActionMessage(A2UIMessageBase):      # 585
    name: str; user_message: str | None (alias userMessage); surface_id: str (alias surfaceId); source_component_id: str (alias sourceComponentId)
    timestamp: str; context: dict[str, Any]; metadata: ComponentMetadata | None; data_model: dict[str, Any] | None (alias dataModel)   # 608-617
class A2UIRendererMessage(BaseModel):      # 740 — .action: ActionMessage | None (755); also callAgentFunction / rendererFunctionResponse / error
class ErrorMessage(A2UIMessageBase):       # 648 — code: str; message: str; surface_id: str | None; path: str | None; function_call_id: str | None
#   _VALIDATION_ERROR_CODES = {"VALIDATION_FAILED","UNALLOWED_PARENT","UNALLOWED_CHILD"} (644) → these REQUIRE surfaceId + path and forbid functionCallId (679); any other code requires exactly one of surfaceId/functionCallId (686)
class UpdateComponents(A2UIMessageBase):   # 473 — surface_id (alias surfaceId); components: list[Component]
class UpdateDataModel(A2UIMessageBase):    # 490 — surface_id (alias surfaceId); path: str | None; value: Any

# packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
def serialize(message) -> dict[str, Any]                                   # 104 — accepts inner message or envelope; writes "version"
def deserialize(data: dict | str | bytes) -> A2UIAgentMessage | A2UIRendererMessage | list[A2UIAgentMessage]   # 155

# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/models.py
class A2UIErrorCode(str, Enum): INVALID_FUNCTION_CALL, UNALLOWED_PARENT, UNALLOWED_CHILD, FORBIDDEN, NOT_FOUND, INTERNAL, TIMEOUT   # 45-61
def error_envelope(code: A2UIErrorCode, message: str, *, function_call_id=None, surface_id=None, path=None) -> dict   # 172 — generic errors (surface_id XOR function_call_id)
# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/dispatch.py:61  A2UI_MAX_DATA_MODEL_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))

# packages/ai-parrot-server/src/parrot/handlers/a2ui.py:156-240 — FRAMING pattern (do not import):
#   single envelope → web.json_response(messages[0], status=200, content_type=A2UI_MEDIA_TYPE); several → json_response({"messages": messages})

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:401 FormSchema — form_uid: uuid.UUID (453), iter_all_fields() (477) for declared field_ids
```

### Does NOT Exist
- ~~`parrot_formdesigner.api.a2ui_wire`~~ — does not exist yet (TASK-3074 creates it)
- ~~`A2UIErrorCode.VALIDATION_FAILED`~~ — NOT an enum member; build `ErrorMessage(code="VALIDATION_FAILED", surface_id=..., path=..., message=...)` directly and `serialize()` it; never pass it to `error_envelope()`
- ~~`error_envelope(..., surface_id=..., path=...)` for validation errors~~ — `error_envelope` takes an `A2UIErrorCode`; validation errors bypass it
- ~~`POST /api/v1/{tenant}/forms/{form_uid}/a2ui`~~ — no such route; dual-wire lives on `/data` and `/validate`
- ~~`A2UIRuntime`~~ / ~~`A2UIHandler`~~ involvement — the runtime routes actions to LLM turns; NOT used here
- ~~`ActionMessage.answers`~~ — answers live in `data_model["answers"]` (preferred) or `context["answers"]`
- ~~`request.content_type == "application/a2ui+json"` being the ONLY detection~~ — body shape `{"version": "v1.0", "action": {...}}` must also be detected (aiohttp clients often send application/json)

---

## Implementation Notes

### Pattern to Follow
```python
# ai-parrot-server handlers/a2ui.py:156-240 — framing: single envelope with A2UI media type, several as {"messages": [...]}
# runtime/dispatch.py:365-380 — data-model size guard (A2UI_MAX_DATA_MODEL_BYTES) + error_envelope(A2UIErrorCode.INTERNAL, ..., surface_id=...)
# runtime/models.py:172 — error_envelope for GENERIC errors only
```
- `ErrorMessage` validates the two shapes itself (models.py:679-686): for `VALIDATION_FAILED` pass `surface_id` AND `path`, never `function_call_id`.
- `deserialize()` may return a `list` for legacy payloads — treat anything that is not an `A2UIRendererMessage` with `.action` as a 400.
- `A2UIWireError.envelope` for surface mismatch: `error_envelope(A2UIErrorCode.NOT_FOUND, "Unknown surface for this form.", surface_id=<incoming surface id>)`.

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py` — how action envelopes are built in tests
- `packages/ai-parrot/tests/outputs/a2ui/test_models.py` — ErrorMessage shape tests

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] `is_a2ui_request` is True for `Content-Type: application/a2ui+json` and for a `{"version": "v1.0", "action": {...}}` body; False for legacy dict bodies and when ai-parrot is missing (monkeypatched import failure).
- [ ] `unwrap_action` returns `A2UIActionSubmission` with answers from `dataModel.answers` (preferred) else `context.answers`, pointer tokens unescaped (`a~1b` → `a/b`).
- [ ] Surface mismatch, missing `action`, wrong action name, or non-dict answers raise `A2UIWireError(status=400)` carrying a generic `error` envelope that passes `validate_message()`.
- [ ] `validation_errors` yields one `error{code: "VALIDATION_FAILED", surfaceId, path: "/answers/<field_id>"}` per field, `__unknown__` → `path == "/answers"`, plus a trailing `updateDataModel{path: "/errors"}`; each passes `validate_message()`.
- [ ] `confirmation` yields `updateDataModel{path: "/submission"}` + `updateComponents` whose single component is `root-status` with `parrot_role == "status"` and `parrot_state == "submitted"`; both pass `validate_message()`.
- [ ] `a2ui_response`: 1 envelope → body is the envelope, `Content-Type: application/a2ui+json`; N → `{"messages": [...]}`.
- [ ] Module imports `parrot.*` lazily; `import parrot_formdesigner.api.a2ui_wire` works without ai-parrot.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/api/test_a2ui_wire.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_a2ui_wire.py
import pytest
pytest.importorskip("parrot.outputs.a2ui")
from parrot_formdesigner.api import a2ui_wire
from parrot.outputs.a2ui.serialization import deserialize
from parrot.outputs.a2ui.catalog import validate_message

def _action(form, answers, *, in_datamodel=True, name="form.submit"):
    a = {"name": name, "surfaceId": f"form-{form.form_uid}", "sourceComponentId": "root-submit",
         "timestamp": "2026-09-10T00:00:00Z", "context": {"form_uid": str(form.form_uid)}}
    (a.setdefault("dataModel", {}) if in_datamodel else a["context"])["answers"] = answers
    return {"version": "v1.0", "action": a}

def test_is_a2ui_request_by_media_type_and_body_shape(make_request): ...
def test_unwrap_prefers_datamodel_over_context(sample_form): ...
def test_unwrap_unescapes_pointer_tokens(sample_form): ...
@pytest.mark.parametrize("mutate", ["surface", "name", "no_action", "answers_not_dict"])
def test_unwrap_rejects_bad_envelopes(sample_form, mutate): ...
def test_validation_errors_shape_and_conformance(): ...
def test_confirmation_shape_and_conformance(): ...
def test_a2ui_response_framing(): ...
def test_import_without_ai_parrot(monkeypatch): ...
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
7. **Move this file** to `sdd/tasks/completed/TASK-3074-a2ui-wire-helpers.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: Created `api/a2ui_wire.py` with `A2UI_SUBMIT_ACTION`/
`A2UI_VALIDATE_ACTION`/`A2UI_CANCEL_ACTION` constants, `A2UI_MAX_BODY_BYTES`
(env `A2UI_MAX_DATA_MODEL_BYTES`, same as the runtime — enforcement is
left to TASK-3075/3076's handlers per spec §7), `A2UIActionSubmission`,
`A2UIWireError` (`status` + ready `error` envelope), `is_a2ui_request`
(never raises — returns `False` on `ImportError`), `unwrap_action`
(deserialize -> require `ActionMessage` -> surfaceId/action-name checks ->
`dataModel.answers` preferred over `context.answers` -> pointer-token
unescape, dropping only undeclared `None`-valued keys), `validation_errors`,
`confirmation`, and `a2ui_response` (single -> `application/a2ui+json`
body; N -> `{"messages": [...]}`). `field_pointer`/
`field_id_from_pointer_token` are imported directly from
`renderers.a2ui` (TASK-3071) — that module has no top-level `parrot.*`
import either, so this remains safe. 14 new tests pass, including a
`validate_message()` conformance check on every produced envelope and a
static AST check (no top-level `parrot.*` import); `ruff check` clean.

**Deviations from spec**: `_malformed`/`_surface_mismatch` use
`A2UIErrorCode.INVALID_FUNCTION_CALL` for "no action" / "wrong action
name" / "answers not a dict" and `A2UIErrorCode.NOT_FOUND` specifically
for surface mismatch (per the Implementation Notes' explicit example) —
the task's Codebase Contract lists `INVALID_FUNCTION_CALL | NOT_FOUND |
FORBIDDEN` as the available codes without prescribing which applies to
which malformed-envelope case; this mapping was chosen as the most
semantically apt of the three and is not otherwise specified.
