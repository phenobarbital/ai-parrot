from typing import Any, Callable, Awaitable, Dict, Optional, TYPE_CHECKING
from botbuilder.dialogs import ComponentDialog

from parrot.forms import FormSchema, StyleSchema, LayoutType
from .presets import (
    SimpleFormDialog,
    WizardFormDialog,
    WizardWithSummaryDialog,
    ConversationalFormDialog,
)

# LayoutType does not include CONVERSATIONAL — the conversational preset
# is opt-in via ``style.meta["conversational"] = True``. Everything else
# maps directly from LayoutType.


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
        meta = (style.meta if style and style.meta else {}) or {}

        # Conversational mode is opt-in via style.meta["conversational"]
        # because LayoutType has no CONVERSATIONAL value — the conversational
        # preset drives one BotBuilder prompt per field instead of Adaptive
        # Cards, so it is a delivery concern, not a visual layout.
        if meta.get("conversational"):
            return ConversationalFormDialog(form=form, style=style)

        if layout == LayoutType.WIZARD:
            # Show the summary/confirmation step when requested via meta.
            if meta.get("show_summary"):
                return WizardWithSummaryDialog(form=form, style=style)
            return WizardFormDialog(form=form, style=style)

        # SINGLE_COLUMN, TWO_COLUMN, ACCORDION, TABS, INLINE all use simple
        return SimpleFormDialog(form=form, style=style)

