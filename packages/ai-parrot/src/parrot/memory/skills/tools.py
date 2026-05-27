"""Deprecated: use parrot.skills.tools instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.tools is deprecated. Use parrot.skills.tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.tools import *  # noqa: F401, F403, E402
