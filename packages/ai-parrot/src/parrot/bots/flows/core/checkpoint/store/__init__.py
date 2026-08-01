"""CheckpointStore backends for AgentsFlow state checkpointing (FEAT-399).

`RedisCheckpointStore` is re-exported directly — the `redis` driver is
already a base project dependency (used project-wide for memory/history),
so importing it here carries no extra cost. `DurableCheckpointStore`
(TASK-2050, heavier optional DB drivers: sqlite/postgres/mongodb) is
intentionally NOT imported here; it is resolved lazily via
`get_checkpoint_store()` so this sub-package stays importable without
those optional DB driver dependencies.
"""
from .base import CheckpointStore
from .factory import get_checkpoint_store
from .redis import RedisCheckpointStore

__all__ = [
    "CheckpointStore",
    "RedisCheckpointStore",
    "get_checkpoint_store",
]
