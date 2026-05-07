"""RequestFormTool — platform-agnostic form request tool.

Allows the LLM to request a structured form from the user when it needs to
collect parameters for another tool. Migrated from
parrot/integrations/msteams/tools/request_form.py — no longer Teams-specific.

Flow:
1. LLM calls request_form(target_tool="search", known_values={"limit": 10})
2. RequestFormTool looks up the target tool in ToolManager
3. Uses ToolExtractor to generate FormSchema, excluding known fields
4. Returns ToolResult(status="form_requested", metadata={"form": schema_dict, ...})
5. The platform wrapper (Teams, Telegram, web) detects status and renders the form
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner tools require the 'ai-parrot' package. "
        "Install it with: uv add ai-parrot"
    ) from exc
from ..extractors.tool import ToolExtractor
from ..services.registry import FormRegistry
from ..core.schema import FormSchema

if TYPE_CHECKING:
    from parrot.tools.manager import ToolManager

logger = logging.getLogger(__name__)


class RequestFormInput(BaseModel):
    """Input schema for the request_form tool.

    Attributes:
        target_tool: Name of the tool to execute after form completion.
        known_values: Parameter values already extracted from conversation.
        fields_to_collect: Specific field names to include in the form.
        form_title: Custom form title.
        context_message: Message explaining to the user why the form is needed.
    """

    target_tool: str = Field(
        ...,
        description=(
            "Name of the tool you intend to execute after collecting data from the user"
        ),
    )
    known_values: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameter values you have already extracted from the conversation. "
            "These will be pre-filled in the form and excluded from collection."
        ),
    )
    fields_to_collect: list[str] | None = Field(
        default=None,
        description=(
            "Specific field names to collect from the user. "
            "If not provided, all required fields not in known_values will be included."
        ),
    )
    form_title: str | None = Field(
        default=None,
        description="Custom title for the form. Auto-generated if not provided.",
    )
    context_message: str | None = Field(
        default=None,
        description="Optional message to show the user explaining why the form is needed.",
    )


class RequestFormTool(AbstractTool):
    """Platform-agnostic tool that requests a form to collect missing parameters.

    The LLM should use this tool when it determines that:
    - A tool needs to be executed but is missing required parameters
    - The missing information is best collected via a structured form
    - Multiple parameters need to be gathered at once

    The tool generates a FormSchema using ToolExtractor and returns it in the
    ToolResult metadata. Platform wrappers (Teams, Telegram, web) detect the
    status="form_requested" signal and render the appropriate form UI.

    Example:
        tool = RequestFormTool(tool_manager=manager)
        result = await tool.execute(
            target_tool="create_employee",
            known_values={"department": "Engineering"},
        )
        # result.status == "form_requested"
        # result.metadata["form"] == FormSchema dict
    """

    name: str = "request_form"
    description: str = (
        "Request structured data collection from the user via a form. "
        "Use this when you need to execute a tool but are missing required parameters. "
        "Set target_tool to the tool you want to execute after the user fills out the form. "
        "Set known_values to any parameters you already know."
    )
    args_schema = RequestFormInput

    def __init__(
        self,
        tool_manager: ToolManager,
        form_registry: FormRegistry | None = None,
        tool_extractor: ToolExtractor | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize RequestFormTool.

        Args:
            tool_manager: Manager for looking up and listing tools.
            form_registry: Optional registry for looking up pre-defined forms.
            tool_extractor: Optional ToolExtractor instance (created if None).
        """
        super().__init__(**kwargs)
        self.tool_manager = tool_manager
        self.form_registry = form_registry
        self._extractor = tool_extractor or ToolExtractor()
        self.logger = logging.getLogger(__name__)

    async def _execute(
        self,
        target_tool: str,
        known_values: dict[str, Any] | None = None,
        fields_to_collect: list[str] | None = None,
        form_title: str | None = None,
        context_message: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Generate a FormSchema for the target tool and return form_requested.

        Args:
            target_tool: Name of the tool to execute after form completion.
            known_values: Already-known parameter values to exclude from form.
            fields_to_collect: Specific fields to include (all required if None).
            form_title: Custom form title.
            context_message: Optional user-facing message.

        Returns:
            ToolResult with status="form_requested" and form schema in metadata.
        """
        known_values = known_values or {}

        # Look up target tool
        tool = self.tool_manager.get_tool(target_tool)
        if tool is None:
            available = getattr(self.tool_manager, "list_tools", lambda: [])()
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={
                    "error": f"Target tool '{target_tool}' not found",
                    "available_tools": available,
                },
            )

        # Validate tool has a schema
        if not hasattr(tool, "args_schema") or tool.args_schema is None:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={
                    "error": (
                        f"Target tool '{target_tool}' has no args_schema "
                        "and cannot be used with forms."
                    )
                },
            )

        try:
            # Determine exclude_fields:
            # Always exclude known_values fields.
            # If fields_to_collect is provided, also exclude everything not in that list.
            exclude_fields: list[str] = list(known_values.keys())

            if fields_to_collect:
                schema_props: set[str] = set(
                    tool.args_schema.model_json_schema()
                    .get("properties", {})
                    .keys()
                )
                exclude_fields = list(
                    schema_props - set(fields_to_collect) | set(known_values.keys())
                )

            # Temporarily patch name/description if custom title provided
            # ToolExtractor uses tool.name as form_id base and tool.description
            # as form description — we pass known_values and exclude_fields directly
            form: FormSchema = self._extractor.extract(
                tool,
                known_values=known_values,
                exclude_fields=set(exclude_fields) if exclude_fields else None,
            )

            # Apply custom title if provided
            if form_title:
                form = form.model_copy(update={"title": form_title})

            # Collect the field labels for the user message
            fields_needed: list[str] = []
            for section in form.sections:
                for field in section.fields:
                    lbl = field.label
                    if isinstance(lbl, dict):
                        lbl = lbl.get("en", field.field_id)
                    fields_needed.append(lbl or field.field_id)

            message = context_message or (
                f"I need some information to proceed with {target_tool}."
            )
            if fields_needed:
                shown = ", ".join(fields_needed[:5])
                extra = (
                    f" and {len(fields_needed) - 5} more"
                    if len(fields_needed) > 5
                    else ""
                )
                message += f" Please provide: {shown}{extra}."

            return ToolResult(
                success=True,
                status="form_requested",
                result={
                    "message": message,
                    "form_id": form.form_id,
                    "target_tool": target_tool,
                    "fields_count": len(fields_needed),
                },
                metadata={
                    "form": form.model_dump(),
                    "target_tool": target_tool,
                    "known_values": known_values,
                    "context_message": context_message,
                    "requires_form": True,
                },
            )

        except Exception as exc:
            self.logger.error(
                "Error generating form for %s: %s", target_tool, exc, exc_info=True
            )
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={"error": f"Failed to generate form: {exc}"},
            )
