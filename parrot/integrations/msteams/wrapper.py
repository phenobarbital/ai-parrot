"""
MS Teams Agent Wrapper.

Connects MS Teams messages to AI-Parrot agents.
"""
import logging
import json
import re
import asyncio
import contextlib
from http import HTTPStatus
from pathlib import Path
from typing import Dict, Optional, Any, Union
from aiohttp import web
from botbuilder.core import (
    ActivityHandler,
    TurnContext,
    ConversationState,
    MemoryStorage,
    UserState,
    MessageFactory,
    CardFactory,
)
import jsonpickle
from botbuilder.core import MemoryStorage
from botbuilder.core.teams import TeamsInfo
from botbuilder.schema import Activity, ActivityTypes, ChannelAccount, Attachment
from botbuilder.dialogs import DialogSet, DialogTurnStatus
from .models import MSTeamsAgentConfig
from .adapter import Adapter
from .handler import MessageHandler
from ..parser import parse_response, ParsedResponse
from ...models.outputs import OutputMode
from .dialogs.orchestrator import FormOrchestrator
from .dialogs.factory import FormDialogFactory
from .dialogs.card_builder import AdaptiveCardBuilder
from .dialogs.validator import FormValidator
from ..dialogs.models import FormDefinition, DialogPreset
from ..dialogs.cache import FormDefinitionCache


logging.getLogger('msrest').setLevel(logging.WARNING)

class DebugMemoryStorage(MemoryStorage):
    async def write(self, changes):
        for k, v in changes.items():
            try:
                jsonpickle.encode(v)
            except Exception as e:
                print("\n=== JSONPICKLE FAILED ===")
                print("storage key:", k)
                print("value type:", type(v))
                # if it's a dict, dump top-level types
                if isinstance(v, dict):
                    print("top-level dict keys/types:")
                    for kk, vv in v.items():
                        print(" ", kk, type(vv))
                raise
        return await super().write(changes)


class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):
    """
    Wraps an Agent for MS Teams integration.

    Features:
    - Sends responses as Adaptive Cards with markdown support
    - Handles images, documents, code blocks, and tables
    - Supports rich formatting via ParsedResponse
    - Automatic form detection when LLM calls request_form
    - YAML-based form definitions
    - Multi-step wizard dialogs
    - Post-form tool execution
    """

    def __init__(
        self,
        agent: Any,
        config: MSTeamsAgentConfig,
        app: web.Application,
        forms_directory: Optional[str] = None,
    ):
        super().__init__()
        self.agent = agent
        self.config = config
        self.app = app
        self.logger = logging.getLogger(f"MSTeamsWrapper.{config.name}")

        # State Management
        self.memory = DebugMemoryStorage()
        self.conversation_state = ConversationState(self.memory)
        self.user_state = UserState(self.memory)

        # Form cache
        self.form_cache = FormDefinitionCache(
            forms_directory=forms_directory or str(
                Path(config.forms_directory) if hasattr(config, 'forms_directory') and config.forms_directory else None
            ),
            watch_files=True,
        )

        # Dialog state
        self.dialog_state = self.conversation_state.create_property(
            "DialogState"
        )
        self.dialogs = DialogSet(self.dialog_state)

        # Form components
        # NOTE: card_builder and validator are no longer stored - dialogs create fresh instances
        self.dialog_factory = FormDialogFactory()

        # Form orchestrator (handles LLM form requests)
        self.form_orchestrator = FormOrchestrator(
            agent=agent,
            dialog_factory=self.dialog_factory,
            form_cache=self.form_cache,
        )

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
        # Load predefined YAML forms
        asyncio.create_task(self._load_yaml_forms())

    async def _load_yaml_forms(self):
        """Load predefined form definitions from YAML files."""
        try:
            await self.form_cache.load_directory()
            self.logger.info("Loaded YAML form definitions")
        except Exception as e:
            self.logger.warning(f"Error loading YAML forms: {e}")

    # =========================================================================
    # Form Dialog Management
    # =========================================================================

    async def _start_form_dialog(
        self,
        dialog_context,
        form: FormDefinition,
        conversation_id: str,
        turn_context: TurnContext = None,
    ):
        """Start a form dialog."""

        # Create dialog from form definition
        # NOTE: We don't pass callbacks here to avoid serialization issues with jsonpickle
        # The wrapper handles completion/cancellation after dialog ends
        dialog = self.dialog_factory.create_dialog(
            form=form,
            on_complete=None,  # Handle in wrapper instead
            on_cancel=None,    # Handle in wrapper instead
        )

        # Store conversation_id in dialog for later use
        dialog._conversation_id = conversation_id

        # Add to dialog set (replace if exists)
        if form.form_id in self.dialogs._dialogs:
            self.dialogs._dialogs.pop(form.form_id)
        self.dialogs.add(dialog)

        # Begin dialog
        await dialog_context.begin_dialog(form.form_id)

        # Explicitly save state to ensure dialog is persisted before next interaction
        if turn_context:
            await self.conversation_state.save_changes(turn_context)

        self.logger.info(f"Started form dialog: {form.form_id}")

    async def _on_form_complete(
        self,
        form_data: Dict[str, Any],
        turn_context: TurnContext,
        conversation_id: str,
    ):
        """Handle form completion."""
        self.logger.info(f"Form completed with data: {list(form_data.keys())}")

        # Delegate to orchestrator for tool execution
        response = await self.form_orchestrator.handle_form_completion(
            form_data=form_data,
            conversation_id=conversation_id,
            turn_context=turn_context,
        )

        # Check if response is an Adaptive Card (dict) or plain text (str)
        if isinstance(response, dict):
            await self.send_card(response, turn_context)
        else:
            await self.send_text(response, turn_context)

    async def _on_form_cancel(
        self,
        turn_context: TurnContext,
        conversation_id: str,
    ):
        """Handle form cancellation."""
        await self.form_orchestrator.handle_form_cancellation(conversation_id)
        await self.send_text("Form cancelled.", turn_context)

    # =========================================================================
    # Card Submission Handling
    # =========================================================================

    async def _handle_card_submission(
        self,
        turn_context: TurnContext,
        dialog_context,
    ):
        """Handle Adaptive Card form submission."""
        submitted_data = turn_context.activity.value

        if not submitted_data:
            return

        self.logger.info(f"Card submission: {submitted_data}")
        conversation_id = turn_context.activity.conversation.id

        # Check for action type
        action = submitted_data.get('_action', 'submit')

        if action == 'cancel':
            # Cancel active dialog
            await dialog_context.cancel_all_dialogs()
            await self._on_form_cancel(turn_context, conversation_id)
            return

        # Set agent in turn_state for dialogs to access (ephemeral per-turn)
        turn_context.turn_state["FormDialog.agent"] = self.agent

        # Continue dialog with submitted data
        # The dialog's waterfall will pick up the data from activity.value
        results = await dialog_context.continue_dialog()

        self.logger.info(f"Dialog continue result: status={results.status}")

        if results.status == DialogTurnStatus.Complete:
            # Dialog finished - handle completion
            form_data = results.result
            if form_data and not form_data.get('_cancelled'):
                await self._on_form_complete(form_data, turn_context, conversation_id)
            elif form_data and form_data.get('_cancelled'):
                await self._on_form_cancel(turn_context, conversation_id)

        elif results.status == DialogTurnStatus.Empty:
            # No active dialog - might be a standalone card
            self.logger.warning("Card submission but no active dialog")
            await self.send_text(
                "I received your submission but wasn't expecting it. Please try again.",
                turn_context
            )

    # =========================================================================
    # Webhook Handler
    # =========================================================================

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
        """Handle incoming text messages."""

        # DEBUG: Log activity details
        self.logger.info(f"🔍 on_message_activity: type={turn_context.activity.type}, "
                         f"has_value={turn_context.activity.value is not None}, "
                         f"text={turn_context.activity.text[:50] if turn_context.activity.text else 'None'}")
        if turn_context.activity.value:
            self.logger.info(f"🔍 Activity value: {turn_context.activity.value}")

        # Create dialog context
        dialog_context = await self.dialogs.create_context(turn_context)
        conversation_id = turn_context.activity.conversation.id

        # DEBUG: Check dialog stack
        self.logger.info(f"🔍 Dialog stack size: {len(dialog_context.stack) if dialog_context.stack else 0}")

        # Handle Adaptive Card submissions
        if turn_context.activity.value:
            await self._handle_card_submission(
                turn_context,
                dialog_context
            )
            return

        # Continue existing dialog if any
        results = await dialog_context.continue_dialog()
        if results.status != DialogTurnStatus.Empty:
            return

        # Process new message
        text = turn_context.activity.text
        if not text:
            return

        # Clean message (remove bot mentions)
        text = self._remove_mentions(turn_context.activity, text)

        self.logger.info(f"Received message: {text}")

        # Send typing indicator
        await self.send_typing(turn_context)

        # Process message with form orchestrator
        # (Orchestrator now handles trigger phrase detection for YAML forms)
        result = await self.form_orchestrator.process_message(
            message=text,
            conversation_id=conversation_id,
            context={
                "user_id": turn_context.activity.from_property.id,
                "session_id": conversation_id,
            }
        )

        # Handle result
        if result.has_error:
            await self.send_text(result.error, turn_context)
            return

        if result.needs_form:
            # Show context message if provided
            if result.context_message:
                await self.send_text(result.context_message, turn_context)

            # Start form dialog
            await self._start_form_dialog(
                dialog_context,
                result.form,
                conversation_id,
                turn_context,  # Pass for explicit state save
            )
            return

        # Normal response - parse and send as Adaptive Card
        if result.raw_response is not None:
            # Parse response to detect Adaptive Cards, tables, code, images
            parsed = self._parse_response(result.raw_response)
            await self._send_parsed_response(parsed, turn_context)
        elif result.response_text:
            # Fallback to plain text if no raw response
            await self.send_text(result.response_text, turn_context)

    # async def on_message_activity(self, turn_context: TurnContext):
    #     """
    #     Handle incoming text messages.
    #     """
    #     text = turn_context.activity.text
    #     if not text:
    #         return

    #     # Handle commands if any (simplified)
    #     # remove mentions if any
    #     text = self._remove_mentions(turn_context.activity, text)

    #     self.logger.info(f"Received message: {text}")

    #     # Send typing indicator
    #     await self.send_typing(turn_context)

    #     # Agent processing
    #     try:
    #         # We can use a per-conversation memory if the Agent supports it
    #         # For now, just simplistic call
    #         response = await self.agent.ask(text, output_mode=OutputMode.MSTEAMS)

    #         # Parse response into structured content
    #         parsed = self._parse_response(response)

    #         # Send response as Adaptive Card with attachments
    #         await self._send_parsed_response(parsed, turn_context)

    #     except Exception as e:
    #         self.logger.error(f"Agent error: {e}", exc_info=True)
    #         await self.send_text(
    #             "I encountered an error processing your request.",
    #             turn_context
    #         )

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
                    await self.send_card(welcome_card, turn_context)

    def _remove_mentions(self, activity: Activity, text: str) -> str:
        """Remove @bot mentions from text."""
        if not text:
            return ""

        # Remove mentions from activity.entities
        if activity.entities:
            for entity in activity.entities:
                if entity.type == "mention":
                    mentioned = entity.additional_properties.get("mentioned", {})
                    if mentioned.get("id") == activity.recipient.id:
                        # Remove the mention text
                        mention_text = entity.additional_properties.get("text", "")
                        text = text.replace(mention_text, "").strip()

        # Fallback: remove bot name at start
        with contextlib.suppress(Exception):
            bot_name = activity.recipient.name
            if bot_name and text.lower().startswith(f"@{bot_name.lower()}"):
                text = text[len(bot_name) + 1:].strip()

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
                        if attachments := parsed_json.get('attachments', []):
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
            await self.send_card(parsed, turn_context)
            return

        # Standard ParsedResponse handling
        # Build and send Adaptive Card for main content
        if parsed.text or parsed.has_code or parsed.has_table:
            card = self._build_adaptive_card(parsed)
            await self.send_card(card, turn_context)

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
