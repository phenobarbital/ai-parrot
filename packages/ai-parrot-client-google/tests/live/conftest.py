"""Independent, redundant collection-time safety gate for tests/live/.

This directory contains ONLY opt-in, paid smoke tests. Two INDEPENDENT
mechanisms enforce the same "never run unless explicitly opted in with
real credentials" rule, so a bug in one does not silently let the other
through:

1. Each test class in ``test_reel_smoke.py`` is decorated
   ``@skip_unless_live`` (a ``pytest.mark.skipif``).
2. THIS conftest's ``pytest_collection_modifyitems`` hook independently
   re-checks the SAME condition and forcibly applies a skip marker to
   EVERY item collected under this directory, regardless of what markers
   the test file itself already applied. Belt and suspenders — a real
   paid API call must never happen without a human deliberately setting
   BOTH ``PARROT_TEST_LIVE_GOOGLE=1`` AND a real credential.
"""

from __future__ import annotations

import os

import pytest

_ENABLED = os.environ.get("PARROT_TEST_LIVE_GOOGLE") == "1"
_HAS_CREDENTIALS = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
_SHOULD_RUN = _ENABLED and _HAS_CREDENTIALS

_SKIP_REASON = (
    "Opt-in paid smoke test — set PARROT_TEST_LIVE_GOOGLE=1 and a real "
    "GOOGLE_API_KEY (or GOOGLE_APPLICATION_CREDENTIALS) to run."
)


def pytest_collection_modifyitems(config, items):
    """Force-skips every item under this directory unless BOTH env
    signals are present — independent of any marker the test module
    itself declares.
    """
    if _SHOULD_RUN:
        return
    skip_marker = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "tests/live/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip_marker)
