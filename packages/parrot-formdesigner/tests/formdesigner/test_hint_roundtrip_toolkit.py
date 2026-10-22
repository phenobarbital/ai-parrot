from __future__ import annotations

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.yaml import YamlExtractor
from parrot_formdesigner.tools.create_form import _SYSTEM_PROMPT
from parrot_formdesigner.tools.edit_toolkit import EditToolkit

YAML_FORM = """
form_id: demo
title: Demo
voice: {max_questions: 4}
llm_validation: {enabled: true, threshold: 0.8}
sections:
  - section_id: s
    fields:
      - field_id: name
        field_type: text
        label: Name
        hint: {en: First name, es: Nombre}
        llm_validation: false
      - field_id: plain
        field_type: text
        label: Plain
"""


def test_yaml_roundtrip_field_and_form_blocks():
    form = YamlExtractor().extract_from_string(YAML_FORM)
    field = form.sections[0].fields[0]
    assert field.hint == {"en": "First name", "es": "Nombre"}
    assert field.llm_validation is False
    assert form.voice.max_questions == 4
    assert form.llm_validation.threshold == 0.8
    plain = form.sections[0].fields[1]
    assert plain.hint is None and plain.llm_validation is None


def test_yaml_invalid_llm_validation_becomes_none():
    form = YamlExtractor().extract_from_string(YAML_FORM.replace("llm_validation: false", "llm_validation: maybe"))
    assert form.sections[0].fields[0].llm_validation is None


def test_create_form_prompt_mentions_hint_and_llm_validation():
    assert '"hint"' in _SYSTEM_PROMPT and '"llm_validation"' in _SYSTEM_PROMPT


async def test_update_field_sets_and_clears_hint():
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    section = FormSection(section_id="s", fields=[field])
    tk = EditToolkit(FormSchema(form_id="demo", title="Demo", tenant="acme", sections=[section]))
    res = await tk.update_field(
        str(section.section_uid), str(field.field_uid), {"hint": {"es": "Nombre"}, "llm_validation": True}
    )
    assert res["success"] and res["updated_field"]["hint"] == {"es": "Nombre"}
    assert res["updated_field"]["llm_validation"] is True
    res = await tk.update_field(str(section.section_uid), str(field.field_uid), {"hint": ""})
    assert res["updated_field"]["hint"] is None
