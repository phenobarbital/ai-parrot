"""FEAT-611 M7 — PublishSurfaceTool standalone-lane LinkedSurfaceService resolution order (spec §4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers Chart under DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata
from parrot.tools.ui_surfaces import PublishSurfaceTool


def _linked_envelope(surface_id: str = "linked-1") -> dict:
    """A structurally-valid Chart surface bound to /activity/rows with one linked source."""
    request = SourceRequest(placeholders={"firstdate": "YESTERDAY", "lastdate": "TODAY"})
    source = LinkedDataSource(
        slug="activity",
        tenant=None,
        conditions=derive_conditions(request, locked={}),
        request=request,
        target="/activity/rows",
    )
    envelope = CreateSurface(
        surfaceId=surface_id,
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["visits"],
                data={"path": "/activity/rows"},
            )
        ],
        dataModel={"activity": {"rows": []}},
        metadata=SurfaceMetadata(
            extensions=Extensions({"parrot_data_sources": {"activity": source.model_dump(mode="json", by_alias=True)}})
        ),
    )
    return envelope.model_dump(by_alias=True, mode="json")


def _fake_store(return_value: str = "surface-1") -> MagicMock:
    store = MagicMock()
    store.save = AsyncMock(return_value=return_value)
    return store


def test_step1_explicit_linked_service_wins() -> None:
    service, guard = MagicMock(), object()
    tool = PublishSurfaceTool(linked_service=service, guard=guard, bot=SimpleNamespace(_dataplane_guard=object()))
    assert tool._resolve_linked_service() is service


def test_step2_guard_kwarg_beats_bot_guard() -> None:
    guard, other = object(), object()
    tool = PublishSurfaceTool(guard=guard, bot=SimpleNamespace(_dataplane_guard=other))
    service = tool._resolve_linked_service()
    assert isinstance(service, LinkedSurfaceService)
    assert service.guard is guard


def test_step3_bot_dataplane_guard() -> None:
    guard = object()
    bot = SimpleNamespace(_dataplane_guard=guard)  # no publish_surface attr -> standalone lane
    tool = PublishSurfaceTool(bot=bot)
    service = tool._resolve_linked_service()
    assert isinstance(service, LinkedSurfaceService)
    assert service.guard is guard


def test_step4_default_is_fail_closed() -> None:
    for tool in (PublishSurfaceTool(), PublishSurfaceTool(bot=SimpleNamespace())):
        service = tool._resolve_linked_service()
        assert isinstance(service, LinkedSurfaceService)
        assert service.guard is None


@pytest.mark.asyncio
async def test_no_guard_anywhere_still_raises_linked_guard_required() -> None:
    """Default behaviour preserved end to end (spec §5: no guard → 403)."""
    store = _fake_store()
    tool = PublishSurfaceTool(surface_store=store, bot=SimpleNamespace())
    with pytest.raises(LinkedGuardRequired):
        await tool._execute(kind="dashboard", title="L", envelope=_linked_envelope())
    store.save.assert_not_awaited()
