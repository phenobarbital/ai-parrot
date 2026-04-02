"""CreateFormTool — LLM-driven form generation tool.

Accepts a natural language prompt and returns a validated FormSchema.
Supports iterative refinement: when refine_form_id is provided, loads
the existing form and asks the LLM to modify it.

Flow:
1. Build a structured system prompt with FormSchema JSON structure
2. If refine_form_id, load existing form from registry and include in prompt
3. Call LLM client to generate JSON
4. Parse and validate against FormSchema (retry up to 2 times with error feedback)
5. Validate generated form using FormValidator (circular dependency check)
6. Optionally register in FormRegistry with persist=True
7. Return FormSchema in ToolResult metadata
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ...tools.abstract import AbstractTool, ToolResult
from ..registry import FormRegistry
from ..schema import FormSchema
from ..types import FieldType
from ..validators import FormValidator

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a form schema generator. Your task is to generate a FormSchema JSON object.

The FormSchema must follow this structure:
{
  "form_id": "string (slug, lowercase with hyphens)",
  "title": "string",
  "description": "string (optional)",
  "sections": [
    {
      "section_id": "string",
      "title": "string (optional)",
      "fields": [
        {
          "field_id": "string (snake_case)",
          "field_type": "one of: text, text_area, number, integer, boolean, date, datetime, time, select, multi_select, file, image, color, url, email, phone, password, hidden, group, array",
          "label": "string",
          "description": "string (optional)",
          "required": true/false,
          "placeholder": "string (optional)",
          "default": "any (optional)",
          "constraints": {
            "min_length": int, "max_length": int,
            "min_value": float, "max_value": float,
            "pattern": "regex string"
          },
          "options": [
            {"value": "string", "label": "string"}
          ]
        }
      ]
    }
  ]
}

IMPORTANT:
- Respond with ONLY valid JSON. No markdown, no explanations.
- Use snake_case for all IDs.
- field_type must be one of the exact values listed above.
- For select/multi_select fields, always include an options array.
- Generate meaningful field IDs that match the label.
"""

_REFINEMENT_PROMPT = """You are a form schema editor. Your task is to modify an existing FormSchema.

Current form JSON:
{existing_form}

User request: {prompt}

Apply the requested modifications to the form and respond with the COMPLETE updated FormSchema JSON.
IMPORTANT: Respond with ONLY valid JSON. No markdown, no explanations.
"""

_RETRY_PROMPT = """Your previous response was not a valid FormSchema. Error: {error}

Please try again and respond with ONLY valid JSON matching the FormSchema structure.
{previous_attempt}
"""


def _slugify(text: str) -> str:
    """Convert text to a slug suitable for form_id.

    Args:
        text: Input string.

    Returns:
        Lowercase slug with hyphens.
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:50] or f"form-{uuid.uuid4().hex[:8]}"


def _extract_json(text: str) -> str:
    """Extract JSON from LLM response (handles markdown code blocks).

    Args:
        text: Raw LLM response text.

    Returns:
        Extracted JSON string.
    """
    # Try to strip markdown code blocks
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1).strip()
    # Try to find first { ... } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        return match.group(0)
    return text.strip()


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class CreateFormInput(BaseModel):
    """Input schema for the create_form tool.

    Attributes:
        prompt: Natural language description of the form to create.
        form_id: Custom form ID. Auto-generated if not provided.
        persist: Whether to save the form to the registry storage.
        refine_form_id: ID of an existing form to load and modify.
    """

    prompt: str = Field(
        ...,
        description="Natural language description of the form to create or modification to apply",
    )
    form_id: str | None = Field(
        default=None,
        description="Custom form ID (slug). Auto-generated from title if not provided.",
    )
    persist: bool = Field(
        default=False,
        description="Save the generated form to the registry (and storage if configured)",
    )
    refine_form_id: str | None = Field(
        default=None,
        description=(
            "Form ID of an existing form to load and refine. "
            "If set, the existing form is modified based on the prompt."
        ),
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

class CreateFormTool(AbstractTool):
    """Create a FormSchema from a natural language prompt using an LLM.

    Supports:
    - New form creation from a prompt
    - Iterative refinement of an existing form
    - Pydantic validation with up to 2 retries (error feedback to LLM)
    - Circular dependency detection via FormValidator
    - Optional registry persistence

    Example:
        tool = CreateFormTool(client=llm_client, registry=registry)
        result = await tool.execute(prompt="Create a customer feedback form")
        form_schema = FormSchema(**result.metadata["form"])
    """

    name: str = "create_form"
    description: str = (
        "Create a form from a natural language description, "
        "or refine an existing form. "
        "Responds with a validated FormSchema. "
        "Use persist=True to save the form for future use."
    )
    args_schema = CreateFormInput

    MAX_RETRIES = 2

    def __init__(
        self,
        client: Any,
        registry: FormRegistry | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize CreateFormTool.

        Args:
            client: LLM client with a completion() or ask() method.
            registry: Optional FormRegistry for refinement lookups and persistence.
        """
        super().__init__(**kwargs)
        self._client = client
        self._registry = registry
        self._validator = FormValidator()
        self.logger = logging.getLogger(__name__)

    async def _execute(
        self,
        prompt: str,
        form_id: str | None = None,
        persist: bool = False,
        refine_form_id: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Generate and validate a FormSchema via LLM.

        Args:
            prompt: Natural language form description or modification request.
            form_id: Custom form_id. Auto-generated if not provided.
            persist: If True, register the form in the registry.
            refine_form_id: If set, load existing form and modify it.

        Returns:
            ToolResult with success=True and form dict in metadata["form"],
            or success=False with error details on failure.
        """
        try:
            # Build the initial prompt
            if refine_form_id and self._registry:
                existing = await self._registry.get(refine_form_id)
                if existing is None:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        metadata={
                            "error": f"Form '{refine_form_id}' not found in registry"
                        },
                    )
                messages = self._build_refinement_messages(existing, prompt)
            else:
                messages = self._build_creation_messages(prompt)

            # LLM generation loop with retry
            form = await self._generate_with_retry(messages, form_id)

            if form is None:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    metadata={
                        "error": "Failed to generate a valid FormSchema after retries"
                    },
                )

            # Validate with FormValidator
            validation = await self._validator.validate(form, {})
            if not validation.is_valid:
                # Circular dependencies or other schema errors
                self.logger.warning(
                    "Generated form has validation issues: %s", validation.errors
                )
                # Don't fail — still return the form with a warning in metadata

            # Optionally persist
            if persist and self._registry:
                try:
                    await self._registry.register(form, persist=True)
                except Exception as exc:
                    self.logger.warning(
                        "Failed to persist form %s: %s", form.form_id, exc
                    )

            return ToolResult(
                success=True,
                status="success",
                result={"form_id": form.form_id, "title": str(form.title)},
                metadata={
                    "form": form.model_dump(),
                    "validation_errors": validation.errors if not validation.is_valid else {},
                },
            )

        except Exception as exc:
            self.logger.error("CreateFormTool error: %s", exc, exc_info=True)
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={"error": str(exc)},
            )

    def _build_creation_messages(self, prompt: str) -> list[dict[str, str]]:
        """Build LLM messages for new form creation.

        Args:
            prompt: User's natural language description.

        Returns:
            List of chat message dicts.
        """
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Create a form for: {prompt}"},
        ]

    def _build_refinement_messages(
        self, existing: FormSchema, prompt: str
    ) -> list[dict[str, str]]:
        """Build LLM messages for form refinement.

        Args:
            existing: Existing FormSchema to modify.
            prompt: Modification request.

        Returns:
            List of chat message dicts.
        """
        existing_json = existing.model_dump_json(indent=2)
        user_content = _REFINEMENT_PROMPT.format(
            existing_form=existing_json,
            prompt=prompt,
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call the LLM client and return text response.

        Supports both completion(messages) and ask(message) interfaces.

        Args:
            messages: List of chat message dicts.

        Returns:
            Raw LLM response text.
        """
        if hasattr(self._client, "completion"):
            return await self._client.completion(messages)
        elif hasattr(self._client, "ask"):
            # Combine messages into a single string for ask() interface
            text = "\n\n".join(m["content"] for m in messages)
            response = await self._client.ask(text)
            return str(response)
        else:
            raise RuntimeError(
                "LLM client has neither completion() nor ask() method"
            )

    async def _generate_with_retry(
        self,
        messages: list[dict[str, str]],
        form_id: str | None,
    ) -> FormSchema | None:
        """Generate and validate FormSchema with retry on validation failure.

        Args:
            messages: Initial LLM messages.
            form_id: Optional custom form_id.

        Returns:
            Validated FormSchema, or None after max retries.
        """
        current_messages = list(messages)

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                raw = await self._call_llm(current_messages)
                json_str = _extract_json(raw)
                data = json.loads(json_str)

                # Apply custom form_id if provided
                if form_id:
                    data["form_id"] = form_id
                elif "form_id" not in data or not data["form_id"]:
                    title = data.get("title", "generated-form")
                    data["form_id"] = _slugify(
                        title if isinstance(title, str) else "generated-form"
                    )

                form = FormSchema.model_validate(data)
                return form

            except Exception as exc:
                if attempt >= self.MAX_RETRIES:
                    self.logger.error(
                        "FormSchema validation failed after %d attempts: %s",
                        attempt + 1,
                        exc,
                    )
                    return None

                # Retry with error feedback
                self.logger.warning(
                    "Attempt %d failed (%s), retrying...", attempt + 1, exc
                )
                retry_content = _RETRY_PROMPT.format(
                    error=str(exc),
                    previous_attempt=json_str if "json_str" in dir() else "(no output)",
                )
                current_messages = list(messages) + [
                    {"role": "assistant", "content": raw if "raw" in dir() else ""},
                    {"role": "user", "content": retry_content},
                ]

        return None
