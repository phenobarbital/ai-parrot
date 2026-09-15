# TASK-3071: A2UIFormRenderer skeleton: surface layout, dataModel, submit/cancel Buttons, pointer helpers

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false — Foundation task — every other task imports from renderers/a2ui.py.

---

## Context

Spec §3 Module 1. Creates `parrot_formdesigner/renderers/a2ui.py` with `A2UIFormRenderer(AbstractFormRenderer)` that lowers a `FormSchema` into ONE A2UI v1.0 `createSurface` envelope: root `Column`, title/description `Text`s, one `Card` per section (a `Column` per subsection), the always-present `root-status` `Text` placeholder, and a `Row` of action Buttons whose submit `action.event` points at the form's own answer endpoint. Field lowering is stubbed here (every field → a `Text` notice) so the layout, dataModel, metadata extensions and validation can be tested independently; TASK-3072 replaces the stub with the real table.

---

## Scope

- Implement `A2UIFormRenderer.__init__(self, *, submit_url_template: str = "/api/v1/{tenant}/forms/{form_uid}/data", catalog_id: str | None = None)` and `async render(form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm` with the EXACT base signature.
- Implement module-level `field_pointer(field_id: str) -> str` (`"/answers/" + RFC 6901 escaped token`: `~`→`~0`, `/`→`~1`) and `field_id_from_pointer_token(token: str) -> str` (inverse). Assert `is_valid_pointer(field_pointer(x))`.
- Implement `_resolve(value: LocalizedString | None, locale: str) -> str` (copy the adaptive_card.py:45 pattern: dict → locale → "en" → first value; str → str; None → "").
- Lower layout with deterministic ids: `root`, `root-title`, `root-description`, `sec-<section_id>`, `sec-<section_id>-title`, `sub-<subsection_id>`, `f-<field_id>`, `root-status`, `root-actions`, `root-submit`, `root-submit-label`, `root-cancel`, `root-cancel-label`. Root `Column` FIRST in `components`.
- Build `dataModel = {"answers": {field_id: prefilled.get(field_id, field.default)}, "errors": {}}` for every field from `form.iter_all_fields()` (precedence prefilled > default > None).
- Submit Button: `Component(id="root-submit", component="Button", variant="primary", child="root-submit-label", action=Action(event=EventAction(name="form.submit", context={"form_uid": str(form.form_uid), "form_id": form.form_id, "tenant": tenant, "submit_url": <template formatted>, "method": "POST", "answers": {"path": "/answers"}})))`; label Text from `_resolve(style.submit_label, locale)`. `tenant` = `form.tenant or "public"` — document the fallback. Cancel Button (`form.cancel`, context `{"form_uid"}`) only when `form.cancel_allowed`.
- Root metadata: `ComponentMetadata(extensions=Extensions({"parrot_variant": "form", "parrot_form_uid": ..., "parrot_form_id": ..., "parrot_form_version": form.version, "parrot_tenant": ..., "parrot_submit_url": ...}))`. Section/subsection title Texts: `parrot_role: "title"`. `root-status`: `Component(id="root-status", component="Text", text="", metadata=extensions {"parrot_role": "status"})`.
- Field stub: `_lower_field(field, section, subsection, locale, errors) -> tuple[list[Component], RenderWarning | None]` returning a `Text` notice (`parrot_role: "notice"`, `parrot_field_id`, `parrot_field_uid`, `parrot_field_type`, `parrot_section_id`, `parrot_subsection_id`) + a `RenderWarning(renderer="a2ui", reason="field lowering not implemented")`. Keep the hook signature stable for TASK-3072.
- Per-field `errors` param: emit a sibling `Text` `f-<field_id>-error` (`parrot_role: "error"`) and seed `dataModel["errors"][field_id]`.
- Build `CreateSurface(surface_id=f"form-{form.form_uid}", catalog_id=self.catalog_id or DEFAULT_CATALOG_ID, send_data_model=True, components=[...], data_model=...)`; call `validate_envelope(surface, origin=ProducerOrigin.TOOL, surface_catalog_id=<catalog_id>)`; return `RenderedForm(content=serialize(surface), content_type=A2UI_MEDIA_TYPE, metadata={"surface_id", "catalog_id", "field_paths": {field_id: pointer for non-degraded fields}, "degraded": [...]}, warnings=[...])`.
- Lazy import: all `parrot.*` imports inside `_a2ui()` helper / function bodies with `try/except ImportError` raising a clear `RuntimeError("A2UIFormRenderer requires the 'ai-parrot' extra")`.
- Unit tests in `tests/unit/renderers/test_a2ui_renderer.py` for everything above (see Test Specification).

**NOT in scope**: the 47-entry FieldType table, constraint→checks lowering and real primitives (TASK-3072); registering the `a2ui` format (TASK-3073); any handler/endpoint change (TASK-3074/3075/3076); docs (TASK-3078).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` | CREATE | A2UIFormRenderer, field_pointer, field_id_from_pointer_token, _resolve, layout lowering, field stub hook |
| `packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_renderer.py` | CREATE | unit tests for layout/dataModel/submit/pointers/validation (skip whole module if `parrot.outputs.a2ui` import fails) |
| `packages/parrot-formdesigner/tests/unit/renderers/__init__.py` | CREATE (if missing) | test package marker |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from parrot_formdesigner.renderers.base import AbstractFormRenderer, FallbackRenderer   # packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:57 / :34
from parrot_formdesigner.core.schema import FormField, FormSubsection, FormSection, FormSchema, RenderWarning, RenderedForm   # core/schema.py:65 / :195 / :229 / :401 / :650 / :671
from parrot_formdesigner.core.types import FieldType, LocalizedString   # core/types.py:16 (47 members :19-70) / :13 (`str | dict[str, str]`)
from parrot_formdesigner.core.constraints import FieldConstraints        # core/constraints.py:21
from parrot_formdesigner.core.options import FieldOption                 # core/options.py:14
from parrot_formdesigner.core.style import StyleSchema                   # core/style.py:52 (submit_label :71, cancel_label)

# ai-parrot core — import LAZILY inside the module (ai-parrot is an OPTIONAL extra of parrot-formdesigner; see pyproject.toml:48-52)
from parrot.outputs.a2ui.models import (                 # packages/ai-parrot/src/parrot/outputs/a2ui/models.py
    is_valid_pointer,   # :112
    DataBinding,        # :155  path validated as JSON Pointer
    FunctionCall,       # :174  (call, args, catalogId)
    EventAction,        # :232  (name, userMessage?, context: dict)
    Action,             # :250  exactly one of event / functionCall
    CheckRule,          # :272  (condition: FunctionCall | DataBinding, message: str | None)
    Extensions,         # :341  RootModel[dict[str, Any]]
    ComponentMetadata,  # :364  (extensions: Extensions | None)
    Component,          # :400  extra="allow"; id, component, catalogId, checks, action, metadata + catalog props top-level
    CreateSurface,      # :446  (surfaceId, catalogId?, sendDataModel=False, components, dataModel={})
)
from parrot.outputs.a2ui.serialization import serialize           # serialization.py:104  -> dict with "version": "v1.0"
from parrot.outputs.a2ui.catalog import validate_envelope         # catalog/__init__.py:499
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, DEFAULT_CATALOG_ID   # catalog/base.py:89 / :53 == "https://parrot.dev/catalogs/v1"
from parrot.a2a.models import A2UI_MEDIA_TYPE                     # a2a/models.py:336 == "application/a2ui+json"
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:57-89
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...   # 67-76

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):   # 65 — field_uid, field_id, field_type, label (123-126); description, placeholder (127-128); required, default, read_only (129-131); constraints, options (132-133); options_source, depends_on (134-135); children, item_template (137-138)
class FormSubsection(BaseModel):  # 195 — subsection_id, title, description, fields, depends_on, meta (217-223)
class FormSection(BaseModel):     # 229 — section_id, title, description, fields, subsections, depends_on, meta (250-256); def iter_fields() (258)
class FormSchema(BaseModel):      # 401 — form_uid, form_id, version, title, description (453-457); sections, submit, cancel_allowed (458-460); tenant (463); is_public (471)
    def iter_all_fields(self) -> Iterator[FormField]   # 477 — layout order; does NOT recurse GROUP/ARRAY
class RenderWarning(BaseModel):   # 650 — field_id: str; field_uid: uuid.UUID | None; field_type: str; renderer: str; reason: str
class RenderedForm(BaseModel):    # 671 — content: Any; content_type: str; style_output: Any | None; metadata: dict | None; warnings: list[RenderWarning] = []

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py:21 FieldConstraints — min_length, max_length (44-45); min_value, max_value, step (46-48); pattern, pattern_message (49-50); min_items, max_items (51-52); scale_min, scale_max, scale_step, anchor_labels (65-68)
# packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py:14 FieldOption — value: str; label: LocalizedString; description; disabled: bool; icon

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py — PATTERN reference (module-private, copy not import)
def _resolve(value: LocalizedString | None, locale: str = "en") -> str      # 45
_FIELD_TYPE_MAP: FieldType -> element | None                                 # 71-119
warnings loop building RenderWarning(field_id, field_uid, field_type, renderer, reason)   # 252-260

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py — PATTERN reference (do NOT call; its FormField has only 6 kinds)
def _lower_field(id_prefix: str, field: FormField) -> Component   # 73 — required -> CheckRule(condition=FunctionCall(call="required", args={"value": {"path": ...}}), message=...)
def build_form(*, id_prefix, title, fields, submit) -> list[Component]   # 119 — root Column FIRST, Button(child=<Text id>, action=Action(event=EventAction(name=..., context={...})))

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:499
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL, surface_catalog_id: str | None = None) -> None

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py — EXACT props of the only v1.0 input primitives (build them as plain `Component(component="TextField", ...)` or via these classes)
class TextField(Component):     label: DynamicString; value: DynamicString | None; placeholder; variant: Literal["longText","number","shortText","obscured"] = "shortText"
class CheckBox(Component):      label: DynamicString; value: DynamicBoolean
class ChoiceOption(BaseModel):  label: DynamicString; value: str
class ChoicePicker(Component):  label?; variant: Literal["multipleSelection","mutuallyExclusive"] = "mutuallyExclusive"; options: list[ChoiceOption]; value: DynamicStringList; displayStyle: Literal["checkbox","chips"] = "checkbox"; filterable: bool = False
class Slider(Component):        label?; min: float = 0; max: float; value: DynamicNumber; steps: int | None (ge=1)
class DateTimeInput(Component): value: DynamicString; enableDate: bool = False; enableTime: bool = False; min?; max?; label?
class Button(Component):        child: str (id of a Text); variant: Literal["default","primary","borderless"]; action: Action
# Basic functions available for CheckRule.condition (catalog/basic/functions.py): required, regex, length, numeric, email, and, or, not, formatString, formatNumber, formatDate, formatCurrency, @index
```

### Does NOT Exist
- ~~`parrot_formdesigner.renderers.a2ui`~~ — does not exist yet (this feature creates it)
- ~~`Form` catalog component~~ — retired by A2UI dialect spec G6; compose Basic primitives, never emit `component="Form"`
- ~~`Component.disabled`~~ / ~~`.visible`~~ / ~~`.hidden`~~ / ~~`.required`~~ — no such v1.0 props (required is a CheckRule; HIDDEN fields are dataModel-only)
- ~~`ChoicePicker.multiple`~~ / ~~`.multi_select`~~ — the prop is `variant="multipleSelection"`
- ~~`TextField.type`~~ / ~~`.input_type`~~ — the prop is `variant`
- ~~`Slider.step`~~ — the prop is `steps` (number of divisions, int >= 1)
- ~~`DateTimeInput.mode`~~ — use `enableDate` / `enableTime`
- ~~Basic functions `minLength`, `maxLength`, `min`, `max`, `url`, `phone`, `pattern`~~ — only `required`, `regex`, `length`, `numeric`, `email` (+ logic/format functions) exist
- ~~`from parrot_formdesigner.renderers.adaptive_card import _resolve`~~ — module-private; copy the 5-line pattern
- ~~`_loc_to_str(value, locale)`~~ — `api/_utils._loc_to_str` takes ONE argument and is not locale-aware
- ~~`RenderedForm.surface_id`~~ / ~~`.envelope`~~ — use `metadata["surface_id"]` and `content`
- ~~top-level `parrot_*` props on a Component~~ — ai-parrot semantics go ONLY under `metadata.extensions` (docs/outputs/a2ui-v1.md §metadata.extensions)
- ~~hand-written `"version": "v1.0"`~~ — always `serialize()`

---

## Implementation Notes

### Pattern to Follow
```python
# catalog/parrot/form.py:148-164 — Button + root Column shape (adapt ids/context; this is the ONLY interaction primitive)
rest.append(Component(id=label_id, component="Text", text=submit.label))
rest.append(Component(id=button_id, component="Button", child=label_id,
                      action=Action(event=EventAction(name=submit.action, context=context))))
root = Component(id=id_prefix, component="Column", children=children_ids)
return [root, *rest]

# renderers/adaptive_card.py:45 — locale resolution (copy)
def _resolve(value: LocalizedString | None, locale: str = "en") -> str: ...

# renderers/audio.py:151-154 — lazy optional import
try:
    from parrot.outputs.a2ui.models import Component, ...
except ImportError as exc:
    raise RuntimeError("A2UIFormRenderer requires the 'ai-parrot' extra") from exc
```
- `Component` is `extra="allow"`: pass catalog props (`text`, `children`, `child`, `variant`, `label`, `value`) as keyword args.
- `metadata=ComponentMetadata(extensions=Extensions({...}))` — `Extensions` is a `RootModel[dict]`.
- `validate_envelope` raises on unknown component names / missing single root — keep `root` first and unique.
- `serialize()` already emits aliases (`surfaceId`, `catalogId`, `sendDataModel`, `dataModel`) — do not post-process the dict.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py` — lowering pattern
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` — renderer structure, `_resolve`, warnings
- `packages/ai-parrot/tests/outputs/a2ui/catalog/test_build_form.py` — how a composed form is asserted in tests
- `docs/outputs/a2ui-v1.md` §"metadata.extensions" — `parrot_*` convention

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] `A2UIFormRenderer.render()` returns `RenderedForm` with `content_type == "application/a2ui+json"` and `content["version"] == "v1.0"`; `content["createSurface"]["surfaceId"] == f"form-{form_uid}"`, `sendDataModel is True`, `catalogId == DEFAULT_CATALOG_ID`.
- [ ] Exactly one component has `id == "root"` (a `Column`) and it is `components[0]`; `root-status` Text present with `metadata.extensions.parrot_role == "status"`.
- [ ] Submit Button `action.event.name == "form.submit"`, `context.submit_url == f"/api/v1/{tenant}/forms/{form_uid}/data"`, `context.answers == {"path": "/answers"}`; cancel Button present iff `form.cancel_allowed`.
- [ ] Root `metadata.extensions` carries `parrot_variant == "form"`, `parrot_form_uid`, `parrot_form_id`, `parrot_tenant`, `parrot_submit_url`; no `parrot_*` key is a top-level prop.
- [ ] `dataModel.answers` has one key per field (prefilled > default > None); `errors=` seeds `dataModel.errors` and emits `f-<id>-error` Texts.
- [ ] `field_pointer("a/b") == "/answers/a~1b"`, `field_pointer("x~y") == "/answers/x~0y"`, round-trips via `field_id_from_pointer_token`; `is_valid_pointer()` true for every emitted path.
- [ ] `validate_envelope(CreateSurface.model_validate(content["createSurface"]), origin=ProducerOrigin.TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)` passes; with `origin=ProducerOrigin.LLM` it raises (action present).
- [ ] `import parrot_formdesigner.renderers.a2ui` does not import `parrot.*` at module import time (lazy).
- [ ] `pytest packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_renderer.py -v` passes; `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_renderer.py
import pytest
pytest.importorskip("parrot.outputs.a2ui")
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer, field_pointer, field_id_from_pointer_token
from parrot.outputs.a2ui.models import CreateSurface, is_valid_pointer
from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, DEFAULT_CATALOG_ID

@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(form_id="demo", title={"en": "Demo", "es": "Demo"}, tenant="acme", sections=[
        FormSection(section_id="main", title="Main", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
            FormField(field_id="agree", field_type=FieldType.BOOLEAN, label="Agree", default=False),
        ])])

async def test_render_returns_createsurface_with_a2ui_media_type(sample_form): ...
async def test_root_is_first_and_unique_with_status_placeholder(sample_form): ...
async def test_submit_button_action_targets_form_data_endpoint(sample_form): ...
async def test_cancel_button_only_when_cancel_allowed(sample_form): ...
async def test_root_extensions_carry_identity(sample_form): ...
async def test_datamodel_seeds_prefilled_then_default_then_null(sample_form): ...
async def test_errors_param_emits_error_text_and_datamodel_errors(sample_form): ...
def test_field_pointer_escapes_rfc6901_and_roundtrips(): ...
async def test_envelope_passes_validate_envelope_tool_origin_and_fails_llm(sample_form): ...
def test_module_import_does_not_import_ai_parrot_eagerly(): ...   # monkeypatch sys.modules / importlib check
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
7. **Move this file** to `sdd/tasks/completed/TASK-3071-a2ui-renderer-skeleton-layout-submit.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: Implemented `A2UIFormRenderer` in
`renderers/a2ui.py` exactly per scope: lazy `_a2ui_ns()` import helper
(raises `RuntimeError` on `ImportError`), `field_pointer`/
`field_id_from_pointer_token` (RFC 6901 escape/unescape), module-private
`_resolve` (copied from `adaptive_card.py`), deterministic layout ids
(`root`, `root-title`, `root-description`, `sec-<id>`, `sec-<id>-title`,
`sub-<id>`, `f-<field_id>`, `f-<field_id>-error`, `root-status`,
`root-actions`, `root-submit(-label)`, `root-cancel(-label)`), submit/cancel
Buttons with `action.event` + `context.submit_url`, `metadata.extensions.
parrot_*` on root/section/subsection/field, `dataModel` with prefilled >
default > None precedence, and the stub `_lower_field` (Text notice +
`RenderWarning(renderer="a2ui", reason="field lowering not implemented")`)
that TASK-3072 replaces. Sections lower as `Card(child=<body Column id>)`
wrapping a `Column` of [title?, field/subsection ids] — an internal
`sec-<id>-body` id not enumerated in the task's deterministic-id list, but
required since `Card.child` is a single id (verified `catalog/basic/
layout.py:67-82`); no test asserts against it, so it's free to name. All
10 unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/
renderers/test_a2ui_renderer.py -v`); `ruff check` clean on both new files.
`test_module_import_does_not_import_ai_parrot_eagerly` uses a static AST
check (no top-level `parrot.*` import) rather than a `sys.modules`
delete/reload dance, to avoid mutating process-global module identity for
later test files in the same session.

**Deviations from spec**: none.
