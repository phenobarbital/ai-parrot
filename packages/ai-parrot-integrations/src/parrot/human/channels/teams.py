"""
Teams HITL Human Channel for AI-Parrot.

Implements the full :class:`~parrot.human.channels.base.HumanChannel` contract
for Microsoft Teams, enabling the Human-in-the-Loop engine to deliver
interactions (approvals, free-text questions, forms, polls, etc.) to
managers/humans via Teams private 1:1 chats.

The channel uses a dedicated HITL bot identity (separate from the
conversational MSTeamsAgentWrapper identity) and relies on:

- :class:`~parrot.integrations.msteams.graph.GraphClient` — email→AAD resolution.
- :class:`~parrot.integrations.msteams.proactive.ProactiveMessenger` — warm/cold
  proactive 1:1 bootstrap.
- :class:`~parrot.integrations.msteams.hitl_cards.TeamsCardRenderer` — per-
  InteractionType Adaptive Card rendering.
- Redis — ConversationReference + sent-activity maps.

See ``parrot/human/channels/telegram.py`` for the reference implementation
and ``sdd/specs/hitl-teams-channel.spec.md`` for the full spec.

Inbound demux:
    The channel's :meth:`TeamsHumanChannel.on_turn` webhook handler inspects
    every incoming activity.  When ``activity.value.get("hitl") is True`` the
    activity is treated as a card-submit response; ``respondent`` is taken from
    the BF-validated ``activity.from_property.aad_object_id`` (never from the
    card payload) and a :class:`~parrot.human.models.HumanResponse` is built
    and dispatched to the stored ``_response_callback``.

Security:
    ``respondent`` identity always comes from the Bot Framework validated
    activity ``from_property.aad_object_id`` — the card payload is untrusted.

Late-reply handling:
    If a ``hitl:result:{interaction_id}`` tombstone key exists in Redis, the
    card submit was received after the interaction expired; the channel sends
    an in-thread acknowledgment and does NOT invoke the response callback.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Optional

from pydantic import BaseModel, Field

from aiohttp import web
from botbuilder.core import CardFactory, MessageFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes

from parrot.human.channels.base import (
    ESCALATE_OPTION_KEY,
    CancelCallback,
    HumanChannel,
    ResponseCallback,
)
from parrot.human.models import HumanInteraction, HumanResponse, InteractionType
from parrot.integrations.msteams.graph import GraphClient
from parrot.integrations.msteams.hitl_cards import TeamsCardRenderer
from parrot.integrations.msteams.proactive import (
    ConversationReferenceStore,
    ProactiveDeliveryError,
    ProactiveMessenger,
    SentActivityStore,
)

_TOMBSTONE_PREFIX = "hitl:result:"


class TeamsHumanChannel(HumanChannel):
    """Teams Human Channel for HITL interactions.

    Delivers :class:`~parrot.human.models.HumanInteraction` objects to
    Microsoft Teams users via proactive 1:1 Adaptive Card messages, and
    captures card-submit responses back to the HITL engine.

    Lifecycle::

        channel = TeamsHumanChannel(adapter, graph_client, redis, config)
        await channel.register_response_handler(manager.receive_response)
        await channel.start()          # registers webhook route on the app
        # … manager handles interactions …
        await channel.stop()

    Args:
        adapter: :class:`~.hitl_adapter.HitlCloudAdapter` for this HITL bot.
        graph_client: :class:`~.graph.GraphClient` for email→AAD resolution.
        redis: Async Redis client for convref + sent-activity stores.
        config: :class:`~.teams_setup.TeamsHitlConfig` boot configuration.
        app: Optional aiohttp ``web.Application``; required when
            :meth:`start` should register the webhook route.
    """

    channel_type = "teams"
    render_reject_button = True

    def __init__(
        self,
        adapter: Any,
        graph_client: GraphClient,
        redis: Any,
        config: Any,  # TeamsHitlConfig — imported lazily to avoid circular import
        app: Optional[web.Application] = None,
    ) -> None:
        self._adapter = adapter
        self._graph_client = graph_client
        self._redis = redis
        self._config = config
        self._app = app

        self.logger = logging.getLogger("parrot.human.channels.teams")

        # Response + cancel callbacks registered by the manager.
        self._response_callback: Optional[ResponseCallback] = None
        self._cancel_callback: Optional[CancelCallback] = None

        # Sub-components (built from injected deps)
        self._convref_store = ConversationReferenceStore(
            redis, ttl=getattr(config, "convref_ttl", 2_592_000)
        )
        self._sent_store = SentActivityStore(redis)
        self._renderer = TeamsCardRenderer(
            render_reject_button=self.render_reject_button
        )
        self._messenger = ProactiveMessenger(
            adapter=adapter,
            convref_store=self._convref_store,
            app_id=getattr(config, "app_id", ""),
            tenant_id=getattr(config, "tenant_id", ""),
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Register the inbound webhook route on the aiohttp app.

        If no ``app`` was supplied at construction, this is a no-op;
        the caller is responsible for registering the route manually via
        :meth:`messages_handler`.
        """
        if self._app is not None:
            route = getattr(self._config, "route", "/api/teams-hitl/messages")
            self._app.router.add_post(route, self.messages_handler)
            self.logger.info(
                "TeamsHumanChannel: webhook registered at %s", route
            )

    async def stop(self) -> None:
        """No-op; the adapter lifecycle is managed externally."""

    # ── Webhook handler ────────────────────────────────────────────────────

    async def messages_handler(self, request: web.Request) -> web.Response:
        """aiohttp handler for ``POST /api/teams-hitl/messages``.

        Processes incoming Bot Framework activities via the CloudAdapter,
        authenticating the JWT and dispatching to :meth:`on_turn`.

        Args:
            request: Incoming aiohttp request.

        Returns:
            An aiohttp ``web.Response``.
        """
        if "application/json" not in request.content_type:
            return web.Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        body = await request.json()
        activity = Activity().deserialize(body)
        auth_header = request.headers.get("Authorization", "")

        try:
            response = await self._adapter.process_activity(
                auth_header, activity, self.on_turn
            )
            if response:
                return web.json_response(
                    data=response.body, status=response.status
                )
            return web.Response(status=HTTPStatus.OK)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Error processing Teams HITL activity: %s", exc, exc_info=True
            )
            return web.Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

    async def on_turn(self, turn_context: TurnContext) -> None:
        """Bot Framework on_turn handler — inbound demux.

        Inspects every incoming activity:
        - Refreshes the ConversationReference cache (cache-on-contact, OQ-4).
        - When ``activity.value`` contains ``hitl: True``, builds a
          :class:`~parrot.human.models.HumanResponse` and calls the stored
          response callback.
        - ``respondent`` is always taken from the BF-validated
          ``activity.from_property.aad_object_id`` (never from the payload).

        Args:
            turn_context: The current Bot Framework turn context.
        """
        activity = turn_context.activity

        # Always refresh ConversationReference on inbound contact (OQ-4).
        # We need the sender's email to key the cache; if not available via
        # AAD object id we skip (we'll refresh next time Graph resolves it).
        sender_aad = (
            getattr(activity.from_property, "aad_object_id", None)
            if activity.from_property
            else None
        )
        if sender_aad:
            await self._messenger.capture_reference(
                activity, sender_aad  # keyed by aad_object_id as fallback
            )

        # Only process message-type activities with HITL value payloads.
        if activity.type != ActivityTypes.message:
            return

        value = activity.value or {}
        if not isinstance(value, dict) or not value.get("hitl"):
            return

        interaction_id = value.get("interaction_id")
        if not interaction_id:
            self.logger.warning("HITL activity missing interaction_id; ignoring.")
            return

        # Check for late-reply tombstone.
        tombstone_key = f"{_TOMBSTONE_PREFIX}{interaction_id}"
        try:
            tombstone = await self._redis.get(tombstone_key)
        except Exception:  # noqa: BLE001
            tombstone = None

        if tombstone:
            # Interaction already resolved; send an in-thread ack.
            await turn_context.send_activity(
                "Esta solicitud ya ha vencido o fue resuelta. "
                "No se registrará esta respuesta."
            )
            return

        # Build HumanResponse — respondent from BF-validated activity, never payload.
        respondent = (
            getattr(activity.from_property, "aad_object_id", None)
            or getattr(activity.from_property, "id", "unknown")
            if activity.from_property
            else "unknown"
        )

        parsed_value = self._parse_response_value(value)
        response_type = self._infer_response_type(value, parsed_value)

        try:
            human_response = HumanResponse(
                interaction_id=interaction_id,
                respondent=respondent,
                response_type=response_type,
                value=parsed_value,
                timestamp=datetime.now(timezone.utc),
                metadata={"channel": "teams", "teams_value": value},
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Failed to build HumanResponse for interaction %r: %s",
                interaction_id,
                exc,
            )
            return

        if self._response_callback is not None:
            await self._response_callback(human_response)
        else:
            self.logger.warning(
                "No response callback registered; discarding response for %r.",
                interaction_id,
            )

    @staticmethod
    def _infer_response_type(
        value: dict, parsed_value: Any
    ) -> InteractionType:
        """Infer the InteractionType from the submit data payload.

        The card always embeds ``interaction_id`` and ``hitl: True``; other
        fields depend on the card type.  We detect approval by boolean
        ``value``, multi-choice by list, form by dict, otherwise free_text.

        Args:
            value: The raw ``activity.value`` dict.
            parsed_value: The parsed semantic value.

        Returns:
            The most appropriate :class:`~parrot.human.models.InteractionType`.
        """
        card_value = value.get("value")
        if card_value in ("approve", "reject", ESCALATE_OPTION_KEY):
            if card_value == ESCALATE_OPTION_KEY:
                return InteractionType.FREE_TEXT  # manager routes via value
            return InteractionType.APPROVAL
        if isinstance(parsed_value, bool):
            return InteractionType.APPROVAL
        if isinstance(parsed_value, list):
            return InteractionType.MULTI_CHOICE
        if isinstance(parsed_value, dict):
            return InteractionType.FORM
        return InteractionType.FREE_TEXT

    @staticmethod
    def _parse_response_value(value: dict) -> Any:
        """Extract the semantic response value from the card submit data.

        Precedence:
        1. ``value["value"]`` — approval / escalate / single-choice value.
        2. ``value["selected_option"]`` — single-choice Input.ChoiceSet.
        3. ``value["selected_options"]`` — multi-choice (comma-separated string).
        4. ``value["poll_choice"]`` — poll.
        5. ``value["response_text"]`` — free-text.
        6. Whole ``value`` dict (form fall-through).

        Args:
            value: The raw ``activity.value`` dict.

        Returns:
            Parsed semantic value.
        """
        if "value" in value:
            raw = value["value"]
            if raw == "approve":
                return True
            if raw == "reject":
                return False
            return raw  # ESCALATE_OPTION_KEY or other string sentinel

        if "selected_option" in value:
            return value["selected_option"]

        if "selected_options" in value:
            opts = value["selected_options"]
            if isinstance(opts, str):
                return [o.strip() for o in opts.split(",") if o.strip()]
            return opts

        if "poll_choice" in value:
            return value["poll_choice"]

        if "response_text" in value:
            return value["response_text"]

        # Form: return whole payload sans hitl / interaction_id metadata.
        form_data = {
            k: v
            for k, v in value.items()
            if k not in ("hitl", "interaction_id", "field")
        }
        return form_data or value

    # ── Outbound ───────────────────────────────────────────────────────────

    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        """Send an HITL interaction card to a Teams user.

        Steps:
        1. Resolve ``recipient`` (email) → AAD user via GraphClient.
        2. Render the Adaptive Card for the interaction type.
        3. Send the card via ProactiveMessenger (warm or cold path).
        4. Store the sent-activity metadata in Redis.

        Args:
            interaction: The pending human interaction.
            recipient: Recipient email address (decision D4).

        Returns:
            ``True`` on successful delivery, ``False`` on any failure.
        """
        # 1. Resolve recipient.
        resolved = await self._graph_client.get_user_by_email(recipient)
        if resolved is None:
            self.logger.warning(
                "Could not resolve Teams user for email %r; "
                "send_interaction returning False.",
                recipient,
            )
            return False

        # 2. Render Adaptive Card.
        card_dict = self._renderer.render(interaction)

        # 3. Send via ProactiveMessenger.
        async def _build_activity(turn_context: TurnContext) -> Optional[str]:
            card_attachment = CardFactory.adaptive_card(card_dict)
            msg = MessageFactory.attachment(card_attachment)
            response = await turn_context.send_activity(msg)
            if response:
                return response.id
            return None

        try:
            act_id = await self._messenger.send(resolved, _build_activity)
        except ProactiveDeliveryError as exc:
            self.logger.error(
                "Proactive delivery failed for %r (interaction %r): %s",
                recipient,
                interaction.interaction_id,
                exc,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(
                "Unexpected error sending interaction %r to %r: %s",
                interaction.interaction_id,
                recipient,
                exc,
            )
            return False

        # 4. Store sent-activity metadata.
        try:
            convref = await self._convref_store.get(recipient)
            if convref is None:
                self.logger.debug(
                    "No convref cached after send for %r; sent map may be incomplete.",
                    recipient,
                )
            else:
                await self._sent_store.set(
                    interaction.interaction_id,
                    convref,
                    act_id or "",
                    recipient,
                )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Error storing sent-activity for interaction %r",
                interaction.interaction_id,
            )

        return True

    async def send_notification(
        self,
        recipient: str,
        message: str,
    ) -> None:
        """Send a one-way notification to a Teams user (no reply expected).

        Uses the same proactive 1:1 bootstrap as :meth:`send_interaction` (D2).

        Args:
            recipient: Recipient email address.
            message: Plain-text notification message.
        """
        resolved = await self._graph_client.get_user_by_email(recipient)
        if resolved is None:
            self.logger.warning(
                "Could not resolve Teams user for email %r; notification not sent.",
                recipient,
            )
            return

        async def _build_activity(turn_context: TurnContext) -> Optional[str]:
            response = await turn_context.send_activity(message)
            if response:
                return response.id
            return None

        try:
            await self._messenger.send(resolved, _build_activity)
        except ProactiveDeliveryError as exc:
            self.logger.error(
                "Notification delivery failed for %r: %s", recipient, exc
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(
                "Unexpected error sending notification to %r: %s", recipient, exc
            )

    async def cancel_interaction(
        self,
        interaction_id: str,
        recipient: str,
    ) -> bool:
        """Cancel/withdraw a pending interaction by updating its card to a disabled state.

        Idempotent: if no sent-activity record exists (already cancelled or
        never sent), returns ``False`` without raising.

        Args:
            interaction_id: The HITL interaction UUID.
            recipient: The recipient's email address.

        Returns:
            ``True`` if the card was successfully updated, ``False`` otherwise.
        """
        sent = await self._sent_store.get(interaction_id)
        if sent is None:
            self.logger.debug(
                "cancel_interaction: no sent record for %r (already cancelled?).",
                interaction_id,
            )
            return False

        disabled_card = self._renderer.render_disabled(
            interaction_id, reason="withdrawn"
        )

        async def _build_update(turn_context: TurnContext) -> Optional[str]:
            update = Activity(
                id=sent["activity_id"],
                type=ActivityTypes.message,
                attachments=[CardFactory.adaptive_card(disabled_card)],
            )
            try:
                await turn_context.update_activity(update)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "update_activity for %r failed: %s — card may already be gone.",
                    interaction_id,
                    exc,
                )
            return None

        try:
            await self._messenger.send(
                _FakeResolvedUser(email=recipient),
                _build_update,
            )
            await self._sent_store.delete(interaction_id)
            return True
        except ProactiveDeliveryError as exc:
            self.logger.error(
                "cancel_interaction delivery failed for %r: %s",
                interaction_id,
                exc,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(
                "Unexpected error cancelling interaction %r: %s",
                interaction_id,
                exc,
            )
            return False

    # ── Callback registration ──────────────────────────────────────────────

    async def register_response_handler(
        self,
        callback: ResponseCallback,
    ) -> None:
        """Store the manager's response callback.

        Args:
            callback: :meth:`HumanInteractionManager.receive_response`.
        """
        self._response_callback = callback

    async def register_cancel_handler(
        self,
        callback: CancelCallback,
    ) -> None:
        """Store the manager's cancel callback.

        Args:
            callback: :meth:`HumanInteractionManager.cancel_pending`.
        """
        self._cancel_callback = callback


class _FakeResolvedUser:
    """Minimal duck-typed ResolvedTeamsUser for cancel_interaction."""

    def __init__(self, email: str) -> None:
        self.email = email
        self.aad_object_id = ""
        self.upn = email
        self.service_url = None


# ── TeamsHitlConfig ───────────────────────────────────────────────────────────

class TeamsHitlConfig(BaseModel):
    """Boot configuration for the shared HITL bot identity.

    All credential fields must be supplied from navconfig / environment
    variables.  Use ``${VAR_NAME}`` style substitution in your config
    files — never hardcode secrets here.

    Attributes:
        app_id: Microsoft App ID for the HITL bot (``MSTEAMS_HITL_APP_ID``).
        app_password: Microsoft App Password (``MSTEAMS_HITL_APP_PASSWORD``).
        tenant_id: AAD tenant ID (``MSTEAMS_TENANT_ID``).
        graph_client_id: Graph app registration client ID.
        graph_client_secret: Graph app registration client secret.
        graph_tenant_id: Tenant ID for the Graph app (may differ from bot tenant).
        redis_url: Async Redis connection URL.
        route: Webhook route for the HITL bot (default: ``/api/teams-hitl/messages``).
        convref_ttl: ConversationReference cache TTL in seconds (default: 30 days).
        app_type: Bot app type (``"MultiTenant"`` or ``"SingleTenant"``).

    Per-agent override (OQ-9 / OQ-9-impl):
        A per-agent HITL identity is exposed via keyed channels on the
        ``HumanInteractionManager``.  Register it as a named entry instead
        of the default ``"teams"``::

            channel = TeamsHumanChannel(adapter, gc, redis, per_agent_config)
            manager.register_channel("teams:my-agent", channel)

        The agent's tier or HITL tool can then reference ``channel="teams:my-agent"``
        to select the dedicated identity.  The default shared identity remains
        at ``"teams"`` for all tiers that do not need a distinct bot appearance.
        Selection mechanism: keyed-channel pattern (simpler than BotConfig at
        construction, avoids deep construction-time coupling).
    """

    app_id: str = Field(
        default_factory=lambda: os.environ.get("MSTEAMS_HITL_APP_ID", ""),
        description="Microsoft App ID for the HITL bot.",
    )
    app_password: str = Field(
        default_factory=lambda: os.environ.get("MSTEAMS_HITL_APP_PASSWORD", ""),
        description="Microsoft App Password for the HITL bot.",
    )
    tenant_id: str = Field(
        default_factory=lambda: os.environ.get("MSTEAMS_TENANT_ID", ""),
        description="AAD tenant ID.",
    )
    graph_client_id: str = Field(
        default_factory=lambda: os.environ.get("MSTEAMS_GRAPH_CLIENT_ID", ""),
        description="Graph app registration client ID.",
    )
    graph_client_secret: str = Field(
        default_factory=lambda: os.environ.get("MSTEAMS_GRAPH_CLIENT_SECRET", ""),
        description="Graph app registration client secret.",
    )
    graph_tenant_id: str = Field(
        default_factory=lambda: os.environ.get("MSTEAMS_GRAPH_TENANT_ID", ""),
        description="Tenant ID for the Graph app registration.",
    )
    redis_url: str = Field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        description="Async Redis connection URL.",
    )
    route: str = Field(
        default="/api/teams-hitl/messages",
        description="aiohttp route for the HITL webhook.",
    )
    convref_ttl: int = Field(
        default=2_592_000,
        description="ConversationReference cache TTL in seconds (default 30 days).",
    )
    app_type: str = Field(
        default="MultiTenant",
        description="Bot app type: 'MultiTenant' or 'SingleTenant'.",
    )


# ── setup_teams_hitl ──────────────────────────────────────────────────────────

async def setup_teams_hitl(
    app: Any,
    manager: Any,  # HumanInteractionManager — Any to avoid circular import
    config: TeamsHitlConfig,
    channel_name: str = "teams",
) -> "TeamsHumanChannel":
    """Wire the shared HITL bot in one call.

    Creates the adapter, GraphClient, Redis connection, and
    :class:`TeamsHumanChannel`, registers the webhook route on the
    aiohttp app, and registers the channel as ``channel_name`` on
    the ``HumanInteractionManager``.

    After this call, ``manager.startup()`` will wire the response and
    cancel handlers by calling :meth:`TeamsHumanChannel.register_response_handler`
    and :meth:`TeamsHumanChannel.register_cancel_handler`.

    Args:
        app: The aiohttp ``web.Application`` instance.
        manager: The :class:`~parrot.human.manager.HumanInteractionManager`.
        config: Boot configuration (all creds from navconfig/env vars).
        channel_name: Channel registration key (default ``"teams"``).
            Use ``"teams:my-agent"`` for per-agent override (OQ-9-impl).

    Returns:
        The constructed :class:`TeamsHumanChannel` instance.

    Example::

        from parrot.human import get_default_human_manager
        from parrot.human.channels.teams import TeamsHitlConfig, setup_teams_hitl

        config = TeamsHitlConfig()   # reads from environment
        manager = get_default_human_manager()
        channel = await setup_teams_hitl(app, manager, config)
        # manager.startup() wires response/cancel handlers; call it after all
        # channels are registered.
    """
    import redis.asyncio as aioredis  # type: ignore[import]

    from parrot.integrations.msteams.graph import GraphClient
    from parrot.integrations.msteams.hitl_adapter import HitlCloudAdapter

    _logger = logging.getLogger("parrot.human.channels.teams.setup")

    # Build the adapter.
    adapter = HitlCloudAdapter(
        app_id=config.app_id,
        app_password=config.app_password,
        app_type=config.app_type,
        tenant_id=config.tenant_id if config.app_type == "SingleTenant" else None,
    )

    # Build the Graph client.
    graph_client = GraphClient(
        client_id=config.graph_client_id,
        client_secret=config.graph_client_secret,
        tenant_id=config.graph_tenant_id,
    )

    # Build the Redis client.
    redis_client = aioredis.from_url(config.redis_url)

    # Assemble the channel.
    channel = TeamsHumanChannel(
        adapter=adapter,
        graph_client=graph_client,
        redis=redis_client,
        config=config,
        app=app,
    )

    # Register route and start the channel (registers webhook route).
    await channel.start()

    # Register the channel on the manager.
    manager.register_channel(channel_name, channel)

    _logger.info(
        "setup_teams_hitl: Teams HITL channel registered as %r "
        "(route=%s, app_id=%s)",
        channel_name,
        config.route,
        config.app_id[:4] + "****" if len(config.app_id) > 4 else "***",
    )

    return channel


# ── Auto-register with ChannelRegistry on import ──────────────────────────────

try:
    from parrot.human.channels import ChannelRegistry
    ChannelRegistry.register("teams", TeamsHumanChannel)
except ImportError:
    pass  # ChannelRegistry not yet available (e.g. during install)
