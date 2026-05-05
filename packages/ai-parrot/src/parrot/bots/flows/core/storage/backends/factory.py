"""Factory for resolving ResultStorage backends by name, instance, or env var."""
from __future__ import annotations

import importlib
from typing import Union

from parrot.conf import CREW_RESULT_STORAGE

from .base import ResultStorage


_REGISTRY: dict[str, str] = {
    "redis": "parrot.bots.flows.core.storage.backends.redis:RedisResultStorage",
    "postgres": "parrot.bots.flows.core.storage.backends.postgres:PostgresResultStorage",
    "documentdb": "parrot.bots.flows.core.storage.backends.documentdb:DocumentDbResultStorage",
}


def _import_class(path: str) -> type:
    """Lazily import a class from a dotted-path string with a colon separator.

    Args:
        path: Module path and class name separated by ``:``, e.g.
            ``"parrot.bots.flows.core.storage.backends.redis:RedisResultStorage"``.

    Returns:
        The imported class object.
    """
    module_path, _, cls_name = path.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


def get_result_storage(
    name_or_instance: Union[str, "ResultStorage", None] = None,
) -> "ResultStorage":
    """Resolve a ``ResultStorage`` instance.

    Resolution precedence:
        1. ``ResultStorage`` instance → returned as-is.
        2. Non-empty string → looked up in the backend registry.
        3. ``None`` → falls back to env var ``CREW_RESULT_STORAGE``,
           then defaults to ``"documentdb"``.

    Args:
        name_or_instance: A ``ResultStorage`` instance, a backend name string
            (``"redis"``, ``"postgres"``, ``"documentdb"``), or ``None``.

    Returns:
        A ``ResultStorage`` instance.

    Raises:
        ValueError: If the name is not found in the backend registry.
    """
    if isinstance(name_or_instance, ResultStorage):
        return name_or_instance

    name = name_or_instance or CREW_RESULT_STORAGE or "documentdb"
    name = name.lower()

    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown ResultStorage backend: {name!r}. "
            f"Valid backends: {sorted(_REGISTRY)}"
        )

    cls = _import_class(_REGISTRY[name])
    return cls()
