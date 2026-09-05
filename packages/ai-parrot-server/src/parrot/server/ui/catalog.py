"""Admin UI catalog endpoint — ``GET /api/v1/admin/catalog``.

Serves the option lists the Admin UI agent-management form needs (LLM
providers, ``operation_mode``/``memory_type`` enums, knowledge-base class
options) so the UI hardcodes none of them (spec §8 Q2, resolved: no
hardcoded KB list — the server owns the catalog).

Follows the same authenticated-endpoint pattern as
``parrot.server.ui.status.AdminStatusHandler`` (TASK-2524): the response
models here are also the TS codegen source (``scripts/generate_ts_types.py``).
"""

from __future__ import annotations

import logging

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import BaseModel

from ...clients.factory import SUPPORTED_CLIENTS
from ...stores.kb import RedisKnowledgeBase


class KnowledgeBaseOption(BaseModel):
    """A single selectable knowledge-base class for ``custom_kbs``."""

    class_path: str
    name: str
    description: str | None = None


class AdminCatalog(BaseModel):
    """Aggregate option-list payload for the Admin UI agent form."""

    llm_providers: list[str]
    operation_modes: list[str]
    memory_types: list[str]
    knowledge_bases: list[KnowledgeBaseOption]
    bot_class_default: str = "BasicBot"


def _dedup_llm_providers() -> list[str]:
    """Return ``SUPPORTED_CLIENTS`` keys deduplicated by resolved client.

    ``SUPPORTED_CLIENTS`` maps several alias keys to the same client
    class — e.g. ``claude``/``anthropic`` both resolve to
    ``AnthropicClient``, ``claude-agent``/``claude-code`` both resolve to
    the same lazy loader. FEAT-523 (TASK-2853): every provider now
    registers via a real `parrot.clients` entry point, so each alias key
    carries its *own* ``EntryPoint`` (and thus its own ``.load`` bound
    method) even when they target the same class — comparing the raw
    registry values no longer detects the alias relationship, so each
    value is resolved (zero-arg lazy loaders are called) before
    deduplicating. Keeps the first key encountered per resolved value,
    sorted.
    """
    seen: list[object] = []
    providers: list[str] = []
    for key, value in SUPPORTED_CLIENTS.items():
        resolved = value() if callable(value) and not isinstance(value, type) else value
        if resolved in seen:
            continue
        seen.append(resolved)
        providers.append(key)
    return sorted(providers)


def _knowledge_base_options() -> list[KnowledgeBaseOption]:
    """Return the importable ``AbstractKnowledgeBase`` classes as options.

    ``RedisKnowledgeBase`` always ships with core ``ai-parrot``.
    ``LocalKB`` requires ``ai-parrot-embeddings`` (lazy ``__getattr__`` in
    ``parrot.stores.kb``) — its import is wrapped so a deployment without
    that extra still returns a valid (shorter) catalog instead of a 500.
    """
    options = [
        KnowledgeBaseOption(
            class_path=(f"{RedisKnowledgeBase.__module__}.{RedisKnowledgeBase.__qualname__}"),
            name=RedisKnowledgeBase.__name__,
            description=(
                (RedisKnowledgeBase.__doc__ or "").strip().splitlines()[0]
                if (RedisKnowledgeBase.__doc__ or "").strip()
                else None
            ),
        ),
    ]
    try:
        from ...stores.kb import LocalKB  # pylint: disable=import-outside-toplevel

        options.append(
            KnowledgeBaseOption(
                class_path=f"{LocalKB.__module__}.{LocalKB.__qualname__}",
                name=LocalKB.__name__,
                description=(
                    (LocalKB.__doc__ or "").strip().splitlines()[0] if (LocalKB.__doc__ or "").strip() else None
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001
        # ai-parrot-embeddings absent (or any other import-time failure) —
        # degrade gracefully, never raise from the catalog builder.
        logging.getLogger(__name__).warning("LocalKB unavailable, dropping from Admin UI catalog: %s", exc)
    return options


def build_catalog() -> AdminCatalog:
    """Assemble the :class:`AdminCatalog` payload.

    Pure and import-safe: no aiohttp request/app dependency, so it is
    unit-testable directly without spinning up a server.

    Returns:
        The aggregated catalog payload.
    """
    return AdminCatalog(
        llm_providers=_dedup_llm_providers(),
        # Mirrors parrot.handlers.models.bots.BotModel.__post_init__
        # (handlers/models/bots.py:307-314) — keep in sync if those enums
        # change.
        operation_modes=["conversational", "agentic", "adaptive"],
        memory_types=["memory", "file", "redis"],
        knowledge_bases=_knowledge_base_options(),
        bot_class_default="BasicBot",
    )


@is_authenticated()
@user_session()
class AdminCatalogHandler(BaseView):
    """``GET /api/v1/admin/catalog`` — option lists for the agent form."""

    async def get(self) -> web.Response:
        """Return the current :class:`AdminCatalog` payload as JSON.

        Returns:
            A 200 JSON response matching :class:`AdminCatalog`. Requires
            an authenticated session (enforced by the class decorators).
        """
        catalog = build_catalog()
        return self.json_response(catalog.model_dump(mode="json"))
