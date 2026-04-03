# TASK-522: YAML Extractor

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518
**Assigned-to**: unassigned

---

## Context

Implements Module 5 from the spec. Parses YAML form definitions into `FormSchema`. Must be backward-compatible with the existing YAML format used by current form files, while also supporting new features (constraints, depends_on, i18n labels).

---

## Scope

- Implement `parrot/forms/extractors/yaml.py` with `YamlExtractor`
- Use `yaml_rs` (Rust) with PyYAML fallback (same pattern as existing code)
- Backward-compatible with existing YAML format (both field name formats, validation syntax, choices)
- Support new schema features: `FieldConstraints`, `DependencyRule`, `LocalizedString` labels
- Support `from_string()` and `from_file()` methods
- Migrate logic from `parrot/integrations/dialogs/parser.py`
- Write unit tests

**NOT in scope**: JSON Schema extraction (TASK-523), form cache (TASK-528).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/extractors/yaml.py` | CREATE | YamlExtractor implementation |
| `packages/ai-parrot/src/parrot/forms/extractors/__init__.py` | MODIFY | Export YamlExtractor |
| `packages/ai-parrot/tests/unit/forms/test_yaml_extractor.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Migrate from `parrot/integrations/dialogs/parser.py` which has `parse_yaml()`, `parse_yaml_file()`, and helper functions `_parse_field()`, `_parse_section()`, `_parse_validation()`, `_parse_choices()`.

```python
class YamlExtractor:
    def extract_from_string(self, content: str) -> FormSchema: ...
    def extract_from_file(self, path: str | Path) -> FormSchema: ...
```

### Key Constraints
- Must support both YAML field formats: `{ name: "field_name", type: "text" }` and `{ field_name: { type: "text" } }`
- Must map old `ValidationRule` names to new `FieldConstraints` fields
- Must map old `FieldType` values (CHOICE, MULTICHOICE, TOGGLE, TEXTAREA) to new enum values (SELECT, MULTI_SELECT, BOOLEAN, TEXT_AREA)
- New YAML keys for constraints, depends_on, and i18n are additive — old files parse without changes
- Use `yaml_rs` if available, `PyYAML` as fallback

### References in Codebase
- `parrot/integrations/dialogs/parser.py` — existing YAML parsing logic
- `parrot/integrations/dialogs/models.py:204-316` — `FormDefinition._from_dict()` existing dict-to-model logic

---

## Acceptance Criteria

- [ ] Existing YAML format parses correctly (backward compatibility)
- [ ] New constraints, depends_on, i18n features parse correctly
- [ ] Both field name formats supported
- [ ] Old FieldType values (CHOICE, TOGGLE, etc.) mapped to new enum values
- [ ] Falls back to PyYAML when yaml_rs unavailable
- [ ] Import works: `from parrot.forms.extractors import YamlExtractor`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_yaml_extractor.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_yaml_extractor.py
import pytest
from parrot.forms import FieldType
from parrot.forms.extractors.yaml import YamlExtractor


@pytest.fixture
def extractor():
    return YamlExtractor()


LEGACY_YAML = """
form_id: test_form
title: Test Form
preset: wizard
sections:
  - name: basics
    title: Basic Info
    fields:
      - name: full_name
        type: text
        label: Full Name
        required: true
        validation:
          min_length: 2
          max_length: 100
      - name: role
        type: choice
        label: Role
        choices:
          - admin
          - user
"""

NEW_YAML = """
form_id: new_form
title:
  en: New Form
  es: Formulario Nuevo
sections:
  - section_id: main
    title:
      en: Main Section
      es: Sección Principal
    fields:
      - field_id: email
        field_type: email
        label:
          en: Email
          es: Correo
        required: true
        constraints:
          pattern: ".+@.+\\..+"
          pattern_message:
            en: Must be a valid email
            es: Debe ser un correo válido
      - field_id: age
        field_type: integer
        label: Age
        depends_on:
          conditions:
            - field_id: show_age
              operator: eq
              value: true
          effect: show
"""


class TestYamlExtractor:
    def test_legacy_format(self, extractor):
        schema = extractor.extract_from_string(LEGACY_YAML)
        assert schema.form_id == "test_form"
        assert len(schema.sections) == 1
        fields = schema.sections[0].fields
        assert fields[0].field_type == FieldType.TEXT
        assert fields[1].field_type == FieldType.SELECT  # CHOICE mapped

    def test_new_format_with_i18n(self, extractor):
        schema = extractor.extract_from_string(NEW_YAML)
        assert schema.title["en"] == "New Form"
        assert schema.sections[0].fields[0].constraints is not None

    def test_depends_on_parsed(self, extractor):
        schema = extractor.extract_from_string(NEW_YAML)
        age_field = schema.sections[0].fields[1]
        assert age_field.depends_on is not None
        assert age_field.depends_on.effect == "show"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 is in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/parser.py` and `parrot/integrations/dialogs/models.py` lines 204-316 for existing parsing logic
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-522-yaml-extractor.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: YamlExtractor with extract_from_string() and extract_from_file(). yaml_rs/PyYAML backend selection. Legacy type mapping (choice/toggle/textarea/multichoice). Legacy validation block mapping to FieldConstraints. Both field formats supported. i18n labels/titles. depends_on and constraints blocks. 17 unit tests pass.

**Deviations from spec**: none
