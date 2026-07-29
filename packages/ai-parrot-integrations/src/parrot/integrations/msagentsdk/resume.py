"""MSAgentSDK conversation-reference store and proactive-resume helper.

FEAT-264 / TASK-1674

When a tool raises :class:`~parrot.auth.credentials.CredentialRequired` during
``ParrotM365Agent._handle_message``, the agent:

1. Saves a :class:`~parrot.human.suspended_store.SuspendedExecution` record
   (keyed by nonce = ``interaction_id``) so the original question can be
   replayed without user re-typing.
2. Saves a :class:`MsaConversationReference` record (also keyed by nonce and
   by ``user_id``) so the proactive-resume helper can route the reply back to
   the correct conversation.

On consent completion, two resume triggers call
:func:`proactive_resume`:

- **OAuth/OBO** — the Bot Framework Token Service sends a ``signin/verifyState``
  or ``signin/tokenExchange`` invoke. The agent looks up the conversation
  reference **by user_id** (since the invoke carries no nonce) and calls
  :func:`proactive_resume`.
- **Static key** — the OOB capture route (TASK-1677) calls
  :meth:`ParrotM365Agent.resume_by_nonce` passing the nonce extracted from
  the callback URL.

Proactive delivery uses the Microsoft 365 Agents SDK::

    await adapter.continue_conversation(agent_app_id, continuation_activity, callback)

Where ``continuation_activity.conversation.id`` and
``continuation_activity.service_url`` are required fields
(``_validate_continuation_activity`` check in the SDK).

The ``MsaConversationRefStore`` falls back to an in-memory dict when no Redis
client is supplied, which makes it usable in unit tests and local dev without
a Redis dependency.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field


__all__ = [
    "MsaConversationReference",
    "MsaConversationRefStore",
    "proactive_resume",
]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class MsaConversationReference(BaseModel):
    """Minimal conversation reference for MSAgentSDK proactive resume.

    Stored alongside the :class:`~parrot.human.suspended_store.SuspendedExecution`
    record so the resume helper can open a proactive turn to the correct
    conversation and channel.

    Attributes:
        nonce: Unique per-suspended-interaction ID (``uuid4().hex``).
            Used as the ``interaction_id`` in the companion
            :class:`~parrot.human.suspended_store.SuspendedExecution` record.
        conversation_id: Bot Framework conversation ID (from
            ``activity.conversation.id``). Required by the SDK's
            ``continue_conversation`` call.
        service_url: Channel service URL (from ``activity.service_url``).
            Required by the SDK's ``continue_conversation`` call.
        user_id: Canonical user identity at the time of suspension.
        channel_id: Bot Framework channel identifier (default: ``"msteams"``).
        created_at: UTC timestamp of record creation.
    """

    nonce: str
    conversation_id: str
    service_url: str
    user_id: str
    channel_id: str = "msteams"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class MsaConversationRefStore:
    """Async store for :class:`MsaConversationReference` records.

    Supports lookup by **nonce** (for static-key capture callback) and by
    **user_id** (for OAuth/OBO signin invokes where no nonce is available).

    Redis key format:
        - ``msasdk:convref:nonce:{nonce}``  → JSON-serialised reference
        - ``msasdk:convref:user:{user_id}`` → nonce string (pointer)

    Falls back to an in-memory dict when ``redis=None`` (unit tests / local dev).

    Args:
        redis: An async Redis client with ``setex`` / ``get`` / ``delete``
            coroutine methods. Pass ``None`` for the in-memory fallback.
    """

    _NONCE_PREFIX = "msasdk:convref:nonce:"
    _USER_PREFIX = "msasdk:convref:user:"
    _DEFAULT_TTL = 3_600  # 1 hour

    def __init__(self, redis: Any = None) -> None:
        self._redis = redis
        self._mem: dict[str, str] = {}
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Internal key builders
    # ------------------------------------------------------------------

    def _nonce_key(self, nonce: str) -> str:
        return f"{self._NONCE_PREFIX}{nonce}"

    def _user_key(self, user_id: str) -> str:
        return f"{self._USER_PREFIX}{user_id}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(
        self,
        ref: MsaConversationReference,
        ttl: int = _DEFAULT_TTL,
    ) -> None:
        """Persist a conversation reference under both nonce and user_id keys.

        Args:
            ref: The :class:`MsaConversationReference` to persist.
            ttl: Time-to-live in seconds (default: 3600 / 1 hour).
        """
        if ttl <= 0:
            ttl = self._DEFAULT_TTL
        payload = ref.model_dump_json()
        nonce_key = self._nonce_key(ref.nonce)
        user_key = self._user_key(ref.user_id)
        if self._redis is not None:
            await self._redis.setex(nonce_key, ttl, payload)
            await self._redis.setex(user_key, ttl, ref.nonce)
        else:
            self._mem[nonce_key] = payload
            self._mem[user_key] = ref.nonce
        self.logger.debug(
            "MsaConversationRefStore: saved nonce=%s user_id=%s",
            ref.nonce,
            ref.user_id,
        )

    async def load_by_nonce(
        self, nonce: str
    ) -> Optional[MsaConversationReference]:
        """Load a conversation reference by nonce.

        Args:
            nonce: The per-interaction nonce (``uuid4().hex``).

        Returns:
            The :class:`MsaConversationReference` if found, ``None`` otherwise.
        """
        key = self._nonce_key(nonce)
        raw: Optional[str] = (
            await self._redis.get(key) if self._redis else self._mem.get(key)
        )
        if not raw:
            return None
        return MsaConversationReference.model_validate_json(raw)

    async def load_by_user(
        self, user_id: str
    ) -> Optional[MsaConversationReference]:
        """Load a conversation reference by canonical user_id.

        Used by OAuth/OBO resume triggers (``signin/verifyState``,
        ``signin/tokenExchange``) where the nonce is not present in the
        incoming invoke activity.

        Args:
            user_id: Canonical user identity.

        Returns:
            The :class:`MsaConversationReference` if found, ``None`` otherwise.
        """
        user_key = self._user_key(user_id)
        nonce: Optional[str] = (
            await self._redis.get(user_key)
            if self._redis
            else self._mem.get(user_key)
        )
        if not nonce:
            return None
        return await self.load_by_nonce(nonce)

    async def delete(self, ref: MsaConversationReference) -> None:
        """Remove both keys for a conversation reference.

        Args:
            ref: The :class:`MsaConversationReference` to remove.
        """
        nonce_key = self._nonce_key(ref.nonce)
        user_key = self._user_key(ref.user_id)
        if self._redis is not None:
            await self._redis.delete(nonce_key, user_key)
        else:
            self._mem.pop(nonce_key, None)
            self._mem.pop(user_key, None)
        self.logger.debug(
            "MsaConversationRefStore: deleted nonce=%s user_id=%s",
            ref.nonce,
            ref.user_id,
        )


# ---------------------------------------------------------------------------
# Proactive-resume helper
# ---------------------------------------------------------------------------


async def proactive_resume(
    adapter: Any,
    agent_app_id: str,
    conv_ref: MsaConversationReference,
    parrot_agent: Any,
    question: str,
    session_id: str,
    user_id: str,
    broker: Optional[Any] = None,
    on_sent: Optional[Callable[[Any], Awaitable[None]]] = None,
) -> None:
    """Re-run the suspended ask() and proactively deliver the response.

    Confirmed proactive SDK API (FEAT-264 TASK-1674 — open question §8)::

        await adapter.continue_conversation(
            agent_app_id,          # str — Microsoft App ID
            continuation_activity, # Activity with .conversation.id + .service_url
            callback,              # async (TurnContext) -> None
        )

    The ``continuation_activity`` must carry:
    - ``continuation_activity.conversation.id`` — the original conversation
    - ``continuation_activity.service_url`` — required by SDK validation

    On credential failure during the re-run, a fallback error message is sent
    rather than raising (no card loop).

    Args:
        adapter: The ``CloudAdapter`` instance from ``MSAgentSDKWrapper``.
        agent_app_id: Microsoft App ID (``config.client_id``).
        conv_ref: Stored :class:`MsaConversationReference` with conversation
            context for the proactive send.
        parrot_agent: The ai-parrot bot to call ``ask()`` on.
        question: The original user question to replay (no re-typing required).
        session_id: Agent session identifier (forwarded to ``ask()``).
        user_id: Canonical user identity (forwarded to ``ask()``).
        broker: Optional :class:`~parrot.auth.broker.CredentialBroker` — passed
            as the broker seam kwargs to ``ask()`` so the re-run can resolve
            credentials.
        on_sent: Optional async callback invoked with the ``TurnContext`` after
            the reply is sent.  Used in tests to capture the context.
    """
    from microsoft_agents.activity import Activity, ActivityTypes, TextFormatTypes

    # Build the minimal continuation activity required by the SDK.
    # conversation.id routes to the correct conversation thread;
    # service_url is required by _validate_continuation_activity.
    continuation_activity = Activity(
        type=ActivityTypes.event,
        conversation={"id": conv_ref.conversation_id},
        service_url=conv_ref.service_url,
        channel_id=conv_ref.channel_id,
    )

    # FEAT-264 Issue 6: the broker is registered on tool_manager at init time,
    # so the low-level _broker/_cred_channel/_cred_user_id kwargs need not be
    # threaded manually. But the re-run still has to tell the broker WHO the
    # caller is: ToolManager.execute_tool reads ``_cred_user_id`` / ``_cred_channel``
    # from the LLM client's ``_permission_context``, which ``ask()`` populates
    # from its ``permission_context`` argument. Without it the seam fails closed
    # ("no user identity provided") even though consent just completed and the
    # credential is now stored. The ``broker`` parameter is kept for backward
    # compatibility but is no longer forwarded to ask().
    from parrot.auth.permission import UserSession, PermissionContext

    resume_pctx = PermissionContext(
        session=UserSession(
            user_id=user_id,
            tenant_id="msagentsdk",
            roles=frozenset(),
        ),
        channel="msagentsdk",
    )

    async def _callback(turn_context: Any) -> None:
        try:
            response = await parrot_agent.ask(
                question=question,
                session_id=session_id,
                user_id=user_id,
                permission_context=resume_pctx,
            )
            from .agent import render_reply_text

            reply_text = render_reply_text(response) if response else "(no response)"
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text=reply_text,
                    text_format=TextFormatTypes.plain,
                )
            )
        except Exception:  # noqa: BLE001
            logger = logging.getLogger(__name__)
            logger.error(
                "proactive_resume: ask() failed for user=%s — sending fallback",
                user_id,
                exc_info=True,
            )
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    text="Sorry, I encountered an error. Please try again.",
                    text_format=TextFormatTypes.plain,
                )
            )
        finally:
            if on_sent is not None:
                await on_sent(turn_context)

    logger = logging.getLogger(__name__)
    logger.info(
        "proactive_resume: continue_conversation for user=%s conv=%s",
        user_id,
        conv_ref.conversation_id,
    )
    await adapter.continue_conversation(agent_app_id, continuation_activity, _callback)
