"""Unit tests for the CardSpec renderer."""
import json

import pytest


class TestRenderTextSection:
    def test_simple_text(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="Hello world")])
        card = render(spec)
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.5"
        assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
        body = card["body"]
        assert len(body) == 1
        assert body[0]["type"] == "TextBlock"
        assert body[0]["text"] == "Hello world"
        assert body[0]["wrap"] is True

    def test_title_role(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="Title", role="title")])
        card = render(spec)
        tb = card["body"][0]
        assert tb["size"] == "Large"
        assert tb["weight"] == "Bolder"

    def test_monospace_role(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="code", role="monospace")])
        card = render(spec)
        assert card["body"][0]["fontType"] == "Monospace"


class TestRenderTableSection:
    def test_native_table(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TableSection(
            columns=["Name", "Age"],
            rows=[["Alice", "30"], ["Bob", "25"]],
        )])
        card = render(spec)
        tables = [e for e in card["body"] if e["type"] == "Table"]
        assert len(tables) == 1
        table = tables[0]
        assert table["firstRowAsHeader"] is True
        assert len(table["columns"]) == 2
        # Header row + 2 data rows
        assert len(table["rows"]) == 3

    def test_truncation_note(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TableSection(
            columns=["X"],
            rows=[[str(i)] for i in range(30)],
            total_rows=50,
            max_display_rows=20,
        )])
        card = render(spec)
        texts = [e for e in card["body"] if e["type"] == "TextBlock"]
        assert any("50" in t["text"] for t in texts)

    def test_ragged_rows_normalized(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TableSection(
            columns=["a", "b", "c"],
            rows=[["1"], ["1", "2", "3", "4"]],
        )])
        card = render(spec)
        table = [e for e in card["body"] if e["type"] == "Table"][0]
        for row in table["rows"]:
            assert len(row["cells"]) == 3


class TestRenderMetricsSection:
    def test_factset_output(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import MetricEntry, MetricsSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[MetricsSection(metrics=[
            MetricEntry(label="Rev", value="$1M", delta="+12%"),
        ])])
        card = render(spec)
        factsets = [e for e in card["body"] if e["type"] == "FactSet"]
        assert len(factsets) == 1
        assert factsets[0]["facts"][0]["title"] == "Rev"
        assert "+12%" in factsets[0]["facts"][0]["value"]


class TestRenderDetailSection:
    def test_factset_output(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import DetailField, DetailSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[DetailSection(fields=[
            DetailField(label="Status", value="Active"),
        ])])
        card = render(spec)
        factsets = [e for e in card["body"] if e["type"] == "FactSet"]
        assert factsets[0]["facts"][0]["value"] == "Active"


class TestRenderImageSection:
    def test_url_image(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import ImageEntry, ImageSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[ImageSection(images=[
            ImageEntry(url="https://example.com/chart.png", alt_text="chart"),
        ])])
        card = render(spec)
        images = [e for e in card["body"] if e["type"] == "Image"]
        assert len(images) == 1
        assert images[0]["url"] == "https://example.com/chart.png"
        assert images[0]["altText"] == "chart"


class TestRenderCodeSection:
    def test_monospace_block(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import CodeSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[CodeSection(
            code="print('hi')", language="python", label="Code (python):",
        )])
        card = render(spec)
        texts = [e for e in card["body"] if e["type"] == "TextBlock"]
        label = [t for t in texts if "Code" in t["text"]]
        code = [t for t in texts if t.get("fontType") == "Monospace"]
        assert len(label) == 1
        assert len(code) == 1
        assert code[0]["text"] == "print('hi')"


class TestRenderStatusSection:
    def test_colored_status(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import StatusSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[StatusSection(
            level="error", message="Failed", details="Timeout",
        )])
        card = render(spec)
        container = [e for e in card["body"] if e["type"] == "Container"][0]
        msg = container["items"][0]
        assert msg["color"] == "Attention"
        assert msg["text"] == "Failed"


class TestRenderFormSection:
    def test_input_elements(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(field_id="name", field_type="text", label="Name", required=True),
            FormFieldSpec(field_id="age", field_type="number", label="Age"),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"].startswith("Input.")]
        assert len(inputs) == 2
        assert inputs[0]["type"] == "Input.Text"
        assert inputs[0]["id"] == "name"
        assert inputs[0]["isRequired"] is True
        assert inputs[1]["type"] == "Input.Number"


class TestRenderToggleSection:
    def test_explicit_toggle(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import ToggleSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import ToggleGroup
        spec = CardSpec(sections=[ToggleSection(toggle=ToggleGroup(
            content=[TextBlock(text="hidden content")],
            group_id="detail",
        ))])
        card = render(spec)
        containers = [e for e in card["body"] if e["type"] == "Container"]
        assert any(c.get("id") == "detail_content" for c in containers)
        assert any(c.get("isVisible") is False for c in containers)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 1


class TestRenderRawSection:
    def test_passthrough(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import RawElementsSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[RawElementsSection(
            elements=[TextBlock(text="raw element", weight="Bolder")],
        )])
        card = render(spec)
        assert card["body"][0]["type"] == "TextBlock"
        assert card["body"][0]["weight"] == "Bolder"


class TestRenderActions:
    def test_submit_and_openurl(self):
        from parrot.outputs.cards.actions import ActionOpenUrl, ActionSubmit
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(actions=[
            ActionSubmit(title="OK", data={"x": 1}),
            ActionOpenUrl(title="Docs", url="https://docs.example.com"),
        ])
        card = render(spec)
        assert len(card["actions"]) == 2
        assert card["actions"][0]["type"] == "Action.Submit"
        assert card["actions"][1]["type"] == "Action.OpenUrl"


class TestRenderCardSpec:
    def test_title_and_summary(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(title="Report", summary="Q2 data")
        card = render(spec)
        texts = [e for e in card["body"] if e["type"] == "TextBlock"]
        titles = [t for t in texts if t.get("weight") == "Bolder"]
        assert any("Report" in t["text"] for t in titles)
        assert any("Q2 data" in t["text"] for t in texts)

    def test_omits_none_values(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[TextSection(text="clean")])
        card = render(spec)
        tb = card["body"][0]
        assert "color" not in tb
        assert "fontType" not in tb
        assert "maxLines" not in tb
        assert "id" not in tb

    def test_size_guard(self):
        from parrot.outputs.cards.renderer import CardRenderError, render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        huge = TextSection(text="x" * 30_000)
        spec = CardSpec(sections=[huge])
        with pytest.raises(CardRenderError):
            render(spec, max_card_bytes=1_000)


class TestRenderText:
    def test_fallback(self):
        from parrot.outputs.cards.renderer import render_text
        from parrot.outputs.cards.sections import MetricEntry, MetricsSection, TextSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(
            title="Report",
            sections=[
                TextSection(text="Overview"),
                MetricsSection(metrics=[MetricEntry(label="Rev", value="$1M")]),
            ],
        )
        text = render_text(spec)
        assert "Report" in text
        assert "Overview" in text
        assert "Rev" in text
        assert "$1M" in text
