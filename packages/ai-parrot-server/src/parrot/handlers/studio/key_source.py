"""Which key serves an LLM call: the server's own or the caller's stored personal (BYOK) one (PA-2).

``credentials_for`` feeds the per-request llm-clients catalogue; :func:`choose_key_source` is the single decision
test/ask and the assistant share: one source available -> it is used; both -> the caller must say which
(``409 key_source_required``); an explicit source that does not exist -> ``422 key_source_unavailable``.
Neither key material nor environment-variable names ever leave this module.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from parrot.auth.broker import byok_store_setting
from parrot.clients.base import AbstractClient
from parrot.clients.factory import LLMFactory
from parrot.interfaces.documentdb import DocumentDb

logger = logging.getLogger(__name__)

STUDIO_CATALOG_USABLE_ONLY = "studio_catalog_usable_only"
"""Host opt-in (``app[STUDIO_CATALOG_USABLE_ONLY] = True``): ``/catalog/llm-clients`` hides rows with no usable
credential unless ``?usable=0`` is sent. Off (default) every row is returned, as before PA-3."""

STUDIO_KEY_SOURCE_CHOICE = "studio_key_source_choice"
"""Host opt-in (``app[STUDIO_KEY_SOURCE_CHOICE] = True``): with BOTH a server and a personal key and no explicit
``key_source`` the call is refused (``409 key_source_required``) instead of silently using the personal key."""

KEY_SOURCES = ("server", "byok")
KeySource = Literal["server", "byok"]
# Several provider keys share one class (``bedrock``/``anthropic-aws`` -> ``AnthropicClient``) but authenticate
# with ambient cloud credentials, not the class's API-key variable: the class cannot speak for them.
AMBIENT_PROVIDERS = frozenset({"bedrock", "anthropic-aws"})


class KeySourceRefusal(Exception):
    """A refusal to pick a key: ``status``/``code``/``message`` plus structured ``details`` for the response."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def _client_class(provider: str) -> type[AbstractClient] | None:
    """The client class registered for ``provider`` (resolving a lazy loader), ``None`` when it cannot load."""
    value = LLMFactory.supported_clients().get(provider)
    if value is None:
        return None
    try:
        return value() if callable(value) and not isinstance(value, type) else value
    except Exception:  # pylint: disable=broad-except
        logger.warning("LLM client for provider %r failed to import", provider, exc_info=True)
        return None


def server_credential_state(provider: str) -> Literal["present", "absent", "unknown"]:
    """Whether the SERVER holds a credential for ``provider``; ``unknown`` when the client cannot say.

    Evaluated on every call (navconfig is read live): a key added to or removed from the environment changes the
    answer without a restart.
    """
    cls = _client_class(provider)
    if cls is None or provider in AMBIENT_PROVIDERS:
        return "unknown"
    overridden = cls.has_server_credentials.__func__ is not AbstractClient.has_server_credentials.__func__
    if cls.credential_env is None and not overridden:
        return "unknown"
    try:
        return "present" if cls.has_server_credentials() else "absent"
    except Exception:  # pylint: disable=broad-except
        logger.warning("has_server_credentials failed for provider %r", provider, exc_info=True)
        return "unknown"


async def user_byok_providers(app: Any, user_id: Any) -> frozenset[str]:
    """Providers the user has a stored key for (no decryption). Fails closed: an unreadable store is "none"."""
    try:
        if byok_store_setting() == "postgres":
            from .storage.byok_store import get_byok_store

            return frozenset(str(k["provider"]).lower() for k in await get_byok_store(app).list_masked(user_id))
        from .byok import COLLECTION

        async with DocumentDb() as db:
            docs = await db.read(COLLECTION, {"user_id": user_id})
        return frozenset(str(d.get("provider", "")).lower() for d in docs or [] if d.get("provider"))
    except Exception:  # pylint: disable=broad-except
        logger.warning("could not list the BYOK providers of user %s", user_id, exc_info=True)
        return frozenset()


def credentials_for(provider: str, byok_providers: frozenset[str]) -> list[KeySource]:
    """The ``credentials`` of a catalogue row: ``byok`` first-class when the caller has a key, ``server`` if any."""
    out: list[KeySource] = []
    if provider.lower() in byok_providers:
        out.append("byok")
    if server_credential_state(provider) == "present":
        out.append("server")
    return out


def key_source_choice_enabled(app: Any) -> bool:
    """Whether the host opted in to :data:`STUDIO_KEY_SOURCE_CHOICE` (default off: the previous behaviour)."""
    return bool(app.get(STUDIO_KEY_SOURCE_CHOICE))


def choose_key_source(
    provider: str, *, has_byok: bool, requested: str | None = None, use_byok: bool = True,
    ask_when_both: bool = False,
) -> KeySource:
    """The key source of one call, or raise :class:`KeySourceRefusal`.

    Args:
        provider: LLM provider key.
        has_byok: The caller has a stored personal key for ``provider``.
        requested: Explicit ``key_source`` of the request (``None`` = not given).
        use_byok: Legacy opt-out; ``False`` with no explicit source means the server key (never asks).
        ask_when_both: The host opted in to :data:`STUDIO_KEY_SOURCE_CHOICE`: both keys and no explicit source raise
            ``409``. Off (default) the personal key wins silently, as before PA-2.
    """
    state = server_credential_state(provider)
    if requested is not None:
        if requested not in KEY_SOURCES:
            raise KeySourceRefusal(422, "invalid_key_source", "key_source must be 'server' or 'byok'.")
        if (requested == "byok" and not has_byok) or (requested == "server" and state == "absent"):
            raise KeySourceRefusal(
                422, "key_source_unavailable", f"No {requested} key is available for provider '{provider}'.",
                {"provider": provider, "requested": requested},
            )
        return requested  # type: ignore[return-value]
    if not use_byok:
        return "server"
    if ask_when_both and has_byok and state == "present":
        raise KeySourceRefusal(
            409, "key_source_required", f"Both a server key and your own key exist for '{provider}': choose one.",
            {"provider": provider, "options": list(KEY_SOURCES)},
        )
    return "byok" if has_byok else "server"
