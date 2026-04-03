# TASK-525: HTML5 Renderer

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 8 from the spec. Renders `FormSchema` + `StyleSchema` as an HTML `<form>` fragment meant to be served via API and embedded in another page. Uses Jinja2 templates. Does NOT include client-side JavaScript for conditional visibility — the consuming frontend handles `data-depends-on` attributes.

---

## Scope

- Implement `parrot/forms/renderers/html5.py` with `HTML5Renderer`
- Use Jinja2 templates for HTML generation
- Map `FieldType` to HTML5 input types: TEXT → `<input type="text">`, EMAIL → `<input type="email">`, NUMBER → `<input type="number">`, BOOLEAN → `<input type="checkbox">`, SELECT → `<select>`, MULTI_SELECT → `<select multiple>`, TEXT_AREA → `<textarea>`, DATE → `<input type="date">`, etc.
- Emit HTML5 validation attributes: `required`, `minlength`, `maxlength`, `min`, `max`, `step`, `pattern`
- Emit `data-depends-on` attributes for conditional visibility (JSON-serialized `DependencyRule`)
- Generate submit handler targeting `SubmitAction` endpoint (form `action` attribute + `method`)
- Support `StyleSchema.layout` (single-column, two-column via CSS classes)
- Resolve `LocalizedString` via `locale` parameter
- Support `prefilled` values and `errors` display
- Write unit tests

**NOT in scope**: Client-side JavaScript, CSS styles (only CSS class names), full HTML page.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/renderers/html5.py` | CREATE | HTML5Renderer implementation |
| `packages/ai-parrot/src/parrot/forms/renderers/templates/` | CREATE | Jinja2 templates directory |
| `packages/ai-parrot/src/parrot/forms/renderers/templates/form.html.j2` | CREATE | Main form template |
| `packages/ai-parrot/src/parrot/forms/renderers/__init__.py` | MODIFY | Export HTML5Renderer |
| `packages/ai-parrot/tests/unit/forms/test_html5_renderer.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class HTML5Renderer(AbstractFormRenderer):
    def __init__(self, template_dir: str | Path | None = None):
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(template_dir or self._default_template_dir()),
            autoescape=True,
        )

    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm:
        template = self._env.get_template("form.html.j2")
        html = template.render(form=form, style=style, locale=locale, ...)
        return RenderedForm(content=html, content_type="text/html")
```

### Key Constraints
- Output is a `<form>` fragment, NOT a full HTML page (no `<html>`, `<head>`, `<body>`)
- `SubmitAction.action_ref` becomes the form `action` attribute, `SubmitAction.method` becomes the `method` attribute
- `data-depends-on` attribute contains JSON: `{"conditions": [...], "logic": "and", "effect": "show"}`
- CSS class conventions: `form-section`, `form-field`, `form-field--{size}` (from FieldStyleHint.size), `form-layout--{layout}` (from StyleSchema.layout)
- Jinja2 `autoescape=True` for XSS prevention
- `confirm_message` from SubmitAction should be a `data-confirm` attribute on the submit button

### References in Codebase
- No existing HTML renderer — this is new. Use `AdaptiveCardBuilder` field mapping as a guide for FieldType → input type mapping.

---

## Acceptance Criteria

- [ ] Renders valid `<form>` HTML fragment
- [ ] HTML5 validation attributes present (required, minlength, maxlength, min, max, pattern, step)
- [ ] `data-depends-on` attributes emitted for fields with DependencyRule
- [ ] Submit handler targets SubmitAction endpoint
- [ ] Labels render in requested locale (i18n)
- [ ] Prefilled values populate input elements
- [ ] Errors display next to fields
- [ ] Layout CSS classes match StyleSchema.layout
- [ ] XSS prevention via Jinja2 autoescape
- [ ] Import works: `from parrot.forms.renderers import HTML5Renderer`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_html5_renderer.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_html5_renderer.py
import pytest
from parrot.forms import (
    FormSchema, FormField, FormSection, FieldType, FieldConstraints,
    SubmitAction, StyleSchema, LayoutType, DependencyRule, FieldCondition,
    ConditionOperator,
)
from parrot.forms.renderers.html5 import HTML5Renderer


@pytest.fixture
def renderer():
    return HTML5Renderer()


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="test", title="Test Form",
        sections=[FormSection(section_id="s1", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT, label="Name",
                      required=True, constraints=FieldConstraints(min_length=2, max_length=100)),
            FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
        ])],
        submit=SubmitAction(action_type="endpoint", action_ref="/api/submit", method="POST"),
    )


class TestHTML5Renderer:
    async def test_renders_form_fragment(self, renderer, sample_form):
        result = await renderer.render(sample_form)
        assert "<form" in result.content
        assert "</form>" in result.content
        assert "<html" not in result.content  # fragment, not full page

    async def test_validation_attributes(self, renderer, sample_form):
        result = await renderer.render(sample_form)
        assert 'required' in result.content
        assert 'minlength="2"' in result.content
        assert 'maxlength="100"' in result.content

    async def test_submit_action(self, renderer, sample_form):
        result = await renderer.render(sample_form)
        assert 'action="/api/submit"' in result.content
        assert 'method="POST"' in result.content

    async def test_depends_on_attribute(self, renderer):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="toggle", field_type=FieldType.BOOLEAN, label="Show extra"),
                FormField(field_id="extra", field_type=FieldType.TEXT, label="Extra",
                          depends_on=DependencyRule(
                              conditions=[FieldCondition(field_id="toggle",
                                          operator=ConditionOperator.EQ, value=True)],
                              effect="show")),
            ])
        ])
        result = await renderer.render(form)
        assert 'data-depends-on' in result.content

    async def test_i18n_labels(self, renderer):
        form = FormSchema(form_id="t", title="T", sections=[
            FormSection(section_id="s", fields=[
                FormField(field_id="f", field_type=FieldType.TEXT,
                          label={"en": "Name", "es": "Nombre"})
            ])
        ])
        result_es = await renderer.render(form, locale="es")
        assert "Nombre" in result_es.content

    async def test_content_type(self, renderer, sample_form):
        result = await renderer.render(sample_form)
        assert result.content_type == "text/html"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-525-html5-renderer.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: HTML5Renderer using Jinja2 (autoescape=True) + form.html.j2 template. render_field() called from template with | safe filter to prevent double-escaping. Renders text/email/number/checkbox/select/textarea/file inputs, HTML5 validation attributes (required, minlength, maxlength, min, max, pattern, step), data-depends-on JSON attributes, i18n via locale parameter, prefilled values, error messages. 18 tests pass.

**Deviations from spec**: none
