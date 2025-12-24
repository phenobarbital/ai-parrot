"""
Conversational Form Dialog - One prompt per field, text-based interaction.

Uses BotBuilder's native prompts instead of Adaptive Cards.
Useful for:
- More natural conversation flow
- Channels with limited Adaptive Card support
- Complex fields requiring contextual help
- Accessibility considerations
"""
from typing import Any, Callable, Awaitable, Dict, List, Optional
from botbuilder.dialogs import (
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus,
)
from botbuilder.dialogs.prompts import (
    TextPrompt,
    NumberPrompt,
    ConfirmPrompt,
    ChoicePrompt,
    DateTimePrompt,
    PromptOptions,
    PromptValidatorContext,
)
from botbuilder.dialogs.choices import Choice, FoundChoice
from botbuilder.core import TurnContext, MessageFactory
from .base import BaseFormDialog
from ....dialogs.models import (
    FormDefinition,
    FormField,
    FieldType,
    ValidationRule,
)
from ..validator import FormValidator


class ConversationalFormDialog(BaseFormDialog):
    """
    Conversational form using native BotBuilder prompts.

    Each field becomes a separate prompt in the waterfall.
    Supports:
    - TextPrompt for text fields
    - NumberPrompt for numeric fields
    - ChoicePrompt for single choice
    - ConfirmPrompt for boolean/toggle
    - DateTimePrompt for dates

    Features:
    - Field-level validation with retry
    - Contextual help messages
    - Skip optional fields
    - Back navigation (restart)

    Flow:
    1. "What is your first name?"
    2. User types: "John"
    3. "What is your email?"
    4. User types: "john@example.com"
    5. ... continues for each field ...
    6. "All done! Here's your summary..."
    """

    def __init__(
        self,
        form: FormDefinition,
        dialog_id: str = None,
        show_progress: bool = True,
        allow_skip_optional: bool = True,
        **kwargs,  # Accept but ignore extra kwargs for backwards compatibility
    ):
        super().__init__(form=form, dialog_id=dialog_id)

        self.show_progress = show_progress
        self.allow_skip_optional = allow_skip_optional

        # Flatten all fields from all sections
        self._fields: List[FormField] = []
        for section in form.sections:
            self._fields.extend(section.fields)

        # Register prompts with validators
        self._register_prompts()

        # Build waterfall steps
        steps = self._build_steps()

        self.add_dialog(
            WaterfallDialog(
                f"{self.form.form_id}_waterfall",
                steps,
            )
        )

        self.initial_dialog_id = f"{self.form.form_id}_waterfall"

    def _register_prompts(self):
        """Register prompt dialogs for each field type."""
        # Text prompt with validation
        self.add_dialog(
            TextPrompt(
                "TextPrompt",
                self._text_validator,
            )
        )

        # Number prompt
        self.add_dialog(
            NumberPrompt(
                "NumberPrompt",
                self._number_validator,
            )
        )

        # Choice prompt
        self.add_dialog(ChoicePrompt("ChoicePrompt"))

        # Confirm prompt (for toggles/booleans)
        self.add_dialog(ConfirmPrompt("ConfirmPrompt"))

        # DateTime prompt
        self.add_dialog(DateTimePrompt("DateTimePrompt"))

        # Email-specific text prompt
        self.add_dialog(
            TextPrompt(
                "EmailPrompt",
                self._email_validator,
            )
        )

        # URL-specific text prompt
        self.add_dialog(
            TextPrompt(
                "UrlPrompt",
                self._url_validator,
            )
        )

    def _build_steps(self) -> List[Callable]:
        """Build waterfall steps: intro + one per field + summary."""
        steps = []

        # Introduction step
        steps.append(self.intro_step)

        # One step per field
        for i, field in enumerate(self._fields):
            steps.append(self._create_field_prompt_step(i))
            steps.append(self._create_field_process_step(i))

        # Summary/completion step
        steps.append(self.summary_step)

        return steps

    # =========================================================================
    # Waterfall Steps
    # =========================================================================

    async def intro_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Introduction step with form title and instructions."""

        intro_message = (
            f"📋 **{self.form.title}**\n\n"
            f"I'll ask you a few questions to collect the information needed. "
        )

        if self.allow_skip_optional:
            intro_message += "Type 'skip' to skip optional fields. "

        intro_message += "Type 'cancel' at any time to stop.\n"

        await step_context.context.send_activity(
            MessageFactory.text(intro_message)
        )

        return await step_context.next(None)

    def _create_field_prompt_step(self, field_index: int) -> Callable:
        """Create step that prompts for a field."""

        async def prompt_step(
            step_context: WaterfallStepContext,
        ) -> DialogTurnResult:
            field = self._fields[field_index]

            # Build prompt message
            prompt_text = self._build_prompt_message(field, field_index)

            # Get appropriate prompt type and options
            prompt_type, options = self._get_prompt_config(field, prompt_text)

            return await step_context.prompt(prompt_type, options)

        prompt_step.__name__ = f"prompt_{field_index}"
        return prompt_step

    def _create_field_process_step(self, field_index: int) -> Callable:
        """Create step that processes field response."""

        async def process_step(
            step_context: WaterfallStepContext,
        ) -> DialogTurnResult:
            field = self._fields[field_index]
            result = step_context.result

            # Check for cancel
            if isinstance(result, str) and result.lower() == 'cancel':
                return await self.handle_cancel(step_context)

            # Check for skip (optional fields only)
            if isinstance(result, str) and result.lower() == 'skip':
                if not field.required and self.allow_skip_optional:
                    await step_context.context.send_activity(
                        MessageFactory.text(f"Skipped {field.label or field.name}.")
                    )
                    return await step_context.next(None)
                else:
                    await step_context.context.send_activity(
                        MessageFactory.text(
                            f"⚠️ {field.label or field.name} is required and cannot be skipped."
                        )
                    )
                    # Re-prompt
                    return await step_context.replace_dialog(self.id)

            # Process and store the value
            processed_value = self._process_result(result, field)

            form_data = self.get_form_data(step_context)
            form_data[field.name] = processed_value
            self.set_form_data(step_context, form_data)

            # Acknowledge (optional, can be verbose)
            if field.field_type == FieldType.TOGGLE:
                ack = "Yes" if processed_value else "No"
            else:
                ack = str(processed_value)

            # Only show for certain types to avoid clutter
            if field.field_type in (FieldType.CHOICE, FieldType.TOGGLE):
                await step_context.context.send_activity(
                    MessageFactory.text(f"✓ {field.label}: {ack}")
                )

            return await step_context.next(processed_value)

        process_step.__name__ = f"process_{field_index}"
        return process_step

    async def summary_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Show summary and complete."""

        form_data = self.get_form_data(step_context)

        # Build summary message
        summary = self._build_summary_message(form_data)

        await step_context.context.send_activity(
            MessageFactory.text(summary)
        )

        # Complete the form
        return await self.handle_complete(step_context, form_data)

    # =========================================================================
    # Prompt Configuration
    # =========================================================================

    def _build_prompt_message(
        self,
        field: FormField,
        field_index: int,
    ) -> str:
        """Build the prompt message for a field."""
        parts = []

        # Progress indicator
        if self.show_progress:
            total = len(self._fields)
            parts.append(f"({field_index + 1}/{total})")

        # Field label/question
        label = field.label or field.name.replace("_", " ").title()

        if field.required:
            parts.append(f"**{label}** (required)")
        else:
            parts.append(f"**{label}** (optional)")

        prompt = " ".join(parts)

        # Add description as hint
        if field.description:
            prompt += f"\n_{field.description}_"

        # Add placeholder as example
        if field.placeholder:
            prompt += f"\n_Example: {field.placeholder}_"

        return prompt

    def _get_prompt_config(
        self,
        field: FormField,
        prompt_text: str,
    ) -> tuple:
        """Get prompt type and options for a field."""

        field_type = field.field_type

        # Text-based fields
        if field_type == FieldType.TEXT:
            return "TextPrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
                retry_prompt=MessageFactory.text(
                    f"Please enter a valid value for {field.label or field.name}."
                ),
            )

        elif field_type == FieldType.TEXTAREA:
            return "TextPrompt", PromptOptions(
                prompt=MessageFactory.text(
                    f"{prompt_text}\n(You can write multiple lines)"
                ),
            )

        elif field_type == FieldType.EMAIL:
            return "EmailPrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
                retry_prompt=MessageFactory.text(
                    "Please enter a valid email address (e.g., name@example.com)."
                ),
            )

        elif field_type == FieldType.URL:
            return "UrlPrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
                retry_prompt=MessageFactory.text(
                    "Please enter a valid URL (e.g., https://example.com)."
                ),
            )

        # Number field
        elif field_type == FieldType.NUMBER:
            return "NumberPrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
                retry_prompt=MessageFactory.text(
                    "Please enter a valid number."
                ),
            )

        # Date fields
        elif field_type in (FieldType.DATE, FieldType.DATETIME):
            return "DateTimePrompt", PromptOptions(
                prompt=MessageFactory.text(
                    f"{prompt_text}\n(e.g., tomorrow, next Monday, 2025-01-15)"
                ),
                retry_prompt=MessageFactory.text(
                    "I couldn't understand that date. Try something like 'next Friday' or '2025-01-15'."
                ),
            )

        # Single choice
        elif field_type == FieldType.CHOICE:
            choices = self._build_choices_list(field.choices)
            return "ChoicePrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
                choices=choices,
                retry_prompt=MessageFactory.text(
                    f"Please choose one of the options: {', '.join(c.value for c in choices)}"
                ),
            )

        # Multi-choice (use text prompt, parse manually)
        elif field_type == FieldType.MULTICHOICE:
            options_text = ", ".join(self._extract_choice_values(field.choices))
            return "TextPrompt", PromptOptions(
                prompt=MessageFactory.text(
                    f"{prompt_text}\nOptions: {options_text}\n(Enter choices separated by commas)"
                ),
            )

        # Toggle/Boolean
        elif field_type == FieldType.TOGGLE:
            return "ConfirmPrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
            )

        # Default to text
        else:
            return "TextPrompt", PromptOptions(
                prompt=MessageFactory.text(prompt_text),
            )

    def _build_choices_list(
        self,
        choices: Optional[List],
    ) -> List[Choice]:
        """Build Choice objects for ChoicePrompt."""
        if not choices:
            return []

        result = []
        for choice in choices:
            if isinstance(choice, str):
                result.append(Choice(value=choice))
            elif isinstance(choice, dict):
                result.append(Choice(
                    value=choice.get("value", choice.get("title", "")),
                    action=None,
                    synonyms=[choice.get("title")] if choice.get("title") != choice.get("value") else None,
                ))

        return result

    def _extract_choice_values(
        self,
        choices: Optional[List],
    ) -> List[str]:
        """Extract string values from choices."""
        if not choices:
            return []

        values = []
        for choice in choices:
            if isinstance(choice, str):
                values.append(choice)
            elif isinstance(choice, dict):
                values.append(choice.get("value", choice.get("title", "")))

        return values

    def _process_result(
        self,
        result: Any,
        field: FormField,
    ) -> Any:
        """Process prompt result into storage format."""

        # ChoicePrompt returns FoundChoice
        if isinstance(result, FoundChoice):
            return result.value

        # ConfirmPrompt returns bool
        if isinstance(result, bool):
            return result

        # DateTimePrompt returns list of resolutions
        if isinstance(result, list) and result:
            if hasattr(result[0], 'value'):
                return result[0].value
            return result[0]

        # Multi-choice: parse comma-separated
        if field.field_type == FieldType.MULTICHOICE and isinstance(result, str):
            return [v.strip() for v in result.split(',') if v.strip()]

        return result

    # =========================================================================
    # Validators
    # =========================================================================

    async def _text_validator(
        self,
        prompt_context: PromptValidatorContext,
    ) -> bool:
        """Validate text input."""
        value = prompt_context.recognized.value

        if not value or not value.strip():
            return False

        # Allow cancel/skip commands
        if value.lower() in ('cancel', 'skip'):
            return True

        return True

    async def _email_validator(
        self,
        prompt_context: PromptValidatorContext,
    ) -> bool:
        """Validate email input."""
        import re

        value = prompt_context.recognized.value

        if not value:
            return False

        # Allow cancel/skip
        if value.lower() in ('cancel', 'skip'):
            return True

        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, value.strip()))

    async def _url_validator(
        self,
        prompt_context: PromptValidatorContext,
    ) -> bool:
        """Validate URL input."""
        import re

        value = prompt_context.recognized.value

        if not value:
            return False

        # Allow cancel/skip
        if value.lower() in ('cancel', 'skip'):
            return True

        pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return bool(re.match(pattern, value.strip()))

    async def _number_validator(
        self,
        prompt_context: PromptValidatorContext,
    ) -> bool:
        """Validate number input."""
        # NumberPrompt already validates, just ensure it succeeded
        return prompt_context.recognized.succeeded

    # =========================================================================
    # Summary
    # =========================================================================

    def _build_summary_message(
        self,
        form_data: Dict[str, Any],
    ) -> str:
        """Build a text summary of collected data."""
        lines = [
            f"✅ **{self.form.title} - Complete**",
            "",
            "Here's what you submitted:",
            "",
        ]

        for section in self.form.sections:
            lines.append(f"**{section.title}**")

            for field in section.fields:
                value = form_data.get(field.name)

                if value is None:
                    display = "_skipped_"
                elif isinstance(value, bool):
                    display = "Yes" if value else "No"
                elif isinstance(value, list):
                    display = ", ".join(str(v) for v in value)
                else:
                    display = str(value)

                lines.append(f"• {field.label or field.name}: {display}")

            lines.append("")

        return "\n".join(lines)
