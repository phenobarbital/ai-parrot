"""WorkingMemoryToolkit — intermediate result store for analytical operations."""
from .tool import WorkingMemoryToolkit
from .models import (
    OperationType,
    JoinHow,
    AggFunc,
    FilterSpec,
    OperationSpecInput,
    ComputeAndStoreInput,
    # Generic entry models (FEAT-074)
    EntryType,
    StoreResultInput,
    GetResultInput,
    SearchStoredInput,
    SaveInteractionInput,
    RecallInteractionInput,
)
from .internals import GenericEntry

__all__ = [
    # Existing exports
    "WorkingMemoryToolkit",
    "OperationType",
    "JoinHow",
    "AggFunc",
    "FilterSpec",
    "OperationSpecInput",
    "ComputeAndStoreInput",
    # New generic entry exports (FEAT-074)
    "EntryType",
    "GenericEntry",
    "StoreResultInput",
    "GetResultInput",
    "SearchStoredInput",
    "SaveInteractionInput",
    "RecallInteractionInput",
]
