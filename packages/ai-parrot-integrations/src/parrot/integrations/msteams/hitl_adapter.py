"""
HITL-dedicated Bot Framework adapter for TeamsHumanChannel.

Vendored / adapted from the azure_teambots private fork's AdapterHandler
pattern (azure_teambots/adapters.py), reusing the same
ConfigurationBotFrameworkAuthentication + BotFrameworkAdapterSettings
construction as the existing Adapter(CloudAdapter) in adapter.py:18.

This module is intentionally isolated — it does not import aiogram and
must never be imported from any Telegram-side module at module level.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from botbuilder.core import (
    BotFrameworkAdapterSettings,
    ConversationState,
    MemoryStorage,
    TurnContext,
)
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)
from botbuilder.schema import Activity, ActivityTypes

if TYPE_CHECKING:
    pass


class HitlBotConfig:
    """Minimal bot configuration shim for the HITL adapter.

    Mirrors the ``BotConfig`` shape expected by
    ``ConfigurationBotFrameworkAuthentication``.  The HITL adapter uses
    dedicated credentials (``MSTEAMS_HITL_APP_ID`` /
    ``MSTEAMS_HITL_APP_PASSWORD``) separate from any conversational-bot
    credentials so the two identities remain independent.

    Args:
        app_id: Microsoft App ID for the HITL bot.
        app_password: Microsoft App Password for the HITL bot.
        app_type: App type string (defaults to ``"MultiTenant"``).
        tenant_id: AAD tenant ID (used for single-tenant apps).
    """

    def __init__(
        self,
        app_id: str,
        app_password: str,
        app_type: str = "MultiTenant",
        tenant_id: Optional[str] = None,
    ) -> None:
        self.APP_ID: str = app_id
        self.APP_PASSWORD: str = app_password
        self.APP_TYPE: str = app_type
        self.APP_TENANTID: Optional[str] = tenant_id


class HitlCloudAdapter(CloudAdapter):
    """CloudAdapter configured for the shared HITL bot identity.

    Follows the same ``ConfigurationBotFrameworkAuthentication`` +
    ``BotFrameworkAdapterSettings`` pattern as the existing
    ``Adapter(CloudAdapter)`` in ``msteams/adapter.py:18``.

    The adapter is *process-level shared*: a single instance is created
    during ``setup_teams_hitl()`` and reused across all proactive sends /
    inbound webhook calls.

    Args:
        app_id: Microsoft App ID for the HITL bot.
        app_password: Microsoft App Password for the HITL bot.
        app_type: App type (defaults to ``"MultiTenant"``).
        tenant_id: AAD tenant ID for single-tenant apps.
        logger: Logger instance. Defaults to module logger.
    """

    def __init__(
        self,
        app_id: str,
        app_password: str,
        app_type: str = "MultiTenant",
        tenant_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._config = HitlBotConfig(
            app_id=app_id,
            app_password=app_password,
            app_type=app_type,
            tenant_id=tenant_id,
        )
        self.app_id = app_id

        auth = ConfigurationBotFrameworkAuthentication(
            self._config,
            logger=self.logger,
        )
        # Also keep a BotFrameworkAdapterSettings reference (mirrors adapter.py).
        self.settings = BotFrameworkAdapterSettings(app_id, app_password)

        super().__init__(auth)

        # Minimal MemoryStorage for the shared HITL adapter
        # (no persistent conversation state required — HITL state lives in Redis).
        _memory = MemoryStorage()
        self._conversation_state = ConversationState(_memory)

    async def on_error(self, context: TurnContext, error: Exception) -> None:
        """Handle unhandled adapter errors.

        Args:
            context: The current turn context.
            error: The exception that was raised.
        """
        self.logger.error(
            "[HitlCloudAdapter.on_error] Unhandled error: %s",
            error,
            exc_info=True,
        )

        try:
            await context.send_activity(
                "The HITL bot encountered an error. Please contact the administrator."
            )
        except Exception:  # noqa: BLE001
            pass  # Never let error-handling crash the process.

        # Emit a trace activity in the emulator channel for easier debugging.
        if context.activity.channel_id == "emulator":
            trace = Activity(
                label="TurnError",
                name="on_turn_error Trace",
                timestamp=datetime.utcnow(),
                type=ActivityTypes.trace,
                value=str(error),
                value_type="https://www.botframework.com/schemas/error",
            )
            try:
                await context.send_activity(trace)
            except Exception:  # noqa: BLE001
                pass
