# TASK-532: MS Teams Integration Rewrite

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-518, TASK-519, TASK-524, TASK-527
**Assigned-to**: unassigned

---

## Context

Implements Module 15 from the spec. Rewrites all MS Teams form consumers to use the new `parrot/forms/` package instead of `parrot/integrations/dialogs/`. This is the hard cutover — 9 files change simultaneously. After this task, Teams uses `FormSchema` instead of `FormDefinition` everywhere.

---

## Scope

Rewrite the following files to import from `parrot/forms/` and use `FormSchema`/`StyleSchema`:

1. **`dialogs/factory.py`** — `FormDialogFactory.create_dialog()` accepts `FormSchema` + optional `StyleSchema`. Maps `StyleSchema.layout` (WIZARD, SINGLE_COLUMN, etc.) to dialog preset selection instead of `FormDefinition.preset`.

2. **`dialogs/orchestrator.py`** — `FormOrchestrator` uses `FormSchema`, delegates rendering to `AdaptiveCardRenderer` (from `parrot/forms/renderers/`). Uses `RequestFormTool` from `parrot/forms/tools/`. Updates `process_message()`, `handle_form_completion()`, and internal methods.

3. **`dialogs/presets/base.py`** — `BaseFormDialog` stores `FormSchema` reference instead of `FormDefinition`. Updates `get_form_data()`, card builder calls to use `AdaptiveCardRenderer`.

4. **`dialogs/presets/simple_form.py`** — Uses `AdaptiveCardRenderer.render()` for complete form card.

5. **`dialogs/presets/wizard.py`** — Uses `AdaptiveCardRenderer.render_section()` for step-by-step cards.

6. **`dialogs/presets/wizard_summary.py`** — Uses `AdaptiveCardRenderer.render_summary()` for confirmation.

7. **`dialogs/presets/conversational.py`** — Reads fields from `FormSchema.sections[].fields`.

8. **`wrapper.py`** — Updates import paths. `FormDefinition` → `FormSchema` in form handling logic.

9. **Remove `dialogs/validator.py`** — Validation now comes from `parrot.forms.validators.FormValidator`.

10. **Remove `dialogs/card_builder.py`** — Rendering now comes from `parrot.forms.renderers.AdaptiveCardRenderer`.

11. **Remove `tools/request_form.py`** — Tool now lives at `parrot.forms.tools.request_form`.

- Write integration tests that verify the full form flow still works.

**NOT in scope**: Removing `parrot/integrations/dialogs/` (TASK-533), HTML5/JSON Schema renderers, CreateFormTool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/factory.py` | MODIFY | Use FormSchema, StyleSchema |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/orchestrator.py` | MODIFY | Use FormSchema, AdaptiveCardRenderer, new RequestFormTool |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/base.py` | MODIFY | Use FormSchema, AdaptiveCardRenderer |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/simple_form.py` | MODIFY | Use AdaptiveCardRenderer |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/wizard.py` | MODIFY | Use AdaptiveCardRenderer.render_section() |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/wizard_summary.py` | MODIFY | Use AdaptiveCardRenderer.render_summary() |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/conversational.py` | MODIFY | Use FormSchema fields |
| `packages/ai-parrot/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Update imports |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/validator.py` | DELETE | Replaced by parrot.forms.validators |
| `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/card_builder.py` | DELETE | Replaced by parrot.forms.renderers.adaptive_card |
| `packages/ai-parrot/src/parrot/integrations/msteams/tools/request_form.py` | DELETE | Replaced by parrot.forms.tools.request_form |
| `packages/ai-parrot/tests/integration/forms/test_teams_forms.py` | CREATE | Integration tests |

---

## Implementation Notes

### Key Migration Mapping

| Old Import | New Import |
|---|---|
| `from ...integrations.dialogs.models import FormDefinition, FormField, FormSection, FieldType, ...` | `from parrot.forms import FormSchema, FormField, FormSection, FieldType, ...` |
| `from .card_builder import AdaptiveCardBuilder` | `from parrot.forms.renderers import AdaptiveCardRenderer` |
| `from .validator import FormValidator, ValidationResult` | `from parrot.forms.validators import FormValidator, ValidationResult` |
| `from ..tools.request_form import RequestFormTool` | `from parrot.forms.tools import RequestFormTool` |

### Key Changes per File

**factory.py:**
- `create_dialog(form: FormDefinition)` → `create_dialog(form: FormSchema, style: StyleSchema | None = None)`
- Preset selection: `form.preset` → `style.layout if style else LayoutType.SINGLE_COLUMN`
- WIZARD layout → WizardFormDialog, SINGLE_COLUMN → SimpleFormDialog, WIZARD+show_section_numbers → WizardWithSummaryDialog

**orchestrator.py:**
- Replace `FormDefinition` with `FormSchema` throughout
- Replace `AdaptiveCardBuilder` instantiation with `AdaptiveCardRenderer()`
- Replace direct `RequestFormTool` import with `parrot.forms.tools.RequestFormTool`
- `_resolve_dynamic_choices()` now works with `OptionsSource` instead of `choices_source`

**presets/base.py:**
- `_form_id` lookup goes through `FormRegistry` which now stores `FormSchema`
- `_get_card_builder()` → renderer obtained from constructor or default `AdaptiveCardRenderer()`
- `_get_validator()` → `FormValidator()` from `parrot.forms.validators`

**presets/simple_form.py, wizard.py, wizard_summary.py:**
- Replace `card_builder.build_complete_form(form, ...)` with `await renderer.render(form, style, ...)`
- Replace `card_builder.build_section_card(form, idx, ...)` with `await renderer.render_section(form, idx, style, ...)`
- Access `result.content` from `RenderedForm` instead of using dict directly

### Key Constraints
- **Backward compatibility**: The Adaptive Card JSON output must remain compatible with the Teams Bot Framework
- Existing dialog waterfall step logic (step_context, values, state management) stays the same — only the form model and renderer change
- The `_FORM_REGISTRY` global dict in `presets/base.py` should be replaced with `FormRegistry` instance

### References in Codebase
- All files listed in the scope above — read each one before modifying

---

## Acceptance Criteria

- [ ] All 8 modified files compile without import errors
- [ ] 3 deleted files removed (validator.py, card_builder.py, tools/request_form.py)
- [ ] No imports from `parrot.integrations.dialogs` remain in msteams/
- [ ] FormDialogFactory creates correct dialog types from StyleSchema.layout
- [ ] FormOrchestrator form request flow works end-to-end
- [ ] Simple form preset renders correctly
- [ ] Wizard preset renders step-by-step correctly
- [ ] Wizard+summary preset renders with confirmation
- [ ] Conversational preset reads fields correctly
- [ ] Integration tests pass
- [ ] All tests pass: `pytest packages/ai-parrot/tests/ -v -k "msteams or forms"`

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/forms/test_teams_forms.py
import pytest
from parrot.forms import (
    FormSchema, FormField, FormSection, FieldType, StyleSchema, LayoutType,
)
from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer
from parrot.forms.validators import FormValidator


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="teams-test", title="Teams Test Form",
        sections=[
            FormSection(section_id="info", title="Basic Info", fields=[
                FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
            ]),
            FormSection(section_id="prefs", title="Preferences", fields=[
                FormField(field_id="theme", field_type=FieldType.SELECT, label="Theme",
                          options=[{"value": "light", "label": "Light"}, {"value": "dark", "label": "Dark"}]),
            ]),
        ],
    )


class TestTeamsFormIntegration:
    async def test_render_complete_form(self, sample_form):
        renderer = AdaptiveCardRenderer()
        result = await renderer.render(sample_form)
        card = result.content
        assert card["type"] == "AdaptiveCard"

    async def test_render_wizard_sections(self, sample_form):
        renderer = AdaptiveCardRenderer()
        style = StyleSchema(layout=LayoutType.WIZARD)
        for i in range(len(sample_form.sections)):
            result = await renderer.render_section(sample_form, i, style)
            assert result.content["type"] == "AdaptiveCard"

    async def test_validate_then_render(self, sample_form):
        validator = FormValidator()
        result = await validator.validate(sample_form, {"name": "Alice", "email": "a@b.com", "theme": "dark"})
        assert result.is_valid
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518, TASK-519, TASK-524, TASK-527 are in `tasks/completed/`
3. **Read ALL files listed in scope** before making any changes
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above — change one file at a time, verify imports
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-532-msteams-integration-rewrite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
