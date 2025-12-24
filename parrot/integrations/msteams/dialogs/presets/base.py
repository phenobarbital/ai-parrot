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


# Global form registry to avoid storing complex FormDefinition on dialog instances
# This is used for runtime lookup - dialogs store only form_id (a string) which is serializable
_FORM_REGISTRY: Dict[str, FormDefinition] = {}


def register_form(form: FormDefinition) -> None:
    """Register a form in the global registry for later lookup."""
    _FORM_REGISTRY[form.form_id] = form


def get_registered_form(form_id: str) -> Optional[FormDefinition]:
    """Get a form from the global registry."""
    return _FORM_REGISTRY.get(form_id)


class BaseFormDialog(ComponentDialog):
    """
    Base class for all form dialog presets.

    Provides:
    - State management helpers (via step_context.values)
    - Common prompt dialogs
    - Card building/sending utilities (via _get_card_builder())
    - Validation integration (via _get_validator())

    NOTE: This dialog stores ONLY the form_id (a string) to avoid jsonpickle
    serialization issues. Complex objects are accessed via:
    - form: looked up from registry via form_id
    - card_builder/validator: created fresh per-use
    - agent: accessed from turn_state
    - callbacks: handled by wrapper after dialog ends
    """

    def __init__(
        self,
        form: FormDefinition,
        dialog_id: str = None,
        **kwargs,  # Accept but ignore extra kwargs for backwards compatibility
    ):
        super().__init__(dialog_id or form.form_id)

        # Store ONLY the form_id (a simple string) to avoid serialization issues
        # The full FormDefinition is registered and looked up at runtime
        self._form_id = form.form_id
        register_form(form)

        # Add standard prompts
        self.add_dialog(TextPrompt("TextPrompt"))
        self.add_dialog(ChoicePrompt("ChoicePrompt"))
        self.add_dialog(ConfirmPrompt("ConfirmPrompt"))

    def __getstate__(self):
        """Return minimal state for pickling - only what's needed to identify the dialog."""
        return {
            '_form_id': self._form_id,
            'id': self.id,
            'initial_dialog_id': getattr(self, 'initial_dialog_id', None),
        }

    def __setstate__(self, state):
        """Restore from minimal state - dialog will be recreated when needed."""
        self._form_id = state.get('_form_id')
        # Note: The dialog won't be fully functional after unpickling
        # but this prevents the recursion error

    @property
    def form(self) -> FormDefinition:
        """Get the form from the global registry."""
        form = get_registered_form(self._form_id)
        if form is None:
            raise ValueError(f"Form '{self._form_id}' not found in registry")
        return form

    # =========================================================================
    # State Management - Using step_context.values for persistence
    # =========================================================================

    def get_form_data(self, step_context: WaterfallStepContext) -> Dict[str, Any]:
        """Get accumulated form data from step_context.values (persists across steps)."""
        return step_context.values.get(FORM_DATA_KEY, {})

    def set_form_data(
        self,
        step_context: WaterfallStepContext,
        data: Dict[str, Any],
    ):
        """Store form data in step_context.values."""
        step_context.values[FORM_DATA_KEY] = data

    def get_current_section(self, step_context: WaterfallStepContext) -> int:
        """Get current section index from step values."""
        return step_context.values.get(CURRENT_SECTION_KEY, 0)

    def set_current_section(
        self,
        step_context: WaterfallStepContext,
        index: int,
    ):
        """Set current section index in step values."""
        step_context.values[CURRENT_SECTION_KEY] = index

    def get_validation_errors(
        self,
        step_context: WaterfallStepContext,
    ) -> Optional[Dict[str, str]]:
        """Get validation errors from step values."""
        return step_context.values.get(VALIDATION_ERRORS_KEY)

    def set_validation_errors(
        self,
        step_context: WaterfallStepContext,
        errors: Optional[Dict[str, str]],
    ):
        """Store validation errors in step values."""
        step_context.values[VALIDATION_ERRORS_KEY] = errors

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

    def _get_card_builder(self) -> AdaptiveCardBuilder:
        """Create a fresh card builder (not stored to avoid serialization issues)."""
        return AdaptiveCardBuilder()

    def _get_validator(self) -> FormValidator:
        """Create a fresh validator (not stored to avoid serialization issues)."""
        return FormValidator()

    async def send_card(
        self,
        step_context: WaterfallStepContext,
        card: Dict[str, Any],
    ):
        """Send an Adaptive Card, validating first."""
        validator = self._get_validator()
        # Validate and sanitize
        if not validator.validate_adaptive_card(card):
            card = validator.sanitize_card(card)

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

        card_builder = self._get_card_builder()
        card = card_builder.build_section_card(
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
        # NOTE: Callback is handled by wrapper after dialog ends
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
        validator = self._get_validator()
        card_builder = self._get_card_builder()

        # Validate all data
        validation = validator.validate_form_data(form_data, self.form)

        if not validation.is_valid:
            # Show errors (don't use replace_dialog to avoid recursion)
            error_card = card_builder.build_error_card(
                title="Validation Errors",
                errors=validation.error_list,
            )
            await self.send_card(step_context, error_card)
            # Return waiting - the user should get another chance
            return DialogTurnResult(DialogTurnStatus.Waiting)

        # NOTE: Completion callback is handled by wrapper after dialog ends
        return await step_context.end_dialog(validation.sanitized_data)
