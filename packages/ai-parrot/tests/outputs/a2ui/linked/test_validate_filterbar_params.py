"""FEAT-611 M4 — FilterBar filters[].param validation against parrot_data_sources."""

from __future__ import annotations

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registers FilterBar/Chart
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata


def _envelope(linked_source, param: dict, *, locked: list[str] | None = None) -> CreateSurface:
    """Chart bound to /activity/rows + a FilterBar whose single filter carries `param`."""
    source = linked_source.model_dump(mode="json", by_alias=True)
    if locked is not None:
        source["locked"] = locked
    return CreateSurface(
        surfaceId="fb-validation",
        catalogId=DEFAULT_CATALOG_ID,
        components=[
            Component(id="root", component="Column", children=["chart", "fb"]),
            Component(
                id="chart",
                component="Chart",
                type="bar",
                x="day",
                y=["visits"],
                data={"path": "/activity/rows"},
            ),
            Component(
                id="fb",
                component="FilterBar",
                filters=[{"column": "day", "label": "From", "options": [], "param": param}],
            ),
        ],
        dataModel={},
        metadata=SurfaceMetadata(extensions=Extensions({"parrot_data_sources": {"activity": source}})),
    )


def _codes(envelope: CreateSurface) -> list[str]:
    """Validate ``envelope`` expecting failure and return the emitted issue codes."""
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    return [issue["code"] for issue in exc_info.value.issues]


def test_validate_filterbar_param_unknown_source(linked_source) -> None:
    """A param naming a missing source key emits only FILTER_PARAM_UNKNOWN_SOURCE."""
    envelope = _envelope(linked_source, {"source": "missing", "name": "firstdate"})
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    issues = exc_info.value.issues
    assert [issue["code"] for issue in issues] == ["FILTER_PARAM_UNKNOWN_SOURCE"]
    assert issues[0]["path"] == "fb.filters[0].param"


def test_validate_filterbar_param_undeclared(linked_source) -> None:
    """A param name absent from the source's params emits FILTER_PARAM_UNDECLARED."""
    envelope = _envelope(linked_source, {"source": "activity", "name": "program"})
    assert _codes(envelope) == ["FILTER_PARAM_UNDECLARED"]


def test_validate_filterbar_param_locked(linked_source) -> None:
    """A param name that is locked on the source emits FILTER_PARAM_UNDECLARED."""
    envelope = _envelope(linked_source, {"source": "activity", "name": "firstdate"}, locked=["firstdate"])
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    issues = exc_info.value.issues
    assert [issue["code"] for issue in issues] == ["FILTER_PARAM_UNDECLARED"]
    assert "locked" in issues[0]["message"]


def test_validate_filterbar_param_valid(linked_source) -> None:
    """A binding to a declared, unlocked param on a known source passes validation."""
    envelope = _envelope(linked_source, {"source": "activity", "name": "firstdate"})
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)
