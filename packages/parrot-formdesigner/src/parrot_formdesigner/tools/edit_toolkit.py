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
import uuid
from typing import Any

try:
    from parrot.tools.abstract import ToolResult
    from parrot.tools.toolkit import AbstractToolkit
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
from ..assembler import FormAssembler
from ..core.constraints import DependencyRule, PostDependency
from ..core.resolution import find_field_by_uid, resolve_rule_references
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection


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
        self, field_uid: uuid.UUID
    ) -> tuple[FormField, FormSection] | tuple[None, None]:
        """Search the form for *field_uid* (FEAT-393).

        Delegates to the canonical ``find_field_by_uid`` lookup — reaches
        fields inside subsections, GROUP ``children``, and ARRAY
        ``item_template`` (not just top-level section fields).

        Args:
            field_uid: The field's immutable UID.

        Returns:
            Tuple of (FormField, FormSection) if found, or (None, None).
        """
        found = find_field_by_uid(self._form, field_uid)
        return found if found else (None, None)

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
        section: section_id/section_uid, title, and for each field only
        field_id/field_uid, label, and field_type.  Options, constraints,
        children, and meta are omitted to keep the response small (at most
        5% of the full JSON for large forms).

        ``field_uid`` (FEAT-393) is the immutable identity to pass into
        ``update_field``/``remove_field``/``move_field``/``get_field``;
        ``field_id`` stays the human-readable key for rule authoring
        (``add_dependency``/``add_post_dependency``).

        Returns:
            Compact dict with form outline including section/field
            uid+id pairs and types.
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
                "section_uid": str(section.section_uid),
                "section_id": section.section_id,
                "title": section.title,
                "field_count": len(self._iter_section_fields(section)),
                "fields": [],
            }

            for field in self._iter_section_fields(section):
                section_entry["fields"].append(
                    {
                        "field_uid": str(field.field_uid),
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

    async def get_field(self, field_uid: str) -> dict:
        """Return the full JSON for a single field by ``field_uid``.

        Searches the entire form, including subsections and nested
        GROUP/ARRAY fields (FEAT-393).

        Args:
            field_uid: UUID string of the field to retrieve — obtain from
                ``get_form_summary`` or ``search_fields``. Example:
                ``"3c3b0847-56fb-493f-bb84-2554b502a31e"``.

        Returns:
            Full field data dict with containing ``section_uid``/
            ``section_id``, or an error dict.
        """
        try:
            uid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{field_uid}' is not a valid field_uid (UUID string)."}
        field, section = self._find_field_and_section(uid)
        if field is None:
            return {
                "error": f"Field '{field_uid}' not found in any section.",
            }
        return {
            "section_uid": str(section.section_uid),
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
            List of match dicts with section_id, field_id, field_uid (str,
            FEAT-393 — feed this into update_field/remove_field/move_field/
            get_field), label, field_type.
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
                            "field_uid": str(field.field_uid),
                            "label": field.label,
                            "field_type": field.field_type,
                        }
                    )

        return results

    # ------------------------------------------------------------------
    # Mutation tools — delegate to operations.py apply functions
    # ------------------------------------------------------------------

    async def update_field(
        self, section_uid: str, field_uid: str, patch: dict
    ) -> dict:
        """Apply an RFC 7396 merge-patch to a single field, addressed by UID.

        Keys present in *patch* override the existing value; keys absent in
        *patch* are preserved; explicit ``null`` values remove the key.
        ``patch`` MAY rename ``field_id`` (subject to per-form uniqueness);
        a patch touching ``field_uid`` is rejected — the identity is
        immutable.

        Args:
            section_uid: UUID string of the section containing the field —
                obtain from ``get_form_summary``. Example:
                ``"3c3b0847-56fb-493f-bb84-2554b502a31e"``.
            field_uid: UUID string of the field to update — obtain from
                ``get_form_summary`` or ``search_fields``.
            patch: RFC 7396 merge-patch dict with fields to update.

        Returns:
            Success dict with updated field data, or error dict on failure.
        """
        try:
            section_uuid = uuid.UUID(section_uid)
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": "section_uid and field_uid must be valid UUID strings."}
        try:
            op = UpdateField(
                op="update_field",
                section_uid=section_uuid,
                field_uid=field_uuid,
                patch=patch,
            )
            self._form = _apply_update_field(self._form, op)
            updated_field, _ = self._find_field_and_section(field_uuid)
            return {
                "success": True,
                "field_uid": field_uid,
                "field_id": updated_field.field_id if updated_field else None,
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
        section_uid: str,
        field: dict,
        position: int | None = None,
    ) -> dict:
        """Add a new field to a section at an optional position.

        ``field`` may carry a client-supplied ``field_uid`` (upsert
        origin); when omitted, a fresh one is minted automatically
        (FEAT-393) and returned in the result.

        Args:
            section_uid: UUID string of the section to add the field to —
                obtain from ``get_form_summary``.
            field: Dict representation of the FormField to add.
            position: Optional 0-based insertion index. Appends if None.

        Returns:
            Success dict with the added field's ``field_uid``/``field_id``,
            or error dict on failure.
        """
        try:
            section_uuid = uuid.UUID(section_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{section_uid}' is not a valid section_uid (UUID string)."}
        try:
            validated_field = FormField.model_validate(field)
            op = AddField(
                op="add_field",
                section_uid=section_uuid,
                field=validated_field,
                position=position,
            )
            self._form = _apply_add_field(self._form, op)
            return {
                "success": True,
                "section_uid": section_uid,
                "field_uid": str(validated_field.field_uid),
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

    async def add_field_from_schema(
        self,
        section_uid: str,
        field_schema: dict,
        position: int | None = None,
    ) -> dict:
        """Add a field from a raw schema dict with shortcut expansion.

        Delegates to `FormAssembler.assemble_field()` (FEAT-388, Module 1)
        to expand convenience shortcuts (auto-generated `field_id` from
        `label`, string `field_type` coercion) before validating and
        applying the mutation via the existing `add_field()`.

        Args:
            section_uid: UUID string of the section to add the field to —
                obtain from ``get_form_summary``.
            field_schema: Dict with field definition (supports shortcuts:
                auto-generated field_id from label, string field_type).
            position: Optional 0-based insertion index. Appends if None.

        Returns:
            Success dict with added field's ``field_uid``/``field_id``, or
            error dict on failure.
        """
        try:
            assembler = FormAssembler()
            validated_field = assembler.assemble_field(field_schema)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("add_field_from_schema validation error: %s", exc)
            return {"error": f"Invalid field schema: {exc}"}

        return await self.add_field(section_uid, validated_field.model_dump(), position)

    async def remove_field(self, section_uid: str, field_uid: str) -> dict:
        """Remove a field from a section, addressed by UID.

        Args:
            section_uid: UUID string of the section containing the field —
                obtain from ``get_form_summary``.
            field_uid: UUID string of the field to remove — obtain from
                ``get_form_summary`` or ``search_fields``.

        Returns:
            Success dict, or error dict on failure.
        """
        try:
            section_uuid = uuid.UUID(section_uid)
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": "section_uid and field_uid must be valid UUID strings."}
        try:
            op = RemoveField(
                op="remove_field",
                section_uid=section_uuid,
                field_uid=field_uuid,
            )
            self._form = _apply_remove_field(self._form, op)
            return {
                "success": True,
                "section_uid": section_uid,
                "field_uid": field_uid,
                "message": f"Field '{field_uid}' removed from section '{section_uid}'.",
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

    async def add_dependency(self, field_uid: str, rule: dict) -> dict:
        """Set or replace the ``depends_on`` rule on a field.

        Validates the rule dict via :class:`DependencyRule` and runs the
        form-level rule-integrity pass before applying.  Returns an error dict
        (form unchanged) if validation fails.

        ``rule``'s conditions/operations may reference other fields by their
        authored ``field_id`` (LLM ergonomics) — after applying, the form is
        routed through ``core.resolution.resolve_rule_references`` (FEAT-393)
        so the stored rule is UID-addressed before the integrity check runs.

        Args:
            field_uid: UUID string of the field to update — obtain from
                ``get_form_summary`` or ``search_fields``.
            rule: Dict representation of a :class:`DependencyRule` — field
                references inside ``conditions``/``operations`` use authored
                ``field_id`` strings.

        Returns:
            Success dict with the updated ``depends_on`` (UID-resolved), or
            an error dict.
        """
        try:
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{field_uid}' is not a valid field_uid (UUID string)."}
        try:
            validated_rule = DependencyRule.model_validate(rule)
        except ValidationError as exc:
            return {"error": f"Invalid DependencyRule: {exc.errors()}"}

        field, _section = self._find_field_and_section(field_uuid)
        if field is None:
            return {"error": f"Field '{field_uid}' not found."}

        # Build a temporary form copy with the new rule applied to validate integrity
        updated_field = field.model_copy(update={"depends_on": validated_rule})
        temp_form = self._replace_field_in_form(self._form, field_uuid, updated_field)

        try:
            temp_form = resolve_rule_references(temp_form)
        except ValueError as exc:
            return {"error": "Rule integrity check failed", "details": [str(exc)]}

        rule_errors = await self._check_rules(temp_form)
        if rule_errors:
            return {"error": "Rule integrity check failed", "details": rule_errors}

        self._form = temp_form
        resolved_field, _ = self._find_field_and_section(field_uuid)
        return {
            "success": True,
            "field_uid": field_uid,
            "depends_on": resolved_field.depends_on.model_dump(mode="json"),
        }

    async def update_dependency(self, field_uid: str, patch: dict) -> dict:
        """Merge-patch the existing ``depends_on`` rule on a field.

        The ``patch`` is merged into the current rule dict.  If the field has
        no existing rule, ``patch`` is used as the full new rule.

        Args:
            field_uid: UUID string of the field to update — obtain from
                ``get_form_summary`` or ``search_fields``.
            patch: Partial dict to merge into the existing DependencyRule.

        Returns:
            Success dict with the updated ``depends_on``, or an error dict.
        """
        try:
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{field_uid}' is not a valid field_uid (UUID string)."}
        field, _section = self._find_field_and_section(field_uuid)
        if field is None:
            return {"error": f"Field '{field_uid}' not found."}

        current = field.depends_on.model_dump() if field.depends_on else {}
        merged = {**current, **patch}
        return await self.add_dependency(field_uid, merged)

    async def remove_dependency(self, field_uid: str) -> dict:
        """Clear the ``depends_on`` rule from a field.

        Args:
            field_uid: UUID string of the field to clear — obtain from
                ``get_form_summary`` or ``search_fields``.

        Returns:
            Success dict, or error dict if the field is not found.
        """
        try:
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{field_uid}' is not a valid field_uid (UUID string)."}
        field, _section = self._find_field_and_section(field_uuid)
        if field is None:
            return {"error": f"Field '{field_uid}' not found."}

        updated_field = field.model_copy(update={"depends_on": None})
        self._form = self._replace_field_in_form(self._form, field_uuid, updated_field)
        return {"success": True, "field_uid": field_uid, "depends_on": None}

    async def add_post_dependency(self, field_uid: str, post: dict) -> dict:
        """Append a :class:`PostDependency` to a field's ``post_depends`` list.

        Validates the post-dependency dict and runs rule-integrity before
        applying.  Returns an error dict (form unchanged) if validation fails.

        ``post``'s ``target``/conditions/operation may reference other
        fields by their authored ``field_id`` (LLM ergonomics) — after
        applying, the form is routed through ``core.resolution.
        resolve_rule_references`` (FEAT-393) so stored references are
        UID-addressed before the integrity check runs.

        Args:
            field_uid: UUID string of the field to update — obtain from
                ``get_form_summary`` or ``search_fields``.
            post: Dict representation of a :class:`PostDependency` — field
                references use authored ``field_id`` strings.

        Returns:
            Success dict with the full updated ``post_depends`` list
            (UID-resolved), or an error dict.
        """
        try:
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{field_uid}' is not a valid field_uid (UUID string)."}
        try:
            validated_post = PostDependency.model_validate(post)
        except ValidationError as exc:
            return {"error": f"Invalid PostDependency: {exc.errors()}"}

        field, _section = self._find_field_and_section(field_uuid)
        if field is None:
            return {"error": f"Field '{field_uid}' not found."}

        existing = list(field.post_depends or [])
        existing.append(validated_post)
        updated_field = field.model_copy(update={"post_depends": existing})
        temp_form = self._replace_field_in_form(self._form, field_uuid, updated_field)

        try:
            temp_form = resolve_rule_references(temp_form)
        except ValueError as exc:
            return {"error": "Rule integrity check failed", "details": [str(exc)]}

        rule_errors = await self._check_rules(temp_form)
        if rule_errors:
            return {"error": "Rule integrity check failed", "details": rule_errors}

        self._form = temp_form
        resolved_field, _ = self._find_field_and_section(field_uuid)
        return {
            "success": True,
            "field_uid": field_uid,
            "post_depends": [p.model_dump(mode="json") for p in resolved_field.post_depends],
        }

    async def remove_post_dependency(self, field_uid: str, target: str) -> dict:
        """Remove a specific post-dependency (by target ``field_uid``) from a field.

        Args:
            field_uid: UUID string of the owning field — obtain from
                ``get_form_summary`` or ``search_fields``.
            target: UUID string — the resolved ``target`` field_uid of the
                PostDependency to remove (as stored after
                ``resolve_rule_references`` has run, e.g. via
                ``add_post_dependency``).

        Returns:
            Success dict with the remaining ``post_depends`` list, or an error dict.
        """
        try:
            field_uuid = uuid.UUID(field_uid)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{field_uid}' is not a valid field_uid (UUID string)."}
        field, _section = self._find_field_and_section(field_uuid)
        if field is None:
            return {"error": f"Field '{field_uid}' not found."}

        try:
            target_uuid = uuid.UUID(target)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"'{target}' is not a valid target field_uid (UUID string)."}

        existing = list(field.post_depends or [])
        # Compare as UUIDs, not raw strings — post.target is always stored
        # canonical (str(uuid.UUID(...))) post-resolution, but a caller-
        # supplied target in a different (still valid) UUID case/format
        # must still match (code review fix).
        updated = [p for p in existing if uuid.UUID(p.target) != target_uuid]
        if len(updated) == len(existing):
            return {
                "error": f"No post_depends with target='{target}' found on field '{field_uid}'."
            }

        updated_field = field.model_copy(update={"post_depends": updated or None})
        self._form = self._replace_field_in_form(self._form, field_uuid, updated_field)
        return {
            "success": True,
            "field_uid": field_uid,
            "removed_target": target,
            "post_depends": [p.model_dump(mode="json") for p in updated],
        }

    # ------------------------------------------------------------------
    # Private helpers for dependency CRUD
    # ------------------------------------------------------------------

    def _replace_field_in_form(
        self,
        form: FormSchema,
        field_uid: uuid.UUID,
        new_field: FormField,
    ) -> FormSchema:
        """Return a deep copy of *form* with the field matching *field_uid*
        replaced by *new_field* (FEAT-393).

        Searches the FULL tree — section-level fields, subsections, GROUP
        ``children``, and ARRAY ``item_template`` — mirroring
        ``core.schema.walk_fields``'s canonical traversal shape (code
        review fix: the previous version only searched one level into
        subsections, silently no-opping — and callers still reported
        ``success: True`` — for a field nested in ``children``/
        ``item_template``).

        Args:
            form: The source FormSchema.
            field_uid: The UID of the field to replace.
            new_field: The replacement FormField.

        Returns:
            A new FormSchema with the field swapped.
        """

        def _replace_in_items(items: list) -> list:
            new_items = []
            for item in items:
                if isinstance(item, FormSubsection):
                    new_items.append(
                        item.model_copy(
                            update={"fields": _replace_in_items(item.fields)}
                        )
                    )
                    continue
                if item.field_uid == field_uid:
                    new_items.append(new_field)
                    continue
                updates: dict[str, Any] = {}
                if item.children:
                    updates["children"] = _replace_in_items(item.children)
                if item.item_template is not None:
                    updates["item_template"] = _replace_in_items(
                        [item.item_template]
                    )[0]
                new_items.append(item.model_copy(update=updates) if updates else item)
            return new_items

        new_sections = [
            section.model_copy(update={"fields": _replace_in_items(section.fields)})
            for section in form.sections
        ]
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

    async def add_section_from_schema(
        self,
        section_schema: dict,
        position: int | None = None,
    ) -> dict:
        """Add a section from a raw schema dict with shortcut expansion.

        Delegates to `FormAssembler.assemble_section()` (FEAT-388, Module 1)
        to expand convenience shortcuts (auto-generated `section_id`,
        per-field shortcuts) before validating and applying the mutation via
        the existing `add_section()`.

        Args:
            section_schema: Dict with section definition (supports
                shortcuts: auto-generated section_id, field shortcuts).
            position: Optional 0-based insertion index. Appends if None.

        Returns:
            Success dict with added section_id, or error dict on failure.
        """
        try:
            assembler = FormAssembler()
            validated_section = assembler.assemble_section(section_schema)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("add_section_from_schema validation error: %s", exc)
            return {"error": f"Invalid section schema: {exc}"}

        return await self.add_section(validated_section.model_dump(), position)

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
        section = self._find_section(section_id)
        if section is None:
            return {
                "error": f"Section '{section_id}' not found.",
                "available_sections": [s.section_id for s in self._form.sections],
            }
        try:
            op = UpdateSectionMeta(
                op="update_section_meta",
                section_uid=section.section_uid,
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
        from_section_uid: str,
        field_uid: str,
        to_section_uid: str,
        position: int | None = None,
    ) -> dict:
        """Move a field within or across sections, addressed by UID.

        Args:
            from_section_uid: UUID string of the source section — obtain
                from ``get_form_summary``.
            field_uid: UUID string of the field to move — obtain from
                ``get_form_summary`` or ``search_fields``.
            to_section_uid: UUID string of the destination section.
            position: Optional 0-based insertion index in the destination section.

        Returns:
            Success dict, or error dict on failure.
        """
        try:
            op = MoveField(
                op="move_field",
                **{
                    "from": {"section_uid": from_section_uid, "field_uid": field_uid},
                    "to": {"section_uid": to_section_uid, "position": position},
                },
            )
            self._form = _apply_move_field(self._form, op)
            return {
                "success": True,
                "field_uid": field_uid,
                "from_section_uid": from_section_uid,
                "to_section_uid": to_section_uid,
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
