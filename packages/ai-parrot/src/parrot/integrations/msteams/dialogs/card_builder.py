"""
Adaptive Card Builder for MS Teams Form Dialogs.

Converts FormDefinition objects into valid Adaptive Card JSON
that can be rendered in Microsoft Teams.
"""
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum
from ...dialogs.models import (
    FormDefinition,
    FormSection,
    FormField,
    FieldType,
    ValidationRule,
)


class CardStyle(str, Enum):
    """Visual style presets for cards."""
    DEFAULT = "default"
    COMPACT = "compact"
    DETAILED = "detailed"


@dataclass
class CardTheme:
    """Theme configuration for Adaptive Cards."""
    accent_color: str = "Accent"
    header_size: str = "Large"
    header_weight: str = "Bolder"
    label_weight: str = "Bolder"
    label_size: str = "Default"
    spacing: str = "Medium"
    separator: bool = True

    # Progress indicator colors
    progress_complete: str = "Good"
    progress_current: str = "Accent"
    progress_pending: str = "Default"


class AdaptiveCardBuilder:
    """
    Builds Adaptive Cards from FormDefinition objects.

    Supports:
    - Complete forms (all sections in one card)
    - Section-by-section cards (for wizards)
    - Summary/confirmation cards
    - Error display cards

    Features:
    - Progress indicators for multi-step forms
    - Validation error highlighting
    - Conditional field visibility
    - Dynamic choices loading
    """

    SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"
    DEFAULT_VERSION = "1.5"

    # Field type to Adaptive Card input mapping
    FIELD_TYPE_MAPPING = {
        FieldType.TEXT: "Input.Text",
        FieldType.NUMBER: "Input.Number",
        FieldType.DATE: "Input.Date",
        FieldType.DATETIME: "Input.Time",  # Combined with Date
        FieldType.CHOICE: "Input.ChoiceSet",
        FieldType.MULTICHOICE: "Input.ChoiceSet",
        FieldType.TOGGLE: "Input.Toggle",
        FieldType.EMAIL: "Input.Text",
        FieldType.URL: "Input.Text",
        FieldType.TEXTAREA: "Input.Text",
    }

    def __init__(
        self,
        theme: CardTheme = None,
        version: str = None,
        style: CardStyle = CardStyle.DEFAULT,
    ):
        self.theme = theme or CardTheme()
        self.version = version or self.DEFAULT_VERSION
        self.style = style

    # =========================================================================
    # Public API
    # =========================================================================

    def build_complete_form(
        self,
        form: FormDefinition,
        prefilled: Dict[str, Any] = None,
        errors: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Build a single Adaptive Card containing all form sections.

        Best for forms with 5 or fewer total fields.

        Args:
            form: The form definition
            prefilled: Pre-filled values for fields
            errors: Validation errors keyed by field name

        Returns:
            Complete Adaptive Card JSON
        """
        prefilled = prefilled or {}
        errors = errors or {}

        body = []

        # Header
        body.append(self._build_header(form.title))

        # All sections
        for i, section in enumerate(form.sections):
            if i > 0 and self.theme.separator:
                body.append({"type": "TextBlock", "text": " ", "separator": True})

            body.extend(self._build_section_body(section, prefilled, errors))

        # Actions
        actions = self._build_form_actions(
            show_cancel=True,
            submit_label="Submit",
        )

        return self._wrap_card(body, actions)

    def build_section_card(
        self,
        form: FormDefinition,
        section_index: int,
        prefilled: Dict[str, Any] = None,
        errors: Dict[str, str] = None,
        show_back: bool = False,
        show_cancel: bool = True,
        show_skip: bool = False,
    ) -> Dict[str, Any]:
        """
        Build an Adaptive Card for a single form section.

        Used in wizard-style multi-step forms.

        Args:
            form: The form definition
            section_index: Index of the section to render
            prefilled: Pre-filled values
            errors: Validation errors
            show_back: Show back button
            show_cancel: Show cancel button
            show_skip: Show skip button (for optional sections)

        Returns:
            Adaptive Card JSON for this section
        """
        prefilled = prefilled or {}
        errors = errors or {}

        section = form.sections[section_index]
        total_sections = len(form.sections)
        is_last = section_index == total_sections - 1
        body = []
        # Header with form title
        body.append(self._build_header(form.title, size="Medium"))

        # Progress indicator
        if total_sections > 1:
            body.append(self._build_progress_indicator(
                current=section_index + 1,
                total=total_sections,
                section_title=section.title,
            ))

        # Section content
        body.extend(self._build_section_body(section, prefilled, errors))

        # Actions
        actions = self._build_wizard_actions(
            is_first=section_index == 0,
            is_last=is_last,
            show_back=show_back,
            show_cancel=show_cancel,
            show_skip=show_skip and section.allow_skip,
        )

        return self._wrap_card(body, actions)

    def build_summary_card(
        self,
        form: FormDefinition,
        form_data: Dict[str, Any],
        summary_text: str = None,
    ) -> Dict[str, Any]:
        """
        Build a summary/confirmation card showing all submitted data.

        Args:
            form: The form definition
            form_data: All collected form data
            summary_text: Optional LLM-generated summary

        Returns:
            Adaptive Card JSON for confirmation
        """
        body = []

        # Header
        body.append(self._build_header("Confirm Submission", size="Medium"))
        body.append({
            "type": "TextBlock",
            "text": form.title,
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        })

        # LLM Summary if provided
        if summary_text:
            body.append({
                "type": "Container",
                "style": "emphasis",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": summary_text,
                        "wrap": True,
                    }
                ],
                "spacing": "Medium",
            })

        # Data summary as FactSet per section
        for section in form.sections:
            facts = []
            for field in section.fields:
                value = form_data.get(field.name)
                if value is not None:
                    # Format value for display
                    display_value = self._format_value_for_display(field, value)
                    facts.append({
                        "title": f"{field.label}:",
                        "value": display_value,
                    })

            if facts:
                body.append({
                    "type": "TextBlock",
                    "text": section.title,
                    "weight": "Bolder",
                    "spacing": "Medium",
                    "separator": True,
                })
                body.append({
                    "type": "FactSet",
                    "facts": facts,
                })

        # Confirmation actions - include form_data so it's passed with the confirm action
        actions = [
            {
                "type": "Action.Submit",
                "title": "✓ Confirm",
                "style": "positive",
                "data": {"_action": "confirm", **form_data},  # Include all form data
            },
            {
                "type": "Action.Submit",
                "title": "Edit",
                "data": {"_action": "edit", **form_data},  # Include data for editing
            },
            {
                "type": "Action.Submit",
                "title": "Cancel",
                "style": "destructive",
                "data": {"_action": "cancel"},
                "associatedInputs": "none",
            },
        ]

        return self._wrap_card(body, actions)

    def build_error_card(
        self,
        title: str,
        errors: List[str],
        retry_action: bool = True,
    ) -> Dict[str, Any]:
        """
        Build an error display card.

        Args:
            title: Error card title
            errors: List of error messages
            retry_action: Include retry button

        Returns:
            Adaptive Card JSON for error display
        """
        body = [
            {
                "type": "TextBlock",
                "text": "⚠️ " + title,
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
                "text": f"• {error}",
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

        return self._wrap_card(body, actions)

    def build_success_card(
        self,
        title: str,
        message: str = None,
        details: Dict[str, Any] = None,
        dismiss_action: bool = True,
    ) -> Dict[str, Any]:
        """
        Build a success display card.

        Args:
            title: Success card title
            message: Optional success message
            details: Optional dict of result details to display
            dismiss_action: Include dismiss button

        Returns:
            Adaptive Card JSON for success display
        """
        body = [
            {
                "type": "TextBlock",
                "text": "✅ " + title,
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good",
            },
        ]

        if message:
            body.append({
                "type": "TextBlock",
                "text": message,
                "wrap": True,
                "spacing": "Small",
            })

        # Add details as FactSet if provided
        if details:
            facts = []
            for key, value in details.items():
                if value is not None:
                    display_key = key.replace("_", " ").title()
                    facts.append({
                        "title": f"{display_key}:",
                        "value": str(value),
                    })
            if facts:
                body.append({
                    "type": "FactSet",
                    "facts": facts,
                    "spacing": "Medium",
                })

        actions = []
        if dismiss_action:
            actions.append({
                "type": "Action.Submit",
                "title": "OK",
                "data": {"_action": "dismiss"},
            })

        return self._wrap_card(body, actions)

    # =========================================================================
    # Internal Builders
    # =========================================================================

    def _wrap_card(
        self,
        body: List[Dict[str, Any]],
        actions: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Wrap body and actions in complete Adaptive Card structure."""
        card = {
            "type": "AdaptiveCard",
            "$schema": self.SCHEMA_URL,
            "version": self.version,
            "body": body,
        }

        if actions:
            card["actions"] = actions

        return card

    def _build_header(
        self,
        text: str,
        size: str = None,
    ) -> Dict[str, Any]:
        """Build header TextBlock."""
        return {
            "type": "TextBlock",
            "text": text,
            "weight": self.theme.header_weight,
            "size": size or self.theme.header_size,
            "wrap": True,
        }

    def _build_progress_indicator(
        self,
        current: int,
        total: int,
        section_title: str = None,
    ) -> Dict[str, Any]:
        """
        Build a visual progress indicator for wizard steps.

        Shows: [●] [●] [○] [○]  Step 2 of 4: Section Name
        """
        # Build step indicators
        indicators = []
        for i in range(1, total + 1):
            if i < current:
                indicators.append("[✓]")
            elif i == current:
                indicators.append("[●]")
            else:
                indicators.append("[○]")

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
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": progress_text,
                            "fontType": "Monospace",
                            "size": "Small",
                        }
                    ],
                },
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": step_text,
                            "size": "Small",
                            "isSubtle": True,
                            "horizontalAlignment": "Right",
                        }
                    ],
                },
            ],
            "spacing": "Small",
        }

    def _build_section_body(
        self,
        section: FormSection,
        prefilled: Dict[str, Any],
        errors: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Build the body elements for a form section."""
        elements = []

        # Section title (if not already shown in progress)
        if section.title and self.style != CardStyle.COMPACT:
            elements.append({
                "type": "TextBlock",
                "text": section.title,
                "weight": "Bolder",
                "spacing": self.theme.spacing,
            })

        # Section description
        if section.description:
            elements.append({
                "type": "TextBlock",
                "text": section.description,
                "isSubtle": True,
                "wrap": True,
                "spacing": "Small",
            })

        # Fields
        for field in section.fields:
            field_elements = self._build_field(field, prefilled, errors)
            elements.extend(field_elements)

        return elements

    def _build_field(
        self,
        field: FormField,
        prefilled: Dict[str, Any],
        errors: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """
        Build Adaptive Card elements for a single form field.

        Returns a list because some fields need multiple elements
        (label + input + error message).
        """
        elements = []
        value = prefilled.get(field.name, field.default)
        error = errors.get(field.name)

        # Label
        label_text = field.label or field.name.replace("_", " ").title()
        if field.required:
            label_text += " *"

        elements.append({
            "type": "TextBlock",
            "text": label_text,
            "weight": self.theme.label_weight,
            "size": self.theme.label_size,
            "spacing": self.theme.spacing,
        })

        # Description/hint
        if field.description and self.style == CardStyle.DETAILED:
            elements.append({
                "type": "TextBlock",
                "text": field.description,
                "isSubtle": True,
                "size": "Small",
                "wrap": True,
                "spacing": "None",
            })

        # Input element based on field type
        input_element = self._build_input_element(field, value)
        if input_element:
            elements.append(input_element)

        # Error message
        if error:
            elements.append({
                "type": "TextBlock",
                "text": f"⚠️ {error}",
                "color": "Attention",
                "size": "Small",
                "spacing": "None",
            })

        return elements

    def _build_input_element(
        self,
        field: FormField,
        value: Any,
    ) -> Optional[Dict[str, Any]]:
        """Build the appropriate input element for a field type."""

        base_input = {
            "id": field.name,
            "isRequired": field.required,
        }

        # Text-based inputs
        if field.field_type in (FieldType.TEXT, FieldType.EMAIL, FieldType.URL):
            input_elem = {
                **base_input,
                "type": "Input.Text",
                "placeholder": field.placeholder or field.description or "",
                "value": str(value) if value else "",
            }

            # Add style for email/url
            if field.field_type == FieldType.EMAIL:
                input_elem["style"] = "Email"
            elif field.field_type == FieldType.URL:
                input_elem["style"] = "Url"

            # Add validation constraints
            for validation in field.validations:
                if validation.rule == ValidationRule.MAX_LENGTH:
                    input_elem["maxLength"] = validation.value
                elif validation.rule == ValidationRule.PATTERN:
                    input_elem["regex"] = validation.value
                    if validation.message:
                        input_elem["errorMessage"] = validation.message

            return input_elem

        # Textarea (multiline text)
        elif field.field_type == FieldType.TEXTAREA:
            return {
                **base_input,
                "type": "Input.Text",
                "isMultiline": True,
                "placeholder": field.placeholder or "",
                "value": str(value) if value else "",
            }

        # Number input
        elif field.field_type == FieldType.NUMBER:
            input_elem = {
                **base_input,
                "type": "Input.Number",
                "placeholder": field.placeholder or "",
            }
            if value is not None:
                input_elem["value"] = value

            # Min/max from validations
            for validation in field.validations:
                if validation.rule == ValidationRule.MIN_VALUE:
                    input_elem["min"] = validation.value
                elif validation.rule == ValidationRule.MAX_VALUE:
                    input_elem["max"] = validation.value

            return input_elem

        # Date input
        elif field.field_type == FieldType.DATE:
            input_elem = {
                **base_input,
                "type": "Input.Date",
            }
            if value:
                input_elem["value"] = str(value)
            return input_elem

        # DateTime (date + time)
        elif field.field_type == FieldType.DATETIME:
            # Adaptive Cards don't have datetime, use date + time
            # Return just date for now, could expand to ColumnSet
            input_elem = {
                **base_input,
                "type": "Input.Date",
            }
            if value:
                input_elem["value"] = str(value).split("T")[0] if "T" in str(value) else str(value)
            return input_elem

        # Choice (dropdown/radio)
        elif field.field_type == FieldType.CHOICE:
            choices = self._build_choices(field.choices)
            input_elem = {
                **base_input,
                "type": "Input.ChoiceSet",
                "style": "compact",  # dropdown
                "choices": choices,
            }
            if value:
                input_elem["value"] = str(value)
            return input_elem

        # Multi-choice (checkboxes)
        elif field.field_type == FieldType.MULTICHOICE:
            choices = self._build_choices(field.choices)
            input_elem = {
                **base_input,
                "type": "Input.ChoiceSet",
                "isMultiSelect": True,
                "style": "expanded",  # checkboxes
                "choices": choices,
            }
            if value:
                if isinstance(value, list):
                    input_elem["value"] = ",".join(str(v) for v in value)
                else:
                    input_elem["value"] = str(value)
            return input_elem

        # Toggle (boolean)
        elif field.field_type == FieldType.TOGGLE:
            return {
                **base_input,
                "type": "Input.Toggle",
                "title": field.description or field.label or "",
                "value": "true" if value else "false",
                "valueOn": "true",
                "valueOff": "false",
            }

        # Fallback to text
        else:
            return {
                **base_input,
                "type": "Input.Text",
                "placeholder": field.placeholder or "",
                "value": str(value) if value else "",
            }

    def _build_choices(
        self,
        choices: Optional[List[Union[str, Dict[str, str]]]],
    ) -> List[Dict[str, str]]:
        """Build choices array for Input.ChoiceSet."""
        if not choices:
            return []

        result = []
        for choice in choices:
            if isinstance(choice, str):
                result.append({"title": choice, "value": choice})
            elif isinstance(choice, dict):
                result.append({
                    "title": choice.get("title", choice.get("value", "")),
                    "value": choice.get("value", choice.get("title", "")),
                })

        return result

    def _build_form_actions(
        self,
        show_cancel: bool = True,
        submit_label: str = "Submit",
    ) -> List[Dict[str, Any]]:
        """Build action buttons for a complete form."""
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
                "title": "Cancel",
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
    ) -> List[Dict[str, Any]]:
        """Build action buttons for wizard step."""
        actions = []

        # Back button (not on first step)
        if not is_first and show_back:
            actions.append({
                "type": "Action.Submit",
                "title": "← Back",
                "data": {"_action": "back"},
                "associatedInputs": "none",
            })

        # Skip button (optional)
        if show_skip:
            actions.append({
                "type": "Action.Submit",
                "title": "Skip",
                "data": {"_action": "skip"},
                "associatedInputs": "none",
            })

        # Cancel button
        if show_cancel:
            actions.append({
                "type": "Action.Submit",
                "title": "Cancel",
                "style": "destructive",
                "data": {"_action": "cancel"},
                "associatedInputs": "none",
            })

        # Next/Submit button
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
                "title": "Next →",
                "style": "positive",
                "data": {"_action": "next"},
            })

        return actions

    def _format_value_for_display(
        self,
        field: FormField,
        value: Any,
    ) -> str:
        """Format a field value for display in summary."""
        if value is None:
            return "Not provided"

        if field.field_type == FieldType.TOGGLE:
            return "Yes" if value in (True, "true", "True", "1") else "No"

        if field.field_type == FieldType.MULTICHOICE:
            if isinstance(value, str):
                return value.replace(",", ", ")
            elif isinstance(value, list):
                return ", ".join(str(v) for v in value)

        if field.field_type == FieldType.CHOICE and field.choices:
            # Try to get display title for value
            for choice in field.choices:
                if isinstance(choice, dict):
                    if choice.get("value") == value:
                        return choice.get("title", value)

        return str(value)
