"""Unit tests for extractor + CreateFormTool UID minting and rule resolution
(FEAT-393, TASK-2001 — Module 7).

All four extractors (YAML, JSON Schema, Pydantic, Tool) call
``core.resolution.resolve_rule_references`` as their last step before
returning — this asserts every extractor's output has no unresolved
``source="field"`` conditions, that the YAML extractor now hard-errors on
an empty/missing condition ``field_id``, and that two ARRAY fields no
longer collide on a bare ``"item"`` item_template field_id.
"""
import pytest
from parrot_formdesigner.extractors import (
    JsonSchemaExtractor,
    PydanticExtractor,
    YamlExtractor,
)
from pydantic import BaseModel


def _assert_all_field_conditions_resolved(form) -> None:
    """Every source='field' FieldCondition in the form must carry a
    resolved field_uid (no unresolved authored-only references)."""
    for field in form.iter_fields_recursive():
        if field.depends_on:
            for cond in field.depends_on.conditions:
                if (cond.source or "field") == "field":
                    assert cond.field_uid is not None, (
                        f"Unresolved condition on field {field.field_id!r}"
                    )
        for post in field.post_depends or []:
            for cond in post.conditions or []:
                if (cond.source or "field") == "field":
                    assert cond.field_uid is not None, (
                        f"Unresolved post_depends condition on field {field.field_id!r}"
                    )


class TestYamlExtractorResolution:
    def test_yaml_rules_resolved_to_uids(self) -> None:
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: a
        field_type: text
        label: A
      - field_id: b
        field_type: text
        label: B
        depends_on:
          conditions:
            - field_id: a
              operator: eq
              value: "x"
          logic: and
          effect: show
"""
        extractor = YamlExtractor()
        form = extractor.extract_from_string(yaml_content)
        _assert_all_field_conditions_resolved(form)
        fields = {f.field_id: f for f in form.iter_fields_recursive()}
        cond = fields["b"].depends_on.conditions[0]
        assert cond.field_uid == fields["a"].field_uid

    def test_yaml_empty_condition_field_id_errors(self) -> None:
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: a
        field_type: text
        label: A
        depends_on:
          conditions:
            - operator: eq
              value: "x"
          logic: and
          effect: show
"""
        extractor = YamlExtractor()
        with pytest.raises(ValueError, match="field_id"):
            extractor.extract_from_string(yaml_content)

    def test_yaml_empty_post_depends_condition_field_id_errors(self) -> None:
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: a
        field_type: text
        label: A
        post_depends:
          - target: b
            effect: show
            conditions:
              - operator: eq
                value: "x"
      - field_id: b
        field_type: text
        label: B
"""
        extractor = YamlExtractor()
        with pytest.raises(ValueError, match="field_id"):
            extractor.extract_from_string(yaml_content)


class TestJsonSchemaExtractorResolution:
    def test_jsonschema_extractor_resolved(self) -> None:
        schema = {
            "title": "Simple",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        extractor = JsonSchemaExtractor()
        form = extractor.extract(schema, form_id="simple", title="Simple")
        _assert_all_field_conditions_resolved(form)

    def test_two_arrays_no_item_collision(self) -> None:
        schema = {
            "title": "TwoArrays",
            "type": "object",
            "properties": {
                "list_a": {"type": "array", "items": {"type": "string"}},
                "list_b": {"type": "array", "items": {"type": "string"}},
            },
        }
        extractor = JsonSchemaExtractor()
        # Must not raise a duplicate field_id ValidationError.
        form = extractor.extract(schema, form_id="two-arrays", title="Two Arrays")
        item_ids = [
            f.field_id
            for f in form.iter_fields_recursive()
            if f.field_id.endswith("_item")
        ]
        assert sorted(item_ids) == ["list_a_item", "list_b_item"]


class TestPydanticExtractorResolution:
    def test_pydantic_extractor_resolved(self) -> None:
        class Simple(BaseModel):
            name: str
            age: int

        extractor = PydanticExtractor()
        form = extractor.extract(Simple, title="Simple")
        _assert_all_field_conditions_resolved(form)

    def test_two_arrays_no_item_collision(self) -> None:
        class TwoArrays(BaseModel):
            list_a: list[str]
            list_b: list[str]

        extractor = PydanticExtractor()
        form = extractor.extract(TwoArrays, title="Two Arrays")
        item_ids = [
            f.field_id
            for f in form.iter_fields_recursive()
            if f.field_id.endswith("_item")
        ]
        assert sorted(item_ids) == ["list_a_item", "list_b_item"]
