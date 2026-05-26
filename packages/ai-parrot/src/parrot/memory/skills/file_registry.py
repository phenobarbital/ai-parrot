"""Deprecated: use parrot.skills.file_registry instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.file_registry is deprecated. Use parrot.skills.file_registry instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.file_registry import *  # noqa: F401, F403, E402
