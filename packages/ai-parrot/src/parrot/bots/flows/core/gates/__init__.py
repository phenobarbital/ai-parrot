"""Public generic gate models and kind registry."""

from .host import AUTO_APPROVER, GateHost
from .kinds import is_registered, register_gate_kind, registered_kinds
from .models import (
    GateError,
    GateErrorCode,
    GateEvent,
    GateRecord,
    GateSpec,
    GateStatusValue,
    GateStore,
    PreReviewVerdict,
)

__all__ = [
    "AUTO_APPROVER",
    "GateError",
    "GateErrorCode",
    "GateEvent",
    "GateHost",
    "GateRecord",
    "GateSpec",
    "GateStatusValue",
    "GateStore",
    "PreReviewVerdict",
    "is_registered",
    "register_gate_kind",
    "registered_kinds",
]
