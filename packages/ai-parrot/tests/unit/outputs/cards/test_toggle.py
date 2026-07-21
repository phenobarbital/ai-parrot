# tests/unit/outputs/cards/test_toggle.py
"""Unit tests for toggle models."""


class TestToggleGroup:
    def test_defaults(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.toggle import ToggleGroup
        tg = ToggleGroup(content=[TextBlock(text="hidden")])
        assert tg.initially_visible is False
        assert tg.label_collapsed == "Show details"
        assert tg.label_expanded == "Hide details"
        assert tg.group_id is None

    def test_custom(self):
        from parrot.outputs.cards.elements import TextBlock
        from parrot.outputs.cards.toggle import ToggleGroup
        tg = ToggleGroup(
            content=[TextBlock(text="data")],
            label_collapsed="Show 15 more rows",
            label_expanded="Hide rows",
            initially_visible=True,
            group_id="table_overflow",
        )
        assert tg.group_id == "table_overflow"
        assert tg.initially_visible is True


class TestAutoCollapsePolicy:
    def test_defaults(self):
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        p = AutoCollapsePolicy()
        assert p.enabled is True
        assert p.table_row_threshold == 5
        assert p.text_char_threshold == 500
        assert p.code_line_threshold == 10
        assert p.image_count_threshold == 2

    def test_disabled(self):
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        p = AutoCollapsePolicy(enabled=False)
        assert p.enabled is False
