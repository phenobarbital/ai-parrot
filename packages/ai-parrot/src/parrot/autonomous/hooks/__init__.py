"""Backward-compatibility shim — hooks have moved to parrot.core.hooks.

This module re-exports everything from the canonical location so that any
existing code importing from ``parrot.autonomous.hooks`` continues to work
without changes.
"""
from parrot.core.hooks import *  # noqa: F401, F403
from parrot.core.hooks import __all__  # noqa: F401
