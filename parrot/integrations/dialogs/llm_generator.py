"""
LLM Form Generator - Generates forms dynamically from tool schemas.

Supports:
- Direct schema conversion (no LLM needed)
- LLM-assisted form generation with smart defaults
- Field filtering based on known values
"""
from typing import Dict, List, Any, Optional
import logging
from pydantic import BaseModel, Field
from .models import (
    FormDefinition,
    FormSection,
    FormField,
    FieldType,
    FieldValidation,
    ValidationRule,
    DialogPreset,
)
from ...tools.abstract import AbstractTool
from ...bots.abstract import AbstractBot


logger = logging.getLogger(__name__)


# =============================================================================
# Structured Output Models for LLM
# =============================================================================

class FieldAnalysis(BaseModel):
    """Analysis of a single field."""
    name: str
    is_required: bool
    has_default: bool
    can_be_inferred: bool
    inferred_value: Optional[Any] = None
    inference_reason: Optional[str] = None


class FormAnalysisResponse(BaseModel):
    """LLM response for form analysis."""
    tool_name: str
    tool_description: str
    fields_analysis: List[FieldAnalysis]
    suggested_title: str
    suggested_sections: List[Dict[str, Any]]
    prefilled_values: Dict[str, Any] = Field(default_factory=dict)


class ToolSelectionResponse(BaseModel):
    """LLM response for tool selection."""
    needs_tool: bool
    tool_name: Optional[str] = None
    confidence: float = 0.0
    extracted_values: Dict[str, Any] = Field(default_factory=dict)
    missing_required: List[str] = Field(default_factory=list)
    reason: str = ""


# =============================================================================
# Type Mapping
# =============================================================================

# JSON Schema type to FieldType mapping
JSON_TYPE_TO_FIELD_TYPE = {
    "string": FieldType.TEXT,
    "integer": FieldType.NUMBER,
    "number": FieldType.NUMBER,
    "boolean": FieldType.TOGGLE,
    "array": FieldType.MULTICHOICE,
}

# JSON Schema format to FieldType mapping
JSON_FORMAT_TO_FIELD_TYPE = {
    "date": FieldType.DATE,
    "date-time": FieldType.DATETIME,
    "email": FieldType.EMAIL,
    "uri": FieldType.URL,
    "url": FieldType.URL,
}


# =============================================================================
# LLM Form Generator
# =============================================================================

class LLMFormGenerator:
    """
    Generates FormDefinitions from tool schemas.

    Two modes:
    1. Direct conversion: Schema → FormDefinition (fast, no LLM)
    2. LLM-assisted: Analyzes context to determine defaults and groupings
    """

    def __init__(
        self,
        agent: Optional['AbstractBot'] = None,
        default_preset: DialogPreset = DialogPreset.WIZARD,
    ):
        """
        Initialize the form generator.

        Args:
            agent: Optional agent for LLM-assisted generation
            default_preset: Default dialog preset to use
        """
        self.agent = agent
        self.default_preset = default_preset

    # =========================================================================
    # Direct Schema Conversion (No LLM)
    # =========================================================================

    def from_tool_schema(
        self,
        tool: 'AbstractTool',
        prefilled: Dict[str, Any] = None,
        exclude_fields: List[str] = None,
        custom_title: str = None,
    ) -> FormDefinition:
        """
        Generate FormDefinition directly from a tool's args_schema.

        This is the fast path - no LLM involved.

        Args:
            tool: The tool to generate form for
            prefilled: Values to pre-fill in the form
            exclude_fields: Field names to exclude from form
            custom_title: Custom form title

        Returns:
            FormDefinition ready to be rendered
        """
        prefilled = prefilled or {}
        exclude_fields = set(exclude_fields or [])

        if not hasattr(tool, 'args_schema') or tool.args_schema is None:
            raise ValueError(f"Tool '{tool.name}' has no args_schema defined")

        # Get JSON schema from Pydantic model
        schema = tool.args_schema.model_json_schema()
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        defs = schema.get("$defs", {})

        # Build fields
        fields = []
        for prop_name, prop_schema in properties.items():
            # Skip excluded fields from explicit list
            if prop_name in exclude_fields:
                continue

            # Skip fields marked with x-exclude-form in json_schema_extra
            if prop_schema.get("x-exclude-form", False):
                continue


            # Skip fields that are pre-filled (unless we want to show them)
            # For now, include all but mark as pre-filled

            field = self._schema_property_to_field(
                name=prop_name,
                prop_schema=prop_schema,
                is_required=prop_name in required,
                defs=defs,
            )

            # Apply pre-filled value as default
            if prop_name in prefilled:
                field.default = prefilled[prop_name]

            fields.append(field)

        # Determine preset based on field count
        if len(fields) <= 3:
            preset = DialogPreset.SIMPLE
        elif len(fields) <= 6:
            preset = DialogPreset.WIZARD
        else:
            preset = DialogPreset.WIZARD_WITH_SUMMARY

        # Create form definition
        form = FormDefinition(
            form_id=f"{tool.name}_form",
            title=custom_title or self._generate_title(tool),
            sections=[
                FormSection(
                    name="parameters",
                    title=tool.description or f"{tool.name} Parameters",
                    fields=fields,
                )
            ],
            preset=preset,
            submit_action=tool.name,
            metadata={
                "tool_name": tool.name,
                "prefilled": prefilled,
                "generated_from": "schema",
            }
        )
        print(
            f"✅ Form generated from schema for tool '{tool.name}' with {len(fields)} fields"
        )
        return form

    def _schema_property_to_field(
        self,
        name: str,
        prop_schema: Dict[str, Any],
        is_required: bool,
        defs: Dict[str, Any],
    ) -> FormField:
        """Convert a JSON Schema property to a FormField."""

        # Handle $ref
        if "$ref" in prop_schema:
            ref_path = prop_schema["$ref"].split("/")[-1]
            if ref_path in defs:
                prop_schema = {**defs[ref_path], **prop_schema}

        # Handle anyOf/oneOf (usually for Optional types)
        if "anyOf" in prop_schema:
            # Find the non-null type
            for variant in prop_schema["anyOf"]:
                if variant.get("type") != "null":
                    prop_schema = {
                        **variant, **{k: v for k, v in prop_schema.items() if k != "anyOf"}
                    }
                    break

        # Determine field type
        field_type = self._determine_field_type(prop_schema)

        # Extract choices for enums
        choices = None
        if "enum" in prop_schema:
            choices = prop_schema["enum"]
            field_type = FieldType.MULTICHOICE if prop_schema.get("type") == "array" else FieldType.CHOICE

        # Build validations
        validations = self._extract_validations(prop_schema, is_required)

        return FormField(
            name=name,
            field_type=field_type,
            label=prop_schema.get("title", name.replace("_", " ").title()),
            description=prop_schema.get("description", ""),
            placeholder=prop_schema.get("examples", [None])[0] if prop_schema.get("examples") else None,
            required=is_required,
            default=prop_schema.get("default"),
            choices=choices,
            validations=validations,
        )

    def _determine_field_type(self, prop_schema: Dict[str, Any]) -> FieldType:
        """Determine FieldType from JSON Schema property."""

        # Check format first (more specific)
        fmt = prop_schema.get("format")
        if fmt and fmt in JSON_FORMAT_TO_FIELD_TYPE:
            return JSON_FORMAT_TO_FIELD_TYPE[fmt]

        # Check for enum (choice)
        if "enum" in prop_schema:
            return FieldType.CHOICE
        # Check type
        json_type = prop_schema.get("type", "string")

        # Handle array type
        if json_type == "array":
            items = prop_schema.get("items", {})
            if "enum" in items:
                return FieldType.MULTICHOICE
            return FieldType.TEXTAREA  # Default array to textarea

        # Check for multiline hint
        if json_type == "string":
            max_length = prop_schema.get("maxLength", 0)
            if max_length > 200 or prop_schema.get("x-multiline"):
                return FieldType.TEXTAREA

        return JSON_TYPE_TO_FIELD_TYPE.get(json_type, FieldType.TEXT)

    def _extract_validations(
        self,
        prop_schema: Dict[str, Any],
        is_required: bool,
    ) -> List[FieldValidation]:
        """Extract validation rules from JSON Schema."""
        validations = []

        if is_required:
            validations.append(FieldValidation(rule=ValidationRule.REQUIRED))

        if "minLength" in prop_schema:
            validations.append(FieldValidation(
                rule=ValidationRule.MIN_LENGTH,
                value=prop_schema["minLength"],
            ))

        if "maxLength" in prop_schema:
            validations.append(FieldValidation(
                rule=ValidationRule.MAX_LENGTH,
                value=prop_schema["maxLength"],
            ))

        if "minimum" in prop_schema:
            validations.append(FieldValidation(
                rule=ValidationRule.MIN_VALUE,
                value=prop_schema["minimum"],
            ))

        if "maximum" in prop_schema:
            validations.append(FieldValidation(
                rule=ValidationRule.MAX_VALUE,
                value=prop_schema["maximum"],
            ))

        if "pattern" in prop_schema:
            validations.append(FieldValidation(
                rule=ValidationRule.PATTERN,
                value=prop_schema["pattern"],
            ))

        fmt = prop_schema.get("format")
        if fmt == "email":
            validations.append(FieldValidation(rule=ValidationRule.EMAIL))
        elif fmt in ("uri", "url"):
            validations.append(FieldValidation(rule=ValidationRule.URL))

        return validations

    def _generate_title(self, tool: 'AbstractTool') -> str:
        """Generate a user-friendly title from tool."""
        name = tool.name.replace("_", " ").replace("-", " ")
        # Title case
        return name.title()

    # =========================================================================
    # LLM-Assisted Generation
    # =========================================================================

    async def analyze_and_generate(
        self,
        tool: 'AbstractTool',
        user_query: str,
        conversation_context: str = "",
    ) -> FormDefinition:
        """
        Use LLM to analyze context and generate optimized form.

        The LLM will:
        1. Determine which fields can be inferred from context
        2. Suggest appropriate groupings/sections
        3. Pre-fill values it can confidently extract

        Args:
            tool: The tool to generate form for
            user_query: The user's original query
            conversation_context: Recent conversation for context

        Returns:
            FormDefinition with intelligent defaults
        """
        if not self.agent:
            # Fallback to direct conversion
            return self.from_tool_schema(tool)

        # Get schema info
        schema = tool.args_schema.model_json_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Build prompt for LLM analysis
        prompt = self._build_analysis_prompt(
            tool=tool,
            properties=properties,
            required=required,
            user_query=user_query,
            context=conversation_context,
        )

        try:
            # Ask LLM for analysis
            response = await self.agent.ask(
                prompt,
                structured_output=FormAnalysisResponse,
                use_tools=False,
            )

            # Parse and apply LLM suggestions
            return self._apply_llm_analysis(tool, response, properties, required)

        except Exception as e:
            logger.warning(f"LLM analysis failed, using direct conversion: {e}")
            return self.from_tool_schema(tool)

    def _build_analysis_prompt(
        self,
        tool: 'AbstractTool',
        properties: Dict[str, Any],
        required: List[str],
        user_query: str,
        context: str,
    ) -> str:
        """Build prompt for LLM form analysis."""

        # Format properties for the prompt
        props_description = []
        for name, prop in properties.items():
            req = "(required)" if name in required else "(optional)"
            desc = prop.get("description", "No description")
            default = prop.get("default", "None")
            props_description.append(
                f"- {name} {req}: {desc} [default: {default}]"
            )

        return f"""Analyze this tool and user request to determine form configuration.

TOOL: {tool.name}
DESCRIPTION: {tool.description}

PARAMETERS:
{chr(10).join(props_description)}

USER QUERY: "{user_query}"

CONVERSATION CONTEXT:
{context or "No previous context"}

YOUR TASK:
1. Analyze which parameter values can be CONFIDENTLY inferred from the user query or context
2. Only infer values you are HIGHLY confident about (90%+)
3. Suggest a user-friendly form title
4. Group related fields into logical sections if there are 4+ fields

Respond with:
- tool_name: the tool name
- tool_description: brief description
- fields_analysis: for each field, analyze if it can be inferred
- suggested_title: user-friendly title for the form
- suggested_sections: how to group fields (name, title, field_names)
- prefilled_values: values you can confidently fill

Be CONSERVATIVE with inferences. When in doubt, leave the field for the user to fill."""

    def _apply_llm_analysis(
        self,
        tool: 'AbstractTool',
        analysis: FormAnalysisResponse,
        properties: Dict[str, Any],
        required: List[str],
    ) -> FormDefinition:
        """Apply LLM analysis to generate optimized form."""

        schema = tool.args_schema.model_json_schema()
        defs = schema.get("$defs", {})

        # Build fields with LLM insights
        all_fields = {}
        for prop_name, prop_schema in properties.items():
            field = self._schema_property_to_field(
                name=prop_name,
                prop_schema=prop_schema,
                is_required=prop_name in required,
                defs=defs,
            )

            # Apply inferred value if available
            if prop_name in analysis.prefilled_values:
                field.default = analysis.prefilled_values[prop_name]

            all_fields[prop_name] = field

        # Build sections from LLM suggestions
        sections = []
        used_fields = set()

        for section_data in analysis.suggested_sections:
            section_fields = []
            for field_name in section_data.get("field_names", []):
                if field_name in all_fields:
                    section_fields.append(all_fields[field_name])
                    used_fields.add(field_name)

            if section_fields:
                sections.append(FormSection(
                    name=section_data.get("name", f"section_{len(sections)}"),
                    title=section_data.get("title", "Information"),
                    fields=section_fields,
                ))

        # Add any remaining fields to a final section
        if remaining_fields := [
            all_fields[name] for name in all_fields if name not in used_fields
        ]:
            if sections:
                # Add to last section
                sections[-1].fields.extend(remaining_fields)
            else:
                # Create default section
                sections.append(FormSection(
                    name="parameters",
                    title="Parameters",
                    fields=remaining_fields,
                ))

        # Determine preset
        total_fields = sum(len(s.fields) for s in sections)
        if total_fields <= 3:
            preset = DialogPreset.SIMPLE
        elif len(sections) > 1 or total_fields > 6:
            preset = DialogPreset.WIZARD_WITH_SUMMARY
        else:
            preset = DialogPreset.WIZARD

        return FormDefinition(
            form_id=f"{tool.name}_form",
            title=analysis.suggested_title or self._generate_title(tool),
            sections=sections,
            preset=preset,
            submit_action=tool.name,
            metadata={
                "tool_name": tool.name,
                "prefilled": analysis.prefilled_values,
                "generated_from": "llm_analysis",
            }
        )
