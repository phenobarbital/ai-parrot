"""Deprecated: use parrot.skills.mixin instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.mixin is deprecated. Use parrot.skills.mixin instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.mixin import *  # noqa: F401, F403, E402
