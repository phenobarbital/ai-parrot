"""Unit tests for briefing renderer & edit-before-execute re-validation.

Tests render_briefing (template + raw fallback), build_form_schema,
revalidate_edit, and the FORM path in ConfirmationGuard.confirm().

Run with:
    pytest packages/ai-parrot/tests/test_confirmation_briefing.py -v
"""
from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
    build_form_schema,
    render_briefing,
    revalidate_edit,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


class _CheckinSchema(BaseModel):
    employee_id: int
    time: str


def _make_tool(
    name: str = "workday_checkin",
    requires_confirmation: bool = True,
    confirm_template: Optional[str] = None,
    allow_edit: bool = False,
    args_schema=None,
):
    """Create a minimal AbstractTool stub."""
    tool = MagicMock()
    tool.name = name
    tool.routing_meta = {
        "requires_confirmation": requires_confirmation,
        "allow_edit": allow_edit,
    }
    if confirm_template is not None:
        tool.routing_meta["confirm_template"] = confirm_template
    tool.args_schema = args_schema
    return tool


class _FakeResult:
    def __init__(self, value: Any = None, timed_out: bool = False):
        self.consolidated_value = value
        self.timed_out = timed_out
        self.interaction_id = "fake"
        self.responses = []


class _FakeManager:
    def __init__(self, result: _FakeResult):
        self._result = result
        self.calls = 0

    async def request_human_input(self, interaction, channel=None):
        self.calls += 1
        return self._result


# ── render_briefing tests ──────────────────────────────────────────────────────


def test_briefing_uses_template():
    """confirm_template is rendered with tool name and params."""
    tool = _make_tool(confirm_template="Run {tool} with {params}")
    result = render_briefing(tool, {"x": 1})
    assert "Run" in result
    assert "workday_checkin" in result
    assert "x" in result


def test_briefing_template_with_direct_params():
    """Template can reference individual parameters."""
    tool = _make_tool(confirm_template="Check in employee {employee_id} at {time}")
    result = render_briefing(tool, {"employee_id": 42, "time": "09:00"})
    assert "42" in result
    assert "09:00" in result


def test_briefing_raw_fallback_on_missing_template():
    """No template → raw 'tool with: k=v' listing."""
    tool = _make_tool(confirm_template=None)
    result = render_briefing(tool, {"employee_id": 42})
    assert "workday_checkin" in result
    assert "employee_id" in result


def test_raw_fallback_on_bad_template():
    """Malformed template (missing key) falls back to raw listing, no exception."""
    tool = _make_tool(confirm_template="{missing_key}")
    result = render_briefing(tool, {"x": 1})
    # No exception; should contain x from raw fallback
    assert "x" in result
    assert "{missing_key}" not in result


def test_briefing_empty_params():
    """No params → tool name only."""
    tool = _make_tool(confirm_template=None)
    result = render_briefing(tool, {})
    assert "workday_checkin" in result
    assert "no parameters" in result


def test_briefing_template_index_error_fallback():
    """A template with index formatting errors falls back gracefully."""
    tool = _make_tool(confirm_template="{0}")  # positional key in kwargs-only format
    result = render_briefing(tool, {"x": 1})
    assert "x" in result  # raw fallback


# ── build_form_schema tests ───────────────────────────────────────────────────


def test_build_form_schema_with_pydantic_schema():
    """build_form_schema extracts fields from a Pydantic args_schema."""
    tool = _make_tool(args_schema=_CheckinSchema)
    params = {"employee_id": 42, "time": "09:00"}
    schema = build_form_schema(tool, params)
    # Must be non-empty (required by HumanInteraction model_validator)
    assert schema
    assert "fields" in schema
    assert "employee_id" in schema["fields"]
    assert "time" in schema["fields"]
    # Defaults should be pre-filled
    assert schema["fields"]["employee_id"].get("default") == 42


def test_build_form_schema_non_empty_without_schema():
    """build_form_schema produces non-empty result even without args_schema."""
    tool = _make_tool(args_schema=None)
    params = {"foo": "bar", "count": 3}
    schema = build_form_schema(tool, params)
    assert schema  # non-empty
    # Should contain the parameter keys
    if "fields" in schema:
        assert "foo" in schema["fields"] or "current_values" in schema


def test_build_form_schema_empty_params_non_empty():
    """build_form_schema with no params still returns a non-empty dict."""
    tool = _make_tool(args_schema=None)
    schema = build_form_schema(tool, {})
    assert schema  # must be non-empty for FORM validator


# ── revalidate_edit tests ──────────────────────────────────────────────────────


def test_edit_valid_values_pass():
    """Valid edited values pass schema validation and return model dump."""
    tool = _make_tool(args_schema=_CheckinSchema)
    edited = {"employee_id": 99, "time": "10:30"}
    result = revalidate_edit(tool, edited)
    assert result["employee_id"] == 99
    assert result["time"] == "10:30"


def test_edit_invalid_values_raise():
    """Invalid edited values raise ValidationError."""
    tool = _make_tool(args_schema=_CheckinSchema)
    invalid_edited = {"employee_id": "not-an-int", "time": "10:30"}
    with pytest.raises(Exception):  # ValidationError or similar
        revalidate_edit(tool, invalid_edited)


def test_edit_no_schema_passthrough():
    """When no args_schema is set, revalidate_edit passes values through."""
    tool = _make_tool(args_schema=None)
    edited = {"any_key": "any_value"}
    result = revalidate_edit(tool, edited)
    assert result == edited


# ── FORM path in ConfirmationGuard ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_form_approved_with_edits():
    """FORM path with allow_edit: valid edits → allowed=True, parameters=<edited>."""
    store = InMemoryConfirmationWindowStore()
    edited_params = {"employee_id": 99, "time": "10:00"}
    fake_manager = _FakeManager(_FakeResult(value=edited_params))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)

    tool = _make_tool(
        requires_confirmation=True,
        allow_edit=True,
        args_schema=_CheckinSchema,
    )
    params = {"employee_id": 42, "time": "09:00"}

    decision = await guard.confirm(tool=tool, parameters=params)

    assert decision.allowed is True
    assert decision.status == "confirmed"
    assert decision.parameters is not None
    assert decision.parameters["employee_id"] == 99


@pytest.mark.asyncio
async def test_form_cancelled_by_user():
    """FORM path: user sends None/False → cancelled."""
    store = InMemoryConfirmationWindowStore()
    fake_manager = _FakeManager(_FakeResult(value=None))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)

    tool = _make_tool(requires_confirmation=True, allow_edit=True)
    decision = await guard.confirm(tool=tool, parameters={"x": 1})

    assert decision.allowed is False
    assert decision.status == "cancelled"


@pytest.mark.asyncio
async def test_edit_invalid_beyond_retries_cancels():
    """Invalid edit beyond max_edit_retries → allowed=False, status=cancelled."""
    store = InMemoryConfirmationWindowStore()

    # First call returns invalid dict, second (if any) returns another invalid dict
    call_count = 0

    class _RetryManager:
        async def request_human_input(self, interaction, channel=None):
            nonlocal call_count
            call_count += 1
            # Always return an invalid dict for _CheckinSchema
            return _FakeResult(value={"employee_id": "not-an-int", "time": "x"})

    guard = ConfirmationGuard(
        store=store,
        human_manager=_RetryManager(),
        config=ConfirmationConfig(max_edit_retries=1),  # 1 retry = 2 total attempts
    )
    tool = _make_tool(
        requires_confirmation=True,
        allow_edit=True,
        args_schema=_CheckinSchema,
    )

    decision = await guard.confirm(tool=tool, parameters={"employee_id": 42, "time": "09:00"})

    assert decision.allowed is False
    assert decision.status == "cancelled"
    assert call_count == 2  # initial attempt + 1 retry


@pytest.mark.asyncio
async def test_non_allow_edit_still_uses_approval_path():
    """Tool without allow_edit still uses APPROVAL (not FORM) path."""
    store = InMemoryConfirmationWindowStore()

    interaction_types_used = []

    class _RecordingManager:
        async def request_human_input(self, interaction, channel=None):
            interaction_types_used.append(interaction.interaction_type)
            return _FakeResult(value=True)

    guard = ConfirmationGuard(store=store, human_manager=_RecordingManager())
    tool = _make_tool(requires_confirmation=True, allow_edit=False)
    decision = await guard.confirm(tool=tool, parameters={"x": 1})

    assert decision.allowed is True
    from parrot.human.models import InteractionType
    assert interaction_types_used == [InteractionType.APPROVAL]
