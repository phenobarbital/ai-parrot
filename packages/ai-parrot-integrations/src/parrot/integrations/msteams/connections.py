"""Teams connections (FEAT-775): principal source, permission context, notifier and cards.

TASK-5066 owns the principal/context part; TASK-5067 appends the notifier, TASK-5068 the card builders.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext, build_principal_context
from parrot.auth.principal import Principal

from .auth import MSTeamsSessionStore, MSTeamsUserSession

if TYPE_CHECKING:  # pragma: no cover
    from botbuilder.core import TurnContext

logger = logging.getLogger(__name__)

MSTEAMS_CHANNEL = "msteams"


class TeamsConnectState(BaseModel):
    """What the Teams channel puts in ``IntegrationsService.start_connect(extra_state=...)``."""

    conversation_reference: Dict[str, Any]
    bot_app_id: str


class MSTeamsPrincipalSource:
    """Principal for the speaking Teams user, from the cached FEAT-729 session; never runs an exchange."""

    def __init__(self, store: Optional[MSTeamsSessionStore]) -> None:
        self._store = store

    async def session_for_turn(self, turn_context: "TurnContext") -> Optional[MSTeamsUserSession]:
        """Return the live authenticated session, or ``None``.

        Requires ``authenticated``, ``nav_user_id``, ``aad_object_id`` and an unexpired credential.
        """
        if self._store is None:
            return None
        session = await self._store.get_or_create(turn_context)
        if (
            session.authenticated
            and session.nav_user_id
            and session.aad_object_id
            and not self._store.is_expired(session)
        ):
            return session
        return None

    async def principal_for_turn(self, turn_context: "TurnContext") -> Optional[Principal]:
        """Return the FEAT-773 principal for an authenticated turn, else ``None``."""
        session = await self.session_for_turn(turn_context)
        if session is None:
            return None
        return Principal(
            user_id=str(session.nav_user_id),
            canonical_identity=session.aad_object_id,
            tenant_id=session.tenant_id,
            channel=MSTEAMS_CHANNEL,
            channel_user_id=str(session.aad_object_id),
        )


def build_msteams_permission_context(session: MSTeamsUserSession) -> PermissionContext:
    """Build the Navigator PBAC context for a validated Teams session.

    ``session.user_id`` is the Navigator id (PBAC subject); ``channel_user_id`` is the AAD oid used only for
    OAuth credential lookup. Roles stay empty: Teams sessions carry no verified role claims.
    """
    context = build_principal_context(
        str(session.nav_user_id),
        channel=MSTEAMS_CHANNEL,
        tenant_id=session.tenant_id,
        roles=frozenset(),
    )
    context.channel_user_id = session.aad_object_id
    return context


_CONVREF_KEY = "msteams:convref:{nav_user_id}"
_CONVREF_TTL_S = 30 * 86400


class MSTeamsConversationRefStore:
    """Latest personal conversation reference per Navigator user (Redis, JSON)."""

    def __init__(self, redis: Any, ttl_s: int = _CONVREF_TTL_S) -> None:
        self._redis = redis
        self._ttl_s = ttl_s

    async def save(self, nav_user_id: str, conversation_reference: Dict[str, Any]) -> None:
        """Store (and refresh the TTL of) the reference; log and swallow Redis errors."""
        try:
            key = _CONVREF_KEY.format(nav_user_id=nav_user_id)
            await self._redis.set(key, json.dumps(conversation_reference), ex=self._ttl_s)
        except Exception:  # noqa: BLE001 — a conversation-reference cache failure must not fail the turn
            logger.warning("Failed to store Teams conversation reference for user=%s", nav_user_id, exc_info=True)

    async def get(self, nav_user_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored reference or ``None`` (missing, undecodable or Redis error)."""
        try:
            key = _CONVREF_KEY.format(nav_user_id=nav_user_id)
            value = await self._redis.get(key)
            if value is None:
                return None
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else None
        except Exception:  # noqa: BLE001 — a conversation-reference cache failure must not fail notification
            logger.warning("Failed to load Teams conversation reference for user=%s", nav_user_id, exc_info=True)
            return None


class MSTeamsConnectionNotifier:
    """FEAT-773 ``ChannelNotifier`` for Teams: every provider, every lifecycle event, multi-bot routing."""

    channel = MSTEAMS_CHANNEL

    def __init__(self, ref_store: Optional[MSTeamsConversationRefStore]) -> None:
        self._ref_store = ref_store
        self._adapters: Dict[str, Any] = {}

    def attach(self, app_id: str, adapter: Any) -> None:
        """Register the adapter of one Teams bot under its Microsoft app id."""
        if app_id:
            self._adapters[app_id] = adapter

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Send the lifecycle message to the owning conversation; log every failure, never raise."""
        try:
            extra = (state_payload or {}).get("extra") or {}
            ref = extra.get("conversation_reference") or None
            if ref is None and self._ref_store is not None:
                ref = await self._ref_store.get(event.user_id)
            if not ref:
                logger.warning("Teams notifier: no conversation reference for provider=%s", event.provider)
                return
            app_id = self._resolve_app_id(extra, ref)
            adapter = self._adapters.get(app_id or "")
            if adapter is None:
                logger.warning("Teams notifier: no adapter attached for app id %r", app_id)
                return
            text = self._message(event)

            from botbuilder.schema import Activity, ConversationReference

            conversation_reference = ConversationReference.deserialize(ref)

            async def _callback(turn_context: Any) -> None:
                await turn_context.send_activity(Activity(type="message", text=text))

            await adapter.continue_conversation(conversation_reference, _callback, app_id)
        except Exception:  # noqa: BLE001 — FEAT-773 publisher contract: never raise
            logger.exception("Teams notifier failed for provider=%s kind=%s", event.provider, event.kind)

    @staticmethod
    def _resolve_app_id(extra: Dict[str, Any], ref: Dict[str, Any]) -> Optional[str]:
        """``bot_app_id`` from state, else the reference's ``bot.id`` without the ``28:`` prefix."""
        state_app_id = extra.get("bot_app_id")
        if state_app_id:
            return str(state_app_id)
        bot = ref.get("bot") or {}
        bot_id = bot.get("id") if isinstance(bot, dict) else None
        if not bot_id:
            return None
        bot_id = str(bot_id)
        return bot_id[3:] if bot_id.startswith("28:") else bot_id

    @staticmethod
    def _message(event: ConnectionEvent) -> str:
        """Exact per-kind text from spec §2; never includes token material or event.reason."""
        provider = OAuth2ProviderRegistry().get(event.provider)
        name = getattr(provider, "display_name", None) or event.provider
        if event.kind == "connection.completed":
            return f"{name} connected as **{event.display_name}**. Ask again to use it."
        if event.kind == "connection.revoked":
            return f"{name} disconnected."
        if event.kind == "connection.refresh_failed":
            return f"{name} access expired — `/connect {event.provider}` to reconnect."
        raise ValueError(f"Unsupported connection event kind: {event.kind}")
