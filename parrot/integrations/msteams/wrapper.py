"""
MS Teams Agent Wrapper.

Connects MS Teams messages to AI-Parrot agents.
"""
import uuid
import asyncio
from http import HTTPStatus
from typing import Dict, Optional, Any
from aiohttp import web
from botbuilder.core import (
    ActivityHandler,
    TurnContext,
    ConversationState,
    MemoryStorage,
    UserState
)
from botbuilder.schema import Activity, ActivityTypes, ChannelAccount
from botbuilder.core.teams import TeamsInfo
from navconfig.logging import logging

from .models import MSTeamsAgentConfig
from .adapter import Adapter
from .handler import MessageHandler


class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):
    """
    Wraps an Agent for MS Teams integration.
    """
    
    def __init__(
        self,
        agent: Any,
        config: MSTeamsAgentConfig,
        app: web.Application
    ):
        super().__init__()
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"MSTeamsWrapper.{config.name}")
        
        # State Management
        self.memory = MemoryStorage()
        self.conversation_state = ConversationState(self.memory)
        self.user_state = UserState(self.memory)
        
        # Initialize Adapter
        self.adapter = Adapter(
            config=self.config,
            logger=self.logger,
            conversation_state=self.conversation_state
        )
        
        # Route
        # Clean chatbot_id to be safe for URL
        safe_id = self.config.chatbot_id.replace(' ', '_').lower()
        self.route = f"/api/teambots/{safe_id}/messages"
        
        # Register Handler
        self.app.router.add_post(self.route, self.handle_request)
        self.logger.info(f"Registered MS Teams webhook at {self.route}")

    async def handle_request(self, request: web.Request) -> web.Response:
        """
        Handle incoming webhook requests.
        """
        if request.content_type.lower() != 'application/json':
            return web.Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        body = await request.json()
        activity = Activity().deserialize(body)
        auth_header = request.headers.get('Authorization', '')

        try:
            response = await self.adapter.process_activity(
                auth_header, activity, self.on_turn
            )
            if response:
                return web.json_response(
                    data=response.body,
                    status=response.status
                )
            return web.Response(status=HTTPStatus.OK)
            
        except Exception as e:
            self.logger.error(f"Error processing request: {e}", exc_info=True)
            return web.Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

    async def on_turn(self, turn_context: TurnContext):
        """
        Handle the turn. Application logic.
        """
        # Save state changes after routing
        await super().on_turn(turn_context)
        await self.conversation_state.save_changes(turn_context)
        await self.user_state.save_changes(turn_context)

    async def on_message_activity(self, turn_context: TurnContext):
        """
        Handle incoming text messages.
        """
        text = turn_context.activity.text
        if not text:
            return

        # Handle commands if any (simplified)
        # remove mentions if any
        text = self._remove_mentions(turn_context.activity, text)
        
        self.logger.info(f"Received message: {text}")
        
        # Send typing indicator
        await self.send_typing(turn_context)

        # Agent processing
        try:
            # We can use a per-conversation memory if the Agent supports it
            # For now, just simplistic call
            response = await self.agent.ask(text)
            
            response_text = self._extract_response_text(response)
            
            await self.send_text(response_text, turn_context)
            
            # TODO: Handle files/images in response
            
        except Exception as e:
            self.logger.error(f"Agent error: {e}", exc_info=True)
            await self.send_text(
                "I encountered an error processing your request.", 
                turn_context
            )

    async def on_members_added_activity(
        self,
        members_added: list[ChannelAccount],
        turn_context: TurnContext
    ):
        """
        Welcome new members.
        """
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                if self.config.welcome_message:
                    await self.send_text(self.config.welcome_message, turn_context)

    def _remove_mentions(self, activity: Activity, text: str) -> str:
        """
        Remove @bot mentions from text.
        """
        if not text:
            return ""
        # TODO: Implement robust mention removal using activity.entities
        try:
            # Simple fallback: remove bot name if at start
            bot_name = activity.recipient.name
            if text.startswith(f"@{bot_name}"):
                return text[len(bot_name)+1:].strip()
        except:
            pass
        return text.strip()

    async def send_typing(self, turn_context: TurnContext):
        activity = Activity(type=ActivityTypes.typing)
        activity.relates_to = turn_context.activity.conversation
        await turn_context.send_activity(activity)

    def _extract_response_text(self, response: Any) -> str:
        """Extract text content from agent response."""
        if response is None:
            return "I don't have a response for that."
        if hasattr(response, 'content'):
            return str(response.content)
        if hasattr(response, 'response'):
            return str(response.response)
        if hasattr(response, 'text'):
            return str(response.text)
        if isinstance(response, str):
            return response
        return str(response)
