from typing import Any, Callable, Awaitable, Dict, Optional, TYPE_CHECKING
from botbuilder.dialogs import ComponentDialog

from ...dialogs.models import FormDefinition, DialogPreset
from .presets import (
    SimpleFormDialog,
    WizardFormDialog,
    WizardWithSummaryDialog,
    ConversationalFormDialog,
)


class FormDialogFactory:
    """
    Factory to create WaterfallDialogs from FormDefinitions.

    Supports different presets:
    - SIMPLE: Single Adaptive Card with all fields
    - WIZARD: One section per step
    - WIZARD_WITH_SUMMARY: Wizard + confirmation step
    - CONVERSATIONAL: One prompt per field

    NOTE: Dialogs no longer accept card_builder, validator, callbacks, or agent
    to avoid serialization issues with jsonpickle. These are accessed via:
    - card_builder/validator: created fresh via _get_card_builder()/_get_validator()
    - agent: accessed via turn_state
    - callbacks: handled by wrapper after dialog ends
    """

    def create_dialog(
        self,
        form: FormDefinition,
        on_complete: Callable[[Dict[str, Any]], Awaitable[Any]] = None,  # Ignored - wrapper handles
        on_cancel: Optional[Callable[[], Awaitable[Any]]] = None,       # Ignored - wrapper handles
    ) -> ComponentDialog:
        """
        Create appropriate dialog based on form preset.

        Args:
            form: The FormDefinition
            on_complete: Ignored - completion handled by wrapper
            on_cancel: Ignored - cancellation handled by wrapper

        Returns:
            ComponentDialog for the form
        """
        if form.preset == DialogPreset.SIMPLE:
            return SimpleFormDialog(form=form)
        elif form.preset == DialogPreset.WIZARD:
            return WizardFormDialog(form=form)
        elif form.preset == DialogPreset.WIZARD_WITH_SUMMARY:
            return WizardWithSummaryDialog(form=form)
        elif form.preset == DialogPreset.CONVERSATIONAL:
            return ConversationalFormDialog(form=form)
        else:
            # Default to wizard
            return WizardFormDialog(form=form)

