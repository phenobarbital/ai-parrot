"""Deprecated: use parrot.skills.parsers instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.parsers is deprecated. Use parrot.skills.parsers instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.parsers import *  # noqa: F401, F403, E402
