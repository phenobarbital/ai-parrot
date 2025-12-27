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

    # Key for storing agent in turn_state (ephemeral per-turn)
    AGENT_TURNSTATE_KEY = "FormDialog.agent"

    def __init__(
        self,
        form: FormDefinition,
        dialog_id: str = None,
        **kwargs,  # Accept but ignore extra kwargs for backwards compatibility
    ):
        # NOTE: Don't store agent on self to avoid serialization issues
        # The wrapper should set it in turn_state before continuing dialog
        super().__init__(form=form, dialog_id=dialog_id)

    def _get_agent(self, step_context) -> Optional['AbstractBot']:
        """Get agent from turn_state (set by wrapper per-turn)."""
        return step_context.context.turn_state.get(self.AGENT_TURNSTATE_KEY)

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
                # Go back to last section
                last_index = len(self.form.sections) - 1
                self.set_current_section(step_context, last_index)
                await self.send_section_card(
                    step_context,
                    section_index=last_index,
                    show_back=last_index > 0,
                )
                return DialogTurnResult(DialogTurnStatus.Waiting)

            # Merge final section data
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

        # Generate summary
        summary_text = None
        agent = self._get_agent(step_context)
        if self.form.llm_summary and agent:
            summary_text = await self._generate_llm_summary(form_data, agent)

        # Build and send summary card
        card = self._get_card_builder().build_summary_card(
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
            self.set_current_section(step_context, 0)
            await self.send_section_card(
                step_context,
                section_index=0,
                show_back=False,
            )
            return DialogTurnResult(DialogTurnStatus.Waiting)

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
        agent = self._get_agent(step_context)
        if self.form.llm_validation and agent:
            validation_result = await self._llm_validate(form_data, agent)
            if not validation_result['valid']:
                await step_context.context.send_activity(
                    MessageFactory.text(
                        f"⚠️ {validation_result.get('message', 'Validation failed')}"
                    )
                )
                # Show first section to re-edit
                self.set_current_section(step_context, 0)
                await self.send_section_card(
                    step_context,
                    section_index=0,
                    show_back=False,
                )
                return DialogTurnResult(DialogTurnStatus.Waiting)

        return await self.handle_complete(step_context, form_data)

    async def _generate_llm_summary(
        self,
        form_data: Dict[str, Any],
        agent: 'AbstractBot',
    ) -> str:
        """Generate a human-readable summary using LLM."""
        if not agent:
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
            response = await agent.ask(prompt)
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
                    display = self._get_card_builder()._format_value_for_display(field, value)
                    section_values.append(f"{field.label}: {display}")

            if section_values:
                lines.append(f"**{section.title}**: " + ", ".join(section_values))

        return "\n".join(lines)

    async def _llm_validate(
        self,
        form_data: Dict[str, Any],
        agent: 'AbstractBot',
    ) -> Dict[str, Any]:
        """Use LLM to validate form data."""
        if not agent:
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
            response = await agent.ask(prompt)
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
