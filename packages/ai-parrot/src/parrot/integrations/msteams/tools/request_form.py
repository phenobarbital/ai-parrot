"""
Request Form Tool - Allows LLM to explicitly request a form from the user.

This tool is invoked by the LLM when it determines that:
1. A tool needs to be executed
2. Required parameters are missing from the user's query
3. A structured form is the best way to collect the information
"""
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
import logging
from pydantic import BaseModel, Field
from ....tools.abstract import AbstractTool, ToolResult

if TYPE_CHECKING:
    from parrot.tools.manager import ToolManager
    from parrot.integrations.dialogs.llm_generator import LLMFormGenerator
    from parrot.integrations.dialogs.models import FormDefinition


logger = logging.getLogger(__name__)


# =============================================================================
# Input Schema
# =============================================================================

class RequestFormInput(BaseModel):
    """Input schema for the request_form tool."""

    target_tool: str = Field(
        ...,
        description="Name of the tool you intend to execute after collecting data from the user"
    )

    known_values: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameter values you have already extracted from the conversation. "
            "These will be pre-filled in the form. Only include values you are confident about."
        )
    )

    fields_to_collect: Optional[List[str]] = Field(
        default=None,
        description=(
            "Specific field names to collect from the user. "
            "If not provided, all required fields without known values will be collected."
        )
    )

    form_title: Optional[str] = Field(
        default=None,
        description="Custom title for the form. If not provided, one will be generated."
    )

    context_message: Optional[str] = Field(
        default=None,
        description="Optional message to show the user explaining why you need this information."
    )


# =============================================================================
# Tool Result Types
# =============================================================================

@dataclass
class FormRequestResult:
    """Result when a form is successfully requested."""
    form_definition: 'FormDefinition'
    target_tool: str
    context_message: Optional[str]
    known_values: Dict[str, Any]


# =============================================================================
# Request Form Tool
# =============================================================================

class RequestFormTool(AbstractTool):
    """
    Meta-tool that allows the LLM to request a structured form from the user.

    The LLM should use this tool when:
    - It needs to execute another tool but lacks required parameters
    - The missing information is best collected via a structured form
    - Multiple pieces of information need to be collected at once

    The tool generates a FormDefinition that the chat wrapper will render
    as an Adaptive Card (MS Teams) or inline keyboard (Telegram).

    Example LLM reasoning:
        User: "Create a new employee record"
        LLM thinks: I need to use create_employee tool, but I need name, email,
                   department, and start_date. I'll request a form.
        LLM calls: request_form(
            target_tool="create_employee",
            known_values={},
            form_title="New Employee Registration"
        )
    """

    name: str = "request_form"
    description: str = """
CRITICAL: Use this tool to collect missing parameters from the user via a structured form.

**WHEN TO USE (MANDATORY):**
- You need to execute a tool but are MISSING required parameters
- You need to collect 1 or more pieces of information from the user
- User requests creation, registration, update, or any action requiring input data

**EXAMPLES OF WHEN TO USE:**
- "create a ticket" → Use request_form with target_tool="jira_create_issue"
- "create a jira ticket" → Use request_form with target_tool="jira_create_issue"
- "register employee" → Use request_form with target_tool="create_employee"
- "send email to john" → Use request_form, known_values={"recipient": "john"}, target_tool="send_email"

**DO NOT ask text questions to collect parameters. ALWAYS use this tool instead.**

**HOW TO USE:**
1. Set target_tool: the tool you want to execute after collecting data
2. Set known_values: any parameters you already know from the conversation
3. Optionally set form_title and context_message for better UX

The form will be displayed as an Adaptive Card. After user fills it, the target_tool executes automatically.
"""

    args_schema = RequestFormInput

    def __init__(
        self,
        form_generator: 'LLMFormGenerator',
        tool_manager: 'ToolManager',
        **kwargs
    ):
        """
        Initialize the RequestFormTool.

        Args:
            form_generator: Generator for creating FormDefinitions
            tool_manager: Manager to look up target tools
        """
        super().__init__(**kwargs)
        self.form_generator = form_generator
        self.tool_manager = tool_manager

    async def _execute(
        self,
        target_tool: str,
        known_values: Dict[str, Any] = None,
        fields_to_collect: List[str] = None,
        form_title: str = None,
        context_message: str = None,
        **kwargs
    ) -> ToolResult:
        """
        Generate a form request for the specified tool.

        Args:
            target_tool: Name of the tool to execute after form completion
            known_values: Values already known from conversation
            fields_to_collect: Specific fields to include (optional)
            form_title: Custom form title (optional)
            context_message: Message to show user (optional)

        Returns:
            ToolResult with form_definition in metadata
        """
        known_values = known_values or {}

        # Validate target tool exists
        tool = self.tool_manager.get_tool(target_tool)
        if not tool:
            return ToolResult(
                status="error",
                error=f"Target tool '{target_tool}' not found. Available tools: {self.tool_manager.list_tools()}",
                result=None,
            )

        # Validate tool has schema
        if not hasattr(tool, 'args_schema') or tool.args_schema is None:
            return ToolResult(
                status="error",
                error=f"Target tool '{target_tool}' has no args_schema and cannot be used with forms.",
                result=None,
            )

        try:
            # Determine which fields to exclude (already known)
            exclude_fields = []
            if fields_to_collect:
                # User specified exact fields, exclude all others
                schema = tool.args_schema.model_json_schema()
                all_fields = set(schema.get("properties", {}).keys())
                exclude_fields = list(all_fields - set(fields_to_collect))

            # Generate form definition
            form = self.form_generator.from_tool_schema(
                tool=tool,
                prefilled=known_values,
                exclude_fields=exclude_fields,
                custom_title=form_title,
            )

            # Add metadata for the wrapper to use
            form.metadata.update({
                "target_tool": target_tool,
                "known_values": known_values,
                "context_message": context_message,
                "requested_by_llm": True,
            })

            # Build user-friendly message
            fields_needed = []
            for section in form.sections:
                for field in section.fields:
                    if field.name not in known_values:
                        fields_needed.append(field.label or field.name)

            message = context_message or f"I need some information to proceed with {tool.name}."
            if fields_needed:
                message += f" Please provide: {', '.join(fields_needed[:5])}"
                if len(fields_needed) > 5:
                    message += f" and {len(fields_needed) - 5} more fields."

            return ToolResult(
                status="form_requested",
                result={
                    "message": message,
                    "form_id": form.form_id,
                    "target_tool": target_tool,
                    "fields_count": len(fields_needed),
                },
                metadata={
                    "requires_form": True,
                    "form_definition": form,
                    "target_tool": target_tool,
                    "known_values": known_values,
                }
            )

        except Exception as e:
            logger.error(
                f"Error generating form for {target_tool}: {e}", exc_info=True
            )
            return ToolResult(
                status="error",
                error=f"Failed to generate form: {str(e)}",
                result=None,
            )

    def get_tool_schema(self) -> Dict[str, Any]:
        """Get the tool schema with enhanced description."""
        base_schema = super().get_tool_schema()

        # Add examples to help LLM understand usage
        base_schema["examples"] = [
            {
                "description": "Request form for employee creation",
                "input": {
                    "target_tool": "create_employee",
                    "known_values": {},
                    "form_title": "New Employee Registration"
                }
            },
            {
                "description": "Request form with some known values",
                "input": {
                    "target_tool": "send_email",
                    "known_values": {"recipient": "john@example.com"},
                    "fields_to_collect": ["subject", "body"],
                    "context_message": "I'll help you compose an email to John."
                }
            }
        ]

        return base_schema
