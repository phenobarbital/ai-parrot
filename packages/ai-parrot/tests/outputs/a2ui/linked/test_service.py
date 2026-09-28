"""FEAT-598 S1/S2/S11 — LinkedSurfaceService (spec §4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers Chart/etc. under DEFAULT_CATALOG_ID
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked import executor as executor_mod
from parrot.outputs.a2ui.linked.executor import ExecutionOutcome, SourceOutcome
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService, SnapshotError
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata

pytestmark = pytest.mark.asyncio


class _FakeGuard:
    """Records authorize_source calls; denies the (source_type, source_id) pairs in `deny`."""

    def __init__(self, deny: set[str] | None = None) -> None:
        self.deny = deny or set()
        self.calls: list[tuple[Any, Any]] = []

    async def authorize_source(self, ctx: Any, resources: Any) -> None:
        self.calls.append((ctx, resources))
        key = f"{resources.source_type}:{resources.source_id}"
        if key in self.deny:
            raise AuthorizationRequired(tool_name="dataplane_authz", message="denied")


@pytest.fixture
def owner():
    return build_principal_context("owner-1", channel="ui_surfaces")


def _sources_payload(linked_source, **changes: object) -> dict:
    """Return a JSON-ready {"activity": <descriptor>} mapping (mirrors test_validate_linked.py)."""
    payload = linked_source.model_dump(mode="json", by_alias=True)
    payload.update(changes)
    return {"activity": payload}


def _envelope(linked_source, **changes: object) -> CreateSurface:
    """Return a structurally-valid Chart surface bound to /activity/rows with one linked source."""
    return CreateSurface(
        surfaceId="linked-service",
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
        dataModel={},
        metadata=SurfaceMetadata(
            extensions=Extensions({"parrot_data_sources": _sources_payload(linked_source, **changes)})
        ),
    )


def _dict_envelope(linked_source, *, data_model: dict | None = None, **changes: object) -> dict:
    """Same envelope as `_envelope`, dumped to the flat by-alias dict shape the service operates on."""
    payload = _envelope(linked_source, **changes).model_dump(mode="json", by_alias=True)
    if data_model is not None:
        payload["dataModel"] = data_model
    return payload


async def test_persist_validates_envelope(owner) -> None:
    """A linked envelope with no root component fails structural validation (AC14)."""
    envelope = CreateSurface(
        surfaceId="linked-invalid",
        components=[],
        dataModel={},
        metadata=SurfaceMetadata(extensions=Extensions({"parrot_data_sources": {"activity": {"placeholder": True}}})),
    )
    service = LinkedSurfaceService(guard=_FakeGuard())
    with pytest.raises(CatalogValidationError):
        await service.validate_for_persistence(envelope, owner_pctx=owner)


async def test_persist_requires_guard_fail_closed(owner, linked_source) -> None:
    """A structurally-valid linked envelope with no guard fails closed (AC14)."""
    envelope = _envelope(linked_source)
    service = LinkedSurfaceService(guard=None)
    with pytest.raises(LinkedGuardRequired):
        await service.validate_for_persistence(envelope, owner_pctx=owner)


async def test_persist_baked_envelope_passthrough(owner) -> None:
    """A baked (non-linked) envelope skips validation and the guard entirely (AC11)."""
    envelope = CreateSurface(surfaceId="baked", components=[], dataModel={})
    service = LinkedSurfaceService(guard=None)
    await service.validate_for_persistence(envelope, owner_pctx=owner)  # no error raised


async def test_persist_owner_slug_execute_denied(owner, linked_source) -> None:
    """One denied (tenant, slug) => AuthorizationRequired, structural validation already passed (S2)."""
    envelope = _envelope(linked_source)
    guard = _FakeGuard(deny={"query_slug:public:epson_field_activity"})
    service = LinkedSurfaceService(guard=guard)
    with pytest.raises(AuthorizationRequired):
        await service.validate_for_persistence(envelope, owner_pctx=owner)
    assert guard.calls  # the guard was actually consulted


async def test_ensure_snapshot_executes_once(owner, linked_source, monkeypatch) -> None:
    """execute_sources runs exactly once and patches rows + snapshot_at into a copy of the envelope (AC8/S1)."""
    envelope = _dict_envelope(linked_source)  # dataModel={} -> no rows/snapshot_at yet
    calls: list[tuple[Any, dict]] = []

    async def _fake_execute_sources(sources, **kwargs):
        calls.append((sources, kwargs))
        return ExecutionOutcome(
            outcomes={
                "activity": SourceOutcome(
                    key="activity", rows=[{"day": "2026-09-01"}], snapshot_at=datetime.now(timezone.utc)
                )
            }
        )

    monkeypatch.setattr(executor_mod, "execute_sources", _fake_execute_sources)
    service = LinkedSurfaceService(guard=_FakeGuard())

    patched = await service.ensure_snapshot(envelope, owner_pctx=owner)

    assert len(calls) == 1
    assert calls[0][1]["pctx"] is owner
    assert calls[0][1]["guard"] is service.guard
    assert patched["dataModel"]["activity"]["rows"] == [{"day": "2026-09-01"}]
    assert patched["metadata"]["extensions"]["parrot_data_sources"]["activity"]["snapshot_at"] is not None
    assert envelope["dataModel"] == {}  # original input left untouched


async def test_ensure_snapshot_failure_raises(owner, linked_source, monkeypatch) -> None:
    """A failing source maps to SnapshotError(503, "tenant_store_unavailable")."""
    envelope = _dict_envelope(linked_source)

    async def _fake_execute_sources(sources, **kwargs):
        return ExecutionOutcome(outcomes={"activity": SourceOutcome(key="activity", error="tenant_store_unavailable")})

    monkeypatch.setattr(executor_mod, "execute_sources", _fake_execute_sources)
    service = LinkedSurfaceService(guard=_FakeGuard())

    with pytest.raises(SnapshotError) as exc_info:
        await service.ensure_snapshot(envelope, owner_pctx=owner)
    assert exc_info.value.status == 503
    assert exc_info.value.code == "tenant_store_unavailable"


async def test_ensure_snapshot_input_untouched_on_failure(owner, linked_source, monkeypatch) -> None:
    """On failure, the caller's input dict is left completely unmodified (S1: nothing is returned for persistence)."""
    envelope = _dict_envelope(linked_source)
    before = {"dataModel": dict(envelope["dataModel"])}

    async def _fake_execute_sources(sources, **kwargs):
        return ExecutionOutcome(outcomes={"activity": SourceOutcome(key="activity", error="data_stage")})

    monkeypatch.setattr(executor_mod, "execute_sources", _fake_execute_sources)
    service = LinkedSurfaceService(guard=_FakeGuard())

    with pytest.raises(SnapshotError):
        await service.ensure_snapshot(envelope, owner_pctx=owner)

    assert envelope["dataModel"] == before["dataModel"]


async def test_refresh_partial_failure_warnings(owner, linked_source, monkeypatch) -> None:
    """A partial failure is reported as a warning, not an error status (S11)."""
    envelope = _dict_envelope(linked_source)
    other = linked_source.model_copy(update={"slug": "other_slug", "target": "/other/rows"})
    envelope["metadata"]["extensions"]["parrot_data_sources"]["other"] = other.model_dump(mode="json", by_alias=True)

    async def _fake_execute_sources(sources, **kwargs):
        return ExecutionOutcome(
            outcomes={
                "activity": SourceOutcome(key="activity", rows=[{"a": 1}], snapshot_at=datetime.now(timezone.utc)),
                "other": SourceOutcome(key="other", error="query_not_found"),
            }
        )

    monkeypatch.setattr(executor_mod, "execute_sources", _fake_execute_sources)
    service = LinkedSurfaceService(guard=_FakeGuard())

    outcome = await service.refresh(envelope, params={}, owner_pctx=owner)

    assert outcome.error_status is None
    assert outcome.error_code is None
    assert any("other" in warning and "query_not_found" in warning for warning in outcome.warnings)
    assert outcome.envelope["dataModel"]["activity"]["rows"] == [{"a": 1}]


async def test_refresh_all_failed_status(owner, linked_source, monkeypatch) -> None:
    """Every source failing signals error_status/error_code so the caller answers accordingly (S11)."""
    envelope = _dict_envelope(linked_source)

    async def _fake_execute_sources(sources, **kwargs):
        return ExecutionOutcome(outcomes={"activity": SourceOutcome(key="activity", error="tenant_not_available")})

    monkeypatch.setattr(executor_mod, "execute_sources", _fake_execute_sources)
    service = LinkedSurfaceService(guard=_FakeGuard())

    outcome = await service.refresh(envelope, params={}, owner_pctx=owner)

    assert outcome.error_status == 404
    assert outcome.error_code == "tenant_not_available"


async def test_refresh_passes_owner_pctx(owner, linked_source, monkeypatch) -> None:
    """refresh() re-authorises and passes owner_pctx + guard through to execute_sources (AC18)."""
    envelope = _dict_envelope(linked_source)
    guard = _FakeGuard()
    captured: dict[str, Any] = {}

    async def _fake_execute_sources(sources, **kwargs):
        captured.update(kwargs)
        return ExecutionOutcome(
            outcomes={
                "activity": SourceOutcome(key="activity", rows=[{"a": 1}], snapshot_at=datetime.now(timezone.utc))
            }
        )

    monkeypatch.setattr(executor_mod, "execute_sources", _fake_execute_sources)
    service = LinkedSurfaceService(guard=guard)

    await service.refresh(envelope, params={"firstdate": "2026-01-01"}, owner_pctx=owner)

    assert guard.calls, "refresh must re-authorise the owner before executing"
    assert captured["pctx"] is owner
    assert captured["guard"] is guard
    assert captured["param_overrides"]["activity"]["firstdate"] == "2026-01-01"
