"""FEAT-598 M8 — InfographicAuthoringMixin.publish_surface linked boundary (spec §4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers Chart/etc. under DEFAULT_CATALOG_ID
from parrot.auth.exceptions import AuthorizationRequired
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata

pytestmark = pytest.mark.asyncio


class _AuthoringAgent(InfographicAuthoringMixin, PandasAgent):
    """Test composition: mixin before PandasAgent (cooperative MRO)."""


def _fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    return store


@pytest.fixture(scope="module")
def agent():
    """One composed agent for the whole module (instantiation is heavy)."""
    return _AuthoringAgent(name="reporter", artifact_store=_fake_artifact_store())


@pytest.fixture
def fake_surface_store():
    store = MagicMock()
    store.save = AsyncMock(return_value="surface-1")
    return store


@pytest.fixture
def fake_linked_service():
    service = MagicMock()
    service.validate_for_persistence = AsyncMock()
    # Default: echo the envelope dump back unchanged (tests override .return_value when they care).
    service.ensure_snapshot = AsyncMock(side_effect=lambda envelope_dump, owner_pctx: envelope_dump)
    return service


@pytest.fixture(autouse=True)
def _bind_linked_service(agent, fake_linked_service):
    """Bind the fake linked service to the module-scoped agent, then reset it (avoids test leakage)."""
    agent._linked_surface_service = fake_linked_service
    yield
    del agent._linked_surface_service


def _linked_envelope(surface_id: str = "linked-1") -> CreateSurface:
    """A structurally-valid Chart surface bound to /activity/rows with one linked source."""
    request = SourceRequest(placeholders={"firstdate": "YESTERDAY", "lastdate": "TODAY"})
    source = LinkedDataSource(
        slug="activity",
        tenant=None,
        conditions=derive_conditions(request, locked={}),
        request=request,
        target="/activity/rows",
    )
    return CreateSurface(
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


def _baked_envelope(surface_id: str = "baked-1") -> CreateSurface:
    return CreateSurface(surfaceId=surface_id, components=[], dataModel={})


async def test_publish_surface_linked_snapshot_persisted(agent, fake_surface_store, fake_linked_service):
    envelope = _linked_envelope()
    snapshot = envelope.model_dump(by_alias=True, mode="json")
    snapshot["dataModel"] = {"activity": {"rows": [{"day": "2026-09-01", "visits": 10}]}}
    fake_linked_service.ensure_snapshot.side_effect = None
    fake_linked_service.ensure_snapshot.return_value = snapshot

    await agent.publish_surface(
        kind="dashboard",
        title="Linked",
        envelope=envelope,
        surface_store=fake_surface_store,
    )

    fake_linked_service.validate_for_persistence.assert_awaited_once()
    fake_linked_service.ensure_snapshot.assert_awaited_once()
    record = fake_surface_store.save.call_args.args[0]
    assert record.envelope == snapshot


async def test_publish_surface_owner_pctx(agent, fake_surface_store, fake_linked_service):
    await agent.publish_surface(
        kind="dashboard",
        title="Linked",
        envelope=_linked_envelope(),
        user_id="alice",
        surface_store=fake_surface_store,
    )

    owner_pctx = fake_linked_service.ensure_snapshot.call_args.kwargs["owner_pctx"]
    assert owner_pctx.user_id == "alice"
    assert owner_pctx.channel == "ui_surfaces"


async def test_publish_surface_denied_persists_nothing(agent, fake_surface_store, fake_linked_service):
    fake_linked_service.validate_for_persistence.side_effect = AuthorizationRequired("query_slug", "not permitted")

    with pytest.raises(AuthorizationRequired):
        await agent.publish_surface(
            kind="dashboard",
            title="Linked",
            envelope=_linked_envelope(),
            surface_store=fake_surface_store,
        )

    fake_surface_store.save.assert_not_awaited()
    fake_linked_service.ensure_snapshot.assert_not_awaited()


async def test_publish_surface_baked_unchanged(agent, fake_surface_store, fake_linked_service):
    envelope = _baked_envelope()

    surface_id = await agent.publish_surface(
        kind="widget",
        title="Baked",
        envelope=envelope,
        surface_store=fake_surface_store,
    )

    assert surface_id == "surface-1"
    fake_linked_service.validate_for_persistence.assert_not_awaited()
    fake_linked_service.ensure_snapshot.assert_not_awaited()
    record = fake_surface_store.save.call_args.args[0]
    assert record.envelope == envelope.model_dump(by_alias=True, mode="json")
