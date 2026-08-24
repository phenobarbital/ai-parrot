"""BusinessAutomationToolkit — generic, domain-neutral business-operation
engine (FEAT-453, Layer 2).

Site-specific plans (e.g. a bookkeeping product integration) stay out of
this repository (spec §8, resolved: generic-public / plans-private) — this
package contains zero site-specific identifiers.
"""

from .models import BusinessOperation, ImportRun, OperationKind
from .toolkit import BusinessAutomationToolkit

__all__ = [
    "BusinessAutomationToolkit",
    "BusinessOperation",
    "ImportRun",
    "OperationKind",
]
