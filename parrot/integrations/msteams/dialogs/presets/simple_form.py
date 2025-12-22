"""
Simple Form Dialog - Single Adaptive Card with all fields.
"""
from typing import Any, Callable, Awaitable, Dict, Optional
from botbuilder.dialogs import (
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus,
)
from botbuilder.core import TurnContext
from .base import BaseFormDialog
from ....dialogs.models import FormDefinition
from ..card_builder import AdaptiveCardBuilder
from ..validator import FormValidator


class SimpleFormDialog(BaseFormDialog):
    """
    Single Adaptive Card containing all form fields.

    Best for:
    - Forms with 5 or fewer fields
    - Quick data collection
    - Simple workflows

    Flow:
    1. Show complete form
    2. User fills and submits
    3. Validate → show errors OR complete
    """

    def __init__(
        self,
        form: FormDefinition,
        card_builder: AdaptiveCardBuilder = None,
        validator: FormValidator = None,
        on_complete: Callable[[Dict[str, Any], TurnContext], Awaitable[Any]] = None,
        on_cancel: Callable[[TurnContext], Awaitable[Any]] = None,
    ):
        super().__init__(
            form=form,
            card_builder=card_builder,
            validator=validator,
            on_complete=on_complete,
            on_cancel=on_cancel,
        )

        # Define waterfall steps
        self.add_dialog(
            WaterfallDialog(
                f"{self.form.form_id}_waterfall",
                [
                    self.show_form_step,
                    self.process_submission_step,
                ]
            )
        )

        self.initial_dialog_id = f"{self.form.form_id}_waterfall"

    async def show_form_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Show the complete form as a single Adaptive Card."""
        prefilled = self.get_form_data(step_context)
        errors = self.get_validation_errors(step_context)

        card = self.card_builder.build_complete_form(
            form=self.form,
            prefilled=prefilled,
            errors=errors,
        )

        await self.send_card(step_context, card)

        # Clear errors after display
        self.set_validation_errors(step_context, None)

        # Wait for user submission
        return DialogTurnResult(DialogTurnStatus.Waiting)

    async def process_submission_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Process the submitted form data."""
        submitted = step_context.context.activity.value

        if not submitted:
            # No data - might be timeout or error
            return await step_context.end_dialog()

        # Check for cancel
        action = submitted.get('_action')
        if action == 'cancel':
            return await self.handle_cancel(step_context)

        # Merge data
        form_data = self.merge_submitted_data(step_context, submitted)

        # Validate
        validation = self.validator.validate_form_data(form_data, self.form)

        if not validation.is_valid:
            # Store errors and re-show form
            self.set_validation_errors(step_context, validation.errors)
            return await step_context.replace_dialog(self.id)

        # Complete
        return await self.handle_complete(step_context, validation.sanitized_data)
