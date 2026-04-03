"""Tool extractor for FormSchema generation from AbstractTool instances.

Extracts FormSchema from a tool's args_schema by delegating to PydanticExtractor
with tool-specific metadata (name, description) and field filtering.
"""

from typing import Any

from ..schema import FormField, FormSchema, FormSection
from .pydantic import PydanticExtractor


class ToolExtractor:
    """Extracts FormSchema from AbstractTool.args_schema.

    Delegates Pydantic model introspection to PydanticExtractor, then
    applies tool-specific metadata and field filtering:
    - Excludes context fields (AbstractToolArgsSchema._context_fields)
    - Excludes pre-filled known_values fields
    - Sets form_id to "{tool.name}_form"
    - Uses tool.description as form description

    Example:
        extractor = ToolExtractor()
        schema = extractor.extract(my_tool, known_values={"user_id": "123"})
    """

    def __init__(self, pydantic_extractor: PydanticExtractor | None = None) -> None:
        """Initialize ToolExtractor.

        Args:
            pydantic_extractor: Optional PydanticExtractor instance to use.
                Defaults to a new PydanticExtractor.
        """
        self._pydantic = pydantic_extractor or PydanticExtractor()

    def extract(
        self,
        tool: Any,
        *,
        exclude_fields: set[str] | None = None,
        known_values: dict[str, Any] | None = None,
    ) -> FormSchema:
        """Extract FormSchema from a tool's args_schema.

        Args:
            tool: AbstractTool instance (or duck-typed object with name,
                description, args_schema attributes).
            exclude_fields: Additional field IDs to exclude from the form.
            known_values: Pre-filled field values. Fields in this dict are
                excluded from the generated form.

        Returns:
            FormSchema representing the tool's input parameters.

        Raises:
            ValueError: If the tool has no args_schema.
        """
        # Validate args_schema presence
        if not hasattr(tool, "args_schema") or tool.args_schema is None:
            raise ValueError(
                f"Tool '{getattr(tool, 'name', repr(tool))}' has no args_schema. "
                "Cannot generate form without an args_schema."
            )

        schema_class = tool.args_schema
        tool_name = getattr(tool, "name", "tool")
        tool_description = getattr(tool, "description", None)

        # Build exclusion set
        excluded: set[str] = set(exclude_fields or set())

        # Exclude AbstractToolArgsSchema context fields
        # In Pydantic v2, _context_fields is a private attribute stored in __private_attributes__
        context_fields = frozenset()
        private_attrs = getattr(schema_class, "__private_attributes__", {})
        if "_context_fields" in private_attrs:
            cf_attr = private_attrs["_context_fields"]
            context_fields = cf_attr.default if cf_attr.default is not None else frozenset()
        excluded.update(context_fields)

        # Exclude known_values fields (pre-filled, not needed in form)
        if known_values:
            excluded.update(known_values.keys())

        # Extract full schema via PydanticExtractor
        full_schema = self._pydantic.extract(
            schema_class,
            form_id=f"{tool_name}_form",
            title=self._format_tool_title(tool_name),
        )

        # Filter fields to remove excluded ones
        filtered_fields: list[FormField] = []
        for section in full_schema.sections:
            for field in section.fields:
                if field.field_id not in excluded:
                    filtered_fields.append(field)

        return FormSchema(
            form_id=f"{tool_name}_form",
            title=self._format_tool_title(tool_name),
            description=tool_description,
            sections=[
                FormSection(
                    section_id="parameters",
                    title="Parameters",
                    fields=filtered_fields,
                )
            ],
        )

    @staticmethod
    def _format_tool_title(tool_name: str) -> str:
        """Format a tool name into a human-readable form title.

        Args:
            tool_name: Tool name in snake_case (e.g., "search_tool").

        Returns:
            Title-cased string (e.g., "Search Tool").
        """
        return tool_name.replace("_", " ").title()
