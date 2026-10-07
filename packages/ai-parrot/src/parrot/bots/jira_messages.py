"""Localized operational messages for JiraSpecialist (FEAT-638).

These are Python-authored messages (Telegram callback toasts, nudges, manager
escalations) that no prompt directive can reach, so they follow the bot's
`language` through this catalog instead.

Each entry is a ``string.Template`` with *protected* placeholders: values such as
issue keys and Jira status names are substituted verbatim and must never be
translated. Adding a language means adding a row here, in SUPPORTED_LANGUAGES and
in GROUNDING_SENTINELS (see docs/prompts/output-language.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Any, Final, Optional

from parrot.bots.prompts.language import FALLBACK_LANGUAGE, normalize_language


@dataclass(frozen=True)
class MessageTemplate:
    """A localized operational message whose placeholders must not be translated.

    Attributes:
        template: ``string.Template`` source.
        protected: Placeholder names substituted verbatim in every language.
    """

    template: str
    protected: frozenset[str]


JIRA_MESSAGES: Final[dict[str, dict[str, MessageTemplate]]] = {
    "en": {
        "transition_error": MessageTemplate("⚠️ Error transitioning ${ticket_key}", frozenset({"ticket_key"})),
        "transition_ok": MessageTemplate("✅ ${ticket_key} → ${status}", frozenset({"ticket_key", "status"})),
        "transition_edit": MessageTemplate(
            "✅ *${name}*, your ticket *${ticket_key}* has been moved to *${status}*.\n\nLet's get to work! 💪",
            frozenset({"name", "ticket_key", "status"}),
        ),
        "skip_ok": MessageTemplate("👍 Got it", frozenset()),
        "skip_edit": MessageTemplate(
            "👍 *${name}*, got it. You already have your plan for today.", frozenset({"name"})
        ),
        "nudge": MessageTemplate(
            "👋 *${name}*, you haven't selected your ticket for today yet.\n\nNeed help prioritizing?",
            frozenset({"name"}),
        ),
        "escalation": MessageTemplate(
            "⚠️ *Daily Standup Escalation*\n\n"
            "The following devs haven't selected a ticket after ${hours}h:\n\n"
            "${names}\n\n"
            "They may need help prioritizing.",
            frozenset({"hours", "names"}),
        ),
    },
    "es": {
        "transition_error": MessageTemplate("⚠️ Error transicionando ${ticket_key}", frozenset({"ticket_key"})),
        "transition_ok": MessageTemplate("✅ ${ticket_key} → ${status}", frozenset({"ticket_key", "status"})),
        "transition_edit": MessageTemplate(
            "✅ *${name}*, tu ticket *${ticket_key}* ha sido marcado como *${status}*.\n\n¡A trabajar! 💪",
            frozenset({"name", "ticket_key", "status"}),
        ),
        "skip_ok": MessageTemplate("👍 Entendido", frozenset()),
        "skip_edit": MessageTemplate("👍 *${name}*, entendido. Ya tienes tu plan para hoy.", frozenset({"name"})),
        "nudge": MessageTemplate(
            "👋 *${name}*, aún no has seleccionado tu ticket para hoy.\n\n¿Necesitas ayuda con la priorización?",
            frozenset({"name"}),
        ),
        "escalation": MessageTemplate(
            "⚠️ *Escalación Daily Standup*\n\n"
            "Los siguientes devs no han seleccionado ticket tras ${hours}h:\n\n"
            "${names}\n\n"
            "Puede que necesiten ayuda con priorización.",
            frozenset({"hours", "names"}),
        ),
    },
}
"""Language code -> message key -> template. Every language defines every key."""


def render_message(key: str, language: Optional[str], **params: Any) -> str:
    """Render an operational message in the configured language.

    Args:
        key: Message key, e.g. ``"transition_ok"``.
        language: The bot's raw ``language`` value; normalized here. ``None`` or an
            unsupported value falls back to :data:`FALLBACK_LANGUAGE`.
        **params: Values for the message's protected placeholders, substituted verbatim.

    Returns:
        The rendered message.

    Raises:
        KeyError: When ``key`` is unknown in the fallback language, or a placeholder
            value is missing from ``params``.
    """
    code = normalize_language(language) or FALLBACK_LANGUAGE
    message = JIRA_MESSAGES.get(code, {}).get(key) or JIRA_MESSAGES[FALLBACK_LANGUAGE][key]
    return Template(message.template).substitute(params)
