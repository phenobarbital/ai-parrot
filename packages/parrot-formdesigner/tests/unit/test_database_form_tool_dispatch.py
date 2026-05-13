"""Dispatcher-level tests for DatabaseFormTool (post-refactor) — TASK-1129."""

from typing import Any

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.tools.database_form import DatabaseFormInput, DatabaseFormTool
from parrot_formdesigner.tools.services import (
    AbstractFormService,
    register_form_service,
)
from parrot_formdesigner.tools.services.registry import _SERVICE_REGISTRY


class _StubService(AbstractFormService):
    """Minimal stub service for dispatcher tests."""

    last_params: dict[str, Any] | None = None
    last_form: FormSchema | None = None

    async def fetch(self, **params: Any) -> dict[str, Any]:  # type: ignore[override]
        """Record params and return a stub dict."""
        _StubService.last_params = params
        return {"params": params}

    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:  # type: ignore[override]
        """Return a stub FormSchema."""
        form = FormSchema(form_id="stub-1", title="Stub", sections=[])
        _StubService.last_form = form
        return form


@pytest.fixture
def registry() -> FormRegistry:
    """Fresh FormRegistry for each test."""
    return FormRegistry()


@pytest.fixture
def stub_registered():
    """Register the stub service and clean up after the test."""
    register_form_service("__stub__", _StubService)
    yield
    _SERVICE_REGISTRY.pop("__stub__", None)


def test_input_defaults() -> None:
    """DatabaseFormInput defaults: service='networkninja', params=None, persist=False."""
    inp = DatabaseFormInput(formid=1, orgid=1)
    assert inp.service == "networkninja"
    assert inp.params is None
    assert inp.persist is False


def test_constructor_backward_compat(registry: FormRegistry) -> None:
    """DatabaseFormTool(registry=registry) still works — mirrors api/handlers.py."""
    tool = DatabaseFormTool(registry=registry)
    assert tool is not None


def test_constructor_rejects_dsn_kwarg(registry: FormRegistry) -> None:
    """Removed kwarg dsn= raises TypeError."""
    with pytest.raises(TypeError):
        DatabaseFormTool(registry=registry, dsn="postgres://x")  # type: ignore[call-arg]


def test_constructor_rejects_db_kwarg(registry: FormRegistry) -> None:
    """Removed kwarg db= raises TypeError."""
    with pytest.raises(TypeError):
        DatabaseFormTool(registry=registry, db=object())  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_unknown_service_returns_failing_toolresult(registry: FormRegistry) -> None:
    """Unknown service name → ToolResult(success=False, status='error')."""
    tool = DatabaseFormTool(registry=registry)
    result = await tool._execute(
        service="definitely-not-a-real-service",
        formid=1,
        orgid=1,
    )
    assert result.success is False
    assert result.status == "error"
    assert "definitely-not-a-real-service" in (result.error or "")


@pytest.mark.asyncio
async def test_dispatcher_invokes_service_with_validated_kwargs(
    registry: FormRegistry,
    stub_registered: None,
) -> None:
    """Stub service is called with correct formid, orgid, and extra params."""
    tool = DatabaseFormTool(registry=registry)
    result = await tool._execute(
        service="__stub__",
        formid=42,
        orgid=7,
        params={"extra": "value"},
    )
    assert result.success is True
    assert _StubService.last_params == {"formid": 42, "orgid": 7, "extra": "value"}


@pytest.mark.asyncio
async def test_dispatcher_registers_form_in_registry(
    registry: FormRegistry,
    stub_registered: None,
) -> None:
    """After successful dispatch, FormSchema is in the registry."""
    tool = DatabaseFormTool(registry=registry)
    await tool._execute(service="__stub__", formid=1, orgid=1)
    assert await registry.get("stub-1") is not None


@pytest.mark.asyncio
async def test_handlers_import_unchanged() -> None:
    """api/handlers.py still imports clean after the refactor."""
    from parrot_formdesigner.api.handlers import FormAPIHandler  # noqa: F401
