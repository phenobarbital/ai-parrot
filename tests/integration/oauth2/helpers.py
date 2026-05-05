"""Shared test helpers for the OAuth2 integration test package.

These are plain functions (not pytest fixtures) used by multiple test modules.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def make_mock_db() -> tuple[MagicMock, AsyncMock]:
    """Return (mock_db_cls, mock_db_instance) pair for patching DocumentDb.

    Usage::

        mock_db_cls, mock_db = make_mock_db()
        with patch("parrot.integrations.oauth2.persistence.DocumentDb", mock_db_cls):
            ...
        mock_db.update_one.assert_called_once()
    """
    mock_db_instance = AsyncMock()
    mock_db_cls = MagicMock()
    mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db_instance)
    mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_db_cls, mock_db_instance
