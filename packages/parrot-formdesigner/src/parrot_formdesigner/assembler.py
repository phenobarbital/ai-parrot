"""FormAssembler — deterministic, LLM-free form assembly.

Encapsulates format detection, convenience-shortcut expansion, extractor
delegation, and whole-form / component-level assembly for structured
(non-LLM) form creation. `FormAssembler` is a plain, synchronous class
with no external side effects — it is usable independently of
`CreateFormTool` or any LLM client.

See ``sdd/specs/deterministic-creationformtool.spec.md`` (FEAT-388,
Module 1) for the full design.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from .core.schema import FormField, FormSchema, FormSection
from .extractors import JsonSchemaExtractor

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to a kebab-case slug suitable for form_id/section_id.

    Mirrors ``_slugify`` in ``tools/create_form.py`` so deterministic and
    LLM-generated forms produce identically-shaped IDs.

    Args:
        text: Input string (e.g. a form title).

    Returns:
        Lowercase slug with hyphens, capped at 50 characters. Falls back
        to a random ``form-<hex>`` slug if the input has no usable
        characters.
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:50] or f"form-{uuid.uuid4().hex[:8]}"


def _field_id_from_label(label: Any) -> str:
    """Convert a field label to a snake_case field_id.

    Args:
        label: A ``LocalizedString`` (plain string or a dict of locale ->
            text). When a dict is given, the first value is used.

    Returns:
        Snake_case identifier capped at 50 characters, falling back to
        ``"field"`` if the label has no usable characters.
    """
    if isinstance(label, dict):
        label = next(iter(label.values()), "field")
    text = str(label).lower().strip()
    text = re.sub(r"[^a-z0-9\s_]", "", text)
    text = re.sub(r"[\s]+", "_", text)
    return text[:50] or "field"


def _as_text(value: Any) -> str | None:
    """Extract plain text from a ``LocalizedString``-shaped value.

    Args:
        value: A plain string, a dict of locale -> text, or ``None``.

    Returns:
        The plain string, the first dict value, or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return next(iter(value.values()), None)
    return str(value)


class FormAssembler:
    """Deterministic form assembly from structured input.

    Handles format detection, shortcut expansion, extractor delegation,
    and component-level assembly. Usable independently of
    `CreateFormTool` — no LLM client required. All methods are
    synchronous: assembly is pure Pydantic validation and dict
    manipulation.
    """

    def __init__(self) -> None:
        self._jsonschema_extractor = JsonSchemaExtractor()

    def assemble(
        self,
        schema: dict[str, Any],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema:
        """Assemble a complete FormSchema from a schema dict.

        Detects whether the input is JSON Schema (draft-07) or
        FormSchema-native JSON, then delegates accordingly.

        Args:
            schema: JSON Schema dict or FormSchema-native dict (with
                optional shortcuts).
            form_id: Optional override for the form ID.
            title: Optional override for the form title.

        Returns:
            A validated FormSchema.

        Raises:
            pydantic.ValidationError: If the input does not validate as
                a FormSchema (native path) or contains an unknown field
                type.
        """
        if self.detect_format(schema) == "jsonschema":
            return self._jsonschema_extractor.extract(schema, form_id=form_id, title=title)

        data = dict(schema)
        if form_id is not None:
            data["form_id"] = form_id
        if title is not None:
            data["title"] = title

        expanded = self.expand_shortcuts(data)
        return FormSchema.model_validate(expanded)

    def assemble_from_sections(
        self,
        sections: list[dict[str, Any]],
        *,
        form_id: str | None = None,
        title: str | None = None,
    ) -> FormSchema:
        """Assemble a FormSchema from a list of section dicts.

        Args:
            sections: List of section dicts (with optional shortcuts).
            form_id: Optional form ID. Auto-generated from `title` when
                omitted.
            title: Optional form title.

        Returns:
            A validated FormSchema.
        """
        data: dict[str, Any] = {"sections": sections}
        if form_id is not None:
            data["form_id"] = form_id
        if title is not None:
            data["title"] = title

        expanded = self.expand_shortcuts(data)
        return FormSchema.model_validate(expanded)

    def assemble_from_fields(
        self,
        fields: list[dict[str, Any]],
        *,
        form_id: str | None = None,
        title: str | None = None,
        section_title: str | None = None,
    ) -> FormSchema:
        """Assemble a FormSchema from a flat list of field dicts.

        Fields are wrapped in a single default section.

        Args:
            fields: Flat list of field dicts (with optional shortcuts).
            form_id: Optional form ID. Auto-generated from `title` when
                omitted.
            title: Optional form title.
            section_title: Optional title for the auto-created default
                section.

        Returns:
            A validated FormSchema with a single section containing all
            provided fields.
        """
        section: dict[str, Any] = {"fields": fields}
        if section_title is not None:
            section["title"] = section_title

        data: dict[str, Any] = {"sections": [section]}
        if form_id is not None:
            data["form_id"] = form_id
        if title is not None:
            data["title"] = title

        expanded = self.expand_shortcuts(data)
        return FormSchema.model_validate(expanded)

    def assemble_field(self, field_dict: dict[str, Any]) -> FormField:
        """Create a single FormField from a dict with shortcut expansion.

        Args:
            field_dict: Field dict (with optional shortcuts).

        Returns:
            A validated FormField.
        """
        expanded = self._expand_field(field_dict, set())
        return FormField.model_validate(expanded)

    def assemble_section(self, section_dict: dict[str, Any]) -> FormSection:
        """Create a single FormSection from a dict with shortcut expansion.

        Args:
            section_dict: Section dict (with optional shortcuts).

        Returns:
            A validated FormSection.
        """
        expanded = self._expand_section(section_dict, 1)
        return FormSection.model_validate(expanded)

    def detect_format(self, schema: dict[str, Any]) -> str:
        """Detect input format: 'jsonschema' or 'native'.

        Args:
            schema: The input schema dict.

        Returns:
            ``"jsonschema"`` when the dict has ``"type": "object"`` and a
            ``"properties"`` key; ``"native"`` otherwise (including the
            fallback case where neither shape is recognized — Pydantic
            validation is left to fail fast).
        """
        if schema.get("type") == "object" and "properties" in schema:
            return "jsonschema"
        return "native"

    def expand_shortcuts(self, data: dict[str, Any]) -> dict[str, Any]:
        """Expand convenience shortcuts in FormSchema-native JSON.

        Handles:
        - Top-level `fields` (no `sections`) wrapped in a default section.
        - Missing `section_id` -> sequential `"section-1"`, `"section-2"`, ...
        - Missing `field_id` -> slugified `label` (snake_case), with a
          numeric suffix on collision.
        - Missing `form_id` -> slugified `title`.
        - String `field_type` values are passed through unchanged (Pydantic
          coerces them to `FieldType`).

        Args:
            data: FormSchema-native dict, possibly with shortcuts.

        Returns:
            A new dict with all shortcuts expanded. The input is not
            mutated.
        """
        data = dict(data)

        if "fields" in data and "sections" not in data:
            data["sections"] = [{"fields": data.pop("fields")}]

        sections = data.get("sections")
        if sections is not None:
            data["sections"] = [
                self._expand_section(section, index)
                for index, section in enumerate(sections, start=1)
            ]

        if not data.get("form_id"):
            title_text = _as_text(data.get("title"))
            if title_text:
                data["form_id"] = _slugify(title_text)

        return data

    def _expand_section(self, section: dict[str, Any], index: int) -> dict[str, Any]:
        """Expand shortcuts for a single section dict.

        Args:
            section: Section dict, possibly missing `section_id`.
            index: 1-based position of the section, used to auto-generate
                `section_id` when missing.

        Returns:
            A new section dict with shortcuts expanded.
        """
        section = dict(section)
        if not section.get("section_id"):
            section["section_id"] = f"section-{index}"

        fields = section.get("fields")
        if fields is not None:
            seen_field_ids: set[str] = set()
            section["fields"] = [self._expand_field(field, seen_field_ids) for field in fields]

        return section

    def _expand_field(self, field: dict[str, Any], seen_field_ids: set[str]) -> dict[str, Any]:
        """Expand shortcuts for a single field dict.

        Args:
            field: Field dict, possibly missing `field_id`.
            seen_field_ids: Field IDs already assigned within the current
                scope (section or single-field call), used to detect
                collisions and append a numeric suffix.

        Returns:
            A new field dict with shortcuts expanded.
        """
        field = dict(field)
        if not field.get("field_id"):
            base_id = _field_id_from_label(field.get("label", "field"))
            field_id = base_id
            suffix = 2
            while field_id in seen_field_ids:
                field_id = f"{base_id}_{suffix}"
                suffix += 1
            field["field_id"] = field_id

        seen_field_ids.add(field["field_id"])
        return field
