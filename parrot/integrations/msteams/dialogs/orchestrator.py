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
from .card_builder import AdaptiveCardBuilder
from ...dialogs.cache import FormDefinitionCache
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
        form_cache: FormDefinitionCache = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            agent: The AI agent for processing messages (must have tool_manager)
            dialog_factory: Factory for creating form dialogs
            form_cache: Cache for YAML form definitions with trigger phrase lookup
        """
        self.agent = agent
        self.dialog_factory = dialog_factory or FormDialogFactory()
        self.form_cache = form_cache

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

    def _check_trigger_phrases(self, message: str) -> Optional[FormDefinition]:
        """
        Check if message matches any YAML form trigger phrases.

        Args:
            message: User's message text

        Returns:
            FormDefinition if trigger matched, None otherwise
        """
        if not self.form_cache:
            return None

        message_lower = message.lower().strip()

        # Check forms in cache for trigger phrase matches
        for form_id, entry in list(self.form_cache._memory_cache.items()):
            if entry and entry.form.trigger_phrases:
                for phrase in entry.form.trigger_phrases:
                    if phrase.lower() in message_lower:
                        logger.info(f"🎯 Trigger phrase '{phrase}' matched form '{form_id}'")
                        return entry.form

        return None

    async def _resolve_dynamic_choices(self, form: FormDefinition) -> FormDefinition:
        """
        Resolve dynamic choices from tool sources for form fields.

        Args:
            form: FormDefinition with fields that may have choices_source

        Returns:
            FormDefinition with choices populated from tools
        """
        for section in form.sections:
            for field in section.fields:
                if field.choices_source:
                    try:
                        # Get the tool by name
                        tool = self.agent.tool_manager.get_tool(field.choices_source)
                        if tool:
                            # Execute tool to get choices
                            result = await tool.execute()
                            if hasattr(result, 'result') and result.result:
                                choices = result.result
                                if isinstance(choices, list):
                                    field.choices = choices
                                    logger.info(f"✅ Loaded {len(choices)} choices from '{field.choices_source}' for field '{field.name}'")
                                elif isinstance(choices, dict):
                                    # Convert dict to list of choice dicts
                                    field.choices = [
                                        {"title": str(v), "value": str(k)}
                                        for k, v in choices.items()
                                    ]
                        else:
                            logger.warning(f"Tool '{field.choices_source}' not found for field '{field.name}'")
                    except Exception as e:
                        logger.error(f"Error loading choices from '{field.choices_source}': {e}")

        return form

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
            # FIRST: Check for trigger phrases from YAML forms
            triggered_form = self._check_trigger_phrases(message)
            if triggered_form:
                # Resolve dynamic choices if any
                triggered_form = await self._resolve_dynamic_choices(triggered_form)

                # Store pending execution for the form's submit_action
                if triggered_form.submit_action:
                    self._pending[conversation_id] = PendingExecution(
                        tool_name=triggered_form.submit_action,
                        form_id=triggered_form.form_id,
                        known_values={},  # No pre-filled values from trigger
                        conversation_id=conversation_id,
                    )

                return ProcessResult(
                    form=triggered_form,
                    pending_tool=triggered_form.submit_action,
                    known_values={},
                    context_message=f"Starting: {triggered_form.title}",
                )

            # SECOND: Execute agent with tools enabled (LLM path)
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
        1. request_form tool calls and generates form from target_tool
        2. Tool results with requires_form metadata
        """
        # Check for tool calls in response
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                # ToolCall is a Pydantic model with: id, name, arguments, result, error
                tool_name = getattr(tool_call, 'name', '')
                result = getattr(tool_call, 'result', None)

                # Check if this is a request_form tool call
                if tool_name == 'request_form':
                    logger.info(f"Found request_form tool call with result: {type(result)}")

                    # Extract target_tool and known_values from result
                    target_tool = None
                    known_values = {}
                    context_message = None

                    if isinstance(result, dict):
                        # Result structure: {'result': {...}, 'metadata': {...}} or just the inner result
                        result_data = result.get('result', result)
                        if isinstance(result_data, dict):
                            target_tool = result_data.get('target_tool')
                            context_message = result_data.get('message')

                        # Check metadata if present
                        metadata = result.get('metadata', {})
                        if metadata.get('requires_form'):
                            known_values = metadata.get('known_values', {})
                            form_def = metadata.get('form_definition')
                            if form_def:
                                return {
                                    "form": form_def,
                                    "target_tool": metadata.get('target_tool', target_tool),
                                    "known_values": known_values,
                                    "context_message": context_message,
                                }

                    elif hasattr(result, 'metadata') and result.metadata:
                        # ToolResult object
                        metadata = result.metadata
                        if metadata.get('requires_form'):
                            return {
                                "form": metadata.get('form_definition'),
                                "target_tool": metadata.get('target_tool'),
                                "known_values": metadata.get('known_values', {}),
                                "context_message": getattr(result, 'result', {}).get('message') if hasattr(result, 'result') else None,
                            }

                    # If we have target_tool but no form_definition (metadata was lost),
                    # regenerate the form from the target tool's schema
                    if target_tool:
                        logger.info(f"Regenerating form for target_tool: {target_tool}")
                        tool = self.agent.tool_manager.get_tool(target_tool)
                        if tool:
                            # Get known_values from the original request_form arguments
                            arguments = getattr(tool_call, 'arguments', {})
                            known_values = arguments.get('known_values', {})

                            form = self.form_generator.from_tool_schema(
                                tool=tool,
                                prefilled=known_values,
                            )
                            return {
                                "form": form,
                                "target_tool": target_tool,
                                "known_values": known_values,
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
        Handle form completion and execute the pending action.

        Supports two action types:
        - Tool execution: "tool_name" -> calls registered tool via agent
        - Function call: "fn:module.path.function_name" -> calls function directly

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

        # Check action type based on prefix
        action = pending.tool_name

        if action and action.startswith("fn:"):
            # Direct function call: fn:module.path.function_name
            func_path = action[3:]  # Remove "fn:" prefix
            return await self._execute_function(
                func_path=func_path,
                form_data=complete_data,
                turn_context=turn_context,
            )
        else:
            # Default: Execute as registered tool
            return await self._execute_tool(
                tool_name=action,
                form_data=complete_data,
            )

    async def _execute_tool(
        self,
        tool_name: str,
        form_data: Dict[str, Any],
    ) -> str:
        """Execute a registered tool with form data."""
        tool = self.agent.tool_manager.get_tool(tool_name)

        if not tool:
            return f"❌ Error: Tool '{tool_name}' not found."

        try:
            result = await tool.execute(**form_data)
            return self._format_tool_result(result, tool)
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
            return f"❌ Error executing {tool_name}: {str(e)}"

    async def _execute_function(
        self,
        func_path: str,
        form_data: Dict[str, Any],
        turn_context: TurnContext,
    ) -> str:
        """
        Execute a function directly by import path.

        Supports both sync and async functions.
        Sync functions are run in a thread pool to avoid blocking.

        Args:
            func_path: Module path to function, e.g., "resources.employees.save_new_employee"
            form_data: Form data to pass to the function
            turn_context: Bot turn context

        Returns:
            Response message or formatted result
        """
        import asyncio
        import importlib
        from concurrent.futures import ThreadPoolExecutor

        try:
            # Split path: "resources.employees.save_new_employee" -> module="resources.employees", func="save_new_employee"
            if "." not in func_path:
                return f"❌ Invalid function path: '{func_path}'. Expected format: module.path.function_name"

            parts = func_path.rsplit(".", 1)
            module_path, func_name = parts[0], parts[1]

            logger.info(f"Executing function: {module_path}.{func_name}")

            # Import module dynamically
            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as e:
                logger.error(f"Module not found: {module_path}")
                return f"❌ Module not found: '{module_path}'"

            # Get function from module
            if not hasattr(module, func_name):
                logger.error(f"Function not found: {func_name} in {module_path}")
                return f"❌ Function '{func_name}' not found in module '{module_path}'"

            func = getattr(module, func_name)

            if not callable(func):
                return f"❌ '{func_path}' is not a callable function"

            # Execute function (handle both async and sync)
            if asyncio.iscoroutinefunction(func):
                # Async function - call directly
                result = await func(form_data, turn_context)
            else:
                # Sync function - run in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as executor:
                    result = await loop.run_in_executor(
                        executor,
                        lambda: func(form_data, turn_context)
                    )

            # Format result
            if result is None:
                return "✅ Form processed successfully."
            elif isinstance(result, str):
                return result
            elif isinstance(result, dict):
                # Return as Adaptive Card if it looks like one, otherwise format
                if "$schema" in result or "type" in result:
                    return result  # It's an Adaptive Card
                else:
                    # Format dict as message
                    message = result.get("message", "✅ Form processed successfully.")
                    return message
            else:
                return f"✅ Result: {result}"

        except Exception as e:
            logger.error(f"Error executing function {func_path}: {e}", exc_info=True)
            return f"❌ Error executing function: {str(e)}"

    def _format_tool_result(
        self,
        result: 'ToolResult',
        tool: Any,
    ) -> Dict[str, Any]:
        """
        Format tool result for user display as an Adaptive Card.

        Returns:
            Adaptive Card JSON dict
        """
        card_builder = AdaptiveCardBuilder()

        if hasattr(result, 'status'):
            if result.status == "success":
                # Extract message and details from result
                message = None
                details = None

                if hasattr(result, 'result') and result.result:
                    if isinstance(result.result, str):
                        message = result.result
                    elif isinstance(result.result, dict):
                        message = result.result.get('message') or result.result.get('result')
                        # Extract useful details for display
                        details = {k: v for k, v in result.result.items()
                                  if k not in ('message', 'result', 'metadata') and v is not None}

                title = tool.name.replace('_', ' ').title() + " Completed"
                return card_builder.build_success_card(
                    title=title,
                    message=message,
                    details=details if details else None,
                )

            elif result.status == "error":
                error_msg = getattr(result, 'error', 'Unknown error')
                return card_builder.build_error_card(
                    title="Operation Failed",
                    errors=[error_msg],
                    retry_action=False,
                )

        # Fallback success card
        title = tool.name.replace('_', ' ').title() + " Completed"
        return card_builder.build_success_card(title=title)

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
