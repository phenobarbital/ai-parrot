"""
Wizard Form Dialog - Multi-step form with navigation.
"""
from typing import Any, Callable, Awaitable, Dict, List
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


class WizardFormDialog(BaseFormDialog):
    """
    Multi-step wizard dialog with one section per step.

    Features:
    - Progress indicator
    - Back/Next navigation
    - Per-section validation
    - Skip optional sections

    Flow:
    1. Show Section 1
    2. User fills → validates → Next
    3. Show Section 2
    4. ... repeat ...
    5. Final section → Submit
    """

    def __init__(
        self,
        form: FormDefinition,
        dialog_id: str = None,
        **kwargs,  # Accept but ignore extra kwargs for backwards compatibility
    ):
        super().__init__(form=form, dialog_id=dialog_id)

        # Build waterfall steps dynamically
        steps = self._build_steps()

        self.add_dialog(
            WaterfallDialog(
                f"{self.form.form_id}_waterfall",
                steps,
            )
        )

        self.initial_dialog_id = f"{self.form.form_id}_waterfall"

    def _build_steps(self) -> List[Callable]:
        """Build list of waterfall step functions."""
        steps = []

        # One step per section
        for i in range(len(self.form.sections)):
            steps.append(self._create_section_step(i))

        # Final processing step
        steps.append(self.final_step)

        return steps

    def _create_section_step(self, section_index: int) -> Callable:
        """
        Factory to create a step function for a specific section.

        This uses closure to capture section_index.
        """
        async def section_step(
            step_context: WaterfallStepContext,
        ) -> DialogTurnResult:
            return await self._handle_section(step_context, section_index)

        # Give the function a meaningful name for debugging
        section_step.__name__ = f"section_{section_index}_step"

        return section_step

    async def _handle_section(
        self,
        step_context: WaterfallStepContext,
        section_index: int,
    ) -> DialogTurnResult:
        """Handle a single section step."""

        # Process any submitted data from previous step
        submitted = step_context.context.activity.value

        if submitted:
            action = submitted.get('_action')

            # Handle navigation actions
            if action == 'cancel':
                return await self.handle_cancel(step_context)

            if action == 'back' and section_index > 0:
                # Go back: show previous section's card
                prev_index = section_index - 1
                self.set_current_section(step_context, prev_index)
                await self.send_section_card(
                    step_context,
                    section_index=prev_index,
                    show_back=prev_index > 0,
                )
                return DialogTurnResult(DialogTurnStatus.Waiting)

            if action == 'skip':
                # Skip this section, continue to next
                return await step_context.next(None)

            # Process submitted data (next or submit action)
            form_data = self.merge_submitted_data(step_context, submitted)

            # Validate previous section (the one that was just submitted)
            if section_index > 0:
                prev_section = self.form.sections[section_index - 1]
                validation = self._get_validator().validate_section(form_data, prev_section)

                if not validation.is_valid:
                    # Show previous section with errors (don't use replace_dialog)
                    prev_index = section_index - 1
                    self.set_current_section(step_context, prev_index)
                    await self.send_section_card(
                        step_context,
                        section_index=prev_index,
                        show_back=prev_index > 0,
                    )
                    return DialogTurnResult(DialogTurnStatus.Waiting)

            # If we have submitted data and it's validated, advance to next step
            # (This means user clicked Next/Submit on a previous card)
            if action in ('next', 'submit'):
                return await step_context.next(None)

        # First time showing this section (or after validation failure)
        # Record current section
        self.set_current_section(step_context, section_index)

        # Show this section's card
        await self.send_section_card(
            step_context,
            section_index=section_index,
            show_back=section_index > 0,
        )

        return DialogTurnResult(DialogTurnStatus.Waiting)

    async def final_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Final step: validate last section and complete."""

        # Process last section's submission
        submitted = step_context.context.activity.value

        if submitted:
            action = submitted.get('_action')

            if action == 'cancel':
                return await self.handle_cancel(step_context)

            if action == 'back':
                # Go back to last section
                last_index = len(self.form.sections) - 1
                self.set_current_section(step_context, last_index)
                await self.send_section_card(
                    step_context,
                    section_index=last_index,
                    show_back=last_index > 0,
                )
                return DialogTurnResult(DialogTurnStatus.Waiting)

            # Merge final data
            form_data = self.merge_submitted_data(step_context, submitted)

            # Validate last section
            last_section = self.form.sections[-1]
            validation = self._get_validator().validate_section(form_data, last_section)

            if not validation.is_valid:
                # Show last section with errors
                last_index = len(self.form.sections) - 1
                self.set_current_section(step_context, last_index)
                await self.send_section_card(
                    step_context,
                    section_index=last_index,
                    show_back=last_index > 0,
                )
                return DialogTurnResult(DialogTurnStatus.Waiting)
        else:
            form_data = self.get_form_data(step_context)

        # Complete the form
        return await self.handle_complete(step_context, form_data)
