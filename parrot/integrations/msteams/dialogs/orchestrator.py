"""
Form Orchestrator - Coordinates form generation, display, and tool execution.

Integrates:
- RequestFormTool for LLM-initiated forms
- Form dialog management
- Post-form tool execution
"""
from typing import Dict, List, Any, Optional, Callable, Awaitable, TYPE_CHECKING
from dataclasses import dataclass, field
import logging
import asyncio
import json
from botbuilder.core import TurnContext
from botbuilder.dialogs import DialogSet, DialogTurnStatus

from ..tools.request_form import RequestFormTool
from ...dialogs.models import FormDefinition, DialogPreset
from ...dialogs.llm_generator import LLMFormGenerator
from .factory import FormDialogFactory
from ....models.outputs import OutputMode
if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.tools.manager import ToolManager
    from parrot.tools.abstract import ToolResult


logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PendingExecution:
    """Tracks a pending tool execution after form completion."""
    tool_name: str
    form_id: str
    known_values: Dict[str, Any]
    conversation_id: str
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


@dataclass
class ProcessResult:
    """Result of processing a message."""

    # Response text to send (if any)
    response_text: Optional[str] = None

    # Form to display (if form was requested)
    form: Optional[FormDefinition] = None

    # Target tool after form completion
    pending_tool: Optional[str] = None

    # Known values to pre-fill
    known_values: Dict[str, Any] = field(default_factory=dict)

    # Context message from LLM
    context_message: Optional[str] = None

    # Raw agent response (for non-form cases)
    raw_response: Optional[Any] = None

    # Whether a form was requested
    @property
    def needs_form(self) -> bool:
        return self.form is not None

    # Whether there's an error
    error: Optional[str] = None

    @property
    def has_error(self) -> bool:
        return self.error is not None


# =============================================================================
# Form Orchestrator
# =============================================================================

class FormOrchestrator:
    """
    Orchestrates the form-based interaction flow.

    Responsibilities:
    1. Register RequestFormTool with the agent
    2. Detect when LLM requests a form
    3. Coordinate form display and submission
    4. Execute target tool after form completion

    Flow:
        User message → Agent processes → LLM may call request_form
        → Orchestrator detects form request → Returns FormDefinition
        → Wrapper displays form → User fills → Wrapper calls on_complete
        → Orchestrator executes target tool → Returns result
    """

    def __init__(
        self,
        agent: 'AbstractBot',
        dialog_factory: FormDialogFactory = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            agent: The AI agent for processing messages (must have tool_manager)
            dialog_factory: Factory for creating form dialogs
        """
        self.agent = agent
        self.dialog_factory = dialog_factory or FormDialogFactory()

        # Form generator
        self.form_generator = LLMFormGenerator(agent=agent)

        # Pending tool executions (keyed by conversation_id)
        self._pending: Dict[str, PendingExecution] = {}

        # Register the request_form tool with agent's tool manager
        self._register_form_tool()

    def _register_form_tool(self):
        """Register the RequestFormTool with the agent's tool manager."""
        form_tool = RequestFormTool(
            form_generator=self.form_generator,
            tool_manager=self.agent.tool_manager,
        )

        # Use agent.register_tool() to register in BOTH agent.tool_manager AND LLM's tool_manager
        # This is critical for tools registered after configure() - they need to be synced to the LLM
        self.agent.register_tool(form_tool)

        # Verify registration
        registered_tools = self.agent.tool_manager.list_tools()
        if 'request_form' in registered_tools:
            logger.info(f"✅ Registered request_form tool with agent. Total tools: {len(registered_tools)}")
        else:
            logger.error(f"❌ request_form tool NOT found in tool manager! Available: {registered_tools[:10]}...")

    # =========================================================================
    # Message Processing
    # =========================================================================

    async def process_message(
        self,
        message: str,
        conversation_id: str,
        context: Dict[str, Any] = None,
    ) -> ProcessResult:
        """
        Process a user message with form awareness.

        Args:
            message: The user's message
            conversation_id: Unique conversation identifier
            context: Additional context (user_id, etc.)

        Returns:
            ProcessResult indicating response or form needed
        """
        try:
            # Execute agent with tools enabled
            response = await self.agent.ask(
                message,
                output_mode=OutputMode.MSTEAMS,
                **(context or {})
            )

            # Check if the agent requested a form
            if form_request := self._extract_form_request(response):
                # Store pending execution
                self._pending[conversation_id] = PendingExecution(
                    tool_name=form_request["target_tool"],
                    form_id=form_request["form"].form_id,
                    known_values=form_request.get("known_values", {}),
                    conversation_id=conversation_id,
                )

                return ProcessResult(
                    form=form_request["form"],
                    pending_tool=form_request["target_tool"],
                    known_values=form_request.get("known_values", {}),
                    context_message=form_request.get("context_message"),
                )

            # Normal response
            response_text = self._extract_response_text(response)

            return ProcessResult(
                response_text=response_text,
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return ProcessResult(
                error=f"Error processing your request: {str(e)}"
            )

    def _extract_form_request(
        self,
        response: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract form request from agent response.

        Looks for:
        1. Tool results with requires_form metadata
        2. Structured form_definition in response
        """
        # Check for tool results in response
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                # ToolCall is a Pydantic model with attributes: id, name, arguments, result, error
                result = getattr(tool_call, 'result', None)

                # Check metadata for form request
                metadata = None
                if isinstance(result, dict):
                    metadata = result.get('metadata', {})
                elif hasattr(result, 'metadata'):
                    metadata = result.metadata

                if metadata and metadata.get('requires_form'):
                    # Extract context message from result
                    context_message = None
                    if isinstance(result, dict):
                        result_data = result.get('result', {})
                        if isinstance(result_data, dict):
                            context_message = result_data.get('message')

                    return {
                        "form": metadata.get('form_definition'),
                        "target_tool": metadata.get('target_tool'),
                        "known_values": metadata.get('known_values', {}),
                        "context_message": context_message,
                    }

        # Check for ToolResult objects
        if hasattr(response, 'tool_results'):
            for result in response.tool_results:
                if isinstance(result, dict):
                    metadata = result.get('metadata', {})
                    if metadata.get('requires_form'):
                        return {
                            "form": metadata.get('form_definition'),
                            "target_tool": metadata.get('target_tool'),
                            "known_values": metadata.get('known_values', {}),
                        }

        # Check content for inline form request (backup)
        if hasattr(response, 'content') and isinstance(response.content, str):
            if '"__request_form__": true' in response.content:
                try:
                    # Try to extract JSON from response
                    start = response.content.find('{')
                    end = response.content.rfind('}') + 1
                    if start >= 0 and end > start:
                        data = json.loads(response.content[start:end])
                        if data.get('__request_form__'):
                            # Generate form for the requested tool
                            tool = self.agent.tool_manager.get_tool(data.get('tool_name'))
                            if tool:
                                form = self.form_generator.from_tool_schema(
                                    tool,
                                    prefilled=data.get('known_values', {}),
                                )
                                return {
                                    "form": form,
                                    "target_tool": data.get('tool_name'),
                                    "known_values": data.get('known_values', {}),
                                }
                except (json.JSONDecodeError, Exception):
                    pass

        return None

    def _extract_response_text(self, response: Any) -> str:
        """Extract text content from agent response."""
        if response is None:
            return "I'm not sure how to respond to that."

        if isinstance(response, str):
            return response

        if hasattr(response, 'content'):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Handle multi-part content
                texts = []
                for part in content:
                    if isinstance(part, str):
                        texts.append(part)
                    elif isinstance(part, dict) and part.get('type') == 'text':
                        texts.append(part.get('text', ''))
                    elif hasattr(part, 'text'):
                        texts.append(part.text)
                return '\n'.join(texts)

        return response.text if hasattr(response, 'text') else str(response)

    # =========================================================================
    # Form Completion Handling
    # =========================================================================

    async def handle_form_completion(
        self,
        form_data: Dict[str, Any],
        conversation_id: str,
        turn_context: TurnContext,
    ) -> str:
        """
        Handle form completion and execute the pending tool.

        Args:
            form_data: Data collected from the form
            conversation_id: Conversation identifier
            turn_context: Bot turn context for sending responses

        Returns:
            Response message to send to user
        """
        # Get pending execution
        pending = self._pending.pop(conversation_id, None)

        if not pending:
            logger.warning(f"No pending execution for conversation {conversation_id}")
            return "✅ Form submitted successfully."

        # Merge known values with form data
        complete_data = {**pending.known_values, **form_data}

        # Get and execute the target tool
        tool = self.agent.tool_manager.get_tool(pending.tool_name)

        if not tool:
            return f"❌ Error: Tool '{pending.tool_name}' not found."

        try:
            # Execute the tool
            result = await tool.execute(**complete_data)

            # Format result for user
            return self._format_tool_result(result, tool)

        except Exception as e:
            logger.error(f"Error executing {pending.tool_name}: {e}", exc_info=True)
            return f"❌ Error executing {pending.tool_name}: {str(e)}"

    def _format_tool_result(
        self,
        result: 'ToolResult',
        tool: Any,
    ) -> str:
        """Format tool result for user display."""
        if hasattr(result, 'status'):
            if result.status == "success":
                if hasattr(result, 'result') and result.result:
                    if isinstance(result.result, str):
                        return f"✅ {result.result}"
                    elif isinstance(result.result, dict):
                        # Try to extract a message
                        if msg := result.result.get('message') or result.result.get('result'):
                            return f"✅ {msg}"
                return f"✅ {tool.name} completed successfully."

            elif result.status == "error":
                error_msg = getattr(result, 'error', 'Unknown error')
                return f"❌ {error_msg}"

        # Fallback
        return f"✅ {tool.name} completed."

    # =========================================================================
    # Cancellation
    # =========================================================================

    async def handle_form_cancellation(
        self,
        conversation_id: str,
    ):
        """Handle form cancellation."""
        # Remove pending execution
        self._pending.pop(conversation_id, None)
        logger.info(f"Form cancelled for conversation {conversation_id}")

    # =========================================================================
    # Utilities
    # =========================================================================

    def get_pending_execution(
        self,
        conversation_id: str,
    ) -> Optional[PendingExecution]:
        """Get pending execution for a conversation."""
        return self._pending.get(conversation_id)

    def has_pending_form(self, conversation_id: str) -> bool:
        """Check if there's a pending form for this conversation."""
        return conversation_id in self._pending

    def cleanup_stale_pending(self, max_age_seconds: float = 3600):
        """Remove stale pending executions."""
        now = asyncio.get_event_loop().time()
        stale = [
            conv_id for conv_id, pending in self._pending.items()
            if now - pending.created_at > max_age_seconds
        ]
        for conv_id in stale:
            del self._pending[conv_id]

        if stale:
            logger.info(f"Cleaned up {len(stale)} stale pending executions")
