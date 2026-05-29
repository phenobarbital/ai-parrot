"""
Unit tests for the Teams HITL card renderer (TASK-003 / FEAT-205).

Covers:
  - All six InteractionType values embed ``interaction_id`` in submit data.
  - Policy-bound interactions with render_reject_button → escalate action.
  - Disabled/expired card variant builder.
  - FORM schema → Input.* field mapping (OQ-5).
"""
from __future__ import annotations

import pytest

from parrot.human.channels.base import ESCALATE_OPTION_KEY
from parrot.human.models import (
    ChoiceOption,
    EscalationPolicy,
    HumanInteraction,
    InteractionType,
)
from parrot.integrations.msteams.hitl_cards import TeamsCardRenderer


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def renderer() -> TeamsCardRenderer:
    """Return a renderer with reject-button enabled."""
    return TeamsCardRenderer(render_reject_button=True)


def _make_interaction(
    itype: InteractionType,
    interaction_id: str = "test-id-001",
    question: str = "¿Apruebas esto?",
    options: list | None = None,
    form_schema: dict | None = None,
    policy: str | None = None,
) -> HumanInteraction:
    """Build a minimal HumanInteraction for testing.

    Args:
        itype: The interaction type.
        interaction_id: UUID for correlation.
        question: Card header text.
        options: Choice options (required for SINGLE/MULTI/POLL).
        form_schema: Form schema (required for FORM).
        policy: Optional policy ID string to make the interaction policy-bound.
            Converted to an EscalationPolicy object internally.

    Returns:
        A constructed HumanInteraction.
    """
    kwargs: dict = {
        "interaction_id": interaction_id,
        "question": question,
        "interaction_type": itype,
    }
    if options is not None:
        kwargs["options"] = options
    if form_schema is not None:
        kwargs["form_schema"] = form_schema
    if policy is not None:
        # HumanInteraction.policy is Optional[EscalationPolicy], not str.
        kwargs["policy"] = EscalationPolicy(policy_id=policy, name=policy)
    return HumanInteraction(**kwargs)


def _default_options() -> list[ChoiceOption]:
    return [
        ChoiceOption(key="opt_a", label="Opción A"),
        ChoiceOption(key="opt_b", label="Opción B"),
    ]


def _collect_all_submit_data(card: dict) -> list[dict]:
    """Recursively collect all Action.Submit data dicts from a card.

    Args:
        card: The Adaptive Card dict.

    Returns:
        List of ``data`` dicts found in ``Action.Submit`` elements.
    """
    results = []

    def _walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "Action.Submit" and "data" in obj:
                results.append(obj["data"])
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(card)
    return results


# ── Parametrised: all InteractionTypes embed interaction_id ───────────────────

INTERACTION_TYPES_AND_EXTRAS = [
    (InteractionType.FREE_TEXT, {}, None),
    (InteractionType.APPROVAL, {}, None),
    (InteractionType.SINGLE_CHOICE, {"options": _default_options()}, None),
    (InteractionType.MULTI_CHOICE, {"options": _default_options()}, None),
    (
        InteractionType.FORM,
        {
            "form_schema": {
                "properties": {
                    "name": {"type": "string", "label": "Name"},
                    "count": {"type": "integer", "label": "Count"},
                }
            }
        },
        None,
    ),
    (InteractionType.POLL, {"options": _default_options()}, None),
]


@pytest.mark.parametrize("itype,extras,_", INTERACTION_TYPES_AND_EXTRAS)
def test_card_embeds_interaction_id(
    renderer: TeamsCardRenderer,
    itype: InteractionType,
    extras: dict,
    _,
) -> None:
    """Every Action.Submit data must carry interaction_id for all types.

    Args:
        renderer: The card renderer fixture.
        itype: The interaction type being tested.
        extras: Additional HumanInteraction constructor kwargs.
        _: Unused third parameter from parametrize tuple.
    """
    interaction = _make_interaction(itype, **extras)
    card = renderer.render(interaction)

    submit_data = _collect_all_submit_data(card)
    assert submit_data, f"No Action.Submit found for {itype!r}"

    for data in submit_data:
        assert "interaction_id" in data, (
            f"interaction_id missing from submit data for {itype!r}: {data!r}"
        )
        assert data["interaction_id"] == interaction.interaction_id
        assert data.get("hitl") is True, (
            f"hitl flag missing from submit data for {itype!r}: {data!r}"
        )


@pytest.mark.parametrize("itype,extras,_", INTERACTION_TYPES_AND_EXTRAS)
def test_card_has_body_and_actions(
    renderer: TeamsCardRenderer,
    itype: InteractionType,
    extras: dict,
    _,
) -> None:
    """Every rendered card has a body and at least one action.

    Args:
        renderer: The card renderer fixture.
        itype: The interaction type being tested.
        extras: Additional HumanInteraction constructor kwargs.
        _: Unused third parameter from parametrize tuple.
    """
    interaction = _make_interaction(itype, **extras)
    card = renderer.render(interaction)

    assert card["type"] == "AdaptiveCard"
    assert isinstance(card.get("body"), list) and len(card["body"]) > 0
    assert isinstance(card.get("actions"), list)


# ── Escalate action ───────────────────────────────────────────────────────────

def test_escalate_action_when_policy_bound(renderer: TeamsCardRenderer) -> None:
    """Policy-bound APPROVAL renders an additional escalate action."""
    interaction = _make_interaction(
        InteractionType.APPROVAL,
        policy="tier-1-escalation",
    )
    card = renderer.render(interaction)

    escalate_actions = [
        a for a in card.get("actions", [])
        if a.get("type") == "Action.Submit"
        and a.get("data", {}).get("value") == ESCALATE_OPTION_KEY
    ]
    assert escalate_actions, (
        "No escalate Action.Submit found in policy-bound APPROVAL card"
    )
    escalate_data = escalate_actions[0]["data"]
    assert escalate_data["value"] == ESCALATE_OPTION_KEY
    assert escalate_data["interaction_id"] == interaction.interaction_id
    assert escalate_data.get("hitl") is True


def test_no_escalate_when_not_policy_bound(renderer: TeamsCardRenderer) -> None:
    """Non-policy-bound interactions must NOT have an escalate action."""
    interaction = _make_interaction(InteractionType.APPROVAL)
    card = renderer.render(interaction)

    escalate_actions = [
        a for a in card.get("actions", [])
        if a.get("data", {}).get("value") == ESCALATE_OPTION_KEY
    ]
    assert not escalate_actions, (
        "Escalate action present in non-policy-bound card — should not be."
    )


def test_no_escalate_when_render_reject_button_disabled() -> None:
    """render_reject_button=False → no escalate even if policy-bound."""
    renderer_no_escalate = TeamsCardRenderer(render_reject_button=False)
    interaction = _make_interaction(
        InteractionType.APPROVAL, policy="tier-1-escalation"
    )
    card = renderer_no_escalate.render(interaction)

    escalate_actions = [
        a for a in card.get("actions", [])
        if a.get("data", {}).get("value") == ESCALATE_OPTION_KEY
    ]
    assert not escalate_actions


# ── Disabled card variant ─────────────────────────────────────────────────────

def test_disabled_card_variant(renderer: TeamsCardRenderer) -> None:
    """render_disabled builds a card with no actions and an expiry message."""
    interaction_id = "expired-interaction-id"
    card = renderer.render_disabled(interaction_id, reason="timeout")

    assert card["type"] == "AdaptiveCard"
    assert card.get("actions") == []

    body_text = " ".join(
        el.get("text", "") for el in card.get("body", []) if el.get("type") == "TextBlock"
    )
    assert interaction_id in body_text, "interaction_id not found in disabled card body"
    assert "timeout" in body_text.lower() or "expirado" in body_text.lower() or "expir" in body_text.lower()


# ── APPROVAL card details ─────────────────────────────────────────────────────

def test_approval_has_approve_and_reject(renderer: TeamsCardRenderer) -> None:
    """APPROVAL renders Approve (value=approve) and Reject (value=reject) actions."""
    interaction = _make_interaction(InteractionType.APPROVAL)
    card = renderer.render(interaction)

    values = {
        a["data"]["value"]
        for a in card.get("actions", [])
        if a.get("type") == "Action.Submit" and "value" in a.get("data", {})
    }
    assert "approve" in values, f"approve missing from APPROVAL actions: {values!r}"
    assert "reject" in values, f"reject missing from APPROVAL actions: {values!r}"


# ── FORM field mapping ────────────────────────────────────────────────────────

def test_form_renders_input_fields(renderer: TeamsCardRenderer) -> None:
    """FORM renders Input.* elements for each schema property."""
    schema = {
        "properties": {
            "employee_name": {"type": "string", "label": "Name"},
            "days_off": {"type": "integer", "label": "Days off"},
            "confirmed": {"type": "boolean", "label": "Confirmed"},
            "start_date": {"type": "date", "label": "Start date"},
        }
    }
    interaction = _make_interaction(InteractionType.FORM, form_schema=schema)
    card = renderer.render(interaction)

    # Collect all input types from nested Containers
    def _collect_types(obj, types=None):
        if types is None:
            types = set()
        if isinstance(obj, dict):
            t = obj.get("type", "")
            if t.startswith("Input."):
                types.add(t)
            for v in obj.values():
                _collect_types(v, types)
        elif isinstance(obj, list):
            for item in obj:
                _collect_types(item, types)
        return types

    input_types = _collect_types(card)
    assert "Input.Text" in input_types, f"Input.Text not found: {input_types}"
    assert "Input.Number" in input_types, f"Input.Number not found: {input_types}"
    assert "Input.Toggle" in input_types, f"Input.Toggle not found: {input_types}"
    assert "Input.Date" in input_types, f"Input.Date not found: {input_types}"


def test_form_submit_has_interaction_id(renderer: TeamsCardRenderer) -> None:
    """FORM submit action data includes interaction_id."""
    schema = {"properties": {"notes": {"type": "text", "label": "Notes"}}}
    interaction = _make_interaction(InteractionType.FORM, form_schema=schema)
    card = renderer.render(interaction)

    submit_data = _collect_all_submit_data(card)
    assert submit_data
    for data in submit_data:
        if data.get("value") == ESCALATE_OPTION_KEY:
            continue
        assert data["interaction_id"] == interaction.interaction_id


# ── FREE_TEXT details ─────────────────────────────────────────────────────────

def test_free_text_has_multiline_input(renderer: TeamsCardRenderer) -> None:
    """FREE_TEXT card includes an isMultiline Input.Text."""
    interaction = _make_interaction(InteractionType.FREE_TEXT)
    card = renderer.render(interaction)

    def _find_input_text(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "Input.Text" and obj.get("isMultiline") is True:
                return True
            return any(_find_input_text(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_find_input_text(item) for item in obj)
        return False

    assert _find_input_text(card), "No multiline Input.Text found in FREE_TEXT card"
