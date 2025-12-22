"""
Base Form Dialog with common functionality.
"""
from typing import Any, Callable, Awaitable, Dict, Optional, TYPE_CHECKING
from botbuilder.dialogs import (
    ComponentDialog,
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus,
)
from botbuilder.dialogs.prompts import TextPrompt, ChoicePrompt, ConfirmPrompt
from botbuilder.core import MessageFactory, CardFactory, TurnContext
from ....dialogs.models import FormDefinition
from ..card_builder import AdaptiveCardBuilder
from ..validator import FormValidator


# Turn state keys
FORM_DATA_KEY = "FormDialog.data"
CURRENT_SECTION_KEY = "FormDialog.section_index"
VALIDATION_ERRORS_KEY = "FormDialog.errors"
FORM_DEFINITION_KEY = "FormDialog.form"


class BaseFormDialog(ComponentDialog):
    """
    Base class for all form dialog presets.

    Provides:
    - State management helpers
    - Common prompt dialogs
    - Card building/sending utilities
    - Validation integration
    """

    def __init__(
        self,
        form: FormDefinition,
        card_builder: AdaptiveCardBuilder = None,
        validator: FormValidator = None,
        on_complete: Callable[[Dict[str, Any], TurnContext], Awaitable[Any]] = None,
        on_cancel: Callable[[TurnContext], Awaitable[Any]] = None,
        dialog_id: str = None,
    ):
        super().__init__(dialog_id or form.form_id)

        self.form = form
        self.card_builder = card_builder or AdaptiveCardBuilder()
        self.validator = validator or FormValidator()
        self.on_complete = on_complete
        self.on_cancel = on_cancel

        # Add standard prompts
        self.add_dialog(TextPrompt("TextPrompt"))
        self.add_dialog(ChoicePrompt("ChoicePrompt"))
        self.add_dialog(ConfirmPrompt("ConfirmPrompt"))

    # =========================================================================
    # State Management
    # =========================================================================

    def get_form_data(self, step_context: WaterfallStepContext) -> Dict[str, Any]:
        """Get accumulated form data from turn_state."""
        return step_context.context.turn_state.get(FORM_DATA_KEY, {})

    def set_form_data(
        self,
        step_context: WaterfallStepContext,
        data: Dict[str, Any],
    ):
        """Store form data in turn_state."""
        step_context.context.turn_state[FORM_DATA_KEY] = data

    def get_current_section(self, step_context: WaterfallStepContext) -> int:
        """Get current section index."""
        return step_context.context.turn_state.get(CURRENT_SECTION_KEY, 0)

    def set_current_section(
        self,
        step_context: WaterfallStepContext,
        index: int,
    ):
        """Set current section index."""
        step_context.context.turn_state[CURRENT_SECTION_KEY] = index

    def get_validation_errors(
        self,
        step_context: WaterfallStepContext,
    ) -> Optional[Dict[str, str]]:
        """Get validation errors from previous step."""
        return step_context.context.turn_state.get(VALIDATION_ERRORS_KEY)

    def set_validation_errors(
        self,
        step_context: WaterfallStepContext,
        errors: Optional[Dict[str, str]],
    ):
        """Store validation errors for display."""
        step_context.context.turn_state[VALIDATION_ERRORS_KEY] = errors

    def merge_submitted_data(
        self,
        step_context: WaterfallStepContext,
        submitted: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge submitted values with existing form data.

        Filters out internal keys (prefixed with _).
        """
        form_data = self.get_form_data(step_context)

        for key, value in submitted.items():
            if not key.startswith('_'):
                form_data[key] = value

        self.set_form_data(step_context, form_data)
        return form_data

    # =========================================================================
    # Card Utilities
    # =========================================================================

    async def send_card(
        self,
        step_context: WaterfallStepContext,
        card: Dict[str, Any],
    ):
        """Send an Adaptive Card, validating first."""
        # Validate and sanitize
        if not self.validator.validate_adaptive_card(card):
            card = self.validator.sanitize_card(card)

        attachment = CardFactory.adaptive_card(card)
        message = MessageFactory.attachment(attachment)
        await step_context.context.send_activity(message)

    async def send_section_card(
        self,
        step_context: WaterfallStepContext,
        section_index: int,
        show_back: bool = False,
    ):
        """Build and send card for a section."""
        prefilled = self.get_form_data(step_context)
        errors = self.get_validation_errors(step_context)

        card = self.card_builder.build_section_card(
            form=self.form,
            section_index=section_index,
            prefilled=prefilled,
            errors=errors,
            show_back=show_back,
            show_cancel=True,
            show_skip=self.form.sections[section_index].allow_skip,
        )

        await self.send_card(step_context, card)

        # Clear errors after display
        self.set_validation_errors(step_context, None)

    # =========================================================================
    # Action Handlers
    # =========================================================================

    def get_submitted_action(
        self,
        step_context: WaterfallStepContext,
    ) -> Optional[str]:
        """Get the action from submitted data."""
        submitted = step_context.context.activity.value
        return submitted.get('_action') if submitted else None

    async def handle_cancel(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Handle cancel action."""
        if self.on_cancel:
            await self.on_cancel(step_context.context)

        await step_context.context.send_activity(
            MessageFactory.text("Form cancelled.")
        )

        return await step_context.end_dialog({"_cancelled": True})

    async def handle_complete(
        self,
        step_context: WaterfallStepContext,
        form_data: Dict[str, Any],
    ) -> DialogTurnResult:
        """Handle form completion."""
        # Validate all data
        validation = self.validator.validate_form_data(form_data, self.form)

        if not validation.is_valid:
            # Show errors
            error_card = self.card_builder.build_error_card(
                title="Validation Errors",
                errors=validation.error_list,
            )
            await self.send_card(step_context, error_card)
            return await step_context.replace_dialog(self.id)

        # Call completion callback
        if self.on_complete:
            await self.on_complete(validation.sanitized_data, step_context.context)

        return await step_context.end_dialog(validation.sanitized_data)
