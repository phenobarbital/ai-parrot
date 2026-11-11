"""Unit tests for the CardSpec renderer."""
import json

import pytest


class TestRenderTextSection:
    def test_simple_text(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION, CardSpec
        spec = CardSpec(sections=[TextSection(text="Hello world")])
        card = render(spec)
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == DEFAULT_ADAPTIVE_CARD_VERSION
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
        spec = CardSpec(version="1.5", sections=[TableSection(
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

    def test_columnset_table_below_1_5(self):
        """AC <= 1.4 has no native Table: header and rows become ColumnSets."""
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(version="1.4", sections=[TableSection(
            columns=["Name", "Age"],
            rows=[["Alice", "30"], ["Bob", "25"]],
        )])
        card = render(spec)
        assert not [e for e in card["body"] if e["type"] == "Table"]
        column_sets = [e for e in card["body"] if e["type"] == "ColumnSet"]
        # Header row + 2 data rows
        assert len(column_sets) == 3
        header = column_sets[0]
        assert header["separator"] is True
        assert [c["items"][0]["text"] for c in header["columns"]] == ["Name", "Age"]
        assert all(c["items"][0]["weight"] == "Bolder" for c in header["columns"])
        assert [c["items"][0]["text"] for c in column_sets[1]["columns"]] == ["Alice", "30"]

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
        spec = CardSpec(version="1.5", sections=[TableSection(
            columns=["a", "b", "c"],
            rows=[["1"], ["1", "2", "3", "4"]],
        )])
        card = render(spec)
        table = [e for e in card["body"] if e["type"] == "Table"][0]
        for row in table["rows"]:
            assert len(row["cells"]) == 3

    def test_ragged_rows_normalized_below_1_5(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(version="1.4", sections=[TableSection(
            columns=["a", "b", "c"],
            rows=[["1"], ["1", "2", "3", "4"]],
        )])
        card = render(spec)
        column_sets = [e for e in card["body"] if e["type"] == "ColumnSet"]
        assert len(column_sets) == 3
        for column_set in column_sets:
            assert len(column_set["columns"]) == 3


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


class TestRenderFormFieldTypes:
    def test_boolean_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(field_id="agree", field_type="boolean", label="Agree", description="I agree to terms"),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"] == "Input.Toggle"]
        assert len(inputs) == 1
        assert inputs[0]["id"] == "agree"

    def test_date_input(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(field_id="dob", field_type="date", label="Date of Birth"),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"] == "Input.Date"]
        assert len(inputs) == 1

    def test_time_input(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(field_id="start", field_type="time", label="Start Time"),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"] == "Input.Time"]
        assert len(inputs) == 1

    def test_select_choiceset(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.inputs import InputChoice
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(
                field_id="role", field_type="select", label="Role",
                options=[InputChoice(title="Admin", value="admin"),
                         InputChoice(title="User", value="user")],
            ),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"] == "Input.ChoiceSet"]
        assert len(inputs) == 1
        assert inputs[0]["isMultiSelect"] is False

    def test_multi_select_choiceset(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.inputs import InputChoice
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(
                field_id="tags", field_type="multi_select", label="Tags",
                options=[InputChoice(title="A", value="a")],
            ),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"] == "Input.ChoiceSet"]
        assert len(inputs) == 1
        assert inputs[0]["isMultiSelect"] is True

    def test_email_style(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import FormFieldSpec, FormSection
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[FormSection(fields=[
            FormFieldSpec(field_id="email", field_type="email", label="Email"),
        ])])
        card = render(spec)
        inputs = [e for e in card["body"] if e["type"] == "Input.Text"]
        assert len(inputs) == 1
        assert inputs[0]["style"] == "Email"


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


def _wide_table(n_rows: int, n_cols: int):
    from parrot.outputs.cards.sections import TableSection
    return TableSection(
        columns=[f"column_{c}" for c in range(n_cols)],
        rows=[[f"value {r}-{c} 12,345.67" for c in range(n_cols)] for r in range(n_rows)],
    )


def _card_bytes(card: dict) -> int:
    return len(json.dumps(card).encode("utf-8"))


def _body_texts(card: dict) -> list[str]:
    return [b.get("text", "") for b in card["body"] if b.get("type") == "TextBlock"]


class TestRenderFit:
    """``render(fit=True)`` shrinks an oversize card instead of raising."""

    @pytest.mark.parametrize("version", ["1.4", "1.5"])
    def test_large_table_is_shrunk_to_fit(self, version):
        from parrot.outputs.cards.renderer import CardRenderError, render
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(sections=[_wide_table(50, 8)], auto_collapse=AutoCollapsePolicy(), version=version)
        with pytest.raises(CardRenderError):
            render(spec)
        card = render(spec, fit=True)
        assert _card_bytes(card) <= 28_000
        texts = _body_texts(card)
        assert "Showing 15 of 50" in texts
        assert any("shortened" in t for t in texts)

    def test_fitting_card_is_unchanged(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(sections=[_wide_table(5, 3)], auto_collapse=AutoCollapsePolicy())
        assert render(spec, fit=True) == render(spec)

    def test_rows_halved_until_fit(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        spec = CardSpec(sections=[_wide_table(50, 25)])
        card = render(spec, fit=True)
        assert _card_bytes(card) <= 28_000
        shown = [t for t in _body_texts(card) if t.startswith("Showing ")]
        assert len(shown) == 1
        assert shown[0].endswith(" of 50")

    def test_total_rows_preserved_in_footer(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        table = _wide_table(50, 10).model_copy(update={"total_rows": 1_000})
        card = render(CardSpec(sections=[table]), max_card_bytes=20_000, fit=True)
        assert any(t.startswith("Showing ") and t.endswith(" of 1000") for t in _body_texts(card))

    def test_inline_image_dropped_but_table_kept(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import ImageEntry, ImageSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        chart = ImageSection(images=[
            ImageEntry(url="data:image/png;base64," + "A" * 60_000),
            ImageEntry(url="https://cdn.example/fig.png"),
        ])
        spec = CardSpec(sections=[_wide_table(30, 6), chart], auto_collapse=AutoCollapsePolicy())
        card = render(spec, fit=True)
        assert _card_bytes(card) <= 28_000
        urls = [b["url"] for b in card["body"] if b.get("type") == "Image"]
        assert urls == ["https://cdn.example/fig.png"]
        texts = _body_texts(card)
        assert "Showing 15 of 30" in texts
        assert any("1 embedded image omitted" in t for t in texts)

    def test_long_text_is_truncated(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(sections=[TextSection(text="lorem ipsum " * 5_000)], auto_collapse=AutoCollapsePolicy())
        card = render(spec, fit=True)
        assert _card_bytes(card) <= 28_000
        assert card["body"][0]["text"].endswith(" …")

    def test_original_spec_not_mutated(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.spec import CardSpec
        table = _wide_table(50, 8)
        spec = CardSpec(sections=[table])
        render(spec, fit=True)
        assert len(spec.sections) == 1
        assert len(spec.sections[0].rows) == 50
        assert spec.sections[0].max_display_rows == 50

    def test_raises_when_nothing_can_shrink(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.renderer import CardRenderError, render
        from parrot.outputs.cards.sections import RawElementsSection
        from parrot.outputs.cards.spec import CardSpec
        raw = RawElementsSection(elements=[TextBlock(text="x" * 40_000)])
        with pytest.raises(CardRenderError):
            render(CardSpec(sections=[raw]), fit=True)


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
