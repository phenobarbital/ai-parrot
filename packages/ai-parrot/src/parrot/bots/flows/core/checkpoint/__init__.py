"""AgentsFlow state checkpointing plane (FEAT-399).

A sibling of `core/storage/` (the results/audit plane): checkpoints are
recoverable *state* (expiring by default, opt-in durable), not audit
*results*. See `sdd/specs/agentsflow-state-checkpointing.spec.md`.
"""
from .checkpointer import FlowCheckpointer
from .errors import (
    CheckpointFingerprintMismatchError,
    CheckpointNotFoundError,
    CheckpointPersistenceError,
    FlowLockedError,
    FlowNotExportableError,
)
from .model import (
    CheckpointInputMetadata,
    ContextSnapshot,
    FlowCheckpoint,
    MemoryRefs,
    NodeStateSnapshot,
)
from .recovery import FlowRecoveryService, get_recovery_service
from .serializer import FlowStateSerializer, register_checkpoint_type
from .store import (
    CheckpointStore,
    DurableCheckpointStore,
    RedisCheckpointStore,
    get_checkpoint_store,
)

__all__ = [
    "CheckpointFingerprintMismatchError",
    "CheckpointInputMetadata",
    "CheckpointNotFoundError",
    "CheckpointPersistenceError",
    "CheckpointStore",
    "ContextSnapshot",
    "DurableCheckpointStore",
    "FlowCheckpoint",
    "FlowCheckpointer",
    "FlowLockedError",
    "FlowNotExportableError",
    "FlowRecoveryService",
    "FlowStateSerializer",
    "MemoryRefs",
    "NodeStateSnapshot",
    "RedisCheckpointStore",
    "get_checkpoint_store",
    "get_recovery_service",
    "register_checkpoint_type",
]
