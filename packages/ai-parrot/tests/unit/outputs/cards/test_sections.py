# tests/unit/outputs/cards/test_sections.py
"""Unit tests for section models and CardSpec."""


class TestTextSection:
    def test_defaults(self):
        from parrot.outputs.cards.sections import TextSection
        s = TextSection(text="hello")
        assert s.section_type == "text"
        assert s.role == "body"
        assert s.is_subtle is False


class TestTableSection:
    def test_structure(self):
        from parrot.outputs.cards.sections import TableSection
        s = TableSection(
            columns=["Name", "Age"],
            rows=[["Alice", "30"], ["Bob", "25"]],
            total_rows=100,
        )
        assert s.section_type == "table"
        assert len(s.rows) == 2
        assert s.max_display_rows == 20


class TestMetricsSection:
    def test_with_entries(self):
        from parrot.outputs.cards.sections import MetricsSection, MetricEntry
        s = MetricsSection(metrics=[
            MetricEntry(label="Rev", value="$1M", delta="+12%"),
        ])
        assert s.section_type == "metrics"
        assert s.metrics[0].delta == "+12%"


class TestDetailSection:
    def test_with_fields(self):
        from parrot.outputs.cards.sections import DetailSection, DetailField
        s = DetailSection(fields=[DetailField(label="Status", value="Active")])
        assert s.section_type == "detail"


class TestImageSection:
    def test_with_entries(self):
        from parrot.outputs.cards.sections import ImageSection, ImageEntry
        s = ImageSection(images=[
            ImageEntry(url="https://example.com/img.png", alt_text="chart"),
        ])
        assert s.section_type == "image"
        assert s.images[0].size == "Large"


class TestCodeSection:
    def test_with_language(self):
        from parrot.outputs.cards.sections import CodeSection
        s = CodeSection(code="print('hi')", language="python", label="Code (python):")
        assert s.section_type == "code"


class TestStatusSection:
    def test_defaults(self):
        from parrot.outputs.cards.sections import StatusSection
        s = StatusSection(message="All good")
        assert s.section_type == "status"
        assert s.level == "info"


class TestToggleSection:
    def test_wraps_toggle_group(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.sections import ToggleSection
        from parrot.outputs.cards.toggle import ToggleGroup
        tg = ToggleGroup(content=[TextBlock(text="hidden")])
        s = ToggleSection(toggle=tg)
        assert s.section_type == "toggle"


class TestFormSection:
    def test_with_fields(self):
        from parrot.outputs.cards.sections import FormSection, FormFieldSpec
        s = FormSection(fields=[
            FormFieldSpec(field_id="name", field_type="text", label="Name", required=True),
        ])
        assert s.section_type == "form"
        assert s.fields[0].required is True


class TestRawElementsSection:
    def test_passthrough(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.sections import RawElementsSection
        s = RawElementsSection(elements=[TextBlock(text="raw")])
        assert s.section_type == "raw"
        assert len(s.elements) == 1


class TestCardSpec:
    def test_minimal(self):
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec()
        assert spec.version == "1.5"
        assert spec.sections == []
        assert spec.actions == []
        assert spec.auto_collapse is None

    def test_full(self):
        from parrot.outputs.cards.actions import ActionSubmit
        from parrot.outputs.cards.sections import TableSection, TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            title="Report",
            summary="Q2 summary",
            sections=[
                TextSection(text="Overview"),
                TableSection(columns=["A"], rows=[["1"]]),
            ],
            actions=[ActionSubmit(title="OK")],
            auto_collapse=AutoCollapsePolicy(table_row_threshold=10),
        )
        assert spec.title == "Report"
        assert len(spec.sections) == 2
