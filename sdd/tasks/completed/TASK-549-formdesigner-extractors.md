# TASK-549: Extractors Migration

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

Implements Module 2 of FEAT-079. Moves the four extractor modules from
`packages/ai-parrot/src/parrot/forms/extractors/` into the new
`parrot-formdesigner` package under `parrot/formdesigner/extractors/`.

Extractors convert external representations (Pydantic models, tool schemas, YAML,
JSON Schema) into `FormSchema` objects. They depend only on core models (TASK-548).

---

## Scope

- Move extractor files, updating imports from `parrot.forms.*` to `parrot.formdesigner.*`:
  - `parrot/forms/extractors/__init__.py` → `parrot/formdesigner/extractors/__init__.py`
  - `parrot/forms/extractors/pydantic.py` → `parrot/formdesigner/extractors/pydantic.py`
  - `parrot/forms/extractors/tool.py` → `parrot/formdesigner/extractors/tool.py`
  - `parrot/forms/extractors/yaml.py` → `parrot/formdesigner/extractors/yaml.py`
  - `parrot/forms/extractors/jsonschema.py` → `parrot/formdesigner/extractors/jsonschema.py`
- Update all intra-module imports in moved files
- Create unit tests in `packages/parrot-formdesigner/tests/unit/test_extractors.py`

**NOT in scope**: renderers, services, tools, handlers, or re-export shim.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/__init__.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/pydantic.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/tool.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/yaml.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/jsonschema.py` | CREATE | Moved + imports updated |
| `packages/parrot-formdesigner/tests/unit/test_extractors.py` | CREATE | Unit tests for all extractors |

---

## Implementation Notes

### Import Update Pattern
Replace in all moved files:
- `from parrot.forms.schema import` → `from parrot.formdesigner.core.schema import`
- `from parrot.forms.types import` → `from parrot.formdesigner.core.types import`
- `from parrot.forms.constraints import` → `from parrot.formdesigner.core.constraints import`
- `from parrot.forms.options import` → `from parrot.formdesigner.core.options import`
- `from parrot.forms.style import` → `from parrot.formdesigner.core.style import`
- `from ..schema import` / `from ..types import` → `from ..core.schema import` / `from ..core.types import`

### Key Constraints
- All extractors must remain async where they already are
- Preserve all existing docstrings and type hints

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner.extractors import PydanticExtractor` works
- [ ] `from parrot.formdesigner.extractors import ToolExtractor` works
- [ ] `from parrot.formdesigner.extractors import YAMLExtractor` works
- [ ] `from parrot.formdesigner.extractors import JSONSchemaExtractor` works
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_extractors.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_extractors.py
import pytest
from parrot.formdesigner.core import FormSchema
from parrot.formdesigner.extractors import (
    PydanticExtractor,
    ToolExtractor,
    YAMLExtractor,
    JSONSchemaExtractor,
)
from pydantic import BaseModel


class SampleModel(BaseModel):
    name: str
    age: int
    email: str


class TestPydanticExtractor:
    def test_extract_from_pydantic_model(self):
        extractor = PydanticExtractor()
        schema = extractor.extract(SampleModel)
        assert isinstance(schema, FormSchema)
        assert len(schema.fields) == 3

    def test_field_names_preserved(self):
        extractor = PydanticExtractor()
        schema = extractor.extract(SampleModel)
        field_names = [f.name for f in schema.fields]
        assert "name" in field_names
        assert "email" in field_names


class TestYAMLExtractor:
    def test_extract_from_yaml_string(self):
        yaml_content = """
form_id: contact
title: Contact Form
fields:
  - name: subject
    field_type: text
    label: Subject
"""
        extractor = YAMLExtractor()
        schema = extractor.extract(yaml_content)
        assert isinstance(schema, FormSchema)
        assert schema.form_id == "contact"
```

---

## Agent Instructions

1. **Verify** TASK-548 is in `sdd/tasks/completed/` before starting
2. **Read source files** in `packages/ai-parrot/src/parrot/forms/extractors/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** scope above
5. **Verify** acceptance criteria
6. **Move** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
8. **Commit**: `sdd: implement TASK-549 extractors migration for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
