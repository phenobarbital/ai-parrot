# TASK-3072: FieldType → Basic primitive lowering table, constraint → checks, honest degradation

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3071
**Assigned-to**: unassigned
**Parallel**: false — Edits renderers/a2ui.py created by TASK-3071 (same file) — must run after it; independent of TASK-3073/3074.

---

## Context

Spec §3 Module 2 and the normative mapping table in §7. Replaces TASK-3071's field stub with the real 47-entry `FIELD_LOWERING` table (hybrid decision U3): every `FieldType` Basic can express renders natively (TextField / CheckBox / ChoicePicker / Slider / DateTimeInput), `HIDDEN` is dataModel-only, everything else degrades to a `Text` notice plus a `RenderWarning`. `FieldConstraints` lower to `checks` using the five Basic validation functions.

---

## Scope

- Add `class A2UIFieldLowering(BaseModel)` (`primitive: Literal["TextField","CheckBox","ChoicePicker","Slider","DateTimeInput","notice","hidden"]`, `props: dict[str, Any]`, `check_functions: tuple[str, ...]`) and the module-level `FIELD_LOWERING: dict[FieldType, A2UIFieldLowering]` covering ALL 47 members exactly as the spec §7 table (TEXT/SEARCH/MASKED/COLOR/COLOR_PICKER→shortText; TEXT_AREA→longText; NUMBER/INTEGER→number; PASSWORD→obscured; EMAIL→shortText+`email`; URL/PHONE→shortText+`regex`; BOOLEAN→CheckBox; DATE/TIME/DATETIME→DateTimeInput flags; SELECT/DYNAMIC_SELECT→ChoicePicker mutuallyExclusive; MULTI_SELECT/TAGS/TRANSFER_LIST→multipleSelection (TAGS displayStyle chips); NPS/LIKERT/RANKING→Slider; HIDDEN→hidden; uploads/capture + GROUP/ARRAY/REMOTE_RESPONSE/AVAILABILITY/LOCATION/PLACE/REST/FORMULA/EMOJI/CRON/TREE_SELECT/CREDIT_CARD→notice).
- Implement `_lower_field(...)` for real: build the primitive `Component` with `id=f"f-{field_id}"`, `label=_resolve(field.label)`, `placeholder`, `value={"path": field_pointer(field_id)}` (ChoicePicker `value` binds the same path; Slider `min/max/steps` from `scale_min/scale_max/scale_step` with defaults 0/10; DateTimeInput `min/max` from constraints when str), options from `FieldOption` (`ChoiceOption(label=_resolve(o.label), value=o.value)`; skip `disabled` options), field metadata extensions (`parrot_field_id`, `parrot_field_uid`, `parrot_field_type`, `parrot_section_id`, `parrot_subsection_id`, `parrot_anchor_labels` for scales, `parrot_read_only` when `read_only`).
- Implement `_lower_checks(field) -> list[CheckRule] | None`: `required` → `CheckRule(condition=FunctionCall(call="required", args={"value": binding}), message=f"{label} is required.")`; `pattern` → `regex` (message from `pattern_message` when set); `min_length`/`max_length` → `length`; `min_value`/`max_value` → `numeric`; plus `check_functions` from the table (e.g. `email`). Read the exact argument names of each function from `catalog/basic/functions.py` before emitting them — do not guess.
- Degradation: notice `Text` (`text=f"{label}: not available on this surface"`, `parrot_role: "notice"`, `parrot_field_type`) + `RenderWarning(field_id, field_uid, field_type=field.field_type.value, renderer="a2ui", reason="no A2UI v1.0 primitive for <type>")`; `metadata["degraded"]` records `{"id", "field_id", "field_type", "reason"}`. GROUP/ARRAY children are NOT recursed (v1).
- `HIDDEN`: no component; the field is still seeded in `dataModel.answers` and listed in `metadata["field_paths"]`.
- Rendering must never raise for any FieldType (property test over `list(FieldType)`).
- Extend `tests/unit/renderers/test_a2ui_renderer.py` (or add `test_a2ui_field_lowering.py`).

**NOT in scope**: registration/packaging (TASK-3073); wire/handler work (TASK-3074+); Parrot-catalog form components (follow-up feature); `depends_on` visibility (non-goal U4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` | MODIFY | FIELD_LOWERING table, A2UIFieldLowering, real _lower_field, _lower_checks, _degrade |
| `packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_field_lowering.py` | CREATE | per-FieldType + constraints + degradation tests |

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
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer, field_pointer   # created by TASK-3071
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

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/functions.py — read the FunctionDefinition entries for required/regex/length/numeric/email to get their EXACT arg names before emitting CheckRules
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
# renderers/adaptive_card.py:71-119 — table-driven mapping with explicit None/unsupported entries
_FIELD_TYPE_MAP = {FieldType.TEXT: "Input.Text", ..., FieldType.GROUP: None, ...}

# catalog/parrot/form.py:78-84 — required check
CheckRule(condition=FunctionCall(call="required", args={"value": value_path}), message=f"{field.label} is required.")

# catalog/parrot/form.py:86-115 — per-primitive construction (TextField variant / ChoicePicker options / CheckBox / DateTimeInput enableDate)
```
- Assert at import time (or in a test) that `set(FIELD_LOWERING) == set(FieldType)` so a future FieldType addition fails loudly.
- `ChoicePicker.value` is a `DynamicStringList` — bind it to the same pointer; seed `dataModel.answers[field_id]` as `[]` for multi-select when no default.
- Slider needs `max` — never emit a Slider without it (fallback 10 / NPS 10 / LIKERT 5 when constraints are absent).

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py:505-530` — how constraints (minLength/minimum/pattern/scale) are read from `FieldConstraints` today
- `packages/ai-parrot/tests/outputs/a2ui/catalog/test_functions.py` — function argument shapes

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] `set(FIELD_LOWERING) == set(FieldType)` (47 entries) — test asserts equality.
- [ ] TEXT→`variant="shortText"`, TEXT_AREA→`longText`, NUMBER/INTEGER→`number`, PASSWORD→`obscured`; EMAIL adds an `email` check; URL/PHONE add a `regex` check.
- [ ] BOOLEAN→`CheckBox`; SELECT→`ChoicePicker(variant="mutuallyExclusive")`; MULTI_SELECT/TAGS→`multipleSelection` (TAGS `displayStyle="chips"`); options labels locale-resolved, disabled options skipped.
- [ ] DATE→`enableDate`, TIME→`enableTime`, DATETIME→both; NPS/LIKERT/RANKING→`Slider(min, max, steps)` from `scale_*`.
- [ ] HIDDEN emits no component but appears in `dataModel.answers` and `metadata.field_paths`.
- [ ] `required`/`pattern`/`min_length`/`max_length`/`min_value`/`max_value` lower to `checks` with `required`/`regex`/`length`/`numeric`; `pattern_message` becomes the message.
- [ ] Every degraded type yields a `Text` with `parrot_role == "notice"` and exactly one `RenderWarning(renderer="a2ui")`; `metadata.degraded` lists it; rendering a form containing EVERY FieldType never raises and still passes `validate_envelope(origin=TOOL)`.
- [ ] Every field component carries `parrot_field_id`, `parrot_field_uid`, `parrot_field_type`, `parrot_section_id` in `metadata.extensions`.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/renderers -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_field_lowering.py
import pytest
pytest.importorskip("parrot.outputs.a2ui")
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING, A2UIFormRenderer

def test_every_fieldtype_has_a_lowering_entry():
    assert set(FIELD_LOWERING) == set(FieldType)

@pytest.mark.parametrize("ft,variant", [(FieldType.TEXT,"shortText"),(FieldType.TEXT_AREA,"longText"),(FieldType.NUMBER,"number"),(FieldType.PASSWORD,"obscured")])
async def test_text_family_maps_to_textfield_variants(ft, variant): ...
async def test_email_adds_email_check(): ...
async def test_boolean_maps_to_checkbox(): ...
async def test_select_and_multiselect_map_to_choicepicker(): ...
async def test_date_time_datetime_flags(): ...
async def test_scale_types_map_to_slider(): ...
async def test_hidden_is_datamodel_only(): ...
async def test_constraints_lower_to_checks(): ...
@pytest.mark.parametrize("ft", [FieldType.FILE, FieldType.GROUP, FieldType.ARRAY, FieldType.SIGNATURE, FieldType.CRON])
async def test_unsupported_types_degrade_to_notice_and_warning(ft): ...
async def test_form_with_every_fieldtype_renders_and_validates(): ...
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
7. **Move this file** to `sdd/tasks/completed/TASK-3072-a2ui-field-lowering-checks-degradation.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: Added `A2UIFieldLowering` + the 45-entry `FIELD_LOWERING` table
(module-level `assert set(FIELD_LOWERING) == set(FieldType)` fails loudly at
import time on drift) and replaced the TASK-3071 stub `_lower_field` with
the real table-driven lowering: `TextField`/`CheckBox`/`ChoicePicker`/
`Slider`/`DateTimeInput` for every native FieldType, `"hidden"` for HIDDEN
(no component; still seeded in `dataModel.answers` and `metadata.
field_paths`), `"notice"` (Text + RenderWarning) for everything else.
`_lower_checks` lowers `required`/`pattern`/`min_length`/`max_length`/
`min_value`/`max_value` to `CheckRule`s using the exact `required`/`regex`/
`length`/`numeric`/`email` argument names read from
`catalog/basic/functions.py:466-518`; URL/PHONE get a conservative default
`regex` pattern when the field has no `pattern` constraint of its own
(open question — documented below). `metadata["degraded"]` now carries
`{"id","field_id","field_type","reason"}` dicts (not bare field_ids) and
`field_paths` is populated for every non-degraded (native or HIDDEN)
field. 85 new tests in `test_a2ui_field_lowering.py` (including a
`@pytest.mark.parametrize("field_type", list(FieldType))` property test —
rendering never raises for any FieldType) + all 10 pre-existing TASK-3071
tests still pass (190 total in `tests/unit/renderers`); `ruff check` clean.

**Deviations from spec**: (1) The spec/task's Codebase Contract states
`FieldType` has "47 members" — verified via `list(FieldType)` it is
actually **45**; `FIELD_LOWERING` covers all 45 (the contract's count was
stale, not a functional drift — every field/import/signature referenced
was verified before use). (2) Conservative default `regex` patterns for
URL (`^https?://\S+$`) / PHONE (`^\+?[0-9()\-\s]{7,20}$`) — spec §8 flags
this as an explicit, non-blocking open question for the implementer to
resolve; documented here per that note. (3) `DateTimeInput.min`/`max` from
constraints (spec §7: "min/max from constraints when ISO strings") is
NOT implemented — `FieldConstraints.min_value`/`max_value` are typed
`float | None`, not ISO date strings, so there is no constraint field to
source an ISO string from; implementing this would require guessing an
unspecified convention. Not covered by this task's own Acceptance
Criteria (only `enableDate`/`enableTime` are required for DATE/TIME/
DATETIME). (4) Slider `min`/`max` defaults follow the differentiated
"fallback 10 / NPS 10 / LIKERT 5" from §7 Implementation Notes rather
than the uniform "or 10" in the §7 mapping table (LIKERT defaults to 5,
RANKING to 10) — the two spec passages conflict slightly; the more
specific Implementation Notes wording was treated as authoritative.
