# tests/unit/outputs/cards/test_actions.py
"""Unit tests for AC action models."""
import pytest
from pydantic import ValidationError


class TestActionSubmit:
    def test_minimal(self):
        from parrot.outputs.cards.actions import ActionSubmit
        a = ActionSubmit(title="Submit")
        assert a.action_type == "Action.Submit"
        assert a.data == {}

    def test_with_data_and_style(self):
        from parrot.outputs.cards.actions import ActionSubmit
        a = ActionSubmit(
            title="Cancel",
            style="destructive",
            data={"_action": "cancel"},
            associated_inputs="None",
        )
        assert a.style == "destructive"
        assert a.associated_inputs == "None"


class TestActionOpenUrl:
    def test_minimal(self):
        from parrot.outputs.cards.actions import ActionOpenUrl
        a = ActionOpenUrl(title="Open", url="https://example.com")
        assert a.action_type == "Action.OpenUrl"
        assert a.url == "https://example.com"


class TestActionToggleVisibility:
    def test_toggle_targets(self):
        from parrot.outputs.cards.actions import ActionToggleVisibility, TargetElement
        a = ActionToggleVisibility(
            title="Show details",
            target_elements=[
                TargetElement(element_id="detail_1"),
                TargetElement(element_id="detail_2", is_visible=True),
            ],
        )
        assert a.action_type == "Action.ToggleVisibility"
        assert len(a.target_elements) == 2
        assert a.target_elements[0].is_visible is None  # toggle mode
        assert a.target_elements[1].is_visible is True   # explicit set


class TestActionShowCard:
    @pytest.mark.skip(
        reason="CardSpec/TextSection land in Task 3 (spec.py/sections.py); "
        "deferred per Task 2 brief."
    )
    def test_inline_card(self):
        from parrot.outputs.cards.actions import ActionShowCard
        from parrot.outputs.cards.spec import CardSpec
        from parrot.outputs.cards.sections import TextSection
        inner = CardSpec(
            title="Details",
            sections=[TextSection(text="More info here")],
        )
        a = ActionShowCard(title="Details", card=inner)
        assert a.action_type == "Action.ShowCard"
        assert a.card.title == "Details"
