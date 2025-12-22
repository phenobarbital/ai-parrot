"""
MS Teams Agent Wrapper.

Connects MS Teams messages to AI-Parrot agents.
"""
import uuid
import asyncio
import logging
import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from aiohttp import web
from botbuilder.core import (
    ActivityHandler,
    TurnContext,
    ConversationState,
    MemoryStorage,
    UserState,
    CardFactory
)
from botbuilder.schema import Activity, ActivityTypes, ChannelAccount, Attachment
from botbuilder.core.teams import TeamsInfo
from navconfig.logging import logging

from .models import MSTeamsAgentConfig
from .adapter import Adapter
from .handler import MessageHandler
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode


logging.getLogger('msrest').setLevel(logging.WARNING)


class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):
    """
    Wraps an Agent for MS Teams integration.
    
    Features:
    - Sends responses as Adaptive Cards with markdown support
    - Handles images, documents, code blocks, and tables
    - Supports rich formatting via ParsedResponse
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
            response = await self.agent.ask(text, output_mode=OutputMode.MSTEAMS)
            
            # Parse response into structured content
            parsed = self._parse_response(response)
            
            # Send response as Adaptive Card with attachments
            await self._send_parsed_response(parsed, turn_context)
            
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
                    # Send welcome as a simple card
                    welcome_card = self._build_adaptive_card(
                        ParsedResponse(text=self.config.welcome_message)
                    )
                    await self.send_adaptive_card(welcome_card, turn_context)

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

    def _extract_adaptive_card_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract Adaptive Card JSON from markdown code blocks.
        
        Looks for:
        - ```json ... ``` blocks containing AdaptiveCard
        - Validates if it's a proper Adaptive Card structure
        
        Returns:
            Adaptive Card dict if found and valid, None otherwise
        """
        if not text:
            return None
        
        # Try to find JSON code blocks with triple backticks
        json_pattern = r'```(?:json)?\s*\n(.*?)\n```'
        matches = re.findall(json_pattern, text, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            try:
                parsed_json = json.loads(match.strip())
                
                # Check if it's an Adaptive Card directly
                if isinstance(parsed_json, dict):
                    # Direct AdaptiveCard
                    if parsed_json.get('type') == 'AdaptiveCard':
                        self.logger.info("Detected direct AdaptiveCard in JSON block")
                        return parsed_json
                    
                    # MS Teams message with attachments containing AdaptiveCard
                    if parsed_json.get('type') == 'message':
                        attachments = parsed_json.get('attachments', [])
                        if attachments:
                            for attachment in attachments:
                                if isinstance(attachment, dict):
                                    # Check if attachment has contentType for adaptive card
                                    content_type = attachment.get('contentType', '')
                                    if 'adaptivecard' in content_type.lower():
                                        # Return the content of the adaptive card
                                        card_content = attachment.get('content')
                                        if card_content and isinstance(card_content, dict):
                                            self.logger.info("Detected AdaptiveCard in message attachment")
                                            return card_content
                            
                            # If no specific adaptive card content type but has content
                            # Return first attachment's content if it looks like a card
                            first_attachment = attachments[0]
                            if isinstance(first_attachment, dict):
                                content = first_attachment.get('content', first_attachment)
                                if isinstance(content, dict) and content.get('type') == 'AdaptiveCard':
                                    self.logger.info("Detected AdaptiveCard in first attachment")
                                    return content
                    
            except json.JSONDecodeError:
                continue
        
        return None

    def _parse_response(self, response: Any) -> Union[ParsedResponse, Dict[str, Any]]:
        """
        Parse agent response into structured content.
        
        For MSTEAMS output mode, checks if the response contains an Adaptive Card JSON.
        If found, returns the Adaptive Card dict directly.
        Otherwise, falls back to standard parse_response().
        
        Returns:
            Either a ParsedResponse object or an Adaptive Card dict
        """
        # First check if response contains an Adaptive Card JSON
        text_to_check = None
        
        if hasattr(response, 'output') and response.output:
            text_to_check = str(response.output)
        elif hasattr(response, 'content') and response.content:
            text_to_check = str(response.content)
        elif hasattr(response, 'response') and response.response:
            text_to_check = str(response.response)
        
        if text_to_check:
            adaptive_card = self._extract_adaptive_card_json(text_to_check)
            if adaptive_card:
                # Return the adaptive card directly as a dict marker
                # We'll handle this specially in _send_parsed_response
                return adaptive_card
        
        # Fall back to standard parsing
        return parse_response(response)

    def _extract_response_text(self, response: Any) -> str:
        """Extract text content from agent response (backward compatibility)."""
        parsed = self._parse_response(response)
        if isinstance(parsed, dict):
            # It's an Adaptive Card, return empty string
            return ""
        return parsed.text


    def _build_adaptive_card(self, parsed: ParsedResponse) -> Dict[str, Any]:
        """
        Build an Adaptive Card from parsed response.
        
        Features:
        - Text with markdown support (TextBlock wrap)
        - Code blocks with monospace font
        - Tables as FactSet or ColumnSet
        - Images inline in card
        
        Args:
            parsed: The parsed response content
            
        Returns:
            Adaptive Card JSON structure
        """
        card_body = []
        
        # Add main text content
        if parsed.text:
            card_body.append({
                "type": "TextBlock",
                "text": parsed.text,
                "wrap": True,
                "size": "Medium"
            })
        
        # Add code block if present
        if parsed.has_code:
            # Add separator
            card_body.append({
                "type": "TextBlock",
                "text": f"**Code** ({parsed.code_language or 'text'}):",
                "wrap": True,
                "weight": "Bolder",
                "spacing": "Medium"
            })
            
            # Code in monospace TextBlock
            card_body.append({
                "type": "TextBlock",
                "text": parsed.code,
                "wrap": True,
                "fontType": "Monospace",
                "spacing": "Small"
            })
        
        # Add table if present
        if parsed.has_table and parsed.table_data is not None:
            try:
                df = parsed.table_data
                columns = list(df.columns)
                
                # Create header row
                header_columns = [
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [{
                            "type": "TextBlock",
                            "text": str(col),
                            "weight": "Bolder",
                            "wrap": True
                        }]
                    }
                    for col in columns
                ]
                
                card_body.append({
                    "type": "ColumnSet",
                    "columns": header_columns,
                    "spacing": "Medium"
                })
                
                # Add data rows (limit to 20 for card size)
                for idx, (_, row) in enumerate(df.head(20).iterrows()):
                    row_columns = [
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [{
                                "type": "TextBlock",
                                "text": str(val),
                                "wrap": True
                            }]
                        }
                        for val in row.values
                    ]
                    card_body.append({
                        "type": "ColumnSet",
                        "columns": row_columns,
                        "separator": idx == 0
                    })
                
                if len(df) > 20:
                    card_body.append({
                        "type": "TextBlock",
                        "text": f"*... and {len(df) - 20} more rows*",
                        "wrap": True,
                        "isSubtle": True
                    })
                    
            except Exception as e:
                # Fallback to markdown table
                if parsed.table_markdown:
                    card_body.append({
                        "type": "TextBlock",
                        "text": parsed.table_markdown,
                        "wrap": True,
                        "fontType": "Monospace"
                    })
        elif parsed.table_markdown:
            # If only markdown table available
            card_body.append({
                "type": "TextBlock",
                "text": parsed.table_markdown,
                "wrap": True,
                "fontType": "Monospace"
            })
        
        # Add images inline
        for image_path in parsed.images[:3]:  # Limit to 3 images in card
            # Note: For local files, would need to upload to accessible URL
            # This is a placeholder for URL-based images
            card_body.append({
                "type": "TextBlock",
                "text": f"📷 Image: {image_path.name}",
                "wrap": True,
                "isSubtle": True
            })
        
        # Add document mentions
        for doc_path in parsed.documents[:5]:
            card_body.append({
                "type": "TextBlock",
                "text": f"📎 Document: {doc_path.name}",
                "wrap": True,
                "isSubtle": True
            })
        
        # Build the card
        adaptive_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": card_body
        }
        
        return adaptive_card

    async def _send_parsed_response(
        self,
        parsed: Union[ParsedResponse, Dict[str, Any]],
        turn_context: TurnContext
    ) -> None:
        """
        Send parsed response to MS Teams.
        
        Handles both:
        - ParsedResponse: Sends an Adaptive Card built from parsed content
        - Dict (Adaptive Card): Sends the Adaptive Card directly
        
        Sends separate attachments for files if needed.
        
        Args:
            parsed: Either ParsedResponse or Adaptive Card dict
            turn_context: The turn context for sending
        """
        # Check if parsed is an Adaptive Card dict
        if isinstance(parsed, dict):
            self.logger.info("Sending Adaptive Card directly from LLM response")
            await self.send_adaptive_card(parsed, turn_context)
            return
        
        # Standard ParsedResponse handling
        # Build and send Adaptive Card for main content
        if parsed.text or parsed.has_code or parsed.has_table:
            card = self._build_adaptive_card(parsed)
            await self.send_adaptive_card(card, turn_context)
        
        # Send document attachments
        for doc_path in parsed.documents:
            try:
                await self.send_file_attachment(doc_path, turn_context)
            except Exception as e:
                self.logger.error(f"Failed to send document {doc_path}: {e}")
        
        # Send media attachments
        for media_path in parsed.media:
            try:
                await self.send_file_attachment(media_path, turn_context)
            except Exception as e:
                self.logger.error(f"Failed to send media {media_path}: {e}")
