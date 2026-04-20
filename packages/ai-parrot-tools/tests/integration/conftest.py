"""Integration test fixtures for NavigatorToolkit — FEAT-107 TASK-757.

Provides the `navigator_dsn` fixture that skips when NAVIGATOR_DSN is unset.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def navigator_dsn() -> str:
    """Return the DSN for the live Navigator Postgres instance.

    Skips the test if NAVIGATOR_DSN environment variable is not set.
    """
    dsn = os.environ.get("NAVIGATOR_DSN")
    if not dsn:
        pytest.skip("NAVIGATOR_DSN not set; integration tests skipped.")
    return dsn
