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

# FEAT-538: the composition root callers pass as `task_memory=` to opt
# the toolkit into recoverable task memory. Exported because it is the
# supported wiring entry point; the stores, service, reducer and the
# ten tool methods behind it stay private to `.task_memory`.
from .task_memory.tools import TaskMemory

__all__ = [
    # Existing exports
    "WorkingMemoryToolkit",
    "TaskMemory",
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
