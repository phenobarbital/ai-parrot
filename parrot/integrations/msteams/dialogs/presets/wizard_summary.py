"""
Wizard with Summary Dialog - Multi-step form with confirmation.
"""
from typing import Any, Callable, Awaitable, Dict, List, Optional, TYPE_CHECKING
from botbuilder.dialogs import (
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus,
)
from botbuilder.core import TurnContext, MessageFactory

from .wizard import WizardFormDialog
from ....dialogs.models import FormDefinition
from ..card_builder import AdaptiveCardBuilder
from ..validator import FormValidator

if TYPE_CHECKING:
    from ....bots.abstract import AbstractBot


class WizardWithSummaryDialog(WizardFormDialog):
    """
    Multi-step wizard with a final summary/confirmation step.

    Features:
    - All wizard features
    - Summary card before final submit
    - Optional LLM-generated summary
    - Edit option to go back

    Flow:
    1. Section 1 → Section 2 → ... → Section N
    2. Summary/Confirmation card
    3. User confirms → Complete OR User edits → Back to step 1
    """

    def __init__(
        self,
        form: FormDefinition,
        card_builder: AdaptiveCardBuilder = None,
        validator: FormValidator = None,
        on_complete: Callable[[Dict[str, Any], TurnContext], Awaitable[Any]] = None,
        on_cancel: Callable[[TurnContext], Awaitable[Any]] = None,
        agent: Optional['AbstractBot'] = None,
    ):
        # Store agent before calling super().__init__
        self.agent = agent

        super().__init__(
            form=form,
            card_builder=card_builder,
            validator=validator,
            on_complete=on_complete,
            on_cancel=on_cancel,
        )

    def _build_steps(self) -> List[Callable]:
        """Build steps including summary and confirmation."""
        steps = []

        # Section steps
        for i in range(len(self.form.sections)):
            steps.append(self._create_section_step(i))

        # Summary step
        steps.append(self.summary_step)

        # Confirmation step
        steps.append(self.confirmation_step)

        return steps

    async def summary_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Show summary of all collected data."""

        # Process last section's data
        submitted = step_context.context.activity.value

        if submitted:
            action = submitted.get('_action')

            if action == 'cancel':
                return await self.handle_cancel(step_context)

            if action == 'back':
                return await step_context.replace_dialog(self.id)

            # Merge final section data
            form_data = self.merge_submitted_data(step_context, submitted)

            # Validate last section
            last_section = self.form.sections[-1]
            validation = self.validator.validate_section(form_data, last_section)

            if not validation.is_valid:
                self.set_validation_errors(step_context, validation.errors)
                return await step_context.replace_dialog(self.id)
        else:
            form_data = self.get_form_data(step_context)

        # Generate summary
        summary_text = None
        if self.form.llm_summary and self.agent:
            summary_text = await self._generate_llm_summary(form_data)

        # Build and send summary card
        card = self.card_builder.build_summary_card(
            form=self.form,
            form_data=form_data,
            summary_text=summary_text,
        )

        await self.send_card(step_context, card)

        return DialogTurnResult(DialogTurnStatus.Waiting)

    async def confirmation_step(
        self,
        step_context: WaterfallStepContext,
    ) -> DialogTurnResult:
        """Process confirmation response."""

        submitted = step_context.context.activity.value
        action = submitted.get('_action', 'confirm') if submitted else 'confirm'

        if action == 'edit':
            # Go back to first section
            return await step_context.replace_dialog(self.id)

        if action == 'cancel':
            return await self.handle_cancel(step_context)

        # Confirmed - get form data from submitted values (included in the confirm button)
        # The form_data is now embedded in the confirm action's data
        if submitted:
            # Extract form data from submitted (exclude _action key)
            form_data = {k: v for k, v in submitted.items() if not k.startswith('_')}
            # Merge with any existing state data for safety
            existing_data = self.get_form_data(step_context)
            form_data = {**existing_data, **form_data}
        else:
            form_data = self.get_form_data(step_context)

        # Optional: LLM validation before final submit
        if self.form.llm_validation and self.agent:
            validation_result = await self._llm_validate(form_data)
            if not validation_result['valid']:
                await step_context.context.send_activity(
                    MessageFactory.text(
                        f"⚠️ {validation_result.get('message', 'Validation failed')}"
                    )
                )
                return await step_context.replace_dialog(self.id)

        return await self.handle_complete(step_context, form_data)

    async def _generate_llm_summary(
        self,
        form_data: Dict[str, Any],
    ) -> str:
        """Generate a human-readable summary using LLM."""
        if not self.agent:
            return self._generate_simple_summary(form_data)

        # Build field descriptions for context
        field_descriptions = []
        for section in self.form.sections:
            for field in section.fields:
                value = form_data.get(field.name)
                if value is not None:
                    field_descriptions.append(
                        f"- {field.label or field.name}: {value}"
                    )

        prompt = f"""
Generate a brief, friendly 2-3 sentence summary of this form submission.
Be concise and focus on the key information.

Form: {self.form.title}

Submitted data:
{chr(10).join(field_descriptions)}

Summary:"""

        try:
            response = await self.agent.ask(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            return content.strip()
        except Exception as e:
            # Fallback to simple summary
            return self._generate_simple_summary(form_data)

    def _generate_simple_summary(
        self,
        form_data: Dict[str, Any],
    ) -> str:
        """Generate simple bullet-point summary."""
        lines = []

        for section in self.form.sections:
            section_values = []
            for field in section.fields:
                value = form_data.get(field.name)
                if value is not None:
                    display = self.card_builder._format_value_for_display(field, value)
                    section_values.append(f"{field.label}: {display}")

            if section_values:
                lines.append(f"**{section.title}**: " + ", ".join(section_values))

        return "\n".join(lines)

    async def _llm_validate(
        self,
        form_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Use LLM to validate form data."""
        if not self.agent:
            return {'valid': True}

        prompt = f"""
Validate this form submission for the "{self.form.title}" form.
Check for:
1. Logical consistency (e.g., end date after start date)
2. Reasonable values
3. Any potential issues

Form data:
{form_data}

Respond with JSON:
{{"valid": true/false, "message": "explanation if invalid"}}
"""

        try:
            response = await self.agent.ask(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Try to parse JSON from response
            import json
            # Find JSON in response
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])

            # Default to valid if can't parse
            return {'valid': True}

        except Exception:
            # Fail open - don't block on LLM errors
            return {'valid': True}
