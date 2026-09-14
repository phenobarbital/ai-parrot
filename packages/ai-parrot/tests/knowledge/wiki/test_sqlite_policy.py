"""Unit tests for the FEAT-557 SQLite connection policy primitives."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy


class TestSQLitePragmaPolicy:
    def test_defaults(self) -> None:
        """Policy defaults match the spec: 15s, opt-in pragmas, 64 MiB WAL cap."""
        policy = SQLitePragmaPolicy()
        assert policy.busy_timeout_s == 15.0
        assert policy.performance_pragmas is False
        assert policy.journal_size_limit == 67_108_864

    @pytest.mark.parametrize("value", [0.0, 0.999, 120.001, -5.0])
    def test_rejects_out_of_range_timeout(self, value: float) -> None:
        """Timeout is validated to the inclusive 1-120 second window (AC-2)."""
        with pytest.raises(ValidationError):
            SQLitePragmaPolicy(busy_timeout_s=value)

    @pytest.mark.parametrize("value", [1.0, 15.0, 120.0])
    def test_accepts_boundary_timeouts(self, value: float) -> None:
        """Both bounds are inclusive."""
        assert SQLitePragmaPolicy(busy_timeout_s=value).busy_timeout_s == value


class TestWikiStoreBusy:
    def test_is_an_operational_error(self) -> None:
        """Existing `except sqlite3.OperationalError` handlers still catch it."""
        assert issubclass(WikiStoreBusy, sqlite3.OperationalError)

    def test_carries_actionable_attributes(self) -> None:
        """Path, operation and waited seconds are addressable and in the message."""
        exc = WikiStoreBusy(Path("/tmp/wiki.db"), "upsert_pages", 15.0)
        assert exc.db_path == Path("/tmp/wiki.db")
        assert exc.operation == "upsert_pages"
        assert exc.waited_seconds == 15.0
        message = str(exc)
        assert "/tmp/wiki.db" in message
        assert "upsert_pages" in message
        assert "15" in message
