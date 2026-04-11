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

from parrot.forms.tools import RequestFormTool
from parrot.forms import FormSchema, StyleSchema
from parrot.forms.extractors.tool import ToolExtractor
from .factory import FormDialogFactory
from parrot.forms.renderers import AdaptiveCardRenderer
from parrot.forms import FormCache
from ....models.outputs import OutputMode

# Legacy aliases — the form-abstraction refactor renamed FormDefinition →
# FormSchema and FormDefinitionCache → FormCache. Keep the old names as
# type aliases so external callers that still reference them (and the few
# annotations left in this module) continue to resolve.
FormDefinition = FormSchema
FormDefinitionCache = FormCache
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
    form: Optional[FormSchema] = None

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
        → Orchestrator detects form request → Returns FormSchema
        → Wrapper displays form → User fills → Wrapper calls on_complete
        → Orchestrator executes target tool → Returns result
    """

    def __init__(
        self,
        agent: 'AbstractBot',
        dialog_factory: FormDialogFactory = None,
        form_cache: FormCache = None,
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

        # FormSchema extractor — replaces the old LLMFormGenerator. Generates
        # FormSchema objects from AbstractTool.args_schema via Pydantic
        # introspection (no LLM roundtrip required).
        self._extractor = ToolExtractor()

        # Pending tool executions (keyed by conversation_id)
        self._pending: Dict[str, PendingExecution] = {}

        # Register the request_form tool with agent's tool manager
        self._register_form_tool()

    def _register_form_tool(self):
        """Register the RequestFormTool with the agent's tool manager."""
        form_tool = RequestFormTool(
            tool_manager=self.agent.tool_manager,
            tool_extractor=self._extractor,
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

    def _check_trigger_phrases(self, message: str) -> Optional[FormSchema]:
        """
        Check if the message matches any cached form's trigger phrases.

        Trigger phrases are stored in ``form.meta["trigger_phrases"]`` — this
        is a convention used by the YAML loader to allow keyword-based form
        activation. FormSchema no longer has a dedicated ``trigger_phrases``
        field, so we read them from the meta bag.

        Args:
            message: User's message text.

        Returns:
            FormSchema if a trigger matched, None otherwise.
        """
        if not self.form_cache:
            return None

        message_lower = message.lower().strip()

        for form_id, entry in list(self.form_cache._memory_cache.items()):
            form = getattr(entry, "form", None)
            if form is None:
                continue
            meta = form.meta or {}
            phrases = meta.get("trigger_phrases") or []
            for phrase in phrases:
                if phrase.lower() in message_lower:
                    logger.info(
                        "🎯 Trigger phrase '%s' matched form '%s'",
                        phrase, form_id,
                    )
                    return form

        return None

    async def _resolve_dynamic_choices(self, form: FormSchema) -> FormSchema:
        """
        Populate ``field.options`` for fields that declare a tool-backed
        ``options_source``.

        Only ``source_type == "tool"`` is resolved here — endpoints/queries
        are handled elsewhere. Results are converted into ``FieldOption``
        instances so the form stays schema-valid for the renderer.

        Args:
            form: FormSchema with fields that may declare options_source.

        Returns:
            The same FormSchema with options populated (in-place mutation).
        """
        from parrot.forms import FieldOption  # local import avoids cycles

        for section in form.sections:
            for field in section.fields:
                source = field.options_source
                if source is None or source.source_type != "tool":
                    continue

                tool_name = source.source_ref
                try:
                    tool = self.agent.tool_manager.get_tool(tool_name)
                    if tool is None:
                        logger.warning(
                            "Tool '%s' not found for field '%s'",
                            tool_name, field.field_id,
                        )
                        continue

                    result = await tool.execute()
                    payload = getattr(result, "result", result)
                    if not payload:
                        continue

                    value_key = source.value_field
                    label_key = source.label_field

                    options: list[FieldOption] = []
                    if isinstance(payload, list):
                        for item in payload:
                            if isinstance(item, dict):
                                options.append(
                                    FieldOption(
                                        value=str(item.get(value_key, "")),
                                        label=str(item.get(label_key, "")),
                                    )
                                )
                            else:
                                options.append(
                                    FieldOption(value=str(item), label=str(item))
                                )
                    elif isinstance(payload, dict):
                        options = [
                            FieldOption(value=str(k), label=str(v))
                            for k, v in payload.items()
                        ]

                    if options:
                        field.options = options
                        logger.info(
                            "✅ Loaded %d options from '%s' for field '%s'",
                            len(options), tool_name, field.field_id,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Error loading options from '%s': %s",
                        tool_name, exc,
                    )

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

                # Resolve the tool name from the form's SubmitAction (only
                # tool_call actions are handled here; endpoint/event
                # submissions are owned by the wrapper).
                submit = triggered_form.submit
                submit_ref = (
                    submit.action_ref
                    if submit and submit.action_type == "tool_call"
                    else None
                )

                if submit_ref:
                    self._pending[conversation_id] = PendingExecution(
                        tool_name=submit_ref,
                        form_id=triggered_form.form_id,
                        known_values={},  # No pre-filled values from trigger
                        conversation_id=conversation_id,
                    )

                return ProcessResult(
                    form=triggered_form,
                    pending_tool=submit_ref,
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

    def _coerce_form(self, candidate: Any) -> Optional[FormSchema]:
        """Coerce a dict-or-FormSchema metadata payload into a FormSchema.

        RequestFormTool serializes the form as ``form.model_dump()`` into
        ``ToolResult.metadata["form"]``. We need to revive that dict back
        into a FormSchema before handing it to the renderer.
        """
        if candidate is None:
            return None
        if isinstance(candidate, FormSchema):
            return candidate
        if isinstance(candidate, dict):
            try:
                return FormSchema.model_validate(candidate)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to revive FormSchema from dict: %s", exc)
                return None
        return None

    def _regenerate_form(
        self,
        target_tool: str,
        known_values: Dict[str, Any],
    ) -> Optional[FormSchema]:
        """Rebuild a FormSchema from a registered tool's args_schema."""
        tool = self.agent.tool_manager.get_tool(target_tool)
        if tool is None:
            logger.warning(
                "Cannot regenerate form: tool '%s' not registered", target_tool
            )
            return None
        try:
            return self._extractor.extract(tool, known_values=known_values or {})
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to regenerate form for '%s': %s", target_tool, exc
            )
            return None

    def _extract_form_request(
        self,
        response: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract a form request from the agent response.

        Looks for, in order:
        1. A ``request_form`` tool call whose ToolResult.metadata carries
           ``requires_form=True`` and a serialized ``form`` dict.
        2. A ``request_form`` tool call without a form dict — regenerate
           the FormSchema from the target tool's args_schema.
        3. Any tool result with ``requires_form=True``.
        4. An inline ``__request_form__`` JSON payload in the response text
           (legacy fallback).
        """
        # ---- 1 & 2: inspect request_form tool calls --------------------
        tool_calls = getattr(response, "tool_calls", None) or []
        for tool_call in tool_calls:
            tool_name = getattr(tool_call, "name", "")
            if tool_name != "request_form":
                continue

            result = getattr(tool_call, "result", None)
            logger.info(
                "Found request_form tool call with result type: %s",
                type(result).__name__,
            )

            target_tool = None
            known_values: Dict[str, Any] = {}
            context_message: Optional[str] = None
            metadata: Dict[str, Any] = {}
            result_data: Any = None

            if isinstance(result, dict):
                result_data = result.get("result", result)
                metadata = result.get("metadata", {}) or {}
            elif result is not None:
                result_data = getattr(result, "result", None)
                metadata = getattr(result, "metadata", {}) or {}

            if isinstance(result_data, dict):
                target_tool = result_data.get("target_tool")
                context_message = result_data.get("message")

            if metadata.get("requires_form"):
                known_values = metadata.get("known_values", {}) or {}
                target_tool = metadata.get("target_tool", target_tool)
                form = self._coerce_form(
                    metadata.get("form") or metadata.get("form_definition")
                )
                if form is not None:
                    return {
                        "form": form,
                        "target_tool": target_tool,
                        "known_values": known_values,
                        "context_message": context_message,
                    }

            # Fallback: regenerate from tool schema using request_form args
            if target_tool:
                arguments = getattr(tool_call, "arguments", {}) or {}
                if isinstance(arguments, dict):
                    known_values = arguments.get("known_values", known_values) or known_values
                form = self._regenerate_form(target_tool, known_values)
                if form is not None:
                    return {
                        "form": form,
                        "target_tool": target_tool,
                        "known_values": known_values,
                        "context_message": context_message,
                    }

        # ---- 3: any tool result with requires_form ----------------------
        tool_results = getattr(response, "tool_results", None) or []
        for result in tool_results:
            metadata = (
                result.get("metadata", {})
                if isinstance(result, dict)
                else getattr(result, "metadata", {}) or {}
            )
            if not metadata.get("requires_form"):
                continue
            form = self._coerce_form(
                metadata.get("form") or metadata.get("form_definition")
            )
            if form is not None:
                return {
                    "form": form,
                    "target_tool": metadata.get("target_tool"),
                    "known_values": metadata.get("known_values", {}) or {},
                }

        # ---- 4: legacy inline JSON payload ------------------------------
        content = getattr(response, "content", None)
        if isinstance(content, str) and '"__request_form__": true' in content:
            try:
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    if data.get("__request_form__"):
                        tool_ref = data.get("tool_name")
                        known_values = data.get("known_values", {}) or {}
                        form = self._regenerate_form(tool_ref, known_values)
                        if form is not None:
                            return {
                                "form": form,
                                "target_tool": tool_ref,
                                "known_values": known_values,
                            }
            except (json.JSONDecodeError, ValueError) as exc:
                logger.debug("Inline form JSON parse failed: %s", exc)

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

    # Adaptive Card constants for the success/error status cards emitted
    # after tool execution. Kept inline because the shared renderer only
    # knows how to render FormSchemas.
    _ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
    _ADAPTIVE_CARD_VERSION = "1.5"

    def _wrap_card(
        self,
        body: List[Dict[str, Any]],
        actions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Wrap body/actions in a v1.5 AdaptiveCard envelope."""
        card: Dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": self._ADAPTIVE_CARD_SCHEMA,
            "version": self._ADAPTIVE_CARD_VERSION,
            "body": body,
        }
        if actions:
            card["actions"] = actions
        return card

    def _build_success_card(
        self,
        title: str,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a status AdaptiveCard for a successful tool execution."""
        body: List[Dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"✅ {title}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
                "wrap": True,
            }
        ]
        if message:
            body.append(
                {
                    "type": "TextBlock",
                    "text": message,
                    "wrap": True,
                    "spacing": "Small",
                }
            )
        if details:
            facts = [
                {
                    "title": f"{str(k).replace('_', ' ').title()}:",
                    "value": str(v),
                }
                for k, v in details.items()
                if v is not None
            ]
            if facts:
                body.append(
                    {
                        "type": "FactSet",
                        "facts": facts,
                        "spacing": "Medium",
                    }
                )
        return self._wrap_card(
            body,
            actions=[
                {
                    "type": "Action.Submit",
                    "title": "OK",
                    "data": {"_action": "dismiss"},
                }
            ],
        )

    def _build_error_card(
        self,
        title: str,
        errors: List[str],
    ) -> Dict[str, Any]:
        """Build a status AdaptiveCard for a failed tool execution."""
        body: List[Dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"⚠️ {title}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
                "wrap": True,
            }
        ]
        for err in errors:
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"• {err}",
                    "color": "Attention",
                    "wrap": True,
                }
            )
        return self._wrap_card(body)

    def _format_tool_result(
        self,
        result: 'ToolResult',
        tool: Any,
    ) -> Dict[str, Any]:
        """
        Format a ToolResult for the user as an Adaptive Card.

        Returns:
            Adaptive Card JSON dict.
        """
        tool_label = getattr(tool, "name", "tool").replace("_", " ").title()

        status = getattr(result, "status", None)
        if status == "error" or getattr(result, "success", True) is False:
            error_msg = (
                getattr(result, "error", None)
                or (result.metadata or {}).get("error")
                if hasattr(result, "metadata")
                else None
            ) or "Unknown error"
            return self._build_error_card(
                title="Operation Failed",
                errors=[str(error_msg)],
            )

        # Success path — extract a friendly message + flattened details.
        message: Optional[str] = None
        details: Optional[Dict[str, Any]] = None

        payload = getattr(result, "result", None)
        if isinstance(payload, str):
            message = payload
        elif isinstance(payload, dict):
            message = payload.get("message") or payload.get("result")
            details = {
                k: v
                for k, v in payload.items()
                if k not in ("message", "result", "metadata") and v is not None
            }

        return self._build_success_card(
            title=f"{tool_label} Completed",
            message=message,
            details=details or None,
        )

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
