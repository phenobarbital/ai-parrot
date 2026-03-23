# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from datetime import datetime
from botbuilder.core import (
    ConversationState,
    TurnContext,
    BotFrameworkAdapterSettings
)
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication
)
from botbuilder.schema import ActivityTypes, Activity
from navconfig.logging import logging
from .models import MSTeamsAgentConfig


class Adapter(CloudAdapter):
    """Handler for Bot Configuration.
    """
    def __init__(
        self,
        config: MSTeamsAgentConfig,
        logger: logging.Logger,
        conversation_state: ConversationState,
    ):
        self.config: MSTeamsAgentConfig = config
        self.logger: logging.Logger = logger
        settings = ConfigurationBotFrameworkAuthentication(
            self.config,
            logger=self.logger
        )
        self.settings = BotFrameworkAdapterSettings(
            config.APP_ID,
            config.APP_PASSWORD
        )
        super().__init__(settings)
        self._conversation_state = conversation_state

    # Catch-all for errors.
    async def on_error(self, context: TurnContext, error: Exception):
        # This check writes out errors to console log
        # NOTE: In production environment,
        # you should consider logging this to Azure
        # application insights.
        self.logger.error(
            f"[on_turn_error] Unhandled error: {error}",
            exc_info=True
        )

        # Send a message to the user
        await context.send_activity(
            "The bot encountered an error or bug."
        )
        await context.send_activity(
            "To continue to run this bot, please fix the bot source code."
        )
        # Send a trace activity if we're talking to the
        # Bot Framework Emulator
        if context.activity.channel_id == "emulator":
            # Create a trace activity that contains the error object
            trace_activity = Activity(
                label="TurnError",
                name="on_turn_error Trace",
                timestamp=datetime.utcnow(),
                type=ActivityTypes.trace,
                value=f"{error}",
                value_type="https://www.botframework.com/schemas/error",
            )
            # Send a trace activity, which will be displayed in
            # Bot Framework Emulator
            await context.send_activity(trace_activity)

        # Clear out state
        await self._conversation_state.delete(context)
