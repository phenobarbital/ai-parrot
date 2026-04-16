"""
Tests for FEAT-102: Multi-Tab Infographic Block Models & Enums.

TASK-659: Infographic Block Models & Enums
"""
import pytest
from parrot.models.infographic import (
    BlockType,
    BulletListBlock,
    BulletListStyle,
    TableBlock,
    TableStyle,
    ColumnDef,
    AccordionBlock,
    AccordionItem,
    ChecklistBlock,
    ChecklistItem,
    TabViewBlock,
    TabPane,
    InfographicBlock,
    InfographicResponse,
    SummaryBlock,
    TitleBlock,
)


class TestBlockTypeEnum:
    """Tests for the BlockType enum."""

    def test_new_values_exist(self):
        """New enum values should be present."""
        assert BlockType.ACCORDION == "accordion"
        assert BlockType.CHECKLIST == "checklist"
        assert BlockType.TAB_VIEW == "tab_view"

    def test_total_count(self):
        """BlockType should have 15 values (12 original + 3 new)."""
        assert len(BlockType) == 15

    def test_existing_values_unchanged(self):
        """All original enum values should still exist."""
        assert BlockType.TITLE == "title"
        assert BlockType.HERO_CARD == "hero_card"
        assert BlockType.SUMMARY == "summary"
        assert BlockType.CHART == "chart"
        assert BlockType.BULLET_LIST == "bullet_list"
        assert BlockType.TABLE == "table"
        assert BlockType.IMAGE == "image"
        assert BlockType.QUOTE == "quote"
        assert BlockType.CALLOUT == "callout"
        assert BlockType.DIVIDER == "divider"
        assert BlockType.TIMELINE == "timeline"
        assert BlockType.PROGRESS == "progress"


class TestBulletListBlockExtended:
    """Tests for extended BulletListBlock fields."""

    def test_backward_compat(self):
        """Existing JSON without new fields should still validate."""
        b = BulletListBlock(items=["a", "b"])
        assert b.color is None
        assert b.columns is None
        assert b.style is None
        assert b.ordered is False

    def test_with_new_fields(self):
        """BulletListBlock should accept new styling fields."""
        b = BulletListBlock(
            items=["a"], color="#534AB7", columns=2, style=BulletListStyle.TITLED
        )
        assert b.color == "#534AB7"
        assert b.columns == 2
        assert b.style == BulletListStyle.TITLED

    def test_columns_range_validation(self):
        """Columns should be between 1 and 4."""
        b = BulletListBlock(items=["a"], columns=4)
        assert b.columns == 4
        with pytest.raises(Exception):
            BulletListBlock(items=["a"], columns=5)

    def test_bullet_list_style_values(self):
        """BulletListStyle enum should have expected values."""
        assert BulletListStyle.DEFAULT == "default"
        assert BulletListStyle.TITLED == "titled"
        assert BulletListStyle.COMPACT == "compact"


class TestTableBlockRefactored:
    """Tests for refactored TableBlock."""

    def test_backward_compat_string_columns(self):
        """Existing TableBlock with string columns should validate."""
        t = TableBlock(columns=["A", "B"], rows=[["1", "2"]])
        assert t.style is None
        assert t.responsive is True
        assert t.caption is None

    def test_column_def_columns(self):
        """TableBlock should accept ColumnDef columns."""
        t = TableBlock(
            columns=[ColumnDef(header="A", width="200px", align="center")],
            rows=[["1"]],
            style=TableStyle.STRIPED,
        )
        assert t.columns[0].header == "A"
        assert t.columns[0].width == "200px"
        assert t.columns[0].align == "center"
        assert t.style == TableStyle.STRIPED

    def test_dict_normalization_still_works(self):
        """Existing _normalize_table_data handles dict columns."""
        t = TableBlock.model_validate({
            "type": "table",
            "columns": [{"key": "a", "label": "Col A"}],
            "rows": [{"a": "val"}],
        })
        assert t.columns == ["Col A"]
        assert t.rows == [["val"]]

    def test_table_style_enum_values(self):
        """TableStyle enum should have expected values."""
        assert TableStyle.DEFAULT == "default"
        assert TableStyle.STRIPED == "striped"
        assert TableStyle.BORDERED == "bordered"
        assert TableStyle.COMPACT == "compact"
        assert TableStyle.COMPARISON == "comparison"

    def test_column_def_with_color(self):
        """ColumnDef should support color field."""
        col = ColumnDef(header="Revenue", color="#534AB7")
        assert col.color == "#534AB7"
        assert col.align is None

    def test_responsive_default(self):
        """responsive should default to True."""
        t = TableBlock(columns=["A"], rows=[["1"]])
        assert t.responsive is True

    def test_caption_field(self):
        """TableBlock should accept a caption field."""
        t = TableBlock(columns=["A"], rows=[["1"]], caption="Table 1: Summary")
        assert t.caption == "Table 1: Summary"


class TestAccordionBlock:
    """Tests for AccordionBlock and AccordionItem."""

    def test_with_content_blocks(self):
        """AccordionItem should accept content_blocks."""
        a = AccordionBlock(items=[
            AccordionItem(
                title="Phase 1",
                content_blocks=[BulletListBlock(items=["item"])],
            ),
        ])
        assert len(a.items) == 1
        assert len(a.items[0].content_blocks) == 1

    def test_with_html_content(self):
        """AccordionItem should accept html_content."""
        a = AccordionBlock(items=[
            AccordionItem(title="X", html_content="<p>Hello</p>"),
        ])
        assert a.items[0].html_content == "<p>Hello</p>"

    def test_item_fields(self):
        """AccordionItem should support all optional fields."""
        item = AccordionItem(
            title="Phase 1",
            subtitle="Overview",
            badge="Weeks 1-2",
            badge_color="#e8e4f8",
            number=1,
            number_color="#534AB7",
            expanded=True,
        )
        assert item.subtitle == "Overview"
        assert item.badge == "Weeks 1-2"
        assert item.number == 1
        assert item.expanded is True

    def test_allow_multiple_default(self):
        """allow_multiple should default to True."""
        a = AccordionBlock(items=[AccordionItem(title="X")])
        assert a.allow_multiple is True

    def test_empty_content_blocks_default(self):
        """content_blocks should default to empty list."""
        item = AccordionItem(title="X")
        assert item.content_blocks == []
        assert item.html_content is None
        assert item.expanded is False


class TestChecklistBlock:
    """Tests for ChecklistBlock and ChecklistItem."""

    def test_basic(self):
        """ChecklistBlock should validate with mixed checked/unchecked items."""
        c = ChecklistBlock(items=[
            ChecklistItem(text="Done", checked=True),
            ChecklistItem(text="Pending"),
        ])
        assert c.items[0].checked is True
        assert c.items[1].checked is False

    def test_with_description(self):
        """ChecklistItem should support optional description."""
        item = ChecklistItem(text="Security review", description="OWASP top 10")
        assert item.description == "OWASP top 10"

    def test_style_variants(self):
        """ChecklistBlock should accept style variants."""
        for style in ("default", "acceptance", "todo", "compact"):
            c = ChecklistBlock(items=[ChecklistItem(text="x")], style=style)
            assert c.style == style

    def test_default_style(self):
        """ChecklistBlock style should default to 'default'."""
        c = ChecklistBlock(items=[ChecklistItem(text="x")])
        assert c.style == "default"


class TestTabViewBlock:
    """Tests for TabViewBlock and TabPane."""

    def test_valid(self):
        """TabViewBlock with 2+ tabs should validate."""
        tv = TabViewBlock(tabs=[
            TabPane(id="a", label="Tab A", blocks=[SummaryBlock(content="hi")]),
            TabPane(id="b", label="Tab B", blocks=[]),
        ])
        assert len(tv.tabs) == 2

    def test_rejects_single_tab(self):
        """TabViewBlock should reject fewer than 2 tabs."""
        with pytest.raises(Exception):
            TabViewBlock(tabs=[TabPane(id="a", label="A", blocks=[])])

    def test_active_tab_field(self):
        """TabViewBlock should accept active_tab field."""
        tv = TabViewBlock(
            tabs=[
                TabPane(id="a", label="A", blocks=[]),
                TabPane(id="b", label="B", blocks=[]),
            ],
            active_tab="b",
        )
        assert tv.active_tab == "b"

    def test_style_variants(self):
        """TabViewBlock should accept style variants."""
        for style in ("pills", "underline", "boxed"):
            tv = TabViewBlock(
                tabs=[
                    TabPane(id="a", label="A", blocks=[]),
                    TabPane(id="b", label="B", blocks=[]),
                ],
                style=style,
            )
            assert tv.style == style

    def test_default_style(self):
        """TabViewBlock style should default to 'pills'."""
        tv = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[]),
            TabPane(id="b", label="B", blocks=[]),
        ])
        assert tv.style == "pills"

    def test_tab_with_icon(self):
        """TabPane should support icon field."""
        tab = TabPane(id="overview", label="Overview", icon="📊", blocks=[])
        assert tab.icon == "📊"

    def test_roundtrip_json(self):
        """TabViewBlock should round-trip through JSON."""
        tv = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[
                AccordionBlock(items=[AccordionItem(title="X")]),
            ]),
            TabPane(id="b", label="B", blocks=[]),
        ])
        data = tv.model_dump()
        restored = TabViewBlock.model_validate(data)
        assert restored.tabs[0].blocks[0]["type"] == "accordion"

    def test_three_tabs(self):
        """TabViewBlock should accept 3+ tabs."""
        tv = TabViewBlock(tabs=[
            TabPane(id="a", label="A", blocks=[]),
            TabPane(id="b", label="B", blocks=[]),
            TabPane(id="c", label="C", blocks=[]),
        ])
        assert len(tv.tabs) == 3


class TestInfographicResponseWithNewBlocks:
    """Integration tests for InfographicResponse with new block types."""

    def test_multi_tab_response(self):
        """InfographicResponse should accept TabViewBlock in blocks."""
        r = InfographicResponse(
            template="multi_tab",
            blocks=[
                TitleBlock(title="Test"),
                TabViewBlock(tabs=[
                    TabPane(id="a", label="A", blocks=[
                        ChecklistBlock(items=[ChecklistItem(text="x")]),
                    ]),
                    TabPane(id="b", label="B", blocks=[]),
                ]),
            ],
        )
        assert r.blocks[1].type == "tab_view"

    def test_normalise_payload_tab_view(self):
        """_normalise_payload should handle tab_view blocks."""
        data = {
            "blocks": [
                {
                    "type": "tab_view",
                    "tabs": [
                        {"id": "a", "label": "A", "blocks": []},
                        {"id": "b", "label": "B", "blocks": []},
                    ],
                }
            ]
        }
        r = InfographicResponse.model_validate(data)
        assert r.blocks[0].type == "tab_view"
        assert len(r.blocks[0].tabs) == 2

    def test_normalise_payload_accordion(self):
        """_normalise_payload should handle accordion blocks."""
        data = {
            "blocks": [
                {
                    "type": "accordion",
                    "items": [{"title": "Section 1"}],
                }
            ]
        }
        r = InfographicResponse.model_validate(data)
        assert r.blocks[0].type == "accordion"
        assert len(r.blocks[0].items) == 1

    def test_existing_blocks_still_work(self):
        """Existing block types should still work without changes."""
        from parrot.models.infographic import (
            HeroCardBlock, ChartBlock, ChartDataSeries, ChartType,
            BulletListBlock, TableBlock, DividerBlock,
        )
        r = InfographicResponse(
            template="basic",
            blocks=[
                TitleBlock(title="Test"),
                SummaryBlock(content="Summary"),
                BulletListBlock(items=["A", "B"]),
                TableBlock(columns=["X", "Y"], rows=[["1", "2"]]),
                DividerBlock(),
            ],
        )
        assert len(r.blocks) == 5
        assert r.blocks[0].type == "title"
