"""Deprecated: use parrot.skills.models instead.

This module is a compatibility shim. It will be removed in a future release.
"""
import warnings

warnings.warn(
    "parrot.memory.skills.models is deprecated. Use parrot.skills.models instead.",
    DeprecationWarning,
    stacklevel=2,
)

from parrot.skills.models import *  # noqa: F401, F403, E402
