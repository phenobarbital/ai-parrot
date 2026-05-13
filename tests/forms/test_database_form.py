"""Dispatcher-level integration via the public parrot.forms shim (TASK-1130).

After FEAT-166 refactor: the mapping tests live in test_networkninja_form_service.py.
This file exercises the public shim and verifies backward compatibility.
"""

from __future__ import annotations

import pytest

from parrot.forms import DatabaseFormTool, FormRegistry
from parrot_formdesigner.tools.database_form import DatabaseFormInput


@pytest.fixture
def registry() -> FormRegistry:
    """Fresh FormRegistry for each test."""
    return FormRegistry()


def test_public_shim_constructor(registry: FormRegistry) -> None:
    """DatabaseFormTool(registry=registry) still works via the parrot.forms shim."""
    tool = DatabaseFormTool(registry=registry)
    assert tool is not None


def test_public_shim_input_defaults() -> None:
    """DatabaseFormInput defaults are service-aware after FEAT-166."""
    inp = DatabaseFormInput(formid=1, orgid=1)
    assert inp.service == "networkninja"
    assert inp.params is None
    assert inp.persist is False


def test_public_shim_rejects_dsn_kwarg(registry: FormRegistry) -> None:
    """Removed kwarg dsn= raises TypeError even via the shim."""
    with pytest.raises(TypeError):
        DatabaseFormTool(registry=registry, dsn="postgres://x")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_public_shim_unknown_service(registry: FormRegistry) -> None:
    """Unknown service name → ToolResult(success=False) via the shim path."""
    tool = DatabaseFormTool(registry=registry)
    result = await tool._execute(
        service="bogus-service-that-does-not-exist",
        formid=1,
        orgid=1,
    )
    assert result.success is False
    assert result.status == "error"
    assert "bogus-service-that-does-not-exist" in (result.error or "")
