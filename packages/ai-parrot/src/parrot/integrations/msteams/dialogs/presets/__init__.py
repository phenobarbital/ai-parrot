"""
Pre-built form dialog templates.
"""
from .base import BaseFormDialog
from .simple_form import SimpleFormDialog
from .wizard import WizardFormDialog
from .wizard_summary import WizardWithSummaryDialog
from .conversational import ConversationalFormDialog

__all__ = [
    'BaseFormDialog',
    'SimpleFormDialog',
    'WizardFormDialog',
    'WizardWithSummaryDialog',
    'ConversationalFormDialog',
]
