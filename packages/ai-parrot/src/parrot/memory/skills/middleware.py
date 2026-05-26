"""Deprecated: use parrot.skills.middleware instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.middleware is deprecated. Use parrot.skills.middleware instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.middleware import *  # noqa: F401, F403, E402
