"""EditToolkit — LLM-callable toolkit for surgical FormSchema editing.

Implements FEAT-169: instead of sending the full FormSchema JSON to the LLM,
this toolkit exposes 12 focused tools that allow the LLM to inspect and mutate
the form in surgical, targeted operations.

Tool categories:
- Inspection (4): get_form_summary, get_section, get_field, search_fields
- Mutation (7):   update_field, add_field, remove_field, add_section,
                  update_section, move_field, update_form_meta
- Control (1):    done
"""

from __future__ import annotations

import re
from typing import Any

try:
    from parrot.tools.toolkit import AbstractToolkit
    from parrot.tools.abstract import ToolResult
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner EditToolkit requires the 'ai-parrot' package. "
        "Install it with: uv add ai-parrot"
    ) from exc

from pydantic import ValidationError

from ..api.operations import (
    AddField,
    AddSection,
    MoveField,
    OperationError,
    RemoveField,
    UpdateField,
    UpdateFormMeta,
    UpdateSectionMeta,
    _apply_add_field,
    _apply_add_section,
    _apply_move_field,
    _apply_remove_field,
    _apply_update_field,
    _apply_update_form_meta,
    _apply_update_section_meta,
)
from ..core.constraints import DependencyRule, PostDependency
from ..core.schema import FormField, FormSchema, FormSection

class EditToolkit(AbstractToolkit):
    """Toolkit exposing FormSchema inspection and mutation as LLM-callable tools.

    The toolkit manages a deep copy of the FormSchema as its working state.
    Inspection tools read from this copy; mutation tools modify it via the
    operations.py apply functions (reusing all existing validation logic).

    The LLM never sees the full form JSON — it uses ``get_form_summary`` to
    understand the structure, inspection tools to examine specific elements,
    and mutation tools to apply targeted changes.  When all edits are complete
    the LLM calls ``done`` and the caller retrieves the updated form via the
    ``form`` property.

    Usage::

        toolkit = EditToolkit(form)
        tools = toolkit.get_tools()           # List[AbstractTool]
        # Pass tools to GoogleGenAIClient.ask(tools=tools, use_tools=True, ...)
        updated_form = toolkit.form           # Retrieve after done() is called
    """

    #: ``execute_tool`` is an internal dispatcher, not an LLM-callable tool.
    exclude_tools: tuple[str, ...] = ("execute_tool",)

    def __init__(self, form: FormSchema, **kwargs: Any) -> None:
        """Create an EditToolkit with a deep copy of *form*.

        Args:
            form: The FormSchema to edit. A deep copy is made immediately so
                  the original is never mutated.
            **kwargs: Forwarded to AbstractToolkit.__init__.
        """
        super().__init__(**kwargs)
        self._form: FormSchema = form.model_copy(deep=True)
        self._done: bool = False

    # ------------------------------------------------------------------
    # Public state accessors
    # ------------------------------------------------------------------

    @property
    def form(self) -> FormSchema:
        """Current state of the working copy after all mutations."""
        return self._form

    @property
    def is_done(self) -> bool:
        """True after the LLM has called the ``done`` tool."""
        return self._done

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_section(self, section_id: str) -> FormSection | None:
        """Return the section with *section_id*, or None."""
        for section in self._form.sections:
            if section.section_id == section_id:
                return section
        return None

    def _find_field_and_section(
        self, field_id: str
    ) -> tuple[FormField, FormSection] | tuple[None, None]:
        """Search all sections for *field_id*.

        Iterates over all FormField items in each section's fields list.

        Returns:
            Tuple of (FormField, FormSection) if found, or (None, None).
        """
        for section in self._form.sections:
            for field in section.fields:
                if isinstance(field, FormField) and field.field_id == field_id:
                    return field, section
        return None, None

    def _iter_section_fields(self, section: FormSection) -> list[FormField]:
        """Return all FormField items in a section.

        Args:
            section: The section to iterate.

        Returns:
            List of FormField objects in the section.
        """
        return [f for f in section.fields if isinstance(f, FormField)]

    # ------------------------------------------------------------------
    # Inspection tools — public async methods picked up by AbstractToolkit
    # ------------------------------------------------------------------

    async def get_form_summary(self) -> dict:
        """Return a compact outline of the form structure.

        The summary includes form-level metadata and a condensed view of each
        section: section_id, title, and for each field only field_id, label,
        and field_type.  Options, constraints, children, and meta are omitted
        to keep the response small (at most 5% of the full JSON for large forms).

        Returns:
            Compact dict with form outline including section/field IDs and types.
        """
        form = self._form
        summary: dict[str, Any] = {
            "form_id": form.form_id,
            "title": form.title,
            "description": form.description,
            "section_count": len(form.sections),
            "sections": [],
        }

        for section in form.sections:
            section_entry: dict[str, Any] = {
                "section_id": section.section_id,
                "title": section.title,
                "field_count": len(self._iter_section_fields(section)),
                "fields": [],
            }

            for field in self._iter_section_fields(section):
                section_entry["fields"].append(
                    {
                        "field_id": field.field_id,
                        "label": field.label,
                        "field_type": field.field_type,
                        "required": field.required,
                    }
                )

            summary["sections"].append(section_entry)

        return summary

    async def get_section(self, section_id: str) -> dict:
        """Return the full JSON for a single section by section_id.

        Args:
            section_id: ID of the section to retrieve.

        Returns:
            Full section data dict, or an error dict if not found.
        """
        section = self._find_section(section_id)
        if section is None:
            return {
                "error": f"Section '{section_id}' not found.",
                "available_sections": [s.section_id for s in self._form.sections],
            }
        return section.model_dump(mode="json")

    async def get_field(self, field_id: str) -> dict:
        """Return the full JSON for a single field by field_id.

        Searches across all sections.

        Args:
            field_id: ID of the field to retrieve.

        Returns:
            Full field data dict with containing section_id, or an error dict.
        """
        field, section = self._find_field_and_section(field_id)
        if field is None:
            return {
                "error": f"Field '{field_id}' not found in any section.",
            }
        return {
            "section_id": section.section_id,
            "field": field.model_dump(mode="json"),
        }

    async def search_fields(
        self, query: str, field_type: str | None = None
    ) -> list[dict]:
        """Search for fields matching a label substring, type, or ID pattern.

        The *query* is matched as:
        1. Case-insensitive substring of the field label
        2. Exact field_id match
        3. Regex match on field_id

        Args:
            query: Substring or regex pattern to search for in field labels/IDs.
            field_type: Optional field type filter (e.g. "text", "email").

        Returns:
            List of match dicts with section_id, field_id, label, field_type.
        """
        results: list[dict] = []
        query_lower = query.lower()
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = None

        for section in self._form.sections:
            for field in self._iter_section_fields(section):
                # Type filter
                if field_type is not None:
                    ft = (
                        field.field_type.value
                        if hasattr(field.field_type, "value")
                        else str(field.field_type)
                    )
                    if ft != field_type:
                        continue

                # Label substring match
                label_str = str(field.label).lower()
                label_match = query_lower in label_str

                # field_id exact or regex match
                id_exact = field.field_id == query
                id_regex = bool(pattern and pattern.search(field.field_id))

                if label_match or id_exact or id_regex:
                    results.append(
                        {
                            "section_id": section.section_id,
                            "field_id": field.field_id,
                            "label": field.label,
                            "field_type": field.field_type,
                        }
                    )

        return results

    # ------------------------------------------------------------------
    # Mutation tools — delegate to operations.py apply functions
    # ------------------------------------------------------------------

    async def update_field(
        self, section_id: str, field_id: str, patch: dict
    ) -> dict:
        """Apply an RFC 7396 merge-patch to a single field.

        Keys present in *patch* override the existing value; keys absent in
        *patch* are preserved; explicit ``null`` values remove the key.

        Args:
            section_id: ID of the section containing the field.
            field_id: ID of the field to update.
            patch: RFC 7396 merge-patch dict with fields to update.

        Returns:
            Success dict with updated field data, or error dict on failure.
        """
        try:
            op = UpdateField(
                op="update_field",
                section_id=section_id,
                field_id=field_id,
                patch=patch,
            )
            self._form = _apply_update_field(self._form, op)
            updated_field, _ = self._find_field_and_section(field_id)
            return {
                "success": True,
                "field_id": field_id,
                "updated_field": (
                    updated_field.model_dump(mode="json") if updated_field else None
                ),
            }
        except OperationError as exc:
            self.logger.warning("update_field failed: %s", exc)
            return {"error": str(exc.message)}
        except Exception as exc:
            self.logger.error("update_field unexpected error: %s", exc)
            return {"error": str(exc)}

    async def add_field(
        self,
        section_id: str,
        field: dict,
        position: int | None = None,
    ) -> dict:
        """Add a new field to a section at an optional position.

        Args:
            section_id: ID of the section to add the field to.
            field: Dict representation of the FormField to add.
            position: Optional 0-based insertion index. Appends if None.

        Returns:
            Success dict with added field_id, or error dict on failure.
        """
        try:
            validated_field = FormField.model_validate(field)
            op = AddField(
                op="add_field",
                section_id=section_id,
                field=validated_field,
                position=position,
            )
            self._form = _apply_add_field(self._form, op)
            return {
                "success": True,
                "section_id": section_id,
                "field_id": validated_field.field_id,
                "position": position,
            }
        except OperationError as exc:
            self.logger.warning("add_field failed: %s", exc)
            return {"error": str(exc.message)}
        except ValidationError as exc:
            self.logger.warning("add_field validation error: %s", exc)
            return {"error": f"Invalid field definition: {exc.errors()}"}
        except Exception as exc:
            self.logger.error("add_field unexpected error: %s", exc)
            return {"error": str(exc)}

    async def remove_field(self, section_id: str, field_id: str) -> dict:
        """Remove a field from a section.

        Args:
            section_id: ID of the section containing the field.
            field_id: ID of the field to remove.

        Returns:
            Success dict, or error dict on failure.
        """
        try:
            op = RemoveField(
                op="remove_field",
                section_id=section_id,
                field_id=field_id,
            )
            self._form = _apply_remove_field(self._form, op)
            return {
                "success": True,
                "section_id": section_id,
                "field_id": field_id,
                "message": f"Field '{field_id}' removed from section '{section_id}'.",
            }
        except OperationError as exc:
            self.logger.warning("remove_field failed: %s", exc)
            return {"error": str(exc.message)}
        except Exception as exc:
            self.logger.error("remove_field unexpected error: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Dependency / post-dependency CRUD (FEAT-234)
    # ------------------------------------------------------------------

    async def add_dependency(self, field_id: str, rule: dict) -> dict:
        """Set or replace the ``depends_on`` rule on a field.

        Validates the rule dict via :class:`DependencyRule` and runs the
        form-level rule-integrity pass before applying.  Returns an error dict
        (form unchanged) if validation fails.

        Args:
            field_id: ID of the field to update.
            rule: Dict representation of a :class:`DependencyRule`.

        Returns:
            Success dict with the updated ``depends_on``, or an error dict.
        """
        try:
            validated_rule = DependencyRule.model_validate(rule)
        except ValidationError as exc:
            return {"error": f"Invalid DependencyRule: {exc.errors()}"}

        field, section = self._find_field_and_section(field_id)
        if field is None:
            return {"error": f"Field '{field_id}' not found."}

        # Build a temporary form copy with the new rule applied to validate integrity
        updated_field = field.model_copy(update={"depends_on": validated_rule})
        temp_form = self._replace_field_in_form(self._form, section.section_id, field_id, updated_field)

        rule_errors = await self._check_rules(temp_form)
        if rule_errors:
            return {"error": "Rule integrity check failed", "details": rule_errors}

        self._form = temp_form
        return {
            "success": True,
            "field_id": field_id,
            "depends_on": validated_rule.model_dump(mode="json"),
        }

    async def update_dependency(self, field_id: str, patch: dict) -> dict:
        """Merge-patch the existing ``depends_on`` rule on a field.

        The ``patch`` is merged into the current rule dict.  If the field has
        no existing rule, ``patch`` is used as the full new rule.

        Args:
            field_id: ID of the field to update.
            patch: Partial dict to merge into the existing DependencyRule.

        Returns:
            Success dict with the updated ``depends_on``, or an error dict.
        """
        field, section = self._find_field_and_section(field_id)
        if field is None:
            return {"error": f"Field '{field_id}' not found."}

        current = field.depends_on.model_dump() if field.depends_on else {}
        merged = {**current, **patch}
        return await self.add_dependency(field_id, merged)

    async def remove_dependency(self, field_id: str) -> dict:
        """Clear the ``depends_on`` rule from a field.

        Args:
            field_id: ID of the field to clear.

        Returns:
            Success dict, or error dict if the field is not found.
        """
        field, section = self._find_field_and_section(field_id)
        if field is None:
            return {"error": f"Field '{field_id}' not found."}

        updated_field = field.model_copy(update={"depends_on": None})
        self._form = self._replace_field_in_form(
            self._form, section.section_id, field_id, updated_field
        )
        return {"success": True, "field_id": field_id, "depends_on": None}

    async def add_post_dependency(self, field_id: str, post: dict) -> dict:
        """Append a :class:`PostDependency` to a field's ``post_depends`` list.

        Validates the post-dependency dict and runs rule-integrity before
        applying.  Returns an error dict (form unchanged) if validation fails.

        Args:
            field_id: ID of the field to update.
            post: Dict representation of a :class:`PostDependency`.

        Returns:
            Success dict with the full updated ``post_depends`` list, or an error dict.
        """
        try:
            validated_post = PostDependency.model_validate(post)
        except ValidationError as exc:
            return {"error": f"Invalid PostDependency: {exc.errors()}"}

        field, section = self._find_field_and_section(field_id)
        if field is None:
            return {"error": f"Field '{field_id}' not found."}

        existing = list(field.post_depends or [])
        existing.append(validated_post)
        updated_field = field.model_copy(update={"post_depends": existing})
        temp_form = self._replace_field_in_form(self._form, section.section_id, field_id, updated_field)

        rule_errors = await self._check_rules(temp_form)
        if rule_errors:
            return {"error": "Rule integrity check failed", "details": rule_errors}

        self._form = temp_form
        return {
            "success": True,
            "field_id": field_id,
            "post_depends": [p.model_dump(mode="json") for p in existing],
        }

    async def remove_post_dependency(self, field_id: str, target: str) -> dict:
        """Remove a specific post-dependency (by target field_id) from a field.

        Args:
            field_id: ID of the owning field.
            target: The ``target`` field_id of the PostDependency to remove.

        Returns:
            Success dict with the remaining ``post_depends`` list, or an error dict.
        """
        field, section = self._find_field_and_section(field_id)
        if field is None:
            return {"error": f"Field '{field_id}' not found."}

        existing = list(field.post_depends or [])
        updated = [p for p in existing if p.target != target]
        if len(updated) == len(existing):
            return {
                "error": f"No post_depends with target='{target}' found on field '{field_id}'."
            }

        updated_field = field.model_copy(update={"post_depends": updated or None})
        self._form = self._replace_field_in_form(
            self._form, section.section_id, field_id, updated_field
        )
        return {
            "success": True,
            "field_id": field_id,
            "removed_target": target,
            "post_depends": [p.model_dump(mode="json") for p in updated],
        }

    # ------------------------------------------------------------------
    # Private helpers for dependency CRUD
    # ------------------------------------------------------------------

    def _replace_field_in_form(
        self,
        form: FormSchema,
        section_id: str,
        field_id: str,
        new_field: FormField,
    ) -> FormSchema:
        """Return a deep copy of *form* with *field_id* replaced by *new_field*.

        Args:
            form: The source FormSchema.
            section_id: Section containing the field.
            field_id: The field to replace.
            new_field: The replacement FormField.

        Returns:
            A new FormSchema with the field swapped.
        """
        new_sections = []
        for section in form.sections:
            if section.section_id != section_id:
                new_sections.append(section)
                continue
            new_fields = [
                new_field if (isinstance(f, FormField) and f.field_id == field_id) else f
                for f in section.fields
            ]
            new_sections.append(section.model_copy(update={"fields": new_fields}))
        return form.model_copy(update={"sections": new_sections})

    async def _check_rules(self, form: FormSchema) -> list[str]:
        """Run rule-integrity validation on a form copy.

        Lazy-imports FormValidator to avoid a hard circular dependency.

        Args:
            form: The form to validate.

        Returns:
            List of error strings (empty when valid).
        """
        from ..services.validators import FormValidator

        validator = FormValidator()
        cycle_errors = validator._detect_circular_dependencies(form)
        rule_errors = validator.validate_rules(form)
        return cycle_errors + rule_errors

    async def add_section(
        self, section: dict, position: int | None = None
    ) -> dict:
        """Add a new section to the form at an optional position.

        Args:
            section: Dict representation of the FormSection to add.
            position: Optional 0-based insertion index. Appends if None.

        Returns:
            Success dict with added section_id, or error dict on failure.
        """
        try:
            validated_section = FormSection.model_validate(section)
            op = AddSection(
                op="add_section",
                section=validated_section,
                position=position,
            )
            self._form = _apply_add_section(self._form, op)
            return {
                "success": True,
                "section_id": validated_section.section_id,
                "position": position,
            }
        except OperationError as exc:
            self.logger.warning("add_section failed: %s", exc)
            return {"error": str(exc.message)}
        except ValidationError as exc:
            self.logger.warning("add_section validation error: %s", exc)
            return {"error": f"Invalid section definition: {exc.errors()}"}
        except Exception as exc:
            self.logger.error("add_section unexpected error: %s", exc)
            return {"error": str(exc)}

    async def update_section(self, section_id: str, patch: dict) -> dict:
        """Apply an RFC 7396 merge-patch to a section's ``meta`` dict.

        This tool updates only the arbitrary ``meta`` key-value store on the
        section (``section.meta``).  It does NOT update ``section.title``.
        Use ``update_section_title`` to rename a section.

        Args:
            section_id: ID of the section to update.
            patch: Dict of key-value pairs to merge into ``section.meta``.

        Returns:
            Success dict, or error dict on failure.
        """
        try:
            op = UpdateSectionMeta(
                op="update_section_meta",
                section_id=section_id,
                patch=patch,
            )
            self._form = _apply_update_section_meta(self._form, op)
            return {
                "success": True,
                "section_id": section_id,
                "message": f"Section '{section_id}' meta updated.",
            }
        except OperationError as exc:
            self.logger.warning("update_section failed: %s", exc)
            return {"error": str(exc.message)}
        except Exception as exc:
            self.logger.error("update_section unexpected error: %s", exc)
            return {"error": str(exc)}

    async def move_field(
        self,
        from_section: str,
        field_id: str,
        to_section: str,
        position: int | None = None,
    ) -> dict:
        """Move a field within or across sections.

        Args:
            from_section: ID of the source section.
            field_id: ID of the field to move.
            to_section: ID of the destination section.
            position: Optional 0-based insertion index in the destination section.

        Returns:
            Success dict, or error dict on failure.
        """
        try:
            op = MoveField(
                op="move_field",
                **{
                    "from": {"section_id": from_section, "field_id": field_id},
                    "to": {"section_id": to_section, "position": position},
                },
            )
            self._form = _apply_move_field(self._form, op)
            return {
                "success": True,
                "field_id": field_id,
                "from_section": from_section,
                "to_section": to_section,
                "position": position,
            }
        except OperationError as exc:
            self.logger.warning("move_field failed: %s", exc)
            return {"error": str(exc.message)}
        except Exception as exc:
            self.logger.error("move_field unexpected error: %s", exc)
            return {"error": str(exc)}

    async def update_form_meta(self, patch: dict) -> dict:
        """Apply an RFC 7396 merge-patch to the form-level ``meta`` dict.

        This tool updates only the arbitrary ``meta`` key-value store on the
        form (``form.meta``).  It does NOT update ``form.title`` or
        ``form.description``.  Use ``update_form_title`` to rename the form,
        or ``update_form_description`` to change the description.

        Args:
            patch: Dict of key-value pairs to merge into ``form.meta``.

        Returns:
            Success dict, or error dict on failure.
        """
        try:
            op = UpdateFormMeta(
                op="update_form_meta",
                patch=patch,
            )
            self._form = _apply_update_form_meta(self._form, op)
            return {
                "success": True,
                "message": "Form meta dict updated.",
                "form_id": self._form.form_id,
            }
        except OperationError as exc:
            self.logger.warning("update_form_meta failed: %s", exc)
            return {"error": str(exc.message)}
        except Exception as exc:
            self.logger.error("update_form_meta unexpected error: %s", exc)
            return {"error": str(exc)}

    async def update_form_title(self, title: str) -> dict:
        """Update the form title.

        Use this tool when the user asks to rename the form or change its title.
        This is the correct tool for changing ``form.title`` — do NOT use
        ``update_form_meta`` for this purpose.

        Args:
            title: New title for the form.

        Returns:
            Success dict confirming the title was updated, or error dict on failure.
        """
        try:
            form_dict = self._form.model_dump(mode="json")
            form_dict["title"] = title
            self._form = FormSchema.model_validate(form_dict)
            self.logger.info("update_form_title: set title to '%s'", title)
            return {
                "success": True,
                "message": f"Form title updated to '{title}'.",
                "form_id": self._form.form_id,
            }
        except Exception as exc:
            self.logger.error("update_form_title unexpected error: %s", exc)
            return {"error": str(exc)}

    async def update_form_description(self, description: str | None) -> dict:
        """Update the form description.

        Use this tool when the user asks to change or clear the form description.
        This is the correct tool for changing ``form.description`` — do NOT use
        ``update_form_meta`` for this purpose.

        Args:
            description: New description for the form. Pass null to clear it.

        Returns:
            Success dict confirming the description was updated, or error dict on failure.
        """
        try:
            form_dict = self._form.model_dump(mode="json")
            form_dict["description"] = description
            self._form = FormSchema.model_validate(form_dict)
            self.logger.info("update_form_description called")
            return {
                "success": True,
                "message": "Form description updated.",
                "form_id": self._form.form_id,
            }
        except Exception as exc:
            self.logger.error("update_form_description unexpected error: %s", exc)
            return {"error": str(exc)}

    async def update_section_title(self, section_id: str, title: str) -> dict:
        """Update a section's title (rename a section).

        Use this tool when the user asks to rename a section.  This is the
        correct tool for changing ``section.title`` — do NOT use
        ``update_section`` (which only touches ``section.meta``) for this purpose.

        Args:
            section_id: ID of the section to rename.
            title: New title for the section.

        Returns:
            Success dict, or error dict if the section is not found.
        """
        si: int | None = None
        for i, s in enumerate(self._form.sections):
            if s.section_id == section_id:
                si = i
                break
        if si is None:
            return {
                "error": f"Section '{section_id}' not found.",
                "available_sections": [s.section_id for s in self._form.sections],
            }
        try:
            section_dict = self._form.sections[si].model_dump(mode="json")
            section_dict["title"] = title
            self._form.sections[si] = FormSection.model_validate(section_dict)
        except Exception as exc:
            self.logger.error("update_section_title unexpected error: %s", exc)
            return {"error": f"Failed to rename section: {exc}"}
        self.logger.info(
            "update_section_title: section '%s' renamed to '%s'", section_id, title
        )
        return {
            "success": True,
            "section_id": section_id,
            "message": f"Section '{section_id}' renamed to '{title}'.",
        }

    # ------------------------------------------------------------------
    # Control tool
    # ------------------------------------------------------------------

    async def done(self) -> dict:
        """Signal that all edits are complete.

        After calling this tool the LLM should stop making further tool calls.
        The caller retrieves the final updated form via the ``form`` property.

        Returns:
            Success dict confirming edits are complete.
        """
        self._done = True
        self.logger.info(
            "EditToolkit.done() called — form '%s' edit session complete.",
            self._form.form_id,
        )
        return {
            "success": True,
            "message": "All edits complete. The form has been updated.",
            "form_id": self._form.form_id,
        }

    # ------------------------------------------------------------------
    # Compatibility shim — spec defines get_tool_definitions() interface
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list:
        """Return the list of AbstractTool instances for all 12 toolkit tools.

        Delegates to ``get_tools()`` which is the canonical AbstractToolkit
        method for retrieving tool instances.  ``GoogleGenAIClient.ask()``
        accepts the result directly as the ``tools=`` argument.

        Returns:
            List of AbstractTool instances (ToolkitTool wrappers).
        """
        return self.get_tools()

    async def execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a toolkit tool by name.

        Looks up the tool in the toolkit's tool cache and invokes it with
        the given arguments.

        Args:
            tool_name: Name of the tool to invoke (e.g. ``"get_field"``).
            arguments: Dict of arguments to pass to the tool.

        Returns:
            Tool result dict.
        """
        tool = self.get_tool(tool_name)
        if tool is None:
            available = self.list_tool_names()
            return {
                "error": f"Unknown tool '{tool_name}'.",
                "available_tools": available,
            }
        result = await tool.execute(**arguments)
        # AbstractTool.execute() returns a ToolResult — extract the inner result
        # and surface any errors so the LLM can correct its next call.
        if isinstance(result, ToolResult):
            if not result.success:
                return {"error": result.error or "Tool execution failed"}
            return result.result if result.result is not None else {}
        return result
