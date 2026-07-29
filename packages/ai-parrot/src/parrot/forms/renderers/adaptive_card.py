"""Adaptive Card renderer for FormSchema.

Migrated and extended from parrot/integrations/msteams/dialogs/card_builder.py.
Produces valid Adaptive Card JSON (schema v1.5) from FormSchema + StyleSchema.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot.outputs.cards import (
    DEFAULT_ADAPTIVE_CARD_VERSION,
    ActionSubmit,
    CardSpec,
    Column,
    ColumnSet,
    Container,
    DetailField,
    DetailSection,
    InputChoice,
    RawElementsSection,
    TextBlock,
    render as render_card,
)
from parrot.outputs.cards.elements import ACElement
from parrot.outputs.cards.sections import CardSection
from parrot.outputs.cards.sections import FormSection as CardFormSection
from parrot.outputs.cards.sections import FormFieldSpec

from ..schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm
from ..style import LayoutType, StyleSchema
from ..types import FieldType, LocalizedString
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
    DEFAULT_VERSION = DEFAULT_ADAPTIVE_CARD_VERSION
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

        sections: list[CardSection] = []

        # Header
        title = _resolve(form.title, locale)
        sections.append(RawElementsSection(elements=[
            TextBlock(text=title, weight="Bolder", size="Large"),
        ]))

        # Form description if present
        if form.description:
            sections.append(RawElementsSection(elements=[
                TextBlock(
                    text=_resolve(form.description, locale),
                    is_subtle=True,
                    spacing="Small",
                ),
            ]))

        # Render all sections
        for i, section in enumerate(form.sections):
            if i > 0:
                sections.append(RawElementsSection(elements=[
                    TextBlock(text=" ", separator=True),
                ]))
            sections.extend(
                self._build_section_cards(section, prefilled, errors, locale)
            )

        # Actions
        submit_label = _resolve(style.submit_label, locale) or "Submit"
        cancel_label = _resolve(style.cancel_label, locale) or "Cancel"
        actions = self._build_form_actions(
            show_cancel=form.cancel_allowed,
            submit_label=submit_label,
            cancel_label=cancel_label,
        )

        spec = CardSpec(
            sections=sections,
            actions=actions,
            version=self.version,
            schema_url=self.SCHEMA_URL,
        )
        card = render_card(spec)
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

        sections: list[CardSection] = []

        # Form title header
        form_title = _resolve(form.title, locale)
        sections.append(RawElementsSection(elements=[
            TextBlock(text=form_title, weight="Bolder", size="Medium"),
        ]))

        # Progress indicator for multi-section forms
        if total > 1:
            section_title = (
                _resolve(section.title, locale) if section.title else None
            )
            sections.append(RawElementsSection(elements=[
                self._build_progress_indicator(
                    current=section_index + 1,
                    total=total,
                    section_title=section_title,
                ),
            ]))

        # Section body
        sections.extend(
            self._build_section_cards(section, prefilled, errors, locale)
        )

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

        spec = CardSpec(
            sections=sections,
            actions=actions,
            version=self.version,
            schema_url=self.SCHEMA_URL,
        )
        card = render_card(spec)
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
        sections: list[CardSection] = []

        sections.append(RawElementsSection(elements=[
            TextBlock(text="Confirm Submission", weight="Bolder", size="Medium"),
        ]))
        form_title = _resolve(form.title, locale)
        sections.append(RawElementsSection(elements=[
            TextBlock(text=form_title, weight="Bolder", size="Large"),
        ]))

        if summary_text:
            sections.append(RawElementsSection(elements=[
                Container(
                    style="Emphasis",
                    items=[TextBlock(text=summary_text)],
                    spacing="Medium",
                ),
            ]))

        # Data as FactSet per section via DetailSection
        for section in form.sections:
            facts: list[DetailField] = []
            for field in section.iter_fields():
                value = form_data.get(field.field_id)
                if value is not None:
                    label = _resolve(field.label, locale)
                    facts.append(DetailField(
                        label=f"{label}:",
                        value=self._format_value(field, value, locale),
                    ))
            if facts:
                section_title = _resolve(section.title, locale) or ""
                if section_title:
                    sections.append(RawElementsSection(elements=[
                        TextBlock(
                            text=section_title,
                            weight="Bolder",
                            spacing="Medium",
                            separator=True,
                        ),
                    ]))
                sections.append(DetailSection(fields=facts))

        actions = [
            ActionSubmit(
                title="Confirm",
                style="positive",
                data={"_action": "confirm", **form_data},
            ),
            ActionSubmit(
                title="Edit",
                data={"_action": "edit", **form_data},
            ),
            ActionSubmit(
                title="Cancel",
                style="destructive",
                data={"_action": "cancel"},
                associated_inputs="None",
            ),
        ]

        spec = CardSpec(
            sections=sections,
            actions=actions,
            version=self.version,
            schema_url=self.SCHEMA_URL,
        )
        card = render_card(spec)
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
        elements: list[ACElement] = [
            TextBlock(
                text=f"Error: {title}",
                weight="Bolder",
                size="Medium",
                color="Attention",
            ),
            TextBlock(text="Please correct the following:"),
        ]

        for error in errors:
            elements.append(TextBlock(
                text=f"- {error}",
                color="Attention",
            ))

        actions: list[ActionSubmit] = []
        if retry_action:
            actions.append(ActionSubmit(
                title="Try Again",
                data={"_action": "retry"},
            ))

        spec = CardSpec(
            sections=[RawElementsSection(elements=elements)],
            actions=actions,
            version=self.version,
            schema_url=self.SCHEMA_URL,
        )
        card = render_card(spec)
        return RenderedForm(content=card, content_type=self.CONTENT_TYPE)

    # =========================================================================
    # Internal builders
    # =========================================================================

    def _build_progress_indicator(
        self,
        current: int,
        total: int,
        section_title: str | None = None,
    ) -> ColumnSet:
        """Build a wizard progress indicator ColumnSet.

        Args:
            current: Current step (1-based).
            total: Total number of steps.
            section_title: Optional section title for the current step.

        Returns:
            ColumnSet element.
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

        return ColumnSet(
            columns=[
                Column(
                    width="auto",
                    items=[TextBlock(
                        text=progress_text,
                        font_type="Monospace",
                        size="Small",
                    )],
                ),
                Column(
                    width="stretch",
                    items=[TextBlock(
                        text=step_text,
                        size="Small",
                        is_subtle=True,
                        horizontal_alignment="Right",
                    )],
                ),
            ],
            spacing="Small",
        )

    def _build_section_cards(
        self,
        section: FormSection,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        locale: str,
    ) -> list[CardSection]:
        """Build card sections for a form section.

        Args:
            section: FormSection to render.
            prefilled: Pre-filled values.
            errors: Field error messages.
            locale: Locale for i18n.

        Returns:
            List of CardSection objects.
        """
        result: list[CardSection] = []
        header_elements: list[ACElement] = []

        if section.title:
            header_elements.append(TextBlock(
                text=_resolve(section.title, locale),
                weight="Bolder",
                spacing="Medium",
            ))

        if section.description:
            header_elements.append(TextBlock(
                text=_resolve(section.description, locale),
                is_subtle=True,
                spacing="Small",
            ))

        if header_elements:
            result.append(RawElementsSection(elements=header_elements))

        for item in section.fields:
            if isinstance(item, FormSubsection):
                result.extend(
                    self._build_subsection_cards(item, prefilled, errors, locale)
                )
            else:
                result.extend(
                    self._build_field_cards(item, prefilled, errors, locale)
                )

        return result

    def _build_subsection_cards(
        self,
        subsection: FormSubsection,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        locale: str,
    ) -> list[CardSection]:
        """Build card sections for a subsection container.

        Args:
            subsection: Subsection to render.
            prefilled: Pre-filled values.
            errors: Field error messages.
            locale: Locale for i18n.

        Returns:
            List of CardSection objects.
        """
        result: list[CardSection] = []
        header_elements: list[ACElement] = []

        if subsection.title:
            header_elements.append(TextBlock(
                text=_resolve(subsection.title, locale),
                weight="Bolder",
                spacing="Medium",
                separator=True,
            ))
        if subsection.description:
            header_elements.append(TextBlock(
                text=_resolve(subsection.description, locale),
                is_subtle=True,
                size="Small",
                spacing="None",
            ))

        if header_elements:
            result.append(RawElementsSection(elements=header_elements))

        for field in subsection.fields:
            result.extend(
                self._build_field_cards(field, prefilled, errors, locale)
            )

        return result

    def _build_field_cards(
        self,
        field: FormField,
        prefilled: dict[str, Any],
        errors: dict[str, str],
        locale: str,
    ) -> list[CardSection]:
        """Build card sections for a single form field.

        Args:
            field: FormField to render.
            prefilled: Pre-filled values.
            errors: Field error messages.
            locale: Locale for i18n.

        Returns:
            List of CardSection objects (form field + optional error).
        """
        result: list[CardSection] = []
        error = errors.get(field.field_id)

        if field.field_type == FieldType.GROUP and field.children:
            # GROUP: recursively render children
            for child in field.children:
                result.extend(
                    self._build_field_cards(child, prefilled, errors, locale)
                )
        else:
            field_spec = self._build_field_spec(field, prefilled, locale)
            if field_spec:
                result.append(CardFormSection(fields=[field_spec]))

        if error:
            result.append(RawElementsSection(elements=[
                TextBlock(
                    text=f"Error: {error}",
                    color="Attention",
                    size="Small",
                    spacing="None",
                ),
            ]))

        return result

    def _build_field_spec(
        self,
        field: FormField,
        prefilled: dict[str, Any],
        locale: str,
    ) -> FormFieldSpec | None:
        """Build a FormFieldSpec from a FormField.

        Maps the FormField's type, constraints, options, and prefilled value
        into a shared-builder FormFieldSpec that the renderer can expand.

        Args:
            field: FormField definition.
            prefilled: Pre-filled values keyed by field_id.
            locale: Locale for i18n.

        Returns:
            FormFieldSpec, or None for unsupported types.
        """
        ft = field.field_type

        # Unsupported types fall back to generic text input
        if ft in (FieldType.ARRAY, FieldType.FILE, FieldType.IMAGE):
            ft = FieldType.TEXT

        value = prefilled.get(field.field_id, field.default)

        # Resolve label with required indicator
        label_text = (
            _resolve(field.label, locale)
            or field.field_id.replace("_", " ").title()
        )
        if field.required:
            label_text += " *"

        field_type_str = ft.value  # e.g. "text", "text_area", "number"

        # Build constraints dict from Pydantic model
        constraints: dict[str, Any] | None = None
        if field.constraints:
            c: dict[str, Any] = {}
            max_len = getattr(field.constraints, "max_length", None)
            if max_len:
                c["max_length"] = max_len
            pattern = getattr(field.constraints, "pattern", None)
            if pattern:
                c["pattern"] = pattern
            min_val = getattr(field.constraints, "min_value", None)
            if min_val is not None:
                c["min_value"] = min_val
            max_val = getattr(field.constraints, "max_value", None)
            if max_val is not None:
                c["max_value"] = max_val
            if c:
                constraints = c

        # Build options for choice types
        options: list[InputChoice] | None = None
        if ft in (FieldType.SELECT, FieldType.MULTI_SELECT) and field.options:
            options = [
                InputChoice(
                    title=_resolve(opt.label, locale) or opt.value,
                    value=opt.value,
                )
                for opt in field.options
            ]

        # Handle datetime → date value conversion
        default = value
        if ft == FieldType.DATETIME and value:
            v = str(value)
            default = v.split("T")[0] if "T" in v else v

        return FormFieldSpec(
            field_id=field.field_id,
            field_type=field_type_str,
            label=label_text,
            description=(
                _resolve(field.description, locale) if field.description else None
            ),
            placeholder=(
                _resolve(field.placeholder, locale) if field.placeholder else None
            ),
            required=field.required,
            default=default,
            options=options,
            constraints=constraints,
            is_multiline=ft == FieldType.TEXT_AREA,
        )

    def _build_form_actions(
        self,
        show_cancel: bool = True,
        submit_label: str = "Submit",
        cancel_label: str = "Cancel",
    ) -> list[ActionSubmit]:
        """Build action buttons for a complete form.

        Args:
            show_cancel: Whether to include the cancel button.
            submit_label: Submit button label.
            cancel_label: Cancel button label.

        Returns:
            List of ActionSubmit instances.
        """
        actions: list[ActionSubmit] = [
            ActionSubmit(
                title=submit_label,
                style="positive",
                data={"_action": "submit"},
            ),
        ]
        if show_cancel:
            actions.append(ActionSubmit(
                title=cancel_label,
                style="destructive",
                data={"_action": "cancel"},
                associated_inputs="None",
            ))
        return actions

    def _build_wizard_actions(
        self,
        is_first: bool,
        is_last: bool,
        show_back: bool = True,
        show_cancel: bool = True,
        show_skip: bool = False,
        cancel_label: str = "Cancel",
    ) -> list[ActionSubmit]:
        """Build action buttons for a wizard step.

        Args:
            is_first: Whether this is the first step.
            is_last: Whether this is the last step.
            show_back: Whether to show a Back button.
            show_cancel: Whether to show a Cancel button.
            show_skip: Whether to show a Skip button.
            cancel_label: Cancel button label.

        Returns:
            List of ActionSubmit instances.
        """
        actions: list[ActionSubmit] = []

        if not is_first and show_back:
            actions.append(ActionSubmit(
                title="Back",
                data={"_action": "back"},
                associated_inputs="None",
            ))

        if show_skip:
            actions.append(ActionSubmit(
                title="Skip",
                data={"_action": "skip"},
                associated_inputs="None",
            ))

        if show_cancel:
            actions.append(ActionSubmit(
                title=cancel_label,
                style="destructive",
                data={"_action": "cancel"},
                associated_inputs="None",
            ))

        if is_last:
            actions.append(ActionSubmit(
                title="Submit",
                style="positive",
                data={"_action": "submit"},
            ))
        else:
            actions.append(ActionSubmit(
                title="Next",
                style="positive",
                data={"_action": "next"},
            ))

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
