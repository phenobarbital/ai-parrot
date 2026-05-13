"""Unit tests for the form-service registry (TASK-1126)."""

import logging

import pytest

from parrot_formdesigner.tools.services.registry import (
    _SERVICE_REGISTRY,
    get_form_service,
    list_form_services,
    register_form_service,
)
from parrot_formdesigner.tools.services.abstract import AbstractFormService
from parrot_formdesigner.core.schema import FormSchema


class _StubService(AbstractFormService):
    """Stub service A for testing."""

    async def fetch(self, **params):  # type: ignore[override]
        return {}

    def to_form_schema(self, raw):  # type: ignore[override]
        return FormSchema(form_id="x", title="x", sections=[])


class _OtherService(AbstractFormService):
    """Stub service B for testing."""

    async def fetch(self, **params):  # type: ignore[override]
        return {}

    def to_form_schema(self, raw):  # type: ignore[override]
        return FormSchema(form_id="y", title="y", sections=[])


@pytest.fixture(autouse=True)
def clean_registry():
    """Snapshot/restore the module-level registry around each test."""
    snapshot = dict(_SERVICE_REGISTRY)
    _SERVICE_REGISTRY.clear()
    yield
    _SERVICE_REGISTRY.clear()
    _SERVICE_REGISTRY.update(snapshot)


class TestRegistry:
    """Tests for the form-service registry functions."""

    def test_register_and_get(self) -> None:
        """Registering a service and retrieving it returns the same class."""
        register_form_service("stub", _StubService)
        assert get_form_service("stub") is _StubService

    def test_multiple_services_coexist(self) -> None:
        """Two services under different names coexist without interference."""
        register_form_service("a", _StubService)
        register_form_service("b", _OtherService)
        assert get_form_service("a") is _StubService
        assert get_form_service("b") is _OtherService

    def test_overwrite_emits_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Re-registering the same name overwrites and logs a warning."""
        register_form_service("dup", _StubService)
        with caplog.at_level(logging.WARNING):
            register_form_service("dup", _OtherService)
        assert any(
            "overwriting existing entry for name=dup" in rec.message
            for rec in caplog.records
        )
        assert get_form_service("dup") is _OtherService

    def test_get_unknown_raises_keyerror_with_listing(self) -> None:
        """Unknown service name raises KeyError that lists registered names."""
        register_form_service("known", _StubService)
        with pytest.raises(KeyError) as exc:
            get_form_service("missing")
        assert "missing" in str(exc.value)
        assert "known" in str(exc.value)

    def test_list_form_services_returns_insertion_order(self) -> None:
        """list_form_services returns names in insertion order."""
        register_form_service("first", _StubService)
        register_form_service("second", _OtherService)
        register_form_service("third", _StubService)
        assert list_form_services() == ["first", "second", "third"]
