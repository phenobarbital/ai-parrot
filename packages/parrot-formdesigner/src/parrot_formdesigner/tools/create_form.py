"""CreateFormTool — LLM-driven and deterministic form generation tool.

Accepts either a natural language prompt (LLM path) or fully structured
input (`schema`, `sections`, `fields` — deterministic path via
`FormAssembler`, zero LLM calls) and returns a validated FormSchema.
Supports iterative refinement: when refine_form_uid is provided, loads
the existing form (by its immutable form_uid, FEAT-389) and asks the LLM
to modify it.

LLM flow (prompt-only):
1. Build a structured system prompt with FormSchema JSON structure
2. If refine_form_uid, load existing form from registry (by form_uid) and
   include in prompt
3. Call LLM client to generate JSON
4. Parse and validate against FormSchema (retry up to 2 times with error feedback)
5. Validate generated form using FormValidator (circular dependency check)
6. Optionally register in FormRegistry with persist=True
7. Return FormSchema in ToolResult metadata (including form_uid)

FEAT-389: the LLM never generates form_uid — it is always injected by this
tool. New forms get a fresh `str(uuid.uuid4())` (or a caller-supplied
`form_uid`); refinements preserve the existing form's form_uid unchanged
(only form_id/slug and content may change via a refinement prompt).

Deterministic flow (schema/sections/fields — FEAT-388):
1. Detect which structured input was provided
2. Delegate to `FormAssembler` for format detection, shortcut expansion,
   and assembly — no LLM call
3. Validate generated form using FormValidator (circular dependency check)
4. Optionally register in FormRegistry with persist=True
5. Return FormSchema in ToolResult metadata (same shape as the LLM path)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
import warnings
from typing import Any

from pydantic import BaseModel, Field, ValidationError

try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner tools require the 'ai-parrot' package. " "Install it with: uv add ai-parrot"
    ) from exc
from ..assembler import FormAssembler, _slugify
from ..core.schema import FormSchema
from ..services.registry import FormRegistry
from ..services.validators import FormValidator
from .edit_toolkit import EditToolkit
from .field_helpers import (
    get_form_field_schema_snippets,
    list_supported_form_field_types,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_FIELD_TYPE_VALUES = ", ".join(list_supported_form_field_types())
_FIELD_SNIPPETS_JSON = json.dumps(get_form_field_schema_snippets(), indent=2)

_SYSTEM_PROMPT_TEMPLATE = """You are a form schema generator. Your task is to generate a FormSchema JSON object.

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
          "field_type": "one of: __FIELD_TYPES__",
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

Accepted field types:
__FIELD_TYPES__

Field snippet reference by type:
__FIELD_SNIPPETS__

Optional dependency rules on fields:

  "depends_on": {
    "conditions": [{"field_id": "other_field_id", "operator": "eq", "value": "some_value"}],
    "logic": "and",
    "effect": "show",
    "operations": null
  }

  Valid logic values: "and", "or", "xor", "not"
  Valid effect values: "show", "hide", "require", "disable"
  "depends_on" must only reference field_ids declared EARLIER in the form.

  "post_depends": [
    {
      "target": "later_field_id",
      "effect": "cascade_clear",
      "conditions": null,
      "logic": "and",
      "operation": null
    }
  ]

  Valid post_depends effect values: "set", "calc", "reload_options", "show", "hide", "require", "cascade_clear"
  "post_depends" must only target field_ids declared LATER in the form.
  "set" and "calc" effects require an "operation" with: {"op": "copy|add|subtract|...", "operands": ["field_id"], "target": "field_id"}

IMPORTANT:
- Respond with ONLY valid JSON. No markdown, no explanations.
- Use snake_case for all IDs.
- field_type must be one of the exact values listed above.
- For select/multi_select fields, always include an options array.
- Generate meaningful field IDs that match the label.
- Dependency rules are optional. Only include them when the prompt explicitly requests conditional behavior.
"""
_SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.replace("__FIELD_TYPES__", _FIELD_TYPE_VALUES).replace(
    "__FIELD_SNIPPETS__", _FIELD_SNIPPETS_JSON
)

_REFINEMENT_PROMPT = """You are a form schema editor. Your task is to modify an existing FormSchema.

Current form JSON:
{existing_form}

User request: {prompt}

CRITICAL RULES:
1. You MUST preserve the exact same JSON structure (FormSchema format) as the current form.
2. Keep all existing fields, sections, and metadata UNLESS the user explicitly asks to remove them.
3. Preserve form_id, version, and any fields not mentioned in the request.
4. Only modify, add, or remove elements that the user specifically requests.
5. The output must be a COMPLETE, valid FormSchema JSON — not a partial diff.
6. Respond with ONLY valid JSON. No markdown, no explanations.
"""

_RETRY_PROMPT = """Your previous response was not a valid FormSchema. Error: {error}

Please try again and respond with ONLY valid JSON matching the FormSchema structure.
{previous_attempt}
"""

_TOOLKIT_SYSTEM_PROMPT = """You are a form schema editor with access to surgical editing tools.

You MUST follow this workflow to edit the form:

1. ALWAYS start by calling get_form_summary() to understand the form structure.
2. Use get_field(field_id) or search_fields(query) to inspect specific elements before modifying them.
3. Use mutation tools to apply targeted changes:
   - update_field(section_id, field_id, patch) — to change field properties (label, required, etc.)
   - add_field(section_id, field, position) — to add a new field
   - remove_field(section_id, field_id) — to delete a field
   - add_section(section, position) — to add a new section
   - update_section_title(section_id, title) — to RENAME a section (change section.title)
   - update_section(section_id, patch) — to update a section's meta dict ONLY (NOT its title)
   - move_field(from_section, field_id, to_section, position) — to relocate a field
   - update_form_title(title) — to RENAME the form (change form.title)
   - update_form_description(description) — to change the form description
   - update_form_meta(patch) — to update the form-level meta dict ONLY (NOT title or description)
   - add_dependency(field_id, rule) — to set a depends_on rule on a field (references earlier fields)
   - update_dependency(field_id, patch) — to partially update an existing depends_on rule
   - remove_dependency(field_id) — to clear the depends_on rule from a field
   - add_post_dependency(field_id, post) — to add a post_depends entry (targets later fields)
   - remove_post_dependency(field_id, target) — to remove a post_depends entry by target
4. Call done() IMMEDIATELY when all requested edits are complete.

CRITICAL RULES:
- NEVER return the full form JSON as text — use the tools instead.
- NEVER modify fields that were not mentioned in the user's request.
- ALWAYS call done() to signal completion — do not stop without calling it.
- Make only the minimal changes necessary to fulfill the request.
- To rename the form use update_form_title(), NOT update_form_meta().
- To rename a section use update_section_title(), NOT update_section().
"""


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

# `schema` is a valid Pydantic v2 field name (v2 dropped the v1 reserved-name
# restriction — see FEAT-388 spec's "Known Risks / Gotchas"), but Pydantic
# still emits a UserWarning at class-definition time because the name
# shadows BaseModel's deprecated v1 `.schema()` classmethod. Nothing in the
# codebase calls `.schema()` on tool-arg instances (AbstractTool uses
# `model_json_schema()` instead — see `parrot.tools.abstract`), so this
# warning is suppressed rather than renaming the field: renaming to
# `form_schema`/`alias="schema"` would change what `AbstractTool.execute()`
# passes to `_execute()` (it calls `validated_args.model_dump()`, which
# emits field names, not aliases), altering the tool's public argument
# contract — an open design question left to a follow-up decision, not a
# warning-suppression fix.
warnings.filterwarnings(
    "ignore",
    message=r'Field name "schema" in "CreateFormInput" shadows an attribute',
    category=UserWarning,
)


class CreateFormInput(BaseModel):
    """Input schema for the create_form tool.

    Exactly one of `prompt` (LLM path) or a structured input — `schema`,
    `sections`, `fields` (deterministic path, FEAT-388) — must be provided.
    Providing both, or neither, is a validation error raised at execution
    time (see `CreateFormTool._execute`).

    Attributes:
        prompt: Natural language description of the form to create or
            modification to apply. Required only when no structured input
            is given.
        schema: Complete form definition as a dict. Accepts either:
            (1) Standard JSON Schema (draft-07) — detected by 'type'+
            'properties' keys; (2) FormSchema-native JSON (with optional
            shortcuts like auto-generated IDs). No LLM call is made.
        sections: List of section dicts to assemble into a form. No LLM
            call is made.
        fields: Flat list of field dicts. Auto-wrapped in a single default
            section. No LLM call is made.
        form_id: Custom form ID (slug). Auto-generated if not provided.
        form_uid: Optional UUID for the form. Auto-generated if not provided
            (FEAT-389).
        persist: Whether to save the form to the registry storage.
        refine_form_uid: UUID of an existing form to load and modify
            (FEAT-389 — renamed from ``refine_form_id``; forms are now
            looked up by their immutable identity, not their slug).
    """

    prompt: str | None = Field(
        default=None,
        description=(
            "Natural language description of the form to create or modification to apply. "
            "Required only when no structured input (schema/sections/fields) is provided."
        ),
    )
    schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Complete form definition as a dict. Accepts either: "
            "(1) Standard JSON Schema (draft-07) — detected by 'type'+'properties' keys; "
            "(2) FormSchema-native JSON (with optional shortcuts like auto-generated IDs). "
            "No LLM call is made."
        ),
    )
    sections: list[dict[str, Any]] | None = Field(
        default=None,
        description="List of section dicts to assemble into a form. No LLM call is made.",
    )
    fields: list[dict[str, Any]] | None = Field(
        default=None,
        description="Flat list of field dicts. Auto-wrapped in a single default section. No LLM call is made.",
    )
    form_id: str | None = Field(
        default=None,
        description="Custom form ID (slug). Auto-generated from title if not provided.",
    )
    form_uid: str | None = Field(
        default=None,
        description="Optional UUID for the form. Auto-generated if not provided.",
    )
    persist: bool = Field(
        default=False,
        description="Save the generated form to the registry (and storage if configured)",
    )
    refine_form_uid: str | None = Field(
        default=None,
        description=(
            "form_uid of an existing form to load and refine. "
            "If set, the existing form is modified based on the prompt; "
            "its form_uid is preserved unchanged."
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
        model: str | None = None,
        *,
        tenant: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize CreateFormTool.

        Args:
            client: LLM client with a completion() or ask() method.
            registry: Optional FormRegistry for refinement lookups and persistence.
            model: Optional model name override for form generation calls.
            tenant: Optional tenant slug used when looking up and registering forms.
                When ``None``, :class:`FormRegistry` falls back to its configured
                ``default_tenant``.
        """
        super().__init__(**kwargs)
        self._client = client
        self._registry = registry
        self._model = model
        self._tenant = tenant
        self._validator = FormValidator()
        self._assembler = FormAssembler()
        self.logger = logging.getLogger(__name__)

    @property
    def client(self) -> Any:
        """The LLM client used for form generation."""
        return self._client

    @client.setter
    def client(self, value: Any) -> None:
        self._client = value

    async def _execute(
        self,
        prompt: str | None = None,
        form_id: str | None = None,
        form_uid: str | None = None,
        persist: bool = False,
        refine_form_uid: str | None = None,
        schema: dict[str, Any] | None = None,
        sections: list[dict[str, Any]] | None = None,
        fields: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Generate and validate a FormSchema — deterministically or via LLM.

        If any of `schema`, `sections`, or `fields` is provided, the form is
        assembled deterministically via `FormAssembler` (FEAT-388) — zero LLM
        calls. Otherwise, `prompt` drives the existing LLM-based generation
        path (unchanged).

        Args:
            prompt: Natural language form description or modification request.
                Required only when no structured input is provided.
            form_id: Custom form_id (slug). Auto-generated if not provided.
            form_uid: Custom form_uid (FEAT-389). Auto-generated if not
                provided and this is a NEW form. Ignored when
                ``refine_form_uid`` is set — refinements always preserve
                the existing form's form_uid.
            persist: If True, register the form in the registry.
            refine_form_uid: If set, load the existing form by form_uid and
                modify it (FEAT-389 — renamed from ``refine_form_id``).
            schema: Complete form definition dict (JSON Schema or
                FormSchema-native). Triggers the deterministic path.
            sections: List of section dicts to assemble. Triggers the
                deterministic path.
            fields: Flat list of field dicts to assemble into a single
                default section. Triggers the deterministic path.

        Returns:
            ToolResult with success=True and form dict in metadata["form"]
            (plus a top-level metadata["form_uid"]), or success=False with
            error details on failure.
        """
        has_structured = schema is not None or sections is not None or fields is not None

        if has_structured and prompt is not None:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={
                    "error": "Provide either 'prompt' or structured input (schema/sections/fields), not both"
                },
            )
        if not has_structured and not prompt:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={
                    "error": "Either 'prompt' or structured input (schema/sections/fields) is required"
                },
            )

        if has_structured:
            return await self._execute_from_schema(
                schema=schema,
                sections=sections,
                fields=fields,
                form_id=form_id,
                persist=persist,
            )

        try:
            existing: FormSchema | None = None
            effective_form_uid: str
            if refine_form_uid and self._registry is not None:
                existing = await self._registry.get(refine_form_uid, tenant=self._tenant)
                if existing is None:
                    return ToolResult(
                        success=False,
                        status="error",
                        result=None,
                        metadata={"error": f"Form '{refine_form_uid}' not found in registry"},
                    )

                # form_uid is the immutable identity — a refinement NEVER
                # changes it, regardless of any form_uid= kwarg passed in.
                effective_form_uid = existing.form_uid
                # The slug MAY change via an explicit form_id=; otherwise
                # keep the existing slug (previously this incorrectly fell
                # back to refine_form_id — now a form_uid, which must NOT
                # leak into the form_id/slug field).
                effective_form_id = form_id or existing.form_id

                # Route form edits through the toolkit path (FEAT-169).
                # _should_use_toolkit() determines whether to use the toolkit
                # (currently always True per spec Q3).
                form: FormSchema | None = None
                if self._should_use_toolkit(existing):
                    try:
                        form = await self._execute_toolkit_edit(existing, prompt)
                    except Exception as exc:
                        self.logger.warning(
                            "Toolkit edit failed for '%s', falling back to full-form path: %s",
                            refine_form_uid,
                            exc,
                        )
                        form = None

                if form is None:
                    # Fallback: use existing full-form refinement path
                    self.logger.info(
                        "Falling back to full-form refinement for '%s'.", refine_form_uid
                    )
                    messages = self._build_refinement_messages(existing, prompt)
                    form = await self._generate_with_retry(
                        messages, effective_form_id, effective_form_uid
                    )
            else:
                effective_form_uid = form_uid or str(uuid.uuid4())
                messages = self._build_creation_messages(prompt)
                form = await self._generate_with_retry(messages, form_id, effective_form_uid)

            if form is None:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    metadata={"error": "Failed to generate a valid FormSchema after retries"},
                )

            # Check for structural schema issues (circular dependencies)
            circular_errors = self._validator.check_schema(form)
            if circular_errors:
                self.logger.warning(
                    "Generated form has circular dependencies: %s",
                    circular_errors,
                )

            if refine_form_uid and existing is not None:
                from ..api._utils import _bump_version
                form.version = _bump_version(existing.version)

            if persist and self._registry is not None:
                try:
                    overwrite = refine_form_uid is not None
                    await self._registry.register(
                        form, persist=True, overwrite=overwrite, tenant=self._tenant,
                    )
                except Exception as exc:
                    self.logger.warning("Failed to persist form %s: %s", form.form_id, exc)

            return ToolResult(
                success=True,
                status="success",
                result={"form_id": form.form_id, "title": str(form.title)},
                metadata={
                    "form": form.model_dump(),
                    "form_uid": form.form_uid,
                    "circular_dependency_errors": circular_errors or [],
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

    async def _execute_from_schema(
        self,
        schema: dict[str, Any] | None,
        sections: list[dict[str, Any]] | None,
        fields: list[dict[str, Any]] | None,
        form_id: str | None,
        persist: bool,
    ) -> ToolResult:
        """Assemble a FormSchema deterministically from structured input.

        Delegates to `FormAssembler` (FEAT-388, Module 1) — no LLM call is
        made. Exactly one of `schema`, `sections`, `fields` is expected to
        be non-``None`` (enforced by the caller).

        Args:
            schema: Complete form definition dict (JSON Schema or
                FormSchema-native), or ``None``.
            sections: List of section dicts to assemble, or ``None``.
            fields: Flat list of field dicts to assemble, or ``None``.
            form_id: Optional form_id override. Also used as the fallback
                form title for the `sections`/`fields` paths, which have no
                dedicated title input.
            persist: If True, register the assembled form in the registry.

        Returns:
            ToolResult in the same shape as the LLM path: success=True with
            the form dict in metadata["form"], or success=False with error
            details in metadata["error"] on invalid structured input.
        """
        try:
            if schema is not None:
                form = self._assembler.assemble(schema, form_id=form_id)
            elif sections is not None:
                form = self._assembler.assemble_from_sections(
                    sections, form_id=form_id, title=form_id or "Form"
                )
            else:
                form = self._assembler.assemble_from_fields(
                    fields, form_id=form_id, title=form_id or "Form"
                )
        except (ValidationError, ValueError) as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={"error": str(exc)},
            )

        # Check for structural schema issues (circular dependencies) —
        # same as the LLM path.
        circular_errors = self._validator.check_schema(form)
        if circular_errors:
            self.logger.warning(
                "Deterministically assembled form has circular dependencies: %s",
                circular_errors,
            )

        if persist and self._registry is not None:
            try:
                await self._registry.register(
                    form, persist=True, overwrite=False, tenant=self._tenant,
                )
            except Exception as exc:
                self.logger.warning("Failed to persist form %s: %s", form.form_id, exc)

        return ToolResult(
            success=True,
            status="success",
            result={"form_id": form.form_id, "title": str(form.title)},
            metadata={
                "form": form.model_dump(),
                "circular_dependency_errors": circular_errors or [],
            },
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

    def _build_refinement_messages(self, existing: FormSchema, prompt: str) -> list[dict[str, str]]:
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
        For ask(), separates the system prompt from user messages and
        extracts the text content from the AIMessage response.

        Args:
            messages: List of chat message dicts.

        Returns:
            Raw LLM response text.
        """
        if hasattr(self._client, "completion"):
            return await self._client.completion(messages)
        elif hasattr(self._client, "ask"):
            # Separate system prompt from user messages
            system_prompt = None
            user_parts = []
            for m in messages:
                if m["role"] == "system":
                    system_prompt = m["content"]
                else:
                    user_parts.append(m["content"])
            text = "\n\n".join(user_parts)
            ask_kwargs: dict[str, Any] = {
                "system_prompt": system_prompt,
                "stateless": True,
            }
            if self._model:
                ask_kwargs["model"] = self._model
            response = await self._client.ask(text, **ask_kwargs)
            # Extract text from AIMessage (Pydantic model)
            if hasattr(response, "to_text"):
                return response.to_text
            if hasattr(response, "output"):
                return str(response.output)
            return str(response)
        else:
            raise RuntimeError("LLM client has neither completion() nor ask() method")

    async def _generate_with_retry(
        self,
        messages: list[dict[str, str]],
        form_id: str | None,
        form_uid: str | None = None,
    ) -> FormSchema | None:
        """Generate and validate FormSchema with retry on validation failure.

        Args:
            messages: Initial LLM messages.
            form_id: Optional custom form_id.
            form_uid: form_uid to inject into the generated form (FEAT-389).
                The LLM never generates this — it is always tool-injected,
                either freshly generated for new forms or preserved from
                the existing form when refining.

        Returns:
            Validated FormSchema, or None after max retries.
        """
        current_messages = list(messages)
        raw: str = ""
        json_str: str = ""

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
                    data["form_id"] = _slugify(title if isinstance(title, str) else "generated-form")

                # form_uid is always tool-injected (FEAT-389) — never LLM-generated.
                if form_uid:
                    data["form_uid"] = form_uid

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
                self.logger.warning("Attempt %d failed (%s), retrying...", attempt + 1, exc)
                retry_content = _RETRY_PROMPT.format(
                    error=str(exc),
                    previous_attempt=json_str or "(no output)",
                )
                current_messages = list(messages) + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": retry_content},
                ]

        return None

    def _should_use_toolkit(self, form: FormSchema) -> bool:
        """Determine whether to use the EditToolkit for this form edit.

        Per FEAT-169 spec Q3 (resolved): all edit operations use the toolkit
        regardless of form size — no threshold routing.  This method always
        returns True.  Override in subclasses for custom routing logic.

        Args:
            form: The existing FormSchema being edited.

        Returns:
            True — always use the toolkit for form edits.
        """
        return True

    async def _execute_toolkit_edit(
        self,
        existing: FormSchema,
        prompt: str,
    ) -> FormSchema | None:
        """Edit a FormSchema using the tool-calling toolkit loop.

        Creates an EditToolkit from the existing form and calls the LLM client
        with the toolkit tools.  The LLM inspects the form via inspection tools,
        applies targeted changes via mutation tools, and signals completion by
        calling ``done()``.

        Args:
            existing: The FormSchema to edit (a deep copy is made by EditToolkit).
            prompt: The user's edit request.

        Returns:
            Updated FormSchema if the LLM called ``done()``, or None if the
            session exhausted max_iterations without completion.
        """
        toolkit = EditToolkit(existing)
        tools = toolkit.get_tool_definitions()

        self.logger.info(
            "Starting toolkit edit for form '%s' with %d tools.",
            existing.form_id,
            len(tools),
        )

        ask_kwargs: dict[str, Any] = {
            "system_prompt": _TOOLKIT_SYSTEM_PROMPT,
            "tools": tools,
            "use_tools": True,
            "stateless": True,
            "max_iterations": 15,
        }
        if self._model:
            ask_kwargs["model"] = self._model

        try:
            await self._client.ask(prompt, **ask_kwargs)
        except Exception as exc:
            self.logger.warning(
                "Toolkit LLM session raised exception for form '%s': %s",
                existing.form_id,
                exc,
            )
            # Return the form even if an exception occurred partway through —
            # any mutations already applied are preserved in toolkit.form.
            # If done() was called before the exception, we return the result.
            if toolkit.is_done:
                return toolkit.form
            raise

        if not toolkit.is_done:
            self.logger.warning(
                "Toolkit edit for form '%s' exhausted max_iterations without calling done().",
                existing.form_id,
            )
            return None

        self.logger.info(
            "Toolkit edit for form '%s' completed successfully.", existing.form_id
        )
        return toolkit.form
