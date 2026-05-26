"""Deprecated: use parrot.skills.store instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.store is deprecated. Use parrot.skills.store instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.store import *  # noqa: F401, F403, E402
