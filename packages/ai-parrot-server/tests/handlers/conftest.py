"""Shared fixtures for the CommCenter handler test suite (FEAT-417, spec §4).

Centralizes the fixtures the spec's Test Data / Fixtures section names
(``recipients_csv``, ``recipients_xlsx``, ``fake_notify_client``,
``frozen_now``) so every ``test_comm_center_*.py`` module can reuse them
instead of redefining ad hoc versions.
"""
from datetime import datetime
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def recipients_csv() -> Path:
    """CSV with aliased/messy headers: 'Nombre', ' E-Mail ', 'Teléfono', 'user'."""
    return _FIXTURES_DIR / "recipients.csv"


@pytest.fixture
def recipients_xlsx() -> Path:
    """Same data as ``recipients_csv``, as ``.xlsx`` (exercises the openpyxl engine)."""
    return _FIXTURES_DIR / "recipients.xlsx"


@pytest.fixture
def frozen_now() -> datetime:
    """Injected into ``resolve_functions()``/``prepare()`` so ``{{today}}`` is deterministic."""
    return datetime(2026, 8, 6, 12, 0, 0)


class _FakeNotifyClient:
    """Captures every ``stream()`` call: ``(message, stream, use_wrapper)``.

    Asserting on captured payloads is how spec §5's sender criteria are
    verified without a live NotifyWorker.
    """

    def __init__(self, fail_on=frozenset()):
        self.calls: list = []
        self.fail_on = fail_on
        self.connect_called = False
        self.closed = False

    async def connect(self):
        self.connect_called = True

    async def close(self):
        self.closed = True

    async def stream(self, message, stream, use_wrapper=False):
        index = len(self.calls)
        self.calls.append((message, stream, use_wrapper))
        if index in self.fail_on:
            raise ConnectionError("redis down")
        return "1700000000000-0"


@pytest.fixture
def fake_notify_client():
    """A fresh ``_FakeNotifyClient`` — patch ``dispatch._get_notify_client`` to return it."""
    return _FakeNotifyClient()
