"""Adaptive Cards for FormDesigner form serving (FEAT-734 M3)."""

from __future__ import annotations

import copy
from typing import Any, Sequence

from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION

from .formdesigner_client import FormDescriptor

PICKER_ACTION_KEY: str = "_formdesigner_action"
PICKER_GET_FORM: str = "get_form"
_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"

_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "pick_title": "Choose a form",
        "pick_submit": "Open form",
        "login": "Please sign in with /login to use forms.",
        "empty": "There are no forms available for this workspace.",
        "not_found": "No form found for '{ref}'.",
        "upload_note": "Some fields can't be filled in Teams. Use the web form link to complete them.",
    },
    "es": {
        "pick_title": "Elige un formulario",
        "pick_submit": "Abrir formulario",
        "login": "Inicia sesión con /login para usar formularios.",
        "empty": "No hay formularios disponibles para este espacio de trabajo.",
        "not_found": "No se encontró ningún formulario para '{ref}'.",
        "upload_note": "Algunos campos no se pueden completar en Teams. Usa el enlace del formulario web para completarlos.",
    },
}


def _t(key: str, locale: str) -> str:
    """Return localized card text, falling back to English."""
    lang = (locale or "en").split("-")[0]
    return _TEXTS.get(lang, {}).get(key) or _TEXTS["en"][key]


def _card(
    body: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None = None,
    *,
    version: str = DEFAULT_ADAPTIVE_CARD_VERSION,
) -> dict[str, Any]:
    """Build a plain Adaptive Card payload."""
    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": _SCHEMA,
        "version": version,
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def _text(text: str, **extra: Any) -> dict[str, Any]:
    """Build a wrapping Adaptive Card text block."""
    return {"type": "TextBlock", "text": text, "wrap": True, **extra}


def build_picker_card(
    forms: Sequence[FormDescriptor],
    *,
    tenant: str,
    locale: str = "en",
    version: str = DEFAULT_ADAPTIVE_CARD_VERSION,
) -> dict[str, Any]:
    """Build a form picker with one tenant-tagged submit action."""
    choices = [{"title": form.title, "value": str(form.form_uid)} for form in forms]
    body = [
        _text(_t("pick_title", locale), weight="Bolder"),
        {
            "type": "Input.ChoiceSet",
            "id": "form_uid",
            "style": "compact",
            "isRequired": True,
            "choices": choices,
            "value": choices[0]["value"] if choices else None,
        },
    ]
    actions = [
        {
            "type": "Action.Submit",
            "title": _t("pick_submit", locale),
            "data": {PICKER_ACTION_KEY: PICKER_GET_FORM, "tenant": tenant},
        }
    ]
    return _card(body, actions, version=version)


def build_login_required_card(*, locale: str = "en") -> dict[str, Any]:
    """Build a card explaining that ``/login`` is required."""
    return _card([_text(_t("login", locale))])


def build_empty_forms_card(*, locale: str = "en") -> dict[str, Any]:
    """Build an empty-state card for a tenant with no forms."""
    return _card([_text(_t("empty", locale))])


def build_form_not_found_card(ref: str, *, locale: str = "en") -> dict[str, Any]:
    """Build a card for a slug or UUID that matches no form."""
    return _card([_text(_t("not_found", locale).format(ref=ref))])


def build_error_card(message: str) -> dict[str, Any]:
    """Build an attention-styled card from a caller-supplied safe message."""
    return _card([_text(message, color="Attention")])


def append_render_warnings(
    card: dict[str, Any],
    warnings: Sequence[dict[str, Any]],
    *,
    locale: str = "en",
) -> dict[str, Any]:
    """Return a copy of ``card`` with a visible degradation note when needed."""
    result = copy.deepcopy(card)
    if warnings:
        result.setdefault("body", []).append(_text(_t("upload_note", locale), isSubtle=True, size="Small"))
    return result
