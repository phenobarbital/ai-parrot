# TASK-3146: Overridable hooks in `AdaptiveCardRenderer` + golden fixture for byte-identical `adaptive` output

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false — first task; every other task builds on these hooks.

---

## Context

Spec §3 Module 1 (first half). `TeamsFormRenderer` (TASK-3147) must change ONLY the terminal
Submit `data` and the upload-field element without re-implementing `render()`. Today both are
literals inside `AdaptiveCardRenderer` (`adaptive_card.py:1096-1101`, `:1172-1178`, `:1033-1044`).
This task extracts them into overridable hooks whose defaults reproduce the exact current dicts,
threads `form=` into the action builders, and pins the default `adaptive` output with a golden
fixture (spec G5 / AC "byte-identical"). The msteams dialog presets instantiate
`AdaptiveCardRenderer()` directly (`presets/base.py:174-176`), so any drift here breaks Teams dialogs.

---

## Scope

- Add class attributes `RENDERER_NAME = "adaptive_card"` and `accepts_tenant = False` to `AdaptiveCardRenderer`.
- Add hook `_submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]` returning `{"_action": "submit"}`.
- Add hook `_build_upload_element(self, field, value, locale) -> dict[str, Any] | None` containing the code currently at the `elif ft in UPLOAD_FIELD_TYPES:` branch (moved verbatim); the branch now delegates to the hook.
- Add keyword-only `form: FormSchema | None = None` to `_build_form_actions` and `_build_wizard_actions`; the Submit entries call the hook (terminal Submit only — Back/Skip/Cancel/Next literals unchanged).
- `render()` and `render_section()` pass `form=form` to the builders; the RenderWarning `renderer="adaptive_card"` literal becomes `renderer=self.RENDERER_NAME`.
- Golden fixture `tests/unit/fixtures/adaptive_card_golden.json` generated from `sample_schema` BEFORE the refactor, and tests asserting equality after it.

**NOT in scope**: `TeamsFormRenderer`, envelope model, registration, wrapper (TASK-3147..3151). No change to `_AC_FALLBACK_TYPES` or `_FIELD_TYPE_MAPPING`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | hooks + `form=` kwargs + `RENDERER_NAME` |
| `packages/parrot-formdesigner/tests/unit/fixtures/adaptive_card_golden.json` | CREATE | canonical `json.dumps(content, sort_keys=True, indent=2)` of `AdaptiveCardRenderer().render(sample_schema)` |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | golden test + hook default tests + wizard non-terminal test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer, _AC_FALLBACK_TYPES, _FIELD_TYPE_MAPPING  # adaptive_card.py:121, :95, :70
from parrot_formdesigner.core.schema import FormField, FormSchema, RenderedForm, RenderWarning   # schema.py:65, :401, :671, :650
from parrot_formdesigner.core.file_envelope import UPLOAD_FIELD_TYPES                             # file_envelope.py:44-51 (already imported adaptive_card.py:12)
from parrot_formdesigner.core.types import FieldType                                              # types.py:16
# tests
from parrot_formdesigner.core import FormSchema, FormSection                                     # test_renderers.py:4
from parrot_formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer  # test_renderers.py:7
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py
class AdaptiveCardRenderer(AbstractFormRenderer):                                   # 121
    SCHEMA_URL / DEFAULT_VERSION / CONTENT_TYPE                                     # 142-144
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm   # 182
        # actions = self._build_form_actions(show_cancel=form.cancel_allowed, submit_label=..., cancel_label=...)   # 243-247
        # warnings loop: RenderWarning(..., renderer="adaptive_card", ...)          # 251-267 (literal at 262)
    async def render_section(self, form, section_index, style=None, *, locale="en", prefilled=None, errors=None, show_back=False, show_skip=False) -> RenderedForm  # 275
        # actions = self._build_wizard_actions(is_first=..., is_last=is_last, show_back=..., show_cancel=form.cancel_allowed, show_skip=..., cancel_label=...)  # 332-339
    def _build_input_element(self, field, value, locale) -> dict | None            # 758
        # elif ft in UPLOAD_FIELD_TYPES:  ... return {**base, "type": "Input.Text", "placeholder": ..., "value": display_value}   # 1033-1044
    def _build_form_actions(self, show_cancel=True, submit_label="Submit", cancel_label="Cancel") -> list[dict]   # 1079 ; Submit dict 1096-1101
    def _build_wizard_actions(self, is_first, is_last, show_back=True, show_cancel=True, show_skip=False, cancel_label="Cancel") -> list[dict]  # 1115 ; `if is_last:` Submit dict 1170-1178
def _extract_display_name(value: Any) -> str                                        # 29
def _resolve(value: LocalizedString | None, locale: str = "en") -> str             # 45

# packages/parrot-formdesigner/tests/unit/test_renderers.py
def sample_schema() -> FormSchema                                                   # 161 (pytest fixture)
class TestAdaptiveCardRenderer: async def test_renders_adaptive_card(self, sample_schema)   # 391-393
```

### Does NOT Exist
- ~~`AdaptiveCardRenderer._submit_action_data`~~, ~~`_build_upload_element`~~, ~~`RENDERER_NAME`~~, ~~`accepts_tenant`~~ — created by THIS task.
- ~~`_build_form_actions(..., form=)`~~ — kwarg added by THIS task; current call sites pass none.
- ~~`tests/unit/fixtures/`~~ directory — created by THIS task (check with `ls` first; create with `__init__`-less plain dir).
- ~~`tests/unit/conftest.py::sample_form`~~ — `sample_form` lives in `tests/unit/api/test_render_dispatcher.py:50-51`; the renderer tests use `sample_schema` (`test_renderers.py:161`).
- ~~`renderer="teams"`~~ — no Teams anything in this task.

---

## Implementation Notes

### Pattern to Follow
```python
# Hook-with-identical-default pattern (same posture as FallbackRenderer in renderers/base.py:34-54):
def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
    return {"_action": "submit"}
```

### Key Constraints
- Output of `AdaptiveCardRenderer().render(...)` must be byte-identical (dict key ORDER included — the Submit dict keeps `type, title, style, data` order).
- Generate the golden fixture from the UNMODIFIED code first (commit it), then refactor; the test must pass on both.
- Do not touch `_AC_FALLBACK_TYPES`, `_FIELD_TYPE_MAPPING`, choices, summary or error cards.

### References in Codebase
- `renderers/base.py:34-54` — `FallbackRenderer` (default-that-subclasses-override).
- `presets/base.py:174-176` — external consumer that must keep working.

---

## Implementation Blueprint

### Steps (in order)
1. Run the unmodified renderer on `sample_schema` and write `tests/unit/fixtures/adaptive_card_golden.json` (`json.dumps(result.content, sort_keys=True, indent=2)`) — *why*: the fixture must capture pre-refactor output to be a real guard.
2. Add `RENDERER_NAME`/`accepts_tenant` class attrs and the two hooks to `AdaptiveCardRenderer` — *why*: TASK-3147 overrides them; defaults must be literal copies of today's dicts.
3. Thread `form=` through `_build_form_actions`/`_build_wizard_actions` and their two call sites; replace the `renderer="adaptive_card"` literal with `self.RENDERER_NAME` — *why*: the Teams subclass needs the form to build its envelope and its own warning name.
4. Replace the body of the `elif ft in UPLOAD_FIELD_TYPES:` branch with `return self._build_upload_element(field, value, locale)` and move the old body into the hook — *why*: TASK-3148 overrides the upload element only.
5. Add the tests; run `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -q`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` (MODIFY — class attrs + hooks)
```python
# occurrences: 1 (verified: grep -c 'CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"' adaptive_card.py)
# AFTER — insert below `    CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"` (verified: adaptive_card.py:144)
    RENDERER_NAME: str = "adaptive_card"
    accepts_tenant: bool = False

# occurrences: 1 (verified: grep -c 'def _build_form_actions(' adaptive_card.py)
# BEFORE — insert above `    def _build_form_actions(` (verified: adaptive_card.py:1079)
    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
        """Return the ``data`` payload of a Submit action.

        Default is byte-identical to the historical literal ``{"_action": "submit"}``.
        Subclasses may add routing keys but MUST keep ``_action``.

        Args:
            form: The form being rendered (``None`` when a builder is called standalone).
            terminal: ``True`` for the final Submit; ``False`` never reaches the default.
        """
        return {"_action": "submit"}

    def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None:
        """Element for FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD fields (text-placeholder fallback).

        Body moved verbatim from the former ``elif ft in UPLOAD_FIELD_TYPES`` branch.
        """
        base: dict[str, Any] = {"id": field.field_id, "isRequired": field.required}
        display_name = _extract_display_name(value)
        display_value = display_name
        if isinstance(value, dict) and value.get("thumbnail_url"):
            display_value = f"{display_name} ({value['thumbnail_url']})" if display_name else value["thumbnail_url"]
        return {
            **base,
            "type": "Input.Text",
            "placeholder": _resolve(field.placeholder, locale) if field.placeholder else "",
            "value": display_value,
        }
```
**Why this shape**: the hook defaults are literal copies, so the golden test proves no drift. `base` is rebuilt in the hook (same two keys as `:774-777`) so the hook is self-contained for subclasses.

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` (MODIFY — builders + call sites)
```python
# occurrences: 2 (verified: grep -c '"data": {"_action": "submit"},' adaptive_card.py)
# FILL IN: disambiguate — the FIRST occurrence sits inside `_build_form_actions` right after
#   `"style": "positive",` under `"title": submit_label,` (adaptive_card.py:1096-1101); the SECOND sits inside
#   `_build_wizard_actions` under `if is_last:` after `"title": "Submit",` (adaptive_card.py:1170-1178).
#   Replace BOTH with:
                "data": self._submit_action_data(form, terminal=True),

# Signatures (fixed by spec §3 M1 — do not rename):
    def _build_form_actions(self, show_cancel: bool = True, submit_label: str = "Submit",
                            cancel_label: str = "Cancel", *, form: FormSchema | None = None) -> list[dict[str, Any]]:
    def _build_wizard_actions(self, is_first: bool, is_last: bool, show_back: bool = True, show_cancel: bool = True,
                              show_skip: bool = False, cancel_label: str = "Cancel", *, form: FormSchema | None = None) -> list[dict[str, Any]]:

# occurrences: 1 (verified: grep -c 'actions = self._build_form_actions(' adaptive_card.py)   -> add `form=form,` as last kwarg (adaptive_card.py:243)
# occurrences: 1 (verified: grep -c 'actions = self._build_wizard_actions(' adaptive_card.py) -> add `form=form,` as last kwarg (adaptive_card.py:332)
# occurrences: 1 (verified: grep -c 'renderer="adaptive_card",' adaptive_card.py)             -> `renderer=self.RENDERER_NAME,` (adaptive_card.py:262)
# occurrences: 1 (verified: grep -c 'elif ft in UPLOAD_FIELD_TYPES:' adaptive_card.py)        -> body becomes `return self._build_upload_element(field, value, locale)` (adaptive_card.py:1033)
```
**Why**: only the two terminal Submit literals route through the hook; Back/Skip/Cancel/Next keep their literals (spec S2). `form` is keyword-only so existing positional callers (presets) are unaffected.

### `packages/parrot-formdesigner/tests/unit/test_renderers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_adaptive_card_fallback_types_emit_warnings' test_renderers.py)
# BEFORE — insert above `async def test_adaptive_card_fallback_types_emit_warnings():` (verified: test_renderers.py:472)
import json
from pathlib import Path

_GOLDEN = Path(__file__).parent / "fixtures" / "adaptive_card_golden.json"


async def test_adaptive_default_output_golden(sample_schema):
    """AdaptiveCardRenderer output is byte-identical to the committed golden fixture (FEAT-551 G5)."""
    result = await AdaptiveCardRenderer().render(sample_schema)
    assert json.dumps(result.content, sort_keys=True, indent=2) == _GOLDEN.read_text(encoding="utf-8")


def test_submit_action_data_default():
    r = AdaptiveCardRenderer()
    assert r._submit_action_data(None, terminal=True) == {"_action": "submit"}
    assert r._submit_action_data(None, terminal=False) == {"_action": "submit"}
    assert r.RENDERER_NAME == "adaptive_card" and r.accepts_tenant is False


async def test_wizard_non_terminal_actions_unchanged(sample_schema):
    # FILL IN: render_section for index 0 (not last) and the last index — bounded by: non-last step has no
    #   Submit action and its actions' data are the literals {"_action": "back"|"skip"|"cancel"|"next"};
    #   last step's Submit data == {"_action": "submit"}.
    raise NotImplementedError
```
**Why**: golden equality is the guard for AC "byte-identical"; hook tests document the default contract TASK-3147 relies on.

### FILL IN checklist
- [ ] `adaptive_card.py` — both Submit literals replaced (grep count of `"data": {"_action": "submit"},` must be 0 afterwards); bounded by golden test passing.
- [ ] `test_renderers.py::test_wizard_non_terminal_actions_unchanged` — bounded by spec §3 M1 "only the is_last Submit calls the hook".
- [ ] `fixtures/adaptive_card_golden.json` — generated from pre-refactor code; bounded by AC-2.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -v`
- [ ] `grep -c '"data": {"_action": "submit"},' packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` prints `0`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py`
- [ ] Imports work: `from parrot_formdesigner.renderers import AdaptiveCardRenderer`
- [ ] Golden fixture equality holds (AC "byte-identical `adaptive`")
- [ ] `ai-parrot-integrations` msteams presets import still resolves (`python -c "from parrot_formdesigner.renderers import AdaptiveCardRenderer; AdaptiveCardRenderer()._build_form_actions()"`)

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py (additions)
async def test_adaptive_default_output_golden(sample_schema): ...
def test_submit_action_data_default(): ...
async def test_wizard_non_terminal_actions_unchanged(sample_schema): ...
async def test_upload_element_default_matches_previous_fallback(sample_schema):
    """An IMAGE field with a FileEnvelope-like dict value renders Input.Text with filename (thumbnail_url) — as before."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm every anchor line/count above before editing
4. **Update status** in `sdd/tasks/index/msteams-formdesigner-renderer.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3146-adaptive-card-renderer-hooks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
