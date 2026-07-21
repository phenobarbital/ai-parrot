# tests/unit/outputs/cards/test_inputs.py
"""Unit tests for AC input element models."""
import pytest
from pydantic import ValidationError


class TestInputText:
    def test_minimal(self):
        from parrot.outputs.cards.inputs import InputText
        inp = InputText(id="name")
        assert inp.element_type == "Input.Text"
        assert inp.is_multiline is False
        assert inp.is_required is False

    def test_email_style(self):
        from parrot.outputs.cards.inputs import InputText
        inp = InputText(id="email", style="Email", is_required=True, label="Email")
        assert inp.style == "Email"
        assert inp.label == "Email"

    def test_multiline(self):
        from parrot.outputs.cards.inputs import InputText
        inp = InputText(id="notes", is_multiline=True, max_length=500)
        assert inp.is_multiline is True
        assert inp.max_length == 500


class TestInputNumber:
    def test_with_range(self):
        from parrot.outputs.cards.inputs import InputNumber
        inp = InputNumber(id="qty", min=1, max=100, value=5)
        assert inp.element_type == "Input.Number"
        assert inp.min == 1


class TestInputToggle:
    def test_defaults(self):
        from parrot.outputs.cards.inputs import InputToggle
        inp = InputToggle(id="agree", title="I agree")
        assert inp.element_type == "Input.Toggle"
        assert inp.value == "false"
        assert inp.value_on == "true"


class TestInputDate:
    def test_minimal(self):
        from parrot.outputs.cards.inputs import InputDate
        inp = InputDate(id="dob")
        assert inp.element_type == "Input.Date"
        assert inp.value is None


class TestInputTime:
    def test_minimal(self):
        from parrot.outputs.cards.inputs import InputTime
        inp = InputTime(id="start_time")
        assert inp.element_type == "Input.Time"


class TestInputChoiceSet:
    def test_single_select(self):
        from parrot.outputs.cards.inputs import InputChoiceSet, InputChoice
        inp = InputChoiceSet(
            id="role",
            choices=[InputChoice(title="Admin", value="admin"),
                     InputChoice(title="User", value="user")],
            style="compact",
        )
        assert inp.element_type == "Input.ChoiceSet"
        assert inp.is_multi_select is False
        assert len(inp.choices) == 2

    def test_multi_select(self):
        from parrot.outputs.cards.inputs import InputChoiceSet, InputChoice
        inp = InputChoiceSet(
            id="tags",
            choices=[InputChoice(title="A", value="a")],
            is_multi_select=True,
            style="expanded",
        )
        assert inp.is_multi_select is True
