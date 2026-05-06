"""Adaptive Card renderer for FormSchema.

Migrated and extended from parrot/integrations/msteams/dialogs/card_builder.py.
Produces valid Adaptive Card JSON (schema v1.5) from FormSchema + StyleSchema.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.schema import FormField, FormSchema, FormSection, RenderedForm
from ..core.style import LayoutType, StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer

logger = logging.getLogger(__name__)


def _resolve(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve a LocalizedString to a plain string.

    Args:
        value: str or dict with locale keys.
        locale: BCP 47 locale tag.

    Returns:
        Resolved string, or empty string if None.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), "")


# Map new FieldType to Adaptive Card input element type
_FIELD_TYPE_MAPPING: dict[FieldType, str] = {
    FieldType.TEXT: "Input.Text",
    FieldType.TEXT_AREA: "Input.Text",
    FieldType.NUMBER: "Input.Number",
    FieldType.INTEGER: "Input.Number",
    FieldType.BOOLEAN: "Input.Toggle",
    FieldType.DATE: "Input.Date",
    FieldType.DATETIME: "Input.Date",
    FieldType.TIME: "Input.Time",
    FieldType.SELECT: "Input.ChoiceSet",
    FieldType.MULTI_SELECT: "Input.ChoiceSet",
    FieldType.EMAIL: "Input.Text",
    FieldType.URL: "Input.Text",
    FieldType.PHONE: "Input.Text",
    FieldType.PASSWORD: "Input.Text",
    FieldType.COLOR: "Input.Text",
    FieldType.HIDDEN: "Input.Text",
    FieldType.GROUP: None,
    FieldType.ARRAY: None,
    FieldType.FILE: None,
    FieldType.IMAGE: None,
}


class AdaptiveCardRenderer(AbstractFormRenderer):
    """Renders FormSchema as Adaptive Card JSON for MS Teams.

    Produces Adaptive Card v1.5 JSON that is compatible with the
    Bot Framework and MS Teams card rendering pipeline.

    Supports:
    - Complete form rendering (all sections in one card)
    - Section-by-section wizard rendering
    - Summary/confirmation card
    - Error card
    - Prefilled values
    - Validation error display
    - i18n label resolution

    Example:
        renderer = AdaptiveCardRenderer()
        result = await renderer.render(form_schema)
        card_json = result.content  # dict ready for Teams
    """

    SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"
    DEFAULT_VERSION = "1.5"
    CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"

    def __init__(
        self,
        version: str | None = None,
    ) -> None:
        """Initialize AdaptiveCardRenderer.

        Args:
            version: Adaptive Card schema version. Defaults to "1.5".
        """
        self.version = version or self.DEFAULT_VERSION
        self.logger = logging.getLogger(__name__)

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a complete FormSchema as an Adaptive Card.

        In WIZARD layout mode, renders only the first section.
        In all other modes, renders all sections in one card.

        Args:
            form: The form schema.
            style: Style configuration. Defaults to SINGLE_COLUMN layout.
            locale: Locale for i18n label resolution.
            prefilled: Pre-filled field values.
            errors: Field-level error messages.

        Returns:
            RenderedForm with Adaptive Card dict as content.
        """
        style = style or StyleSchema()
        prefilled = prefilled or {}
        errors = errors or {}

        body: list[dict[str, Any]] = []

        # Header
        title = _resolve(form.title, locale)
        body.append(self._build_header(title))

        # Form description if present
        if form.description:
            body.append({
                "type": "TextBlock",
                "text": _resolve(form.description, locale),
                "isSubtle": True,
                "wrap": True,
                "spacing": "Small",
            })

        # Render all sections
        for i, section in enumerate(form.sections):
            if i > 0:
                body.append({"type": "TextBlock", "text": " ", "separator": True})
            body.extend(self._build_section_body(section, prefilled, errors, locale))

        # Actions
        submit_label = _resolve(style.submit_label, locale) or "Submit"
        cancel_label = _resolve(style.cancel_label, locale) or "Cancel"
        actions = self._build_form_actions(
            show_cancel=form.cancel_allowed,
            submit_label=submit_label,
            cancel_label=cancel_label,
        )

        card = self._wrap_card(body, actions)
        return RenderedForm(
            content=card,
            content_type=self.CONTENT_TYPE,
        )

    async def render_section(
        self,
        form: FormSchema,
        section_index: int,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        show_back: bool = False,
        show_skip: bool = False,
    ) -> RenderedForm:
        """Render a single section as a wizard step Adaptive Card.

        Args:
            form: The form schema.
            section_index: 0-based index of the section to render.
            style: Style configuration.
            locale: Locale for i18n resolution.
            prefilled: Pre-filled field values.
            errors: Field-level error messages.
            show_back: Whether to include a Back button.
            show_skip: Whether to include a Skip button.

        Returns:
            RenderedForm with wizard step card as content.
        """
        style = style or StyleSchema()
        prefilled = prefilled or {}
        errors = errors or {}

        section = form.sections[section_index]
        total = len(form.sections)
        is_last = section_index == total - 1

        body: list[dict[str, Any]] = []

        # Form title header
        form_title = _resolve(form.title, locale)
        body.append(self._build_header(form_title, size="Medium"))

        # Progress indicator for multi-section forms
        if total > 1:
            section_title = _resolve(section.title, locale) if section.title else None
            body.append(self._build_progress_indicator(
                current=section_index + 1,
                total=total,
                section_title=section_title,
            ))

        # Section body
        body.extend(self._build_section_body(section, prefilled, errors, locale))

        # Wizard actions
        cancel_label = _resolve(style.cancel_label, locale) or "Cancel"
        actions = self._build_wizard_actions(
            is_first=section_index == 0,
            is_last=is_last,
            show_back=show_back,
            show_cancel=form.cancel_allowed,
            show_skip=show_skip,
            cancel_label=cancel_label,
        )

        card = self._wrap_card(body, actions)
        return RenderedForm(
            content=card,
            content_type=self.CONTENT_TYPE,
        )

    async def render_summary(
        self,
        form: FormSchema,
        form_data: dict[str, Any],
        *,
        locale: str = "en",
        summary_text: str | None = None,
    ) -> RenderedForm:
        """Render a summary/confirmation card with submitted data.

        Args:
            form: The form schema.
            form_data: All collected form data.
            locale: Locale for i18n resolution.
            summary_text: Optional LLM-generated summary text.

        Returns:
            RenderedForm with summary confirmation card.
        """
        body: list[dict[str, Any]] = []

        body.append(self._build_header("Confirm Submission", size="Medium"))
        form_title = _resolve(form.title, locale)
        body.append({
            "type": "TextBlock",
            "text": form_title,
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        })

        if summary_text:
            body.append({
                "type": "Container",
                "style": "emphasis",
                "items": [{"type": "TextBlock", "text": summary_text, "wrap": True}],
                "spacing": "Medium",
            })

        # Data as FactSet per section
        for section in form.sections:
            facts = []
            for field in section.fields:
                value = form_data.get(field.field_id)
                if value is not None:
                    label = _resolve(field.label, locale)
                    facts.append({
                        "title": f"{label}:",
                        "value": self._format_value(field, value, locale),
                    })
            if facts:
                section_title = _resolve(section.title, locale) or ""
                if section_title:
                    body.append({
                        "type": "TextBlock",
                        "text": section_title,
                        "weight": "Bolder",
                        "spacing": "Medium",
                        "separator": True,
                    })
                body.append({"type": "FactSet", "facts": facts})

        actions = [
            {"type": "Action.Submit", "title": "Confirm", "style": "positive",
             "data": {"_action": "confirm", **form_data}},
            {"type": "Action.Submit", "title": "Edit",
             "data": {"_action": "edit", **form_data}},
            {"type": "Action.Submit", "title": "Cancel", "style": "destructive",
             "data": {"_action": "cancel"}, "associatedInputs": "none"},
        ]

        card = self._wrap_card(body, actions)
        return RenderedForm(content=card, content_type=self.CONTENT_TYPE)

    async def render_error(
        self,
        title: str,
        errors: list[str],
        *,
        locale: str = "en",
        retry_action: bool = True,
    ) -> RenderedForm:
        """Render an error card.

        Args:
            title: Error card title.
            errors: List of error messages to display.
            locale: Locale for i18n.
            retry_action: Whether to include a Try Again button.

        Returns:
            RenderedForm with error card.
        """
        body: list[dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"Error: {title}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Attention",
            },
            {
                "type": "TextBlock",
                "text": "Please correct the following:",
                "wrap": True,
            },
        ]

        for error in errors:
            body.append({
                "type": "TextBlock",
                "text": f"- {error}",
                "color": "Attention",
                "wrap": True,
            })

        actions = []
        if retry_action:
            actions.append({
                "type": "Action.Submit",
                "title": "Try Again",
                "data": {"_action": "retry"},
            })

        card = self._wrap_card(body, actions)
        return RenderedForm(content=card, content_type=self.CONTENT_TYPE)

    # =========================================================================
    # Internal builders
    # =========================================================================

    def _wrap_card(
        self,
        body: list[dict[str, Any]],
        actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Wrap body and actions into an Adaptive Card structure.

        Args:
            body: Card body elements.
            actions: Card action buttons.

        Returns:
            Complete Adaptive Card dict.
        """
        card: dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": self.SCHEMA_URL,
            "version": self.version,
            "body": body,
        }
        if actions:
            card["actions"] = actions
        return card

    def _build_header(self, text: str, size: str = "Large") -> dict[str, Any]:
        """Build a header TextBlock element.

        Args:
            text: Header text.
            size: Font size (Large, Medium, etc.).

        Returns:
            TextBlock dict.
        """
        return {
            "type": "TextBlock",
            "text": text,
            "weight": "Bolder",
            "size": size,
            "wrap": True,
        }

    def _build_progress_indicator(
        self,
        current: int,
        total: int,
        section_title: str | None = None,
    ) -> dict[str, Any]:
        """Build a wizard progress indicator ColumnSet.

        Args:
            current: Current step (1-based).
            total: Total number of steps.
            section_title: Optional section title for the current step.

        Returns:
            ColumnSet dict.
        """
        indicators = []
        for i in range(1, total + 1):
            if i < current:
                indicators.append("[v]")
            elif i == current:
                indicators.append("[*]")
            else:
                indicators.append("[o]")

        progress_text = " ".join(indicators)
        step_text = f"Step {current} of {total}"
        if section_title:
            step_text += f": {section_title}"

        return {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "auto",
                    "items": [{"type": "TextBlock", "text": progress_text,
                               "fontType": "Monospace", "size": "Small"}],
                },
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [{"type": "TextBlock", "text": step_text,
                               "size": "Small", "isSubtle": True,
                               "horizontalAlignment": "Right"}],
                },
            ],
            "spacing": "Small",
        }

    def _build_section_body(
        self,
        section: FormSection,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        locale: str,
    ) -> list[dict[str, Any]]:
        """Build body elements for a form section.

        Args:
            section: FormSection to render.
            prefilled: Pre-filled values.
            errors: Field error messages.
            locale: Locale for i18n.

        Returns:
            List of Adaptive Card elements.
        """
        elements: list[dict[str, Any]] = []

        if section.title:
            section_title = _resolve(section.title, locale)
            elements.append({
                "type": "TextBlock",
                "text": section_title,
                "weight": "Bolder",
                "spacing": "Medium",
            })

        if section.description:
            elements.append({
                "type": "TextBlock",
                "text": _resolve(section.description, locale),
                "isSubtle": True,
                "wrap": True,
                "spacing": "Small",
            })

        for field in section.fields:
            elements.extend(self._build_field(field, prefilled, errors, locale))

        return elements

    def _build_field(
        self,
        field: FormField,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        locale: str,
    ) -> list[dict[str, Any]]:
        """Build Adaptive Card elements for a single field.

        Args:
            field: FormField to render.
            prefilled: Pre-filled values.
            errors: Field error messages.
            locale: Locale for i18n.

        Returns:
            List of elements (label, input, optional error).
        """
        elements: list[dict[str, Any]] = []
        value = prefilled.get(field.field_id, field.default)
        error = errors.get(field.field_id)

        # Label
        label_text = _resolve(field.label, locale) or field.field_id.replace("_", " ").title()
        if field.required:
            label_text += " *"

        elements.append({
            "type": "TextBlock",
            "text": label_text,
            "weight": "Bolder",
            "size": "Default",
            "spacing": "Medium",
        })

        # Description
        if field.description:
            elements.append({
                "type": "TextBlock",
                "text": _resolve(field.description, locale),
                "isSubtle": True,
                "size": "Small",
                "wrap": True,
                "spacing": "None",
            })

        # Input element
        input_elem = self._build_input_element(field, value, locale)
        if input_elem:
            elements.append(input_elem)

        # Error message
        if error:
            elements.append({
                "type": "TextBlock",
                "text": f"Error: {error}",
                "color": "Attention",
                "size": "Small",
                "spacing": "None",
            })

        return elements

    def _build_input_element(
        self,
        field: FormField,
        value: Any,
        locale: str,
    ) -> dict[str, Any] | None:
        """Build the Adaptive Card input element for a field.

        Args:
            field: FormField definition.
            value: Pre-filled value.
            locale: Locale for i18n.

        Returns:
            Adaptive Card input element dict, or None for unsupported types.
        """
        base: dict[str, Any] = {
            "id": field.field_id,
            "isRequired": field.required,
        }

        ft = field.field_type

        if ft in (FieldType.TEXT, FieldType.EMAIL, FieldType.URL, FieldType.PHONE,
                  FieldType.COLOR, FieldType.HIDDEN, FieldType.PASSWORD):
            elem: dict[str, Any] = {
                **base,
                "type": "Input.Text",
                "placeholder": _resolve(field.placeholder, locale) if field.placeholder else "",
                "value": str(value) if value is not None else "",
            }
            if ft == FieldType.EMAIL:
                elem["style"] = "Email"
            elif ft == FieldType.URL:
                elem["style"] = "Url"
            elif ft == FieldType.PASSWORD:
                elem["style"] = "Password"
            if field.constraints:
                if field.constraints.max_length:
                    elem["maxLength"] = field.constraints.max_length
                if field.constraints.pattern:
                    elem["regex"] = field.constraints.pattern
            return elem

        elif ft == FieldType.TEXT_AREA:
            return {
                **base,
                "type": "Input.Text",
                "isMultiline": True,
                "placeholder": _resolve(field.placeholder, locale) if field.placeholder else "",
                "value": str(value) if value is not None else "",
            }

        elif ft in (FieldType.NUMBER, FieldType.INTEGER):
            elem = {
                **base,
                "type": "Input.Number",
                "placeholder": _resolve(field.placeholder, locale) if field.placeholder else "",
            }
            if value is not None:
                elem["value"] = value
            if field.constraints:
                if field.constraints.min_value is not None:
                    elem["min"] = field.constraints.min_value
                if field.constraints.max_value is not None:
                    elem["max"] = field.constraints.max_value
            return elem

        elif ft == FieldType.BOOLEAN:
            title = _resolve(field.description, locale) if field.description else _resolve(field.label, locale)
            return {
                **base,
                "type": "Input.Toggle",
                "title": title,
                "value": "true" if value else "false",
                "valueOn": "true",
                "valueOff": "false",
            }

        elif ft == FieldType.DATE:
            elem = {**base, "type": "Input.Date"}
            if value:
                elem["value"] = str(value)
            return elem

        elif ft == FieldType.DATETIME:
            elem = {**base, "type": "Input.Date"}
            if value:
                v = str(value)
                elem["value"] = v.split("T")[0] if "T" in v else v
            return elem

        elif ft == FieldType.TIME:
            elem = {**base, "type": "Input.Time"}
            if value:
                elem["value"] = str(value)
            return elem

        elif ft == FieldType.SELECT:
            choices = self._build_choices(field, locale)
            elem = {
                **base,
                "type": "Input.ChoiceSet",
                "style": "compact",
                "choices": choices,
            }
            if value:
                elem["value"] = str(value)
            return elem

        elif ft == FieldType.MULTI_SELECT:
            choices = self._build_choices(field, locale)
            elem = {
                **base,
                "type": "Input.ChoiceSet",
                "isMultiSelect": True,
                "style": "expanded",
                "choices": choices,
            }
            if value:
                if isinstance(value, list):
                    elem["value"] = ",".join(str(v) for v in value)
                else:
                    elem["value"] = str(value)
            return elem

        # GROUP and ARRAY are rendered as sub-containers (simplified)
        elif ft == FieldType.GROUP and field.children:
            items: list[dict[str, Any]] = []
            for child in field.children:
                items.extend(self._build_field(child, {}, {}, locale))
            return {
                "type": "Container",
                "items": items,
                "spacing": "Small",
            }

        # Fallback for unsupported types
        else:
            logger.debug("No AC input element for field type %s, using text fallback", ft)
            return {
                **base,
                "type": "Input.Text",
                "placeholder": _resolve(field.placeholder, locale) if field.placeholder else "",
                "value": str(value) if value is not None else "",
            }

    def _build_choices(
        self,
        field: FormField,
        locale: str,
    ) -> list[dict[str, str]]:
        """Build choices array for Input.ChoiceSet.

        Args:
            field: FormField with options.
            locale: Locale for i18n option labels.

        Returns:
            List of {title, value} dicts.
        """
        if not field.options:
            return []
        return [
            {
                "title": _resolve(opt.label, locale) or opt.value,
                "value": opt.value,
            }
            for opt in field.options
        ]

    def _build_form_actions(
        self,
        show_cancel: bool = True,
        submit_label: str = "Submit",
        cancel_label: str = "Cancel",
    ) -> list[dict[str, Any]]:
        """Build action buttons for a complete form.

        Args:
            show_cancel: Whether to include the cancel button.
            submit_label: Submit button label.
            cancel_label: Cancel button label.

        Returns:
            List of Action.Submit dicts.
        """
        actions = [
            {
                "type": "Action.Submit",
                "title": submit_label,
                "style": "positive",
                "data": {"_action": "submit"},
            },
        ]
        if show_cancel:
            actions.append({
                "type": "Action.Submit",
                "title": cancel_label,
                "style": "destructive",
                "data": {"_action": "cancel"},
                "associatedInputs": "none",
            })
        return actions

    def _build_wizard_actions(
        self,
        is_first: bool,
        is_last: bool,
        show_back: bool = True,
        show_cancel: bool = True,
        show_skip: bool = False,
        cancel_label: str = "Cancel",
    ) -> list[dict[str, Any]]:
        """Build action buttons for a wizard step.

        Args:
            is_first: Whether this is the first step.
            is_last: Whether this is the last step.
            show_back: Whether to show a Back button.
            show_cancel: Whether to show a Cancel button.
            show_skip: Whether to show a Skip button.
            cancel_label: Cancel button label.

        Returns:
            List of Action.Submit dicts.
        """
        actions: list[dict[str, Any]] = []

        if not is_first and show_back:
            actions.append({
                "type": "Action.Submit",
                "title": "Back",
                "data": {"_action": "back"},
                "associatedInputs": "none",
            })

        if show_skip:
            actions.append({
                "type": "Action.Submit",
                "title": "Skip",
                "data": {"_action": "skip"},
                "associatedInputs": "none",
            })

        if show_cancel:
            actions.append({
                "type": "Action.Submit",
                "title": cancel_label,
                "style": "destructive",
                "data": {"_action": "cancel"},
                "associatedInputs": "none",
            })

        if is_last:
            actions.append({
                "type": "Action.Submit",
                "title": "Submit",
                "style": "positive",
                "data": {"_action": "submit"},
            })
        else:
            actions.append({
                "type": "Action.Submit",
                "title": "Next",
                "style": "positive",
                "data": {"_action": "next"},
            })

        return actions

    def _format_value(
        self,
        field: FormField,
        value: Any,
        locale: str,
    ) -> str:
        """Format a field value for display in summary.

        Args:
            field: FormField definition.
            value: The value to format.
            locale: Locale for i18n.

        Returns:
            Human-readable value string.
        """
        if value is None:
            return "Not provided"

        if field.field_type == FieldType.BOOLEAN:
            return "Yes" if value in (True, "true", "True", "1") else "No"

        if field.field_type == FieldType.MULTI_SELECT:
            if isinstance(value, str):
                return value.replace(",", ", ")
            elif isinstance(value, list):
                return ", ".join(str(v) for v in value)

        if field.field_type == FieldType.SELECT and field.options:
            for opt in field.options:
                if opt.value == str(value):
                    return _resolve(opt.label, locale)

        return str(value)
