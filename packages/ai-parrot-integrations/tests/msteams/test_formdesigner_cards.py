"""FEAT-734 M3 — card builders."""

import json
import uuid

from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, UPLOAD_WARNING_REASON

from parrot.integrations.msteams.formdesigner_cards import (
    PICKER_ACTION_KEY,
    PICKER_GET_FORM,
    append_render_warnings,
    build_empty_forms_card,
    build_error_card,
    build_form_not_found_card,
    build_login_required_card,
    build_picker_card,
)
from parrot.integrations.msteams.formdesigner_client import FormDescriptor


def _forms() -> list[FormDescriptor]:
    """Return two picker descriptors with stable ordering."""
    return [FormDescriptor(form_uid=uuid.uuid4(), form_id=f"f{i}", title=f"Form {i}") for i in range(2)]


def test_picker_card_choiceset_and_action_key() -> None:
    """The picker has one choice input and only the dedicated routing key."""
    forms = _forms()
    card = build_picker_card(forms, tenant="acme", version="1.5")

    choice_sets = [item for item in card["body"] if item["type"] == "Input.ChoiceSet"]
    submit_actions = [action for action in card["actions"] if action["type"] == "Action.Submit"]
    assert card["version"] == "1.5"
    assert len(choice_sets) == 1
    assert choice_sets[0]["id"] == "form_uid"
    assert choice_sets[0]["isRequired"] is True
    assert choice_sets[0]["choices"] == [
        {"title": form.title, "value": str(form.form_uid)} for form in forms
    ]
    assert choice_sets[0]["value"] == str(forms[0].form_uid)
    assert len(submit_actions) == 1
    assert submit_actions[0]["data"] == {PICKER_ACTION_KEY: PICKER_GET_FORM, "tenant": "acme"}

    serialized = json.dumps(card)
    assert f'"{ENVELOPE_KEY}"' not in serialized
    assert "a2ui_token" not in serialized
    assert "a2ui_action" not in serialized


def test_login_and_empty_cards() -> None:
    """Login and empty states are plain cards without actions."""
    login_card = build_login_required_card()
    empty_card = build_empty_forms_card(tenant="acme")

    for card in (login_card, empty_card):
        assert card["type"] == "AdaptiveCard"
        assert card["body"][0]["type"] == "TextBlock"
        assert card["body"][0]["text"]
        assert "actions" not in card
    assert "/login" in login_card["body"][0]["text"]


def test_append_render_warnings_adds_note() -> None:
    """Any renderer warning adds one note without mutating the original card."""
    original = build_login_required_card()
    original_body = list(original["body"])
    warning = {
        "field_id": "receipt",
        "field_uid": None,
        "field_type": "file",
        "renderer": "teams",
        "reason": UPLOAD_WARNING_REASON,
    }

    annotated = append_render_warnings(original, [warning])

    assert annotated is not original
    assert annotated["body"] is not original["body"]
    assert original["body"] == original_body
    assert len(annotated["body"]) == len(original["body"]) + 1
    assert annotated["body"][-1]["isSubtle"] is True
    assert annotated["body"][-1]["size"] == "Small"
    assert append_render_warnings(original, []) == original


def test_not_found_and_error_cards() -> None:
    """Not-found and safe operator errors retain their supplied context."""
    not_found = build_form_not_found_card("store-visit")
    error = build_error_card("Forms are temporarily unavailable.")

    assert "store-visit" in not_found["body"][0]["text"]
    assert error["body"] == [
        {
            "type": "TextBlock",
            "text": "Forms are temporarily unavailable.",
            "wrap": True,
            "color": "Attention",
        }
    ]


def test_spanish_locale_falls_back_cleanly() -> None:
    """Regional Spanish resolves to Spanish and unsupported locales to English."""
    forms = _forms()
    spanish = build_picker_card(forms, tenant="acme", locale="es-MX")
    spanish_base = build_picker_card(forms, tenant="acme", locale="es")
    english = build_picker_card(forms, tenant="acme", locale="en")
    unsupported = build_picker_card(forms, tenant="acme", locale="fr")

    assert spanish["body"][0]["text"] == spanish_base["body"][0]["text"]
    assert spanish["actions"][0]["title"] == spanish_base["actions"][0]["title"]
    assert spanish["body"][0]["text"] != english["body"][0]["text"]
    assert unsupported["body"][0]["text"] == english["body"][0]["text"]
    assert unsupported["actions"][0]["title"] == english["actions"][0]["title"]
