"""
Bridge between ai-parrot AbstractBot and the Microsoft 365 Agents SDK protocol.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

from navconfig.logging import logging

from parrot.integrations.msagentsdk import cards
from parrot.integrations.msagentsdk.semantic import SemanticUIResult

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.auth.context import UserContext
    from parrot.auth.broker import CredentialBroker
    from parrot.auth.identity import CanonicalIdentityMapper
    from parrot.human.suspended_store import SuspendedExecutionStore
    from .auth import BFTokenServiceResolver
    from .resume import MsaConversationRefStore


def render_reply_text(response: Any) -> str:
    """Produce human-readable reply text from an ``AIMessage``.

    ``parrot_agent.ask()`` returns an :class:`~parrot.models.responses.AIMessage`
    whose ``content``/``output`` is a *structured Pydantic model* whenever the
    bot is configured with a ``structured_output`` schema. ``str()`` of such a
    model yields its field-by-field repr — e.g.
    ``explanation='...' data=None code=None metadata=None`` — which leaks into
    the channel as garbled pseudo-JSON instead of a clean message. This helper
    resolves the model's natural-language text instead, in priority order:

    1. ``AIMessage.response`` — the plain-text response the model produced
       before any structured reformatting (``AIMessageFactory`` sets this from
       the raw ``text_response``).
    2. A text-ish field pulled from the structured payload
       (``structured_output`` first, then ``output``) when (1) is empty — covers
       arbitrary downstream schemas that carry their prose in a named field
       (``explanation``, ``answer``, ``text`` …).
    3. ``AIMessage.to_text`` — handles plain-str / dict / DataFrame outputs.
    4. ``str()`` of the payload as an absolute last resort.

    Args:
        response: The object returned by ``parrot_agent.ask()`` (normally an
            ``AIMessage``); may be any object or ``None``.

    Returns:
        A display string safe to send verbatim to the channel. Returns an empty
        string only when *response* itself is falsy.
    """
    if not response:
        return ""

    # 1. Prefer the plain-text response field.
    text = getattr(response, "response", None)
    if isinstance(text, str) and text.strip():
        return text

    # 2. Pull a human-text field out of a structured Pydantic payload.
    from pydantic import BaseModel  # local import: keep module import-light

    payload = getattr(response, "structured_output", None)
    if payload is None:
        payload = getattr(response, "output", None)
    if isinstance(payload, BaseModel):
        for field_name in (
            "explanation", "answer", "text", "message",
            "response", "content", "summary", "output",
        ):
            value = getattr(payload, field_name, None)
            if isinstance(value, str) and value.strip():
                return value

    # 3. Fall back to AIMessage.to_text (str / dict / DataFrame outputs).
    to_text = getattr(response, "to_text", None)
    if isinstance(to_text, str) and to_text.strip():
        return to_text

    # 4. Absolute last resort — never send an empty message.
    return str(payload if payload is not None else response)


class ParrotM365Agent:
    """Bridges ai-parrot AbstractBot to the Microsoft 365 Agent protocol.

    Implements the ``Agent`` protocol from ``microsoft_agents.hosting.core``
    (a single ``on_turn(context: TurnContext)`` coroutine). This class is
    intentionally thin: it extracts the message text, sender identity, and
    conversation ID from the inbound Activity envelope, delegates to
    ``parrot_agent.ask()``, and sends the reply back via
    ``context.send_activity()``.

    All ``microsoft_agents.*`` imports are lazy (inside methods) so the
    package can be imported without the SDK installed.

    Identity extraction prefers the Entra ``aad_object_id`` (stable across
    sessions and surfaces) over the channel-level ``from_property.id``, so
    the Bot Framework Token Service can key per-user tokens correctly.

    Attributes:
        parrot_agent: The ai-parrot bot instance to delegate to.
        welcome_message: Text sent when a new member joins a conversation.
        _resolver: Optional credential resolver for per-user token acquisition.
        _audit_ledger: Optional audit ledger for credential usage recording.
        logger: Logger instance scoped to this bridge.
    """

    def __init__(
        self,
        parrot_agent: AbstractBot,
        welcome_message: Optional[str] = None,
        resolver: Optional["BFTokenServiceResolver"] = None,
        audit_ledger: Optional[Any] = None,
        broker: Optional["CredentialBroker"] = None,
        identity_mapper: Optional["CanonicalIdentityMapper"] = None,
        suspended_store: Optional["SuspendedExecutionStore"] = None,
        conv_ref_store: Optional["MsaConversationRefStore"] = None,
        adapter: Optional[Any] = None,
        agent_app_id: Optional[str] = None,
        enable_semantic_cards: bool = True,
        max_table_rows: int = 15,
        max_card_bytes: int = 25_000,
    ) -> None:
        """Initialise the bridge.

        Args:
            parrot_agent: Any ``AbstractBot`` subclass that implements
                ``ask(question, session_id, user_id) -> AIMessage``.
            welcome_message: Message sent to new conversation members.
                Defaults to a generic greeting if not provided.
            resolver: Optional :class:`BFTokenServiceResolver` for per-user
                token acquisition from the Bot Framework Token Service.
                When ``None``, user-token acquisition is disabled.
            audit_ledger: Optional :class:`AuditLedger` for recording
                per-invocation credential usage. When ``None``, audit logging
                is disabled.
            broker: Optional :class:`~parrot.auth.broker.CredentialBroker`
                (FEAT-264).  When supplied, tool credential resolution flows
                through the broker during ``ask()``.  Takes precedence over
                the legacy ``resolver`` path.
            identity_mapper: Optional
                :class:`~parrot.auth.identity.CanonicalIdentityMapper` for
                cross-surface identity normalisation (FEAT-264 / TASK-1671).
            suspended_store: Optional
                :class:`~parrot.human.suspended_store.SuspendedExecutionStore`
                for persisting the original question while the user completes
                credential consent (FEAT-264 / TASK-1674).  When ``None``,
                suspend/resume is disabled (card is emitted but no proactive
                reply is sent after consent).
            conv_ref_store: Optional
                :class:`~.resume.MsaConversationRefStore` for persisting the
                Bot Framework conversation reference so proactive replies can
                be routed back to the correct conversation (FEAT-264 /
                TASK-1674).  When ``None``, proactive resume is disabled.
            adapter: Optional ``CloudAdapter`` instance used for proactive
                resume (FEAT-264 / TASK-1674).  Must be supplied alongside
                ``agent_app_id`` and the stores for resume to function.
            agent_app_id: Microsoft App ID (``client_id``) required by
                ``adapter.continue_conversation()`` for proactive delivery.
            enable_semantic_cards: If True (default), a ``SemanticUIResult``
                on the agent's response (FEAT-303) is rendered as an
                Adaptive Card; if False, the plain-text path is always used.
            max_table_rows: Maximum table rows rendered in a Semantic UI
                table card before truncating with a "showing N of M" note.
            max_card_bytes: Maximum serialized Semantic UI card size in
                bytes; exceeding it triggers the plain-text fallback.
        """
        self.parrot_agent = parrot_agent
        self.welcome_message = welcome_message or "Hello! I'm ready to help."
        self._resolver = resolver
        self._audit_ledger = audit_ledger
        self._broker: Optional["CredentialBroker"] = broker
        self._identity_mapper: Optional["CanonicalIdentityMapper"] = identity_mapper
        self._suspended_store: Optional["SuspendedExecutionStore"] = suspended_store
        self._conv_ref_store: Optional["MsaConversationRefStore"] = conv_ref_store
        self._adapter: Optional[Any] = adapter
        self._agent_app_id: Optional[str] = agent_app_id
        self._cards_enabled: bool = enable_semantic_cards
        self._max_table_rows: int = max_table_rows
        self._max_card_bytes: int = max_card_bytes
        self.logger = logging.getLogger(
            f"ParrotM365Agent.{type(parrot_agent).__name__}"
        )

        # FEAT-264 Issue 6: register the broker on the agent's tool_manager once
        # so the ContextVar seam (AbstractTool.execute) can resolve credentials
        # transparently — no need to thread _broker/_cred_channel/_cred_user_id
        # through ask() kwargs on every call.
        if broker is not None and hasattr(parrot_agent, "tool_manager"):
            parrot_agent.tool_manager.set_broker(broker)

    async def on_turn(self, context) -> None:
        """Handle an incoming Activity from the Microsoft 365 Agents SDK.

        Routes activities by type:
        - ``message`` → ``_handle_message()``
        - ``conversationUpdate`` → ``_handle_conversation_update()``
        - ``invoke`` → ``_handle_signin_verify()``, ``_handle_signin_exchange()``,
          or ``_handle_adaptive_card_action()`` (FEAT-303) depending on the
          invoke name.
        - Other types → logged at DEBUG and ignored.

        Args:
            context: ``TurnContext`` from the MS Agent SDK (not type-annotated
                here to keep the import lazy).
        """
        from microsoft_agents.activity import ActivityTypes

        activity = context.activity
        activity_type = activity.type

        if activity_type in (ActivityTypes.message, "message"):
            await self._handle_message(context)
        elif activity_type in (ActivityTypes.conversation_update, "conversationUpdate"):
            await self._handle_conversation_update(context)
        elif activity_type in ("invoke",):
            name = getattr(activity, "name", None) or ""
            if name == "signin/verifyState":
                await self._handle_signin_verify(context)
            elif name == "signin/tokenExchange":
                await self._handle_signin_exchange(context)
            elif name == "adaptiveCard/action":
                await self._handle_adaptive_card_action(context)
            else:
                self.logger.debug("Ignoring invoke type: %s", name)
        else:
            self.logger.debug("Ignoring activity type: %s", activity_type)

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    def _extract_user_id(self, activity: Any) -> str:
        """Extract canonical user identity from an Activity.

        Prefers ``aad_object_id`` (Entra identity) from ``from_property`` as
        the stable canonical key for the Bot Framework Token Service. Falls
        back to the channel-level ``from_property.id`` when the Entra id is
        not present (e.g. anonymous / non-Teams channels).

        Args:
            activity: The incoming Activity object.

        Returns:
            A non-empty string user identifier.
        """
        from_prop = getattr(activity, "from_property", None)
        if from_prop is None:
            return "anonymous"
        # Try aad_object_id (Entra identity — preferred canonical key)
        aad_id = getattr(from_prop, "aad_object_id", None)
        if not aad_id:
            # Some SDK versions expose it as camelCase
            aad_id = getattr(from_prop, "aadObjectId", None)
        if aad_id:
            return str(aad_id)
        # Fall back to the channel-level user identifier
        channel_id = getattr(from_prop, "id", None)
        return channel_id or "anonymous"

    def _build_user_context(self, activity: Any) -> "UserContext":
        """Build a :class:`UserContext` from the Activity's sender identity.

        Args:
            activity: The incoming Activity object.

        Returns:
            A :class:`UserContext` with ``channel="msagentsdk"`` and
            ``user_id`` derived from :meth:`_extract_user_id`.
        """
        from parrot.auth.context import UserContext

        user_id = self._extract_user_id(activity)
        display_name: Optional[str] = None
        from_prop = getattr(activity, "from_property", None)
        if from_prop is not None:
            display_name = getattr(from_prop, "name", None)
        session_id: Optional[str] = (
            activity.conversation.id if getattr(activity, "conversation", None) else None
        )
        return UserContext(
            channel="msagentsdk",
            user_id=user_id,
            display_name=display_name,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _handle_message(self, context) -> None:
        """Route a ``message`` activity to the parrot agent and reply.

        Extracts the canonical user identity (``aad_object_id`` preferred),
        builds a :class:`PermissionContext`, sets ``_pctx_var``, and passes a
        :class:`RequestContext` to ``ask()`` so downstream tools can access
        the per-user identity.

        If a tool raises :class:`CredentialRequired`, emits a native OAuthCard
        sign-in activity instead of an error. Never falls back to service
        identity for a per-user tool.

        If the message text is empty or whitespace-only the method returns
        immediately without calling ``ask()`` to avoid unnecessary LLM calls.

        Args:
            context: ``TurnContext`` carrying the inbound message Activity.
        """
        activity = context.activity
        text: Optional[str] = activity.text

        if not text or not text.strip():
            self.logger.debug("Received empty message — skipping ask()")
            return

        raw_user_id: str = self._extract_user_id(activity)

        # FEAT-264 / TASK-1671 — canonical identity normalisation via mapper.
        if self._identity_mapper is not None:
            from_prop = getattr(activity, "from_property", None)
            raw_dict: dict = {}
            if from_prop is not None:
                raw_dict = {
                    "aad_object_id": getattr(from_prop, "aad_object_id", None)
                        or getattr(from_prop, "aadObjectId", None),
                    "from_id": getattr(from_prop, "id", None),
                    "from_email": getattr(from_prop, "email", None),
                }
            canonical = self._identity_mapper.to_canonical(raw_dict)
            user_id: str = canonical if canonical is not None else raw_user_id
        else:
            user_id = raw_user_id

        session_id: Optional[str] = (
            activity.conversation.id if getattr(activity, "conversation", None) else None
        )

        self.logger.info(
            "Message from user=%s session=%s", user_id, session_id
        )

        # Build permission context and set ContextVar for downstream tools.
        from parrot.auth.permission import UserSession, PermissionContext
        from parrot.auth.context import _pctx_var
        from parrot.utils.helpers import RequestContext

        user_session = UserSession(
            user_id=user_id,
            tenant_id="msagentsdk",
            roles=frozenset(),
        )
        pctx = PermissionContext(
            session=user_session,
            channel="msagentsdk",
        )
        token = _pctx_var.set(pctx)
        request_ctx = RequestContext(user_id=user_id, session_id=session_id)

        # FEAT-264 Issue 6: the broker is registered on tool_manager.__init__ so
        # the low-level _broker/_cred_channel/_cred_user_id kwargs need not be
        # threaded manually. But the caller identity still has to reach the LLM
        # client: ``ask()`` forwards ``permission_context`` to
        # ``client._permission_context``, which is where ToolManager.execute_tool
        # reads ``_cred_user_id`` / ``_cred_channel`` from. Setting ``_pctx_var``
        # alone is NOT enough — nothing in the ask()→execute_tool path reads it —
        # so the broker seam would fail closed ("no user identity provided").
        try:
            response = await self.parrot_agent.ask(
                question=text.strip(),
                session_id=session_id,
                user_id=user_id,
                ctx=request_ctx,
                permission_context=pctx,
            )
            semantic_result = self._extract_semantic_result(response)
            if semantic_result is None or not self._cards_enabled:
                await self._send_text(context, render_reply_text(response))
            else:
                await self._send_semantic_card(context, semantic_result, response)
        except Exception as exc:  # noqa: BLE001
            # Canonical CredentialRequired (FEAT-264 / TASK-1667).
            # Raised by AbstractTool.execute() seam when broker returns NeedsAuth.
            from parrot.auth.credentials import CredentialRequired

            if isinstance(exc, CredentialRequired):
                auth_kind = getattr(exc, "auth_kind", "oauth2")
                provider = getattr(exc, "provider", "")
                auth_url = getattr(exc, "auth_url", "") or ""

                # FEAT-264 / TASK-1674 — suspend the interaction so we can
                # proactively deliver the result after consent, without the
                # user having to retype the original question.
                nonce: Optional[str] = None
                if (
                    self._suspended_store is not None
                    and self._conv_ref_store is not None
                ):
                    nonce = uuid.uuid4().hex
                    await self._suspend_interaction(
                        nonce=nonce,
                        question=text.strip(),
                        session_id=session_id or "",
                        user_id=user_id,
                        context=context,
                    )
                    # For static_key: embed the nonce so the capture route
                    # (TASK-1677) can call resume_by_nonce(nonce).
                    if auth_kind == "static_key" and auth_url:
                        sep = "&" if "?" in auth_url else "?"
                        auth_url = f"{auth_url}{sep}nonce={nonce}"

                self.logger.info(
                    "CredentialRequired provider=%s auth_kind=%s nonce=%s — rendering card",
                    provider,
                    auth_kind,
                    nonce,
                )
                if auth_kind == "static_key":
                    await self._emit_adaptive_card(context, auth_url, provider)
                else:
                    # oauth2 / obo → native OAuthCard (connection name = provider_id)
                    await self._emit_oauth_card(context, provider, provider)
            else:
                self.logger.error(
                    "Error processing message from user=%s: %s",
                    user_id,
                    exc,
                    exc_info=True,
                )
                await self._send_text(
                    context, "Sorry, I encountered an error. Please try again."
                )
        finally:
            _pctx_var.reset(token)

    # ------------------------------------------------------------------
    # Semantic UI Model card seam (FEAT-303)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_semantic_result(response: Any) -> Optional[SemanticUIResult]:
        """Extract a `SemanticUIResult` from an `AIMessage` response.

        Checks `response.structured_output` first, then `response.data`, in
        that priority order. Only an actual `SemanticUIResult` instance is
        accepted — no dict duck-typing (spec §7).

        Args:
            response: The `AIMessage` returned by `parrot_agent.ask()`.

        Returns:
            The `SemanticUIResult` instance, or `None` when neither carrier
            holds one.
        """
        structured_output = getattr(response, "structured_output", None)
        if isinstance(structured_output, SemanticUIResult):
            return structured_output
        data = getattr(response, "data", None)
        if isinstance(data, SemanticUIResult):
            return data
        return None

    async def _send_semantic_card(
        self, context, result: SemanticUIResult, response: Any
    ) -> None:
        """Render `result` as an Adaptive Card and send it, with fallback.

        Renders via `cards.render_card()` and sends a single message
        Activity carrying the adaptive card attachment plus the plain-text
        rendering (`cards.render_text()`) as the channel fallback in
        `Activity.text` — same envelope as `_emit_adaptive_card`
        (agent.py:729-738).

        Any exception in the render/send path is logged and degrades to
        `_send_text(render_text(result))`; if even that somehow raises, a
        final fallback sends `render_reply_text(response)`. No exception may
        escape this method.

        Args:
            context: `TurnContext` to send the reply through.
            result: The `SemanticUIResult` to render.
            response: The original `AIMessage`, used only for the
                last-resort text fallback.
        """
        from microsoft_agents.activity import Activity, ActivityTypes

        try:
            card = cards.render_card(
                result,
                max_table_rows=self._max_table_rows,
                max_card_bytes=self._max_card_bytes,
            )
            attachment = cards.build_card_attachment(card)
            fallback_text = cards.render_text(result)
            reply = Activity(
                type=ActivityTypes.message,
                text=fallback_text,
                attachments=[attachment],
            )
            await context.send_activity(reply)
            self.logger.info(
                "Semantic UI card sent: result_type=%s actions=%d",
                result.payload.result_type,
                len(result.actions),
            )
        except Exception as exc:  # noqa: BLE001 - card path must never break the turn
            self.logger.error(
                "Semantic UI card render/send failed — falling back to text: %s",
                exc,
                exc_info=True,
            )
            try:
                await self._send_text(context, cards.render_text(result))
            except Exception:  # noqa: BLE001 - belt-and-braces last resort
                self.logger.error(
                    "render_text() fallback also failed — sending raw content",
                    exc_info=True,
                )
                await self._send_text(context, render_reply_text(response))

    # ------------------------------------------------------------------
    # Invoke handlers (sign-in round-trip)
    # ------------------------------------------------------------------

    async def _handle_signin_verify(self, context) -> None:
        """Handle a ``signin/verifyState`` invoke activity.

        The Bot Framework Token Service sends this activity after the user
        completes the OAuth sign-in. The token is already stored in the token
        service at this point; we acknowledge with a 200 response and then
        proactively deliver the deferred reply.

        FEAT-264 / TASK-1674: after acknowledging the invoke, looks up the
        conversation reference by user_id and calls :func:`.resume.proactive_resume`
        to re-run the original question without user re-typing.

        Args:
            context: ``TurnContext`` carrying the ``invoke`` Activity.
        """
        activity = context.activity
        value = getattr(activity, "value", None) or {}
        state = (
            value.get("state")
            if isinstance(value, dict)
            else getattr(value, "state", None)
        )
        user_id = self._extract_user_id(activity)
        self.logger.info(
            "signin/verifyState received: user=%s state_present=%s",
            user_id,
            bool(state),
        )
        await self._send_invoke_response(context, status_code=200)
        # Proactive resume — look up by user_id (no nonce in signin invoke).
        await self._try_resume_by_user(user_id)

    async def _handle_signin_exchange(self, context) -> None:
        """Handle a ``signin/tokenExchange`` invoke activity.

        The Bot Framework Token Service sends this activity to complete a Teams
        SSO token exchange. The service performs the exchange server-side; we
        acknowledge with a 200 response and then proactively deliver the
        deferred reply.

        FEAT-264 / TASK-1674: after acknowledging the invoke, looks up the
        conversation reference by user_id and calls :func:`.resume.proactive_resume`.

        Args:
            context: ``TurnContext`` carrying the ``invoke`` Activity.
        """
        activity = context.activity
        value = getattr(activity, "value", None) or {}
        connection_name = (
            value.get("connectionName")
            if isinstance(value, dict)
            else getattr(value, "connection_name", None)
        )
        user_id = self._extract_user_id(activity)
        self.logger.info(
            "signin/tokenExchange received: user=%s connection=%s",
            user_id,
            connection_name,
        )
        await self._send_invoke_response(context, status_code=200)
        # Proactive resume — look up by user_id (no nonce in signin invoke).
        await self._try_resume_by_user(user_id)

    async def _handle_adaptive_card_action(self, context) -> None:
        """Handle an ``adaptiveCard/action`` invoke (FEAT-303 compatibility shim).

        Some surfaces (notably M365 Copilot) may deliver a card action click
        as an ``adaptiveCard/action`` Universal-Action invoke instead of a
        normal ``messageBack`` message activity. This shim acknowledges the
        invoke immediately (Bot Framework requires a timely response) and
        then extracts the natural-language prompt embedded in the action's
        ``data`` payload (built by
        :func:`~parrot.integrations.msagentsdk.cards.render_card`'s action
        builder), feeding it through the normal ``_handle_message()`` path so
        it reuses identity extraction, permission context, broker wiring,
        and the Semantic UI card seam wholesale.

        ``messageBack`` clicks (the primary round-trip) need no handling
        here — Teams/Copilot deliver those as ordinary ``message``
        activities that already route to ``_handle_message()``.

        Args:
            context: ``TurnContext`` carrying the ``adaptiveCard/action``
                invoke Activity.
        """
        await self._send_invoke_response(context, status_code=200)

        activity = context.activity
        value = getattr(activity, "value", None) or {}
        action = (
            value.get("action")
            if isinstance(value, dict)
            else getattr(value, "action", None)
        ) or {}
        data = (
            action.get("data")
            if isinstance(action, dict)
            else getattr(action, "data", None)
        ) or {}

        prompt: Optional[str] = None
        if isinstance(data, dict):
            prompt = data.get("feat303_prompt")
            if not prompt:
                msteams = data.get("msteams") or {}
                prompt = msteams.get("text") if isinstance(msteams, dict) else None
        else:
            prompt = getattr(data, "feat303_prompt", None)
            if not prompt:
                msteams = getattr(data, "msteams", None)
                prompt = getattr(msteams, "text", None) if msteams else None

        if not prompt:
            self.logger.warning(
                "adaptiveCard/action invoke had no extractable prompt — ignoring"
            )
            return

        activity.text = prompt
        await self._handle_message(context)

    # ------------------------------------------------------------------
    # Suspend / resume (FEAT-264 / TASK-1674)
    # ------------------------------------------------------------------

    async def _suspend_interaction(
        self,
        *,
        nonce: str,
        question: str,
        session_id: str,
        user_id: str,
        context: Any,
    ) -> None:
        """Persist a suspended execution record and a conversation reference.

        Called when :class:`~parrot.auth.credentials.CredentialRequired` is
        raised and both stores are configured.  The original question is stored
        in :attr:`~parrot.human.suspended_store.SuspendedExecution.messages` so
        the resume helper can replay it without user re-typing.

        Args:
            nonce: Unique interaction ID (``uuid4().hex``).
            question: The original user question to replay.
            session_id: Bot Framework conversation ID.
            user_id: Canonical user identity.
            context: SDK ``TurnContext`` (for ``service_url`` and
                ``channel_id``).
        """
        from parrot.human.suspended_store import SuspendedExecution
        from .resume import MsaConversationReference

        suspension = SuspendedExecution(
            interaction_id=nonce,
            session_id=session_id,
            user_id=user_id,
            agent_name=type(self.parrot_agent).__name__,
            tool_call_id=nonce,
            # Store the original question so the resume can replay it.
            messages=[{"role": "user", "content": question}],
        )
        await self._suspended_store.save(suspension, ttl=3_600)  # type: ignore[union-attr]

        activity = getattr(context, "activity", None)
        conv_ref = MsaConversationReference(
            nonce=nonce,
            conversation_id=session_id,
            service_url=getattr(activity, "service_url", "") or "",
            user_id=user_id,
            channel_id=getattr(activity, "channel_id", "msteams") or "msteams",
        )
        await self._conv_ref_store.save(conv_ref, ttl=3_600)  # type: ignore[union-attr]
        self.logger.info(
            "Suspended nonce=%s user=%s session=%s",
            nonce,
            user_id,
            session_id,
        )

    async def _try_resume_by_user(self, user_id: str) -> None:
        """Attempt proactive resume for a user after OAuth/OBO sign-in.

        Looks up the conversation reference and suspended execution by
        ``user_id``, then calls :func:`.resume.proactive_resume`.  If the
        stores are not configured or no suspended record exists, this is a
        no-op.

        Args:
            user_id: Canonical user identity from the signin invoke.
        """
        if (
            self._conv_ref_store is None
            or self._suspended_store is None
            or self._adapter is None
            or self._agent_app_id is None
        ):
            return

        conv_ref = await self._conv_ref_store.load_by_user(user_id)
        if conv_ref is None:
            self.logger.debug(
                "_try_resume_by_user: no suspended conv ref for user=%s", user_id
            )
            return

        suspension = await self._suspended_store.load(conv_ref.nonce)
        if suspension is None:
            self.logger.warning(
                "_try_resume_by_user: conv ref found but no suspension for nonce=%s",
                conv_ref.nonce,
            )
            return

        question = (
            suspension.messages[0].get("content", "")
            if suspension.messages
            else ""
        )
        self.logger.info(
            "Proactive resume: nonce=%s user=%s question=%r",
            conv_ref.nonce,
            user_id,
            question[:40],
        )

        # Clean up before resuming to prevent duplicate deliveries.
        await self._conv_ref_store.delete(conv_ref)
        await self._suspended_store.delete(conv_ref.nonce)

        from .resume import proactive_resume

        await proactive_resume(
            adapter=self._adapter,
            agent_app_id=self._agent_app_id,
            conv_ref=conv_ref,
            parrot_agent=self.parrot_agent,
            question=question,
            session_id=suspension.session_id,
            user_id=user_id,
            broker=self._broker,
        )

    async def resume_by_nonce(self, nonce: str) -> bool:
        """Attempt proactive resume for a static-key capture callback.

        Called by the OOB capture route (TASK-1677) after the user has
        submitted their API key.  Looks up the conversation reference and
        suspended execution by nonce, then calls
        :func:`.resume.proactive_resume`.

        Args:
            nonce: The nonce embedded in the capture URL
                (``?nonce=<nonce>``).

        Returns:
            ``True`` if a suspended interaction was found and resume was
            attempted, ``False`` if no record was found (already completed
            or expired).
        """
        if (
            self._conv_ref_store is None
            or self._suspended_store is None
            or self._adapter is None
            or self._agent_app_id is None
        ):
            self.logger.debug(
                "resume_by_nonce: stores/adapter not configured — skipping"
            )
            return False

        conv_ref = await self._conv_ref_store.load_by_nonce(nonce)
        if conv_ref is None:
            self.logger.debug(
                "resume_by_nonce: no conv ref for nonce=%s", nonce
            )
            return False

        suspension = await self._suspended_store.load(nonce)
        if suspension is None:
            self.logger.warning(
                "resume_by_nonce: conv ref found but no suspension for nonce=%s",
                nonce,
            )
            return False

        question = (
            suspension.messages[0].get("content", "")
            if suspension.messages
            else ""
        )
        user_id = conv_ref.user_id
        self.logger.info(
            "Proactive resume by nonce: nonce=%s user=%s question=%r",
            nonce,
            user_id,
            question[:40],
        )

        # Clean up before resuming.
        await self._conv_ref_store.delete(conv_ref)
        await self._suspended_store.delete(nonce)

        from .resume import proactive_resume

        await proactive_resume(
            adapter=self._adapter,
            agent_app_id=self._agent_app_id,
            conv_ref=conv_ref,
            parrot_agent=self.parrot_agent,
            question=question,
            session_id=suspension.session_id,
            user_id=user_id,
            broker=self._broker,
        )
        return True

    @staticmethod
    async def _send_invoke_response(context, status_code: int = 200) -> None:
        """Send an invoke response activity.

        Args:
            context: ``TurnContext`` used to emit the response.
            status_code: HTTP-style status code for the invoke response.
        """
        from microsoft_agents.activity import Activity

        # ActivityTypes.invoke_response is not available in all SDK versions;
        # fall back to the raw string which Bot Framework always recognises.
        try:
            from microsoft_agents.activity import ActivityTypes
            invoke_response_type = ActivityTypes.invoke_response
        except AttributeError:
            invoke_response_type = "invokeResponse"

        response = Activity(type=invoke_response_type)
        response.value = {"status": status_code}
        await context.send_activity(response)

    # ------------------------------------------------------------------
    # OAuth sign-in card
    # ------------------------------------------------------------------

    async def _emit_oauth_card(
        self,
        context,
        connection_name: str,
        tool: str,
    ) -> None:
        """Emit a native OAuthCard sign-in activity.

        The OAuthCard triggers the Bot Framework Token Service's hosted OAuth
        flow. The token is NEVER included in the card — the token service
        handles credential exchange server-side.

        Args:
            context: ``TurnContext`` to send the reply through.
            connection_name: Azure Bot OAuth connection name (e.g. ``"graph_sso"``).
            tool: Tool name requesting credentials (used in card text only;
                never exposes a secret).
        """
        from microsoft_agents.activity import Activity, ActivityTypes

        signin_text = f"Please sign in to authorize access for {tool}."
        oauth_card_attachment = {
            "contentType": "application/vnd.microsoft.card.oauth",
            "content": {
                "text": signin_text,
                "connectionName": connection_name,
            },
        }
        reply = Activity(
            type=ActivityTypes.message,
            attachments=[oauth_card_attachment],
        )
        await context.send_activity(reply)
        self.logger.info(
            "OAuthCard emitted for tool=%s connection=%s", tool, connection_name
        )

    async def _emit_adaptive_card(
        self,
        context,
        capture_url: str,
        provider: str,
    ) -> None:
        """Emit an Adaptive Card with a static-key OOB capture link.

        Used when the broker signals ``auth_kind="static_key"`` (e.g. Fireflies
        API key).  The card contains a clickable link to the OOB capture page
        and a plain-text fallback for channels that cannot render Adaptive Cards.

        The ``capture_url`` is the consent / capture URL — it may contain an
        ``a2a_state`` nonce or similar correlation parameter. It is NEVER a
        secret; it is a public URL the user must visit.

        Args:
            context: ``TurnContext`` to send the reply through.
            capture_url: OOB capture URL from
                :class:`~parrot.auth.credentials.NeedsAuth` or
                :class:`~parrot.auth.credentials.CredentialRequired`.
            provider: Provider identifier (e.g. ``"fireflies"``); used in
                card text only.
        """
        from microsoft_agents.activity import Activity, ActivityTypes

        # Adaptive Card body with a link action so Teams/Copilot Studio can
        # render it interactively. Fallback text for plain-text channels.
        adaptive_card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": (
                        f"To use **{provider}**, please authorise access by "
                        f"visiting the link below."
                    ),
                    "wrap": True,
                },
            ],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": f"Authorise {provider}",
                    "url": capture_url,
                }
            ],
        }
        adaptive_card_attachment = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": adaptive_card,
        }
        reply = Activity(
            type=ActivityTypes.message,
            text=f"To authorise {provider!r}, visit: {capture_url}",
            attachments=[adaptive_card_attachment],
        )
        await context.send_activity(reply)
        self.logger.info(
            "Adaptive Card emitted for provider=%s capture_url=<redacted>", provider
        )

    # ------------------------------------------------------------------
    # Conversation update
    # ------------------------------------------------------------------

    async def _handle_conversation_update(self, context) -> None:
        """Send a welcome message when new members join a conversation.

        Only sends the welcome message to members that are NOT the bot
        itself (identified by comparing member IDs to ``recipient.id``).

        Args:
            context: ``TurnContext`` carrying the ``conversationUpdate`` Activity.
        """
        activity = context.activity
        if not activity.members_added:
            return

        bot_id: Optional[str] = (
            activity.recipient.id if activity.recipient else None
        )
        for member in activity.members_added:
            if member.id != bot_id:
                await self._send_text(context, self.welcome_message)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_text(context, text: str) -> None:
        """Send a reply as plain text to avoid channel markdown parsing.

        The Bot Framework defaults an outbound ``message`` Activity's
        ``textFormat`` to ``markdown``. Channels such as Telegram then try
        to render the text as MarkdownV2, where characters like ``-``,
        ``.``, ``!`` and ``(`` are reserved and must be escaped — an
        unescaped one makes the channel reject the message with a 400
        ("can't parse entities"). Sending as ``plain`` tells the channel to
        deliver the text verbatim, so agent replies are never mangled or
        rejected because of incidental markdown characters.

        Args:
            context: ``TurnContext`` used to emit the reply.
            text: The message body to send verbatim.
        """
        from microsoft_agents.activity import Activity, ActivityTypes, TextFormatTypes

        await context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=text,
                text_format=TextFormatTypes.plain,
            )
        )
