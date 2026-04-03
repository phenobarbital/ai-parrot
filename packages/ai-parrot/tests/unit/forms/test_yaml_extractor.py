"""Unit tests for YamlExtractor."""

import pytest
from parrot.forms import FieldType
from parrot.forms.extractors.yaml import YamlExtractor


@pytest.fixture
def extractor():
    """YamlExtractor instance."""
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
          pattern: ".+@.+\\\\..+"
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

ALTERNATE_FIELD_FORMAT_YAML = """
form_id: alt_form
title: Alt Form
sections:
  - name: s1
    title: Section 1
    fields:
      - full_name:
          type: text
          label: Full Name
          required: true
      - age:
          type: number
          label: Age
"""

TOGGLE_TEXTAREA_YAML = """
form_id: legacy_types
title: Legacy Types
sections:
  - name: s1
    fields:
      - name: active
        type: toggle
        label: Active
      - name: notes
        type: textarea
        label: Notes
      - name: items
        type: multichoice
        label: Items
        choices:
          - item1
          - item2
"""


class TestYamlExtractorLegacy:
    """Tests for legacy YAML format parsing."""

    def test_legacy_format(self, extractor):
        """Legacy format parses correctly."""
        schema = extractor.extract_from_string(LEGACY_YAML)
        assert schema.form_id == "test_form"
        assert len(schema.sections) == 1

    def test_legacy_field_count(self, extractor):
        """All fields from legacy format are parsed."""
        schema = extractor.extract_from_string(LEGACY_YAML)
        assert len(schema.sections[0].fields) == 2

    def test_legacy_field_types(self, extractor):
        """Legacy field types are mapped correctly."""
        schema = extractor.extract_from_string(LEGACY_YAML)
        fields = schema.sections[0].fields
        assert fields[0].field_type == FieldType.TEXT
        assert fields[1].field_type == FieldType.SELECT  # CHOICE mapped to SELECT

    def test_legacy_validation_to_constraints(self, extractor):
        """Legacy validation block maps to FieldConstraints."""
        schema = extractor.extract_from_string(LEGACY_YAML)
        full_name = schema.sections[0].fields[0]
        assert full_name.constraints is not None
        assert full_name.constraints.min_length == 2
        assert full_name.constraints.max_length == 100

    def test_legacy_choices_to_options(self, extractor):
        """Legacy choices list maps to FieldOption list."""
        schema = extractor.extract_from_string(LEGACY_YAML)
        role = schema.sections[0].fields[1]
        assert role.options is not None
        values = {opt.value for opt in role.options}
        assert "admin" in values
        assert "user" in values

    def test_legacy_required_field(self, extractor):
        """Legacy required: true is respected."""
        schema = extractor.extract_from_string(LEGACY_YAML)
        assert schema.sections[0].fields[0].required is True

    def test_alternate_field_format(self, extractor):
        """Alternate field format {field_name: {type: ...}} is supported."""
        schema = extractor.extract_from_string(ALTERNATE_FIELD_FORMAT_YAML)
        fields = schema.sections[0].fields
        assert fields[0].field_id == "full_name"
        assert fields[0].field_type == FieldType.TEXT

    def test_toggle_mapped_to_boolean(self, extractor):
        """toggle type maps to BOOLEAN."""
        schema = extractor.extract_from_string(TOGGLE_TEXTAREA_YAML)
        active = next(f for f in schema.sections[0].fields if f.field_id == "active")
        assert active.field_type == FieldType.BOOLEAN

    def test_textarea_mapped_to_text_area(self, extractor):
        """textarea type maps to TEXT_AREA."""
        schema = extractor.extract_from_string(TOGGLE_TEXTAREA_YAML)
        notes = next(f for f in schema.sections[0].fields if f.field_id == "notes")
        assert notes.field_type == FieldType.TEXT_AREA

    def test_multichoice_mapped_to_multi_select(self, extractor):
        """multichoice type maps to MULTI_SELECT."""
        schema = extractor.extract_from_string(TOGGLE_TEXTAREA_YAML)
        items = next(f for f in schema.sections[0].fields if f.field_id == "items")
        assert items.field_type == FieldType.MULTI_SELECT


class TestYamlExtractorNewFormat:
    """Tests for new YAML format with i18n and constraints."""

    def test_new_format_with_i18n(self, extractor):
        """New format with i18n title parses correctly."""
        schema = extractor.extract_from_string(NEW_YAML)
        assert isinstance(schema.title, dict)
        assert schema.title["en"] == "New Form"
        assert schema.title["es"] == "Formulario Nuevo"

    def test_section_i18n_title(self, extractor):
        """Section title can be an i18n dict."""
        schema = extractor.extract_from_string(NEW_YAML)
        title = schema.sections[0].title
        assert isinstance(title, dict)
        assert title["en"] == "Main Section"

    def test_constraints_block_parsed(self, extractor):
        """Constraints block produces FieldConstraints."""
        schema = extractor.extract_from_string(NEW_YAML)
        email = schema.sections[0].fields[0]
        assert email.constraints is not None
        assert email.constraints.pattern is not None

    def test_depends_on_parsed(self, extractor):
        """depends_on block produces DependencyRule."""
        schema = extractor.extract_from_string(NEW_YAML)
        age_field = schema.sections[0].fields[1]
        assert age_field.depends_on is not None
        assert age_field.depends_on.effect == "show"

    def test_depends_on_conditions(self, extractor):
        """DependencyRule has the correct conditions."""
        schema = extractor.extract_from_string(NEW_YAML)
        age_field = schema.sections[0].fields[1]
        assert len(age_field.depends_on.conditions) == 1
        assert age_field.depends_on.conditions[0].field_id == "show_age"

    def test_localized_field_label(self, extractor):
        """Field label can be an i18n dict."""
        schema = extractor.extract_from_string(NEW_YAML)
        email = schema.sections[0].fields[0]
        assert isinstance(email.label, dict)
        assert email.label["en"] == "Email"

    def test_new_section_id(self, extractor):
        """New format uses section_id instead of name."""
        schema = extractor.extract_from_string(NEW_YAML)
        assert schema.sections[0].section_id == "main"
