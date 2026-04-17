"""Placeholder for cache/vector-tier tests.

The ``parrot.tools.databasequery.cache`` and ``parrot.tools.databasequery.models``
modules referenced by the original tests do not exist in the current codebase.
These tests were imported from a feature branch that was never merged.

Skipped until a cache module is implemented.

Part of FEAT-105 — databasetoolkit-clash / TASK-738.
"""
import pytest


@pytest.mark.skip(reason="parrot.tools.databasequery.cache module not yet implemented")
def test_cache_placeholder():
    """Placeholder — cache module not implemented."""
    pass
