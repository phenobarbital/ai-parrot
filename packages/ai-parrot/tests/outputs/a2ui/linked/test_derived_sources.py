"""Linked dashboards — ``kind: "derived"`` sources across models, executor, service, validation and builders."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers Chart/KPICard/FilterBar
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.builders import build_linked_surface
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked import DerivedDataSource, LinkedDataSource, LinkedSources, SourceRequest
from parrot.outputs.a2ui.linked.executor import dependencies_of, execute_sources, execution_order
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService, SnapshotError
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata
from parrot.tools.dataset_manager.sources import query_slug as qsmod

GROUP_BY_PROGRAM = {"ops": [{"op": "group_by", "by": ["program"], "aggregate": {"visits": "sum"}}]}


@pytest.fixture(autouse=True)
def _real_querysource(monkeypatch):
    """Drop the collection-time ``querysource`` stub so the executor resolves the real package (see test_executor)."""
    for name in list(sys.modules):
        if name == "querysource" or name.startswith("querysource."):
            monkeypatch.delitem(sys.modules, name, raising=False)


@pytest.fixture
def fake_qs(monkeypatch):
    """Patch the lazy QS slot with a recorder that serves canned frames per slug."""
    calls: list[str] = []
    registry: dict[str, Any] = {}

    class _FakeQS:
        def __init__(self, *, slug, conditions, **kwargs):
            self.slug = slug
            calls.append(slug)

        async def query(self, output_format=None):
            result = registry.get(self.slug, pd.DataFrame())
            if isinstance(result, BaseException):
                return None, result
            return result, None

        async def close(self):
            return None

    monkeypatch.setattr(qsmod, "QS", None)
    monkeypatch.setattr(qsmod, "_get_qs", lambda: _FakeQS)
    return calls, registry


def _derived(from_: str, key: str, ops: dict | None = None) -> DerivedDataSource:
    return DerivedDataSource.model_validate(
        {"kind": "derived", "from": from_, "transform": ops or GROUP_BY_PROGRAM, "target": f"/{key}/rows"}
    )


# --- models -----------------------------------------------------------------------------------------------------


def test_derived_model_roundtrip_and_alias() -> None:
    """``from`` is the wire name; ``from_`` the Python attribute; extra keys are rejected."""
    src = _derived("activity", "by_program")
    payload = src.model_dump(mode="json", by_alias=True)
    assert payload["from"] == "activity" and "from_" not in payload
    assert DerivedDataSource.model_validate(payload) == src
    with pytest.raises(ValidationError):
        DerivedDataSource.model_validate({**payload, "slug": "x"})


def test_derived_requires_inline_ops() -> None:
    """A derived source must carry ``transform.ops``; a renderer-side ``ref`` is rejected."""
    with pytest.raises(ValidationError):
        _derived("activity", "v", {"ref": {"name": "group_by_day@1.0.0", "integrity": "sha384-hash"}})
    with pytest.raises(ValidationError):
        DerivedDataSource.model_validate({"kind": "derived", "from": "activity", "target": "/v/rows"})
    with pytest.raises(ValidationError):
        _derived("not a key", "v")


def test_linked_sources_discriminates_on_kind(linked_source) -> None:
    """``LinkedSources`` yields the right model per ``kind`` and defaults a missing ``kind`` to query_slug."""
    legacy = linked_source.model_dump(mode="json", by_alias=True)
    legacy.pop("kind")
    parsed = LinkedSources.model_validate(
        {"activity": legacy, "by_program": _derived("activity", "by_program").model_dump(mode="json", by_alias=True)}
    )
    assert isinstance(parsed.root["activity"], LinkedDataSource)
    assert isinstance(parsed.root["by_program"], DerivedDataSource)
    with pytest.raises(ValidationError):
        LinkedSources.model_validate({"other": _derived("activity", "by_program").model_dump(by_alias=True)})


# --- executor ---------------------------------------------------------------------------------------------------


def test_dependencies_and_order(linked_source) -> None:
    """``from`` is a dependency; derived-of-derived chains order parent-first; cycles fail."""
    sources = {
        "top": _derived("by_program", "top", {"ops": [{"op": "limit", "n": 1}]}),
        "by_program": _derived("activity", "by_program"),
        "activity": linked_source,
    }
    assert dependencies_of(sources["by_program"]) == ["activity"]
    order, failed = execution_order(sources)
    assert order == ["activity", "by_program", "top"] and failed == {}

    cyclic = {"a": _derived("b", "a"), "b": _derived("a", "b")}
    assert execution_order(cyclic) == ([], {"a": "data_stage", "b": "data_stage"})


async def test_execute_derived_from_full_parent_frame(fake_qs, linked_source) -> None:
    """One fetch feeds the parent and every derived view; the base is the FULL frame, not the snapshot."""
    calls, registry = fake_qs
    registry[linked_source.slug] = pd.DataFrame(
        {"program": ["epson", "pokemon"] * 300, "visits": [1] * 600, "day": ["d"] * 600}
    )
    sources = {
        "by_program": _derived("activity", "by_program"),
        "activity": linked_source,
        "count": _derived("by_program", "count", {"ops": [{"op": "limit", "n": 1}]}),
    }

    outcome = await execute_sources(sources, max_snapshot_rows=500, param_overrides={"by_program": {"x": 1}})

    assert calls == [linked_source.slug]  # exactly one QuerySource call
    assert list(outcome.frames) == ["activity", "by_program", "count"]
    assert outcome.outcomes["activity"].truncated is True
    assert outcome.outcomes["by_program"].rows == [
        {"program": "epson", "visits": 300},
        {"program": "pokemon", "visits": 300},
    ]
    assert outcome.outcomes["by_program"].ignored_params == ["x"]
    assert outcome.outcomes["by_program"].snapshot_at is not None
    assert outcome.outcomes["count"].rows == [{"program": "epson", "visits": 300}]


async def test_execute_derived_parent_failure_propagates(fake_qs, linked_source) -> None:
    """A parent that fails at fetch time never runs its derived views, which carry the parent's own error code;
    siblings still run, and a failed query_slug source reports only its locked/undeclared overrides as ignored."""
    from querysource.exceptions import QueryAccessDenied

    calls, registry = fake_qs
    registry[linked_source.slug] = QueryAccessDenied()
    other = linked_source.model_copy(update={"slug": "other_slug", "target": "/other/rows"})
    registry["other_slug"] = pd.DataFrame({"a": [1]})
    sources = {"activity": linked_source, "by_program": _derived("activity", "by_program"), "other": other}

    outcome = await execute_sources(
        sources, param_overrides={"activity": {"firstdate": "2026-01-01", "nope": 1}, "by_program": {"z": 1}}
    )

    assert outcome.outcomes["activity"].error == "query_not_found"
    assert outcome.outcomes["activity"].ignored_params == ["nope"]  # the declared `firstdate` was applied
    assert outcome.outcomes["by_program"].error == "query_not_found"  # the root cause, not a generic data_stage
    assert outcome.outcomes["by_program"].rows is None
    assert outcome.outcomes["by_program"].ignored_params == ["z"]
    assert outcome.outcomes["other"].error is None


async def test_execute_derived_transform_error_isolated(fake_qs, linked_source) -> None:
    """A derived TransformError (unknown column) fails only that view; the parent stays ready."""
    calls, registry = fake_qs
    registry[linked_source.slug] = pd.DataFrame({"program": ["a"], "visits": [1]})
    bad = _derived("activity", "bad", {"ops": [{"op": "select", "columns": ["missing"]}]})

    outcome = await execute_sources({"activity": linked_source, "bad": bad})

    assert outcome.outcomes["activity"].error is None
    assert outcome.outcomes["bad"].error == "data_stage"


# --- service ----------------------------------------------------------------------------------------------------


class _Guard:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def authorize_source(self, ctx: Any, resources: Any) -> None:
        self.calls.append(resources)

    async def rls_predicates(self, ctx: Any, resources: Any) -> list[Any]:
        return []


def _dashboard_envelope(linked_source, data_model: dict | None = None) -> dict:
    """Chart on /by_program/rows (derived from activity) + KPICard on /activity/rows/0/visits."""
    sources = {
        "activity": linked_source.model_dump(mode="json", by_alias=True),
        "by_program": _derived("activity", "by_program").model_dump(mode="json", by_alias=True),
    }
    envelope = CreateSurface(
        surfaceId="linked-derived",
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(id="root", component="Column", children=["kpi", "chart"]),
            Component(id="kpi", component="KPICard", label="Visits", value={"path": "/activity/rows/0/visits"}),
            Component(
                id="chart", component="Chart", type="pie", x="program", y=["visits"], data={"path": "/by_program/rows"}
            ),
        ],
        dataModel=data_model or {},
        metadata=SurfaceMetadata(extensions=Extensions({"parrot_data_sources": sources})),
    )
    return envelope.model_dump(mode="json", by_alias=True)


async def test_service_guard_skips_derived_and_snapshots_it(linked_source, fake_qs) -> None:
    """The guard is consulted once (parent only); ensure_snapshot fills and stamps the derived root too."""
    calls, registry = fake_qs
    registry[linked_source.slug] = pd.DataFrame({"program": ["a", "a"], "visits": [1, 2], "day": ["x", "y"]})
    guard = _Guard()
    service = LinkedSurfaceService(guard=guard)
    owner = build_principal_context("owner-1", channel="ui_surfaces")

    patched = await service.ensure_snapshot(_dashboard_envelope(linked_source), owner_pctx=owner)

    # One owner-level check (the service) + one fetch-time check (AuthorizingDataSource) — both for the parent only.
    assert [r.source_id for r in guard.calls if r.source_id] == ["public:epson_field_activity"]
    assert len(guard.calls) == 2
    assert patched["dataModel"]["by_program"] == {"rows": [{"program": "a", "visits": 3}]}
    assert patched["metadata"]["extensions"]["parrot_data_sources"]["by_program"]["snapshot_at"] is not None


async def test_service_refresh_params_never_broadcast_to_derived(linked_source, fake_qs) -> None:
    """Broadcast params reach query_slug sources only; params addressed to a derived key are reported ignored."""
    calls, registry = fake_qs
    registry[linked_source.slug] = pd.DataFrame({"program": ["a"], "visits": [1], "day": ["x"]})
    service = LinkedSurfaceService(guard=_Guard())
    owner = build_principal_context("owner-1", channel="ui_surfaces")

    outcome = await service.refresh(
        _dashboard_envelope(linked_source), params={"firstdate": "2026-01-01", "by_program": {"z": 1}}, owner_pctx=owner
    )

    assert outcome.error_status is None
    assert outcome.warnings == ["source by_program: ignored params ['z']"]
    assert outcome.envelope["dataModel"]["by_program"]["rows"] == [{"program": "a", "visits": 1}]


async def test_service_snapshot_fails_closed_on_derived_error(linked_source, fake_qs) -> None:
    """A derived view that cannot be computed blocks persistence (502 data_stage)."""
    calls, registry = fake_qs
    registry[linked_source.slug] = pd.DataFrame({"nope": [1]})
    service = LinkedSurfaceService(guard=_Guard())
    owner = build_principal_context("owner-1", channel="ui_surfaces")

    with pytest.raises(SnapshotError) as exc_info:
        await service.ensure_snapshot(_dashboard_envelope(linked_source), owner_pctx=owner)
    assert (exc_info.value.status, exc_info.value.code) == (502, "data_stage")


# --- validation -------------------------------------------------------------------------------------------------


def _codes(envelope: CreateSurface) -> list[str]:
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    return [issue["code"] for issue in exc_info.value.issues]


def _validation_envelope(sources: dict, *, filters: list[dict] | None = None) -> CreateSurface:
    components = [
        Component(id="root", component="Column", children=["chart"] + (["fb"] if filters else [])),
        Component(id="chart", component="Chart", type="pie", x="program", y=["visits"], data={"path": "/view/rows"}),
    ]
    if filters:
        components.append(Component(id="fb", component="FilterBar", filters=filters))
    return CreateSurface(
        surfaceId="derived-validation",
        catalogId=DEFAULT_CATALOG_ID,
        components=components,
        dataModel={"activity": {"rows": []}},
        metadata=SurfaceMetadata(extensions=Extensions({"parrot_data_sources": sources})),
    )


def test_validate_derived_ok(linked_source) -> None:
    sources = {
        "activity": linked_source.model_dump(mode="json", by_alias=True),
        "view": _derived("activity", "view").model_dump(mode="json", by_alias=True),
    }
    validate_envelope(_validation_envelope(sources), origin=ProducerOrigin.TOOL)


def test_validate_derived_bad_parent(linked_source) -> None:
    """``from`` must name a sibling; self-reference and unknown keys are ONE DATA_SOURCE_INVALID each (never an
    extra "cycle" issue), and a dependent of a broken parent is not reported as a cycle."""
    activity = linked_source.model_dump(mode="json", by_alias=True)
    unknown = {"activity": activity, "view": _derived("missing", "view").model_dump(mode="json", by_alias=True)}
    assert _codes(_validation_envelope(unknown)) == ["DATA_SOURCE_INVALID"]
    self_ref = {"activity": activity, "view": _derived("view", "view").model_dump(mode="json", by_alias=True)}
    assert _codes(_validation_envelope(self_ref)) == ["DATA_SOURCE_INVALID"]
    ghost_parent = dict(activity, transform={"ops": [{"op": "union", "sources": ["ghost"]}]})
    chained = {"activity": ghost_parent, "view": _derived("activity", "view").model_dump(mode="json", by_alias=True)}
    issues = _codes(_validation_envelope(chained))
    assert issues == ["DATA_SOURCE_INVALID"], "only the ghost union reference is reported, never a cycle"


def test_linked_sources_kindless_from_is_derived() -> None:
    """A kind-less descriptor carrying ``from`` is tagged derived, so its validation error names the derived shape."""
    with pytest.raises(ValidationError) as exc_info:
        LinkedSources.model_validate({"view": {"from": "activity", "target": "/view/rows"}})
    assert "derived" in str(exc_info.value) and "transform" in str(exc_info.value)


def test_validate_derived_parent_with_ref_rejected(linked_source, monkeypatch) -> None:
    from parrot.outputs.a2ui.linked import manifest

    class _Manifest:
        entries = {"group_by_day@1.0.0": object()}

    monkeypatch.setattr(manifest, "load_manifest", lambda: _Manifest())
    activity = linked_source.model_dump(mode="json", by_alias=True)
    activity["transform"] = {"ref": {"name": "group_by_day@1.0.0", "integrity": "sha384-hash"}}
    sources = {"activity": activity, "view": _derived("activity", "view").model_dump(mode="json", by_alias=True)}
    codes = _codes(_validation_envelope(sources))
    assert codes == ["DATA_SOURCE_INVALID"]


def test_validate_derived_cycle(linked_source) -> None:
    sources = {
        "activity": linked_source.model_dump(mode="json", by_alias=True),
        "view": _derived("other", "view").model_dump(mode="json", by_alias=True),
        "other": _derived("view", "other").model_dump(mode="json", by_alias=True),
    }
    envelope = _validation_envelope(sources)
    envelope.data_model["other"] = {"rows": []}
    assert _codes(envelope).count("DATA_SOURCE_INVALID") == 2


def test_validate_filterbar_param_on_derived(linked_source) -> None:
    sources = {
        "activity": linked_source.model_dump(mode="json", by_alias=True),
        "view": _derived("activity", "view").model_dump(mode="json", by_alias=True),
    }
    filters = [{"column": "program", "label": "P", "options": [], "param": {"source": "view", "name": "firstdate"}}]
    assert _codes(_validation_envelope(sources, filters=filters)) == ["FILTER_PARAM_UNDECLARED"]


# --- builders ---------------------------------------------------------------------------------------------------


def test_build_linked_surface_derived_and_inline(activity_frame, linked_source) -> None:
    """Derived frames are validated/snapshotted like any source; inline roots are embedded without a descriptor."""
    by_program = activity_frame.groupby("program", sort=False, as_index=False)["visits"].sum()
    components = [
        {"id": "root", "component": "Column", "children": ["chart", "kpi", "static"]},
        {
            "id": "chart",
            "component": "Chart",
            "type": "pie",
            "x": "program",
            "y": ["visits"],
            "data": {"path": "/by_program/rows"},
        },
        {"id": "kpi", "component": "KPICard", "label": "Visits", "value": {"path": "/activity/rows/0/visits"}},
        {"id": "static", "component": "Chart", "type": "bar", "x": "k", "y": ["v"], "data": {"path": "/static/rows"}},
    ]
    sources = {"activity": linked_source, "by_program": _derived("activity", "by_program")}
    frames = {"activity": activity_frame, "by_program": by_program}
    inline = {"static": [{"k": "a", "v": 1}, {"k": "b", "v": 2}]}
    fixed = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    envelope = build_linked_surface(components, sources, frames, surface_id="derived", inline=inline)

    assert envelope.data_model["static"] == {"rows": inline["static"]}
    assert envelope.data_model["by_program"]["rows"] == [
        {"program": "epson", "visits": 360},
        {"program": "pokemon", "visits": 420},
    ]
    descriptors = envelope.metadata.extensions.root["parrot_data_sources"]
    assert descriptors["by_program"]["kind"] == "derived" and descriptors["by_program"]["from"] == "activity"
    assert descriptors["by_program"]["snapshot_at"] is not None and "static" not in descriptors
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)

    bad = [dict(components[3], y=["k"])]
    with pytest.raises(ValueError, match="y 'k' in source 'static' is not numeric"):
        build_linked_surface(bad, sources, frames, surface_id="derived", inline=inline)
    with pytest.raises(ValueError, match="collide"):
        build_linked_surface(components, sources, frames, surface_id="derived", inline={"activity": []})
    assert build_linked_surface(components, sources, frames, surface_id="d", inline=inline, snapshot=False).data_model[
        "by_program"
    ] == {"rows": []}
    assert fixed  # keeps the fixture import meaningful for golden-style comparisons below


def test_build_linked_surface_derived_missing_frame(activity_frame, linked_source) -> None:
    sources = {"activity": linked_source, "by_program": _derived("activity", "by_program")}
    components = [
        {
            "id": "root",
            "component": "Chart",
            "type": "bar",
            "x": "program",
            "y": ["visits"],
            "data": {"path": "/by_program/rows"},
        }
    ]
    with pytest.raises(ValueError, match="source 'by_program' has no frame"):
        build_linked_surface(components, sources, {"activity": activity_frame}, surface_id="x")
