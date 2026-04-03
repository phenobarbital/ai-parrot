# TASK-550: Renderers Migration

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-548
**Assigned-to**: unassigned

---

## Context

Implements Module 3 of FEAT-079. Moves the renderer modules from
`packages/ai-parrot/src/parrot/forms/renderers/` into the new package
under `parrot/formdesigner/renderers/`. Renderers convert a `FormSchema`
into output formats (HTML5, Adaptive Card, JSON Schema).

---

## Scope

- Move renderer files, updating all imports:
  - `parrot/forms/renderers/__init__.py` → `parrot/formdesigner/renderers/__init__.py`
  - `parrot/forms/renderers/base.py` → `parrot/formdesigner/renderers/base.py`
  - `parrot/forms/renderers/html5.py` → `parrot/formdesigner/renderers/html5.py`
  - `parrot/forms/renderers/adaptive_card.py` → `parrot/formdesigner/renderers/adaptive_card.py`
  - `parrot/forms/renderers/jsonschema.py` → `parrot/formdesigner/renderers/jsonschema.py`
  - `parrot/forms/renderers/templates/form.html.j2` → `parrot/formdesigner/renderers/templates/form.html.j2`
- Update all intra-module imports in moved files
- Create unit tests in `packages/parrot-formdesigner/tests/unit/test_renderers.py`

**NOT in scope**: extractors, services, tools, handlers, or re-export shim.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/__init__.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/adaptive_card.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/jsonschema.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/templates/form.html.j2` | CREATE | Copied template unchanged |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | CREATE | Unit tests for all renderers |

---

## Implementation Notes

### Import Update Pattern
Replace in all moved files:
- `from parrot.forms.schema import` → `from parrot.formdesigner.core.schema import`
- `from parrot.forms.types import` → `from parrot.formdesigner.core.types import`
- `from parrot.forms.style import` → `from parrot.formdesigner.core.style import`
- Relative imports like `from .base import` → keep as-is (still relative within renderers)

### Template File
The Jinja2 template at `renderers/templates/form.html.j2` must be copied as-is.
Verify the HTML5 renderer references the template path correctly after relocation.

### Key Constraints
- Preserve all async render methods
- Keep `renderers/base.py` as the abstract base class

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner.renderers import HTML5Renderer` works
- [ ] `from parrot.formdesigner.renderers import AdaptiveCardRenderer` works
- [ ] `from parrot.formdesigner.renderers import JSONSchemaRenderer` works
- [ ] HTML5 renderer can render a `FormSchema` to HTML string
- [ ] JSON Schema renderer returns valid JSON Schema dict
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py
import pytest
from parrot.formdesigner.core import FormSchema, FormField, FieldType
from parrot.formdesigner.renderers import HTML5Renderer, JSONSchemaRenderer


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test Form",
        fields=[
            FormField(name="name", field_type=FieldType.TEXT, label="Name"),
            FormField(name="email", field_type=FieldType.EMAIL, label="Email"),
        ],
    )


class TestHTML5Renderer:
    def test_renders_html_string(self, sample_schema):
        renderer = HTML5Renderer()
        html = renderer.render(sample_schema)
        assert isinstance(html, str)
        assert "<form" in html
        assert "name" in html

    def test_renders_email_field(self, sample_schema):
        renderer = HTML5Renderer()
        html = renderer.render(sample_schema)
        assert 'type="email"' in html


class TestJSONSchemaRenderer:
    def test_renders_json_schema(self, sample_schema):
        renderer = JSONSchemaRenderer()
        schema = renderer.render(sample_schema)
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "name" in schema["properties"]
```

---

## Agent Instructions

1. **Verify** TASK-548 is in `sdd/tasks/completed/` before starting
2. **Read source files** in `packages/ai-parrot/src/parrot/forms/renderers/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** scope above
5. **Verify** acceptance criteria
6. **Move** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
8. **Commit**: `sdd: implement TASK-550 renderers migration for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
