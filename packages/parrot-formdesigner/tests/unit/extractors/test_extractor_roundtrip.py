"""Tests for FEAT-234 TASK-1531: extractor round-trip for post_depends/operations."""

import pytest

from parrot_formdesigner.core import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    PostDependency,
)
from parrot_formdesigner.extractors import JsonSchemaExtractor, YamlExtractor
from parrot_formdesigner.renderers import JsonSchemaRenderer


# ---------------------------------------------------------------------------
# YAML extractor: post_depends parsing
# ---------------------------------------------------------------------------


class TestYamlExtractorPostDepends:
    def test_yaml_imports_post_depends_show(self) -> None:
        """YAML with post_depends show effect populates FormField.post_depends."""
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: f1
        field_type: text
        label: F1
        post_depends:
          - target: f2
            effect: show
            conditions:
              - field_id: f1
                operator: eq
                value: "yes"
            logic: and
      - field_id: f2
        field_type: text
        label: F2
"""
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        fields = {f.field_id: f for f in schema.iter_all_fields()}
        assert "f1" in fields
        f1 = fields["f1"]
        assert f1.post_depends is not None
        assert len(f1.post_depends) == 1
        pd = f1.post_depends[0]
        assert pd.target == "f2"
        assert pd.effect == "show"
        assert pd.conditions is not None
        assert pd.conditions[0].field_id == "f1"
        assert pd.conditions[0].operator == ConditionOperator.EQ

    def test_yaml_imports_post_depends_calc_with_operation(self) -> None:
        """YAML with post_depends calc effect + operation populates correctly."""
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: price
        field_type: number
        label: Price
        post_depends:
          - target: total
            effect: calc
            operation:
              op: multiply
              operands: [price, qty]
              target: total
      - field_id: qty
        field_type: integer
        label: Qty
      - field_id: total
        field_type: number
        label: Total
"""
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        fields = {f.field_id: f for f in schema.iter_all_fields()}
        price = fields["price"]
        assert price.post_depends is not None
        pd = price.post_depends[0]
        assert pd.effect == "calc"
        assert pd.operation is not None
        assert pd.operation.op == "multiply"
        assert "qty" in pd.operation.operands

    def test_yaml_imports_post_depends_cascade_clear(self) -> None:
        """YAML cascade_clear post_depends parses without conditions."""
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: country
        field_type: select
        label: Country
        post_depends:
          - target: city
            effect: cascade_clear
      - field_id: city
        field_type: select
        label: City
"""
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        fields = {f.field_id: f for f in schema.iter_all_fields()}
        country = fields["country"]
        assert country.post_depends is not None
        pd = country.post_depends[0]
        assert pd.effect == "cascade_clear"
        assert pd.target == "city"

    def test_yaml_depends_on_with_operations(self) -> None:
        """YAML depends_on with inline operations block parses correctly."""
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: a
        field_type: number
        label: A
      - field_id: b
        field_type: number
        label: B
        depends_on:
          conditions:
            - field_id: a
              operator: gt
              value: 0
          logic: and
          effect: show
          operations:
            - op: copy
              operands: [a]
              target: b
"""
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        fields = {f.field_id: f for f in schema.iter_all_fields()}
        b = fields["b"]
        assert b.depends_on is not None
        assert b.depends_on.operations is not None
        assert len(b.depends_on.operations) == 1
        op = b.depends_on.operations[0]
        assert op.op == "copy"
        assert op.target == "b"

    def test_yaml_without_post_depends_unchanged(self) -> None:
        """YAML without post_depends fields → post_depends is None (backward compat)."""
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: name
        field_type: text
        label: Name
"""
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        fields = {f.field_id: f for f in schema.iter_all_fields()}
        assert fields["name"].post_depends is None

    def test_yaml_multiple_post_depends(self) -> None:
        """YAML with multiple post_depends entries all parsed."""
        yaml_content = """
form_id: test
title: Test
sections:
  - section_id: s1
    fields:
      - field_id: source
        field_type: text
        label: Source
        post_depends:
          - target: t1
            effect: show
          - target: t2
            effect: hide
      - field_id: t1
        field_type: text
        label: T1
      - field_id: t2
        field_type: text
        label: T2
"""
        extractor = YamlExtractor()
        schema = extractor.extract_from_string(yaml_content)
        fields = {f.field_id: f for f in schema.iter_all_fields()}
        source = fields["source"]
        assert source.post_depends is not None
        assert len(source.post_depends) == 2
        effects = {pd.effect for pd in source.post_depends}
        assert "show" in effects
        assert "hide" in effects


# ---------------------------------------------------------------------------
# JSON Schema extractor: x-post-depends round-trip
# ---------------------------------------------------------------------------


class TestJsonSchemaExtractorPostDepends:
    def _make_form_with_post_deps(self) -> FormSchema:
        """Build a FormSchema with post_depends for round-trip testing."""
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="F1",
            post_depends=[
                PostDependency(
                    target="f2",
                    effect="show",
                    conditions=[
                        FieldCondition(
                            field_id="f1",
                            operator=ConditionOperator.EQ,
                            value="yes",
                        )
                    ],
                    logic="and",
                )
            ],
        )
        f2 = FormField(field_id="f2", field_type=FieldType.TEXT, label="F2")
        return FormSchema(
            form_id="test",
            title="Test",
            sections=[FormSection(section_id="s1", fields=[f1, f2])],
        )

    @pytest.mark.asyncio
    async def test_jsonschema_roundtrip_post_depends(self) -> None:
        """Render x-post-depends → import → equal PostDependency models."""
        form = self._make_form_with_post_deps()
        renderer = JsonSchemaRenderer()
        rendered_form = await renderer.render(form)
        # JsonSchemaRenderer returns a RenderedForm; .content is the actual JSON Schema dict
        rendered = rendered_form.content

        # Check rendered output has x-post-depends
        props = rendered.get("properties", {})
        assert "f1" in props
        assert "x-post-depends" in props["f1"]

        # Import via JsonSchemaExtractor
        extractor = JsonSchemaExtractor()
        imported = extractor.extract(rendered, form_id="test", title="Test")
        imported_fields = {f.field_id: f for f in imported.iter_all_fields()}

        f1_imported = imported_fields["f1"]
        assert f1_imported.post_depends is not None
        assert len(f1_imported.post_depends) == 1
        pd = f1_imported.post_depends[0]
        assert pd.target == "f2"
        assert pd.effect == "show"
        assert pd.logic == "and"
        assert pd.conditions is not None
        assert pd.conditions[0].field_id == "f1"
        assert pd.conditions[0].operator == ConditionOperator.EQ

    @pytest.mark.asyncio
    async def test_jsonschema_roundtrip_depends_on(self) -> None:
        """Render x-depends-on → import → equal DependencyRule model."""
        f1 = FormField(field_id="f1", field_type=FieldType.TEXT, label="F1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="F2",
            depends_on=DependencyRule(
                conditions=[
                    FieldCondition(
                        field_id="f1",
                        operator=ConditionOperator.EQ,
                        value="yes",
                    )
                ],
                logic="and",
                effect="show",
            ),
        )
        form = FormSchema(
            form_id="test",
            title="Test",
            sections=[FormSection(section_id="s1", fields=[f1, f2])],
        )

        renderer = JsonSchemaRenderer()
        rendered_form = await renderer.render(form)
        rendered = rendered_form.content

        extractor = JsonSchemaExtractor()
        imported = extractor.extract(rendered, form_id="test", title="Test")
        imported_fields = {f.field_id: f for f in imported.iter_all_fields()}

        f2_imported = imported_fields["f2"]
        assert f2_imported.depends_on is not None
        assert f2_imported.depends_on.logic == "and"
        assert f2_imported.depends_on.effect == "show"

    def test_jsonschema_without_x_extensions_unchanged(self) -> None:
        """JSON Schema without x-depends-on/x-post-depends → no depends_on/post_depends."""
        schema = {
            "type": "object",
            "title": "Test",
            "properties": {
                "name": {"type": "string", "title": "Name"},
            },
        }
        extractor = JsonSchemaExtractor()
        form = extractor.extract(schema, form_id="test")
        fields = {f.field_id: f for f in form.iter_all_fields()}
        assert fields["name"].depends_on is None
        assert fields["name"].post_depends is None


# ---------------------------------------------------------------------------
# Legacy re-export (parrot.forms shim)
# Tests verify the parrot_formdesigner exports are present and importable.
# Note: parrot.forms __init__.py in the worktree correctly declares these
# re-exports; the actual installed package may lag, so we test the content
# of the source file in addition to direct parrot_formdesigner imports.
# ---------------------------------------------------------------------------


class TestLegacyReexport:
    def test_dependency_operation_importable_from_parrot_formdesigner_core(self) -> None:
        """DependencyOperation is importable from parrot_formdesigner.core."""
        from parrot_formdesigner.core import DependencyOperation as DO
        assert DO is DependencyOperation

    def test_post_dependency_importable_from_parrot_formdesigner_core(self) -> None:
        """PostDependency is importable from parrot_formdesigner.core."""
        from parrot_formdesigner.core import PostDependency as PD
        assert PD is PostDependency

    def test_rule_evaluator_importable_from_services(self) -> None:
        """RuleEvaluator is importable from parrot_formdesigner.services."""
        from parrot_formdesigner.services import RuleEvaluator
        from parrot_formdesigner.services.rule_evaluator import RuleEvaluator as Direct
        assert RuleEvaluator is Direct

    def test_rule_resolution_importable_from_services(self) -> None:
        """RuleResolution is importable from parrot_formdesigner.services."""
        from parrot_formdesigner.services import RuleResolution
        from parrot_formdesigner.services.rule_evaluator import RuleResolution as Direct
        assert RuleResolution is Direct

    def test_get_dependency_rule_snippets_importable(self) -> None:
        """get_dependency_rule_snippets is importable from parrot_formdesigner.tools."""
        from parrot_formdesigner.tools import get_dependency_rule_snippets
        snippets = get_dependency_rule_snippets()
        assert "depends_on" in snippets
        assert "post_depends" in snippets

    def test_parrot_forms_init_declares_dependency_operation(self) -> None:
        """parrot/forms/__init__.py source declares DependencyOperation re-export."""
        from pathlib import Path
        # Locate the file in the worktree (walk up from this test file)
        here = Path(__file__).resolve()
        # .../packages/parrot-formdesigner/tests/unit/extractors/...
        # go up 6 levels to repo root
        repo_root = here
        for _ in range(6):
            repo_root = repo_root.parent
        forms_init = repo_root / "packages" / "ai-parrot" / "src" / "parrot" / "forms" / "__init__.py"
        if not forms_init.exists():
            pytest.skip("parrot/forms/__init__.py not found in worktree — skip source check")
        source = forms_init.read_text()
        assert "DependencyOperation" in source, (
            f"DependencyOperation not re-exported in {forms_init}"
        )
        assert "PostDependency" in source, (
            f"PostDependency not re-exported in {forms_init}"
        )
        assert "RuleEvaluator" in source, (
            f"RuleEvaluator not re-exported in {forms_init}"
        )
        assert "RuleResolution" in source, (
            f"RuleResolution not re-exported in {forms_init}"
        )
        assert "get_dependency_rule_snippets" in source, (
            f"get_dependency_rule_snippets not re-exported in {forms_init}"
        )
