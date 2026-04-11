from typing import Any, Callable, Awaitable, Dict, Optional, TYPE_CHECKING
from botbuilder.dialogs import ComponentDialog

from parrot.forms import FormSchema, StyleSchema, LayoutType
from .presets import (
    SimpleFormDialog,
    WizardFormDialog,
    WizardWithSummaryDialog,
    ConversationalFormDialog,
)


class FormDialogFactory:
    """
    Factory to create WaterfallDialogs from FormSchemas.

    Supports different layouts:
    - SINGLE_COLUMN: Single Adaptive Card with all fields
    - WIZARD: One section per step
    - ACCORDION: Accordion-style (treated as SINGLE_COLUMN)
    - CONVERSATIONAL: One prompt per field

    NOTE: Dialogs no longer accept card_builder, validator, callbacks, or agent
    to avoid serialization issues with jsonpickle. These are accessed via:
    - renderer/validator: created fresh via _get_card_renderer()/_get_validator()
    - agent: accessed via turn_state
    - callbacks: handled by wrapper after dialog ends
    """

    def create_dialog(
        self,
        form: FormSchema,
        style: Optional[StyleSchema] = None,
        on_complete: Callable[[Dict[str, Any]], Awaitable[Any]] = None,  # Ignored - wrapper handles
        on_cancel: Optional[Callable[[], Awaitable[Any]]] = None,       # Ignored - wrapper handles
    ) -> ComponentDialog:
        """
        Create appropriate dialog based on form layout.

        Args:
            form: The FormSchema
            style: Optional StyleSchema for presentation
            on_complete: Ignored - completion handled by wrapper
            on_cancel: Ignored - cancellation handled by wrapper

        Returns:
            ComponentDialog for the form
        """
        layout = style.layout if style else LayoutType.SINGLE_COLUMN

        # Map layout to dialog preset
        if layout == LayoutType.WIZARD:
            # Check if summary should be shown
            if style and style.show_section_numbers:
                return WizardWithSummaryDialog(form=form, style=style)
            return WizardFormDialog(form=form, style=style)
        elif layout == LayoutType.CONVERSATIONAL:
            return ConversationalFormDialog(form=form, style=style)
        else:
            # SINGLE_COLUMN, TWO_COLUMN, ACCORDION, TABS, INLINE all use simple
            return SimpleFormDialog(form=form, style=style)

