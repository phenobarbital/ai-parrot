"""Unit tests for the submission endpoint (TASK-602 / FEAT-086)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.services.registry import FormRegistry


class TestFormAPIHandlerConstructor:
    """Tests for the updated FormAPIHandler constructor (TASK-602)."""

    def test_backward_compat_no_new_params(self) -> None:
        """FormAPIHandler(registry=...) still works without new params."""
        registry = FormRegistry()
        handler = FormAPIHandler(registry=registry)
        assert handler._submission_storage is None
        assert handler._forwarder is None

    def test_with_submission_storage(self) -> None:
        """submission_storage parameter is stored correctly."""
        registry = FormRegistry()
        mock_storage = MagicMock()
        handler = FormAPIHandler(registry=registry, submission_storage=mock_storage)
        assert handler._submission_storage is mock_storage

    def test_with_forwarder(self) -> None:
        """forwarder parameter is stored correctly."""
        registry = FormRegistry()
        mock_forwarder = MagicMock()
        handler = FormAPIHandler(registry=registry, forwarder=mock_forwarder)
        assert handler._forwarder is mock_forwarder

    def test_with_all_params(self) -> None:
        """All new constructor parameters work together."""
        registry = FormRegistry()
        mock_storage = MagicMock()
        mock_forwarder = MagicMock()
        handler = FormAPIHandler(
            registry=registry,
            submission_storage=mock_storage,
            forwarder=mock_forwarder,
        )
        assert handler._submission_storage is mock_storage
        assert handler._forwarder is mock_forwarder
        assert handler.registry is registry
