"""Factory for resolving CheckpointStore backends (FEAT-399, TASK-2048).

Pattern mirrors `get_result_storage()`
(`core/storage/backends/factory.py`, FEAT-147): resolution precedence is
instance > explicit name arg > env var `FLOW_CHECKPOINT_STORE` > default
`"redis"`. Concrete backend classes are imported lazily inside the
function body so missing drivers only fail when that backend is
actually selected.
"""
from __future__ import annotations

import importlib

from parrot.conf import FLOW_CHECKPOINT_STORE

from .base import CheckpointStore

_REGISTRY: dict[str, str] = {
    "redis": "parrot.bots.flows.core.checkpoint.store.redis:RedisCheckpointStore",
    "sqlite": "parrot.bots.flows.core.checkpoint.store.durable:DurableCheckpointStore",
    "postgres": "parrot.bots.flows.core.checkpoint.store.durable:DurableCheckpointStore",
    "mongodb": "parrot.bots.flows.core.checkpoint.store.durable:DurableCheckpointStore",
}


def _import_class(path: str) -> type:
    """Lazily import a class from a dotted-path string with a colon separator.

    Args:
        path: Module path and class name separated by ``:``, e.g.
            ``"parrot.bots.flows.core.checkpoint.store.redis:RedisCheckpointStore"``.

    Returns:
        The imported class object.
    """
    module_path, _, cls_name = path.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


def get_checkpoint_store(
    arg: str | CheckpointStore | None = None,
) -> CheckpointStore:
    """Resolve a ``CheckpointStore`` instance.

    Resolution precedence:
        1. ``CheckpointStore`` instance → returned as-is.
        2. Non-empty string → looked up in the backend registry
           (``"redis"``, ``"sqlite"``, ``"postgres"``, ``"mongodb"``).
        3. ``None`` → falls back to env var ``FLOW_CHECKPOINT_STORE``,
           then defaults to ``"redis"``.

    Durable backends (``sqlite``/``postgres``/``mongodb``) all resolve to
    the single parametrized ``DurableCheckpointStore`` (TASK-2050), which
    is constructed with the driver name so it knows which asyncdb driver
    to use.

    Args:
        arg: A ``CheckpointStore`` instance, a backend name string, or
            ``None``.

    Returns:
        A ``CheckpointStore`` instance.

    Raises:
        ValueError: If the name is not found in the backend registry.
    """
    if isinstance(arg, CheckpointStore):
        return arg

    name = arg or FLOW_CHECKPOINT_STORE or "redis"
    name = name.lower()

    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown CheckpointStore backend: {name!r}. "
            f"Valid backends: {sorted(_REGISTRY)}"
        )

    cls = _import_class(_REGISTRY[name])
    if name in ("sqlite", "postgres", "mongodb"):
        return cls(driver=name)
    return cls()
