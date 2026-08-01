"""CheckpointStore backends for AgentsFlow state checkpointing (FEAT-399).

Concrete backends (`RedisCheckpointStore`, `DurableCheckpointStore`) are
added by TASK-2049/TASK-2050 and are resolved lazily via
`get_checkpoint_store()` — they are intentionally NOT imported here to
keep this sub-package importable without Redis/DB driver dependencies.
"""
from .base import CheckpointStore
from .factory import get_checkpoint_store

__all__ = [
    "CheckpointStore",
    "get_checkpoint_store",
]
