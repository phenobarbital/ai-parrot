# TASK-524: Adaptive Card Renderer

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 7 from the spec. Migrates `AdaptiveCardBuilder` from `parrot/integrations/msteams/dialogs/card_builder.py` to a new `AdaptiveCardRenderer` that implements `AbstractFormRenderer`. This is the most complex renderer — it must produce identical output for equivalent inputs to maintain MS Teams backward compatibility.

---

## Scope

- Create `parrot/forms/renderers/` package with `__init__.py`
- Implement `parrot/forms/renderers/base.py` with `AbstractFormRenderer` ABC
- Implement `parrot/forms/renderers/adaptive_card.py` with `AdaptiveCardRenderer`
- Migrate all logic from `AdaptiveCardBuilder`: field-to-AC-input mapping, complete form card, section card (wizard), summary card, error card, success card
- Map `StyleSchema.layout` to rendering mode: WIZARD → section-by-section, SINGLE_COLUMN → complete form
- Handle `DependencyRule` via AC `Action.ToggleVisibility` where possible
- Handle i18n by resolving `LocalizedString` via `locale` parameter
- Support `prefilled` and `errors` parameters
- Write unit tests

**NOT in scope**: HTML5 renderer (TASK-525), JSON Schema renderer (TASK-526), Teams dialog presets (TASK-532).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/renderers/__init__.py` | CREATE | Package init, export renderers |
| `packages/ai-parrot/src/parrot/forms/renderers/base.py` | CREATE | AbstractFormRenderer ABC, RenderedForm |
| `packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py` | CREATE | AdaptiveCardRenderer |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export renderers |
| `packages/ai-parrot/tests/unit/forms/test_adaptive_card_renderer.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self, form: FormSchema, style: StyleSchema | None = None, *,
        locale: str = "en", prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...

class AdaptiveCardRenderer(AbstractFormRenderer):
    SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"
    DEFAULT_VERSION = "1.5"

    async def render(self, ...) -> RenderedForm: ...
    async def render_section(self, form, section_index, ...) -> RenderedForm: ...
    async def render_summary(self, form, form_data, ...) -> RenderedForm: ...
    async def render_error(self, title, errors, ...) -> RenderedForm: ...
```

### Key Constraints
- Output must be compatible with MS Teams Bot Framework Adaptive Card schema v1.5
- Must preserve the `FIELD_TYPE_MAPPING` from existing `AdaptiveCardBuilder`
- `CardTheme` and `CardStyle` concepts should be preserved (mapped via `StyleSchema.theme` and `StyleSchema.meta`)
- For wizard mode: `render_section()` produces individual step cards with Back/Next/Skip navigation
- Resolve `LocalizedString` to plain string using the `locale` parameter before embedding in card JSON

### References in Codebase
- `parrot/integrations/msteams/dialogs/card_builder.py` — complete existing implementation to migrate

---

## Acceptance Criteria

- [ ] Full form renders as valid Adaptive Card JSON (schema v1.5)
- [ ] Section-by-section rendering produces correct wizard step cards
- [ ] Summary card renders with all field values
- [ ] Error card renders with error messages
- [ ] StyleSchema.layout affects rendering mode
- [ ] Prefilled values populate input fields
- [ ] Errors display as error messages next to fields
- [ ] i18n labels resolve correctly
- [ ] Import works: `from parrot.forms.renderers import AdaptiveCardRenderer, AbstractFormRenderer`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_adaptive_card_renderer.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_adaptive_card_renderer.py
import pytest
from parrot.forms import (
    FormSchema, FormField, FormSection, FieldType, StyleSchema, LayoutType,
)
from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer


@pytest.fixture
def renderer():
    return AdaptiveCardRenderer()


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="test", title="Test Form",
        sections=[FormSection(section_id="s1", title="Section 1", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
            FormField(field_id="role", field_type=FieldType.SELECT, label="Role",
                      options=[{"value": "admin", "label": "Admin"}, {"value": "user", "label": "User"}]),
        ])]
    )


class TestAdaptiveCardRenderer:
    async def test_complete_form(self, renderer, sample_form):
        result = await renderer.render(sample_form)
        card = result.content
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.5"
        assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"

    async def test_wizard_mode(self, renderer, sample_form):
        style = StyleSchema(layout=LayoutType.WIZARD)
        result = await renderer.render_section(sample_form, 0, style)
        assert result.content["type"] == "AdaptiveCard"

    async def test_prefilled_values(self, renderer, sample_form):
        result = await renderer.render(sample_form, prefilled={"name": "Alice"})
        # Verify the input element has the prefilled value
        card_json = str(result.content)
        assert "Alice" in card_json

    async def test_i18n_label(self, renderer):
        form = FormSchema(
            form_id="t", title={"en": "Test", "es": "Prueba"},
            sections=[FormSection(section_id="s", fields=[
                FormField(field_id="f", field_type=FieldType.TEXT,
                          label={"en": "Name", "es": "Nombre"})
            ])]
        )
        result_en = await renderer.render(form, locale="en")
        result_es = await renderer.render(form, locale="es")
        assert "Name" in str(result_en.content)
        assert "Nombre" in str(result_es.content)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Read** `parrot/integrations/msteams/dialogs/card_builder.py` thoroughly — this is the source to migrate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-524-adaptive-card-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: AbstractFormRenderer ABC in base.py. AdaptiveCardRenderer migrated from card_builder.py with new FieldType enum values. render(), render_section(), render_summary(), render_error(). i18n via _resolve(). All field types mapped. 18 unit tests pass.

**Deviations from spec**: none
