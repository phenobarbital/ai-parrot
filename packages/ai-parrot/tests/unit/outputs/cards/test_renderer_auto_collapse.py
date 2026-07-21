# packages/ai-parrot/tests/unit/outputs/cards/test_renderer_auto_collapse.py
"""Unit tests for auto-collapse behavior in the renderer."""
import pytest


class TestAutoCollapseTable:
    def test_table_exceeding_threshold_gets_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TableSection(
                columns=["X"],
                rows=[[str(i)] for i in range(20)],
                max_display_rows=20,
            )],
            auto_collapse=AutoCollapsePolicy(table_row_threshold=5),
        )
        card = render(spec)
        # Should have a toggle action for the overflow
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) >= 1
        # Should have a hidden container with the overflow rows
        containers = [e for e in card["body"] if e.get("type") == "Container"
                     and e.get("isVisible") is False]
        assert len(containers) >= 1

    def test_table_under_threshold_no_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TableSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TableSection(columns=["X"], rows=[["1"], ["2"]])],
            auto_collapse=AutoCollapsePolicy(table_row_threshold=5),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 0


class TestAutoCollapseText:
    def test_long_text_gets_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TextSection(text="word " * 200)],
            auto_collapse=AutoCollapsePolicy(text_char_threshold=100),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) >= 1

    def test_short_text_no_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TextSection(text="short")],
            auto_collapse=AutoCollapsePolicy(text_char_threshold=100),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 0


class TestAutoCollapseCode:
    def test_long_code_gets_toggle(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import CodeSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        code = "\n".join(f"line {i}" for i in range(20))
        spec = CardSpec(
            sections=[CodeSection(code=code)],
            auto_collapse=AutoCollapsePolicy(code_line_threshold=5),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) >= 1


class TestAutoCollapseDisabled:
    def test_disabled_no_toggles(self):
        from parrot.outputs.cards.renderer import render
        from parrot.outputs.cards.sections import TextSection
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.toggle import AutoCollapsePolicy
        spec = CardSpec(
            sections=[TextSection(text="word " * 200)],
            auto_collapse=AutoCollapsePolicy(enabled=False),
        )
        card = render(spec)
        toggle_actions = [a for a in card.get("actions", [])
                         if a["type"] == "Action.ToggleVisibility"]
        assert len(toggle_actions) == 0
