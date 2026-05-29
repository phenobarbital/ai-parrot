"""
Proactive 1:1 bootstrap and Redis-backed conversation-reference cache.

This module is the net-new core of the Teams HITL channel (spec §3 Module 3).
It implements two capabilities that do not exist anywhere else in the repo:

1. **ConversationReferenceStore** — Redis-backed cache for
   ``ConversationReference`` objects keyed by recipient email
   (``hitl:teams:convref:{email}``).  Long TTL (~30 days) refreshed on
   every inbound activity so frequently-contacted users never see a cold
   bootstrap again.

2. **SentActivityStore** — Redis map
   ``hitl:teams:sent:{interaction_id}`` that records
   ``{conversation_reference, activity_id, recipient}`` for every sent
   card.  Used by ``cancel_interaction`` (``update_activity``) and for
   cross-worker stateless delivery.

3. **ProactiveMessenger** — orchestrates the proactive 1:1:
   - *Warm path*: convref cached →
     ``adapter.continue_conversation(ref, callback, bot_app_id)``.
   - *Cold path*: no cache → ``adapter.create_conversation(...)`` to
     bootstrap the 1:1, capture the new ``ConversationReference``, post.
   Returns the posted ``activity_id`` (for the sent map) or raises
   ``ProactiveDeliveryError`` on failure.

OQ-2 resolution (botbuilder v4.17.1):
    ``CloudAdapter.continue_conversation(reference, callback, bot_app_id)``
    ``CloudAdapter.create_conversation(bot_app_id, callback,
        conversation_parameters, service_url=...)``
    ``ConversationParameters(is_group=False, bot=ChannelAccount(id=app_id),
        members=[ChannelAccount(id=aad_object_id)], tenant_id=tenant_id)``
    ``TurnContext.get_conversation_reference(activity)`` — static method.
    ``MicrosoftAppCredentials.trust_service_url(service_url)`` — before send.

Serialisation format: ``ConversationReference.serialize()`` → JSON string.
Deserialisation: ``ConversationReference.deserialize(json.loads(json_str))``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from botbuilder.core import TurnContext
from botbuilder.schema import (
    Activity,
    ChannelAccount,
    ConversationParameters,
    ConversationReference,
)
from botframework.connector.auth import MicrosoftAppCredentials

from parrot.integrations.msteams.graph import ResolvedTeamsUser


# ── Custom exceptions ─────────────────────────────────────────────────────────

class ProactiveDeliveryError(Exception):
    """Raised when a proactive send fails fatally (cold-create + org-install).

    The caller (``TeamsHumanChannel``) catches this and returns ``False``
    per spec §5 (OQ-COLD fail-fast policy).
    """


# ── ConversationReferenceStore ─────────────────────────────────────────────────

_CONVREF_PREFIX = "hitl:teams:convref:"
_DEFAULT_CONVREF_TTL = 2_592_000  # 30 days


class ConversationReferenceStore:
    """Redis-backed store for Bot Framework ``ConversationReference`` objects.

    Keys: ``hitl:teams:convref:{email}`` → JSON-serialised
    ``ConversationReference``.

    The TTL is refreshed on every inbound activity (cache-on-contact, OQ-4)
    and the ``service_url`` is updated at the same time so proactive sends
    always use a fresh, trusted URL.

    Args:
        redis: An async Redis client (e.g. ``redis.asyncio.Redis``).
        ttl: Cache TTL in seconds (default: 30 days).
    """

    def __init__(self, redis: Any, ttl: int = _DEFAULT_CONVREF_TTL) -> None:
        self._redis = redis
        self._ttl = ttl
        self.logger = logging.getLogger(__name__)

    def _key(self, email: str) -> str:
        return f"{_CONVREF_PREFIX}{email}"

    async def get(self, email: str) -> Optional[ConversationReference]:
        """Return a cached ``ConversationReference``, or ``None`` on miss.

        Args:
            email: Recipient email address.

        Returns:
            Deserialized ``ConversationReference`` or ``None``.
        """
        try:
            raw = await self._redis.get(self._key(email))
            if raw is None:
                return None
            data = json.loads(raw)
            return ConversationReference.deserialize(data)
        except Exception:  # noqa: BLE001
            self.logger.exception("Error reading convref for %r", email)
            return None

    async def set(
        self,
        email: str,
        ref: ConversationReference,
        service_url: Optional[str] = None,
    ) -> None:
        """Store (or refresh) a ``ConversationReference``.

        Also refreshes the TTL and optionally updates the ``service_url``
        from the latest inbound activity (OQ-4).

        Args:
            email: Recipient email address.
            ref: The conversation reference to cache.
            service_url: Fresh service URL from the latest activity.
        """
        try:
            if service_url and ref.service_url != service_url:
                ref.service_url = service_url
            serialized = json.dumps(ref.serialize())
            await self._redis.setex(self._key(email), self._ttl, serialized)
        except Exception:  # noqa: BLE001
            self.logger.exception("Error storing convref for %r", email)

    async def refresh(
        self, email: str, service_url: Optional[str] = None
    ) -> None:
        """Refresh TTL (and optionally service_url) for an existing entry.

        Called on every inbound activity from the user (cache-on-contact).
        Does nothing if no entry exists yet.

        Args:
            email: Recipient email address.
            service_url: Updated service URL from the incoming activity.
        """
        existing = await self.get(email)
        if existing is not None:
            await self.set(email, existing, service_url=service_url)


# ── SentActivityStore ─────────────────────────────────────────────────────────

_SENT_PREFIX = "hitl:teams:sent:"
_DEFAULT_SENT_TTL = 86_400 * 7  # 7 days (interactions expire well before this)


class SentActivityStore:
    """Redis-backed map of sent HITL activities.

    Keys: ``hitl:teams:sent:{interaction_id}`` → JSON dict with
    ``{conversation_reference, activity_id, recipient}``.

    Used by ``cancel_interaction`` to call ``update_activity`` on the
    exact card that was sent, and by cross-worker deployments to look up
    sent cards without local state.

    Args:
        redis: An async Redis client.
        ttl: Entry TTL in seconds (default: 7 days).
    """

    def __init__(self, redis: Any, ttl: int = _DEFAULT_SENT_TTL) -> None:
        self._redis = redis
        self._ttl = ttl
        self.logger = logging.getLogger(__name__)

    def _key(self, interaction_id: str) -> str:
        return f"{_SENT_PREFIX}{interaction_id}"

    async def set(
        self,
        interaction_id: str,
        conversation_reference: ConversationReference,
        activity_id: str,
        recipient: str,
    ) -> None:
        """Store the sent-activity metadata for an interaction.

        Args:
            interaction_id: The HITL interaction UUID.
            conversation_reference: The conversation reference used to send.
            activity_id: The ``activity.id`` returned by the send call.
            recipient: The recipient email address.
        """
        try:
            payload = {
                "conversation_reference": conversation_reference.serialize(),
                "activity_id": activity_id,
                "recipient": recipient,
            }
            await self._redis.setex(
                self._key(interaction_id), self._ttl, json.dumps(payload)
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Error storing sent activity for interaction %r", interaction_id
            )

    async def get(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the sent-activity metadata for an interaction.

        Args:
            interaction_id: The HITL interaction UUID.

        Returns:
            Dict with keys ``conversation_reference`` (deserialized),
            ``activity_id``, and ``recipient``; or ``None`` on miss.
        """
        try:
            raw = await self._redis.get(self._key(interaction_id))
            if raw is None:
                return None
            data = json.loads(raw)
            data["conversation_reference"] = ConversationReference.deserialize(
                data["conversation_reference"]
            )
            return data
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Error reading sent activity for interaction %r", interaction_id
            )
            return None

    async def delete(self, interaction_id: str) -> None:
        """Delete a sent-activity entry (e.g. after successful cancel).

        Args:
            interaction_id: The HITL interaction UUID.
        """
        try:
            await self._redis.delete(self._key(interaction_id))
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Error deleting sent activity for %r", interaction_id
            )


# ── ProactiveMessenger ─────────────────────────────────────────────────────────

class ProactiveMessenger:
    """Orchestrates proactive 1:1 messaging via the Bot Framework.

    Two paths:
    - **Warm**: a ``ConversationReference`` exists in the cache →
      ``adapter.continue_conversation(ref, callback, app_id)``
    - **Cold**: no cache entry → ``adapter.create_conversation(...)`` to
      bootstrap the 1:1 (requires org-wide bot install, OQ-COLD), then
      captures and caches the new reference.

    On any failure the messenger raises :class:`ProactiveDeliveryError`;
    the caller (``TeamsHumanChannel``) catches it and returns ``False``.

    Args:
        adapter: A :class:`~.hitl_adapter.HitlCloudAdapter` instance.
        convref_store: The :class:`ConversationReferenceStore`.
        app_id: The HITL bot's Microsoft App ID.
        tenant_id: AAD tenant ID (for single-tenant create_conversation).
    """

    def __init__(
        self,
        adapter: Any,  # HitlCloudAdapter — typed Any for import flexibility
        convref_store: ConversationReferenceStore,
        app_id: str,
        tenant_id: str,
    ) -> None:
        self._adapter = adapter
        self._convref_store = convref_store
        self._app_id = app_id
        self._tenant_id = tenant_id
        self.logger = logging.getLogger(__name__)

    # ── Public API ─────────────────────────────────────────────────────────

    async def send(
        self,
        recipient: ResolvedTeamsUser,
        build_activity: Callable[[TurnContext], Awaitable[Optional[str]]],
    ) -> str:
        """Send a proactive message in the recipient's 1:1 thread.

        Attempts the warm path first.  Falls back to the cold path if no
        ``ConversationReference`` is cached.

        The ``build_activity`` callback receives a live ``TurnContext`` and
        must send the desired activity (e.g. an Adaptive Card), then return
        the resulting ``activity.id`` string (or ``None`` if unavailable).

        Args:
            recipient: Resolved AAD user (aad_object_id + email + service_url).
            build_activity: Async callable ``(TurnContext) -> Optional[str]``
                that sends the activity and returns the ``activity_id``.

        Returns:
            The ``activity_id`` string of the sent message.

        Raises:
            :class:`ProactiveDeliveryError`: On any delivery failure.
        """
        cached_ref = await self._convref_store.get(recipient.email)

        if cached_ref is not None:
            return await self._warm_send(cached_ref, recipient, build_activity)
        else:
            return await self._cold_send(recipient, build_activity)

    async def capture_reference(
        self, activity: Activity, email: str
    ) -> None:
        """Capture and cache a ``ConversationReference`` from an inbound activity.

        Called on every inbound activity to refresh the cache (cache-on-contact,
        OQ-4).  Also refreshes ``service_url``.

        Args:
            activity: The inbound Bot Framework activity.
            email: The sender's email (used as the cache key).
        """
        ref = TurnContext.get_conversation_reference(activity)
        await self._convref_store.set(
            email, ref, service_url=activity.service_url
        )

    # ── Internal paths ──────────────────────────────────────────────────────

    async def _warm_send(
        self,
        ref: ConversationReference,
        recipient: ResolvedTeamsUser,
        build_activity: Callable[[TurnContext], Awaitable[Optional[str]]],
    ) -> str:
        """Warm path: use an existing ``ConversationReference``.

        Args:
            ref: The cached conversation reference.
            recipient: Resolved AAD user.
            build_activity: Callback that sends the card and returns activity_id.

        Returns:
            The ``activity_id`` of the sent message.

        Raises:
            :class:`ProactiveDeliveryError`: On adapter failure.
        """
        service_url = ref.service_url or recipient.service_url
        if service_url:
            MicrosoftAppCredentials.trust_service_url(service_url)

        activity_id: list[Optional[str]] = [None]

        async def _callback(turn_context: TurnContext) -> None:
            result = await build_activity(turn_context)
            activity_id[0] = result

        try:
            await self._adapter.continue_conversation(
                ref, _callback, self._app_id
            )
        except Exception as exc:
            self.logger.error(
                "Warm proactive send failed for %r: %s", recipient.email, exc
            )
            raise ProactiveDeliveryError(
                f"continue_conversation failed: {exc}"
            ) from exc

        # Refresh TTL on successful contact
        await self._convref_store.refresh(
            recipient.email, service_url=service_url
        )

        return activity_id[0] or ""

    async def _cold_send(
        self,
        recipient: ResolvedTeamsUser,
        build_activity: Callable[[TurnContext], Awaitable[Optional[str]]],
    ) -> str:
        """Cold path: bootstrap a new 1:1 conversation via ``create_conversation``.

        Requires org-wide bot install (OQ-COLD).  On failure raises
        :class:`ProactiveDeliveryError` so the caller returns ``False``.

        Args:
            recipient: Resolved AAD user (aad_object_id + service_url).
            build_activity: Callback that sends the card and returns activity_id.

        Returns:
            The ``activity_id`` of the sent message.

        Raises:
            :class:`ProactiveDeliveryError`: On cold-create failure.
        """
        service_url = recipient.service_url or "https://smba.trafficmanager.net/emea/"
        MicrosoftAppCredentials.trust_service_url(service_url)

        conv_params = ConversationParameters(
            is_group=False,
            bot=ChannelAccount(id=self._app_id),
            members=[ChannelAccount(id=recipient.aad_object_id)],
            tenant_id=self._tenant_id,
        )

        captured_ref: list[Optional[ConversationReference]] = [None]
        activity_id: list[Optional[str]] = [None]

        async def _callback(turn_context: TurnContext) -> None:
            # Capture the new ConversationReference from the bootstrapped 1:1.
            ref = TurnContext.get_conversation_reference(turn_context.activity)
            captured_ref[0] = ref
            result = await build_activity(turn_context)
            activity_id[0] = result

        self.logger.info(
            "Cold-bootstrapping proactive 1:1 for %r (aad=%s)",
            recipient.email,
            recipient.aad_object_id,
        )

        try:
            await self._adapter.create_conversation(
                self._app_id,
                _callback,
                conv_params,
                service_url=service_url,
            )
        except Exception as exc:
            self.logger.error(
                "Cold create_conversation failed for %r: %s. "
                "Ensure the HITL bot is installed org-wide (OQ-COLD).",
                recipient.email,
                exc,
            )
            raise ProactiveDeliveryError(
                f"create_conversation failed for {recipient.email!r}: {exc}"
            ) from exc

        # Cache the captured reference for future warm sends.
        if captured_ref[0] is not None:
            await self._convref_store.set(
                recipient.email,
                captured_ref[0],
                service_url=service_url,
            )
        else:
            self.logger.warning(
                "Cold send succeeded but no ConversationReference was captured "
                "for %r — warm path will re-bootstrap next time.",
                recipient.email,
            )

        return activity_id[0] or ""
