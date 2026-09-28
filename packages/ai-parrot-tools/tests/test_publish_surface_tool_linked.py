"""FEAT-598 M8 — PublishSurfaceTool linked lane (spec §4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers Chart/etc. under DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata
from parrot.tools.ui_surfaces import PublishSurfaceTool

pytestmark = pytest.mark.asyncio


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


def _baked_envelope(surface_id: str = "baked-1") -> dict:
    return CreateSurface(surfaceId=surface_id, components=[], dataModel={}).model_dump(by_alias=True, mode="json")


def _fake_linked_service(snapshot_result: dict | None = None) -> MagicMock:
    service = MagicMock()
    service.validate_for_persistence = AsyncMock()
    service.ensure_snapshot = AsyncMock(return_value=snapshot_result)
    return service


def _fake_store(return_value: str = "surface-1") -> MagicMock:
    store = MagicMock()
    store.save = AsyncMock(return_value=return_value)
    return store


async def test_publish_surface_tool_refreshable_from_record():
    bot = MagicMock()
    bot.publish_surface = AsyncMock(return_value="surface-from-bot")
    tool = PublishSurfaceTool(bot=bot)

    linked_result = await tool._execute(
        kind="dashboard",
        title="Linked",
        envelope=_linked_envelope(),
    )
    assert linked_result["refreshable"] is True

    baked_result = await tool._execute(
        kind="dashboard",
        title="Baked",
        envelope=_baked_envelope(),
    )
    assert baked_result["refreshable"] is False


async def test_standalone_lane_runs_service():
    envelope = _linked_envelope()
    snapshot = dict(envelope)
    snapshot["dataModel"] = {"activity": {"rows": [{"day": "2026-09-01", "visits": 10}]}}
    service = _fake_linked_service(snapshot_result=snapshot)
    store = _fake_store("surface-standalone")
    tool = PublishSurfaceTool(surface_store=store, linked_service=service, user_id="owner-1")

    result = await tool._execute(kind="dashboard", title="Linked", envelope=envelope)

    assert result["surface_id"] == "surface-standalone"
    service.validate_for_persistence.assert_awaited_once()
    service.ensure_snapshot.assert_awaited_once()
    owner_pctx = service.ensure_snapshot.call_args.kwargs["owner_pctx"]
    assert owner_pctx.user_id == "owner-1"
    record = store.save.call_args.args[0]
    assert record.envelope == snapshot


async def test_standalone_lane_guard_missing_fails_closed():
    store = _fake_store()
    tool = PublishSurfaceTool(surface_store=store)  # no linked_service -> guard=None

    with pytest.raises(LinkedGuardRequired):
        await tool._execute(kind="dashboard", title="Linked", envelope=_linked_envelope())

    store.save.assert_not_awaited()


async def test_standalone_lane_baked_untouched():
    service = _fake_linked_service()
    store = _fake_store("surface-baked")
    tool = PublishSurfaceTool(surface_store=store, linked_service=service)

    result = await tool._execute(kind="widget", title="Baked", envelope=_baked_envelope())

    assert result["surface_id"] == "surface-baked"
    service.validate_for_persistence.assert_not_awaited()
    service.ensure_snapshot.assert_not_awaited()


async def test_bot_lane_does_not_call_service():
    bot = MagicMock()
    bot.publish_surface = AsyncMock(return_value="surface-from-bot")
    service = _fake_linked_service()
    tool = PublishSurfaceTool(bot=bot, linked_service=service)

    result = await tool._execute(kind="dashboard", title="Linked", envelope=_linked_envelope())

    assert result["surface_id"] == "surface-from-bot"
    service.validate_for_persistence.assert_not_awaited()
    service.ensure_snapshot.assert_not_awaited()
