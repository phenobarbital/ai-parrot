"""Error types for AgentsFlow state checkpointing (FEAT-399)."""
from __future__ import annotations


class FlowLockedError(RuntimeError):
    """Raised when a resume/suspend is attempted on a flow_id that already
    holds an active resume lease (concurrent resume protection)."""


class CheckpointNotFoundError(LookupError):
    """Raised when a requested checkpoint (or flow) cannot be found —
    e.g. TTL-expired, deleted, or never written."""


class FlowNotExportableError(ValueError):
    """Raised by `AgentsFlow.to_definition()` when the graph contains a
    node type that is not registered in `NODE_REGISTRY` and therefore
    cannot round-trip through a `FlowDefinition` export."""
