from typing import Any, Callable, Awaitable, Dict, Optional, TYPE_CHECKING
from botbuilder.dialogs import (
    ComponentDialog,
    WaterfallDialog,
    WaterfallStepContext,
    DialogTurnResult,
    DialogTurnStatus,
    DialogSet
)
from botbuilder.dialogs.prompts import TextPrompt, ChoicePrompt, ConfirmPrompt
from botbuilder.core import MessageFactory, CardFactory, TurnContext

from ...dialogs.models import (
    FormDefinition,
    FormSection,
    FormField,
    FieldType,
    DialogPreset
)
from .card_builder import AdaptiveCardBuilder
from .validator import FormValidator
from .presets import (
    SimpleFormDialog,
    WizardFormDialog,
    WizardWithSummaryDialog,
    ConversationalFormDialog,
)

if TYPE_CHECKING:
    from ...bots.abstract import AbstractBot


class FormDialogFactory:
    """
    Factory to create WaterfallDialogs from FormDefinitions.

    Supports different presets:
    - SIMPLE: Single Adaptive Card with all fields
    - WIZARD: One section per step
    - WIZARD_WITH_SUMMARY: Wizard + confirmation step
    - CONVERSATIONAL: One prompt per field
    """

    def __init__(
        self,
        card_builder: AdaptiveCardBuilder = None,
        validator: FormValidator = None,
    ):
        self.card_builder = card_builder or AdaptiveCardBuilder()
        self.validator = validator or FormValidator()

    def create_dialog(
        self,
        form: FormDefinition,
        on_complete: Callable[[Dict[str, Any], TurnContext], Awaitable[Any]],
        on_cancel: Optional[Callable[[TurnContext], Awaitable[Any]]] = None,
        agent: Optional['AbstractBot'] = None,  # For LLM validation
    ) -> ComponentDialog:
        """
        Create appropriate dialog based on form preset.
        """
        if form.preset == DialogPreset.SIMPLE:
            return SimpleFormDialog(
                form=form,
                card_builder=self.card_builder,
                validator=self.validator,
                on_complete=on_complete,
                on_cancel=on_cancel,
            )
        elif form.preset == DialogPreset.WIZARD:
            return WizardFormDialog(
                form=form,
                card_builder=self.card_builder,
                validator=self.validator,
                on_complete=on_complete,
                on_cancel=on_cancel,
            )
        elif form.preset == DialogPreset.WIZARD_WITH_SUMMARY:
            return WizardWithSummaryDialog(
                form=form,
                card_builder=self.card_builder,
                validator=self.validator,
                on_complete=on_complete,
                on_cancel=on_cancel,
                agent=agent,
            )
        elif form.preset == DialogPreset.CONVERSATIONAL:
            return ConversationalFormDialog(
                form=form,
                validator=self.validator,
                on_complete=on_complete,
                on_cancel=on_cancel,
            )
        else:
            # Default to wizard
            return WizardFormDialog(
                form=form,
                card_builder=self.card_builder,
                validator=self.validator,
                on_complete=on_complete,
                on_cancel=on_cancel,
            )
