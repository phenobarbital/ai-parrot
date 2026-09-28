"""build_linked_surface / build_surface(surface_metadata) (FEAT-598 M4)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import parrot.outputs.a2ui.linked
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.builders import build_linked_surface, build_surface
from parrot.outputs.a2ui.models import ComponentMetadata, Extensions, SurfaceMetadata

ENVELOPES = Path(parrot.outputs.a2ui.linked.__file__).parent / "contract" / "fixtures" / "envelopes"
FIXED_AT = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _dump(envelope) -> bytes:
    """Serialize an envelope using the linked fixture convention."""
    return (
        json.dumps(
            envelope.model_dump(mode="json", by_alias=True, exclude_none=True), sort_keys=True, indent=2
        ).encode()
        + b"\n"
    )


def _chart() -> list[dict[str, object]]:
    """Return a linked activity Chart component."""
    return [
        {
            "id": "root",
            "component": "Chart",
            "type": "bar",
            "x": "day",
            "y": ["visits"],
            "data": {"path": "/activity/rows"},
        }
    ]


def _sources(linked_source, *, snapshot_at: datetime | None = None):
    """Return the standard source mapping with an optional fixed snapshot time."""
    return {"activity": linked_source.model_copy(update={"snapshot_at": snapshot_at})}


def test_build_surface_surface_metadata() -> None:
    """Surface metadata lands on the envelope, not on its root component."""
    component_metadata = ComponentMetadata(extensions=Extensions({"parrot_component": True}))
    surface_metadata = SurfaceMetadata(extensions=Extensions({"parrot_surface": True}))

    envelope = build_surface(
        "Text",
        {"text": "hello"},
        surface_id="surface-metadata",
        metadata=component_metadata,
        surface_metadata=surface_metadata,
    )

    assert envelope.metadata == surface_metadata
    assert envelope.components[0].metadata == component_metadata


def test_build_surface_without_surface_metadata_unchanged() -> None:
    """The existing builder path leaves surface metadata absent."""
    envelope = build_surface("Text", {"text": "hello"}, surface_id="no-surface-metadata")
    assert envelope.metadata is None


def test_build_linked_surface_axis_validation(activity_frame, linked_source) -> None:
    """Unknown axes and non-numeric chart series name the offending property."""
    unknown_x = _chart()
    unknown_x[0]["x"] = "missing"
    with pytest.raises(ValueError, match="x 'missing' not in source 'activity'"):
        build_linked_surface(unknown_x, _sources(linked_source), {"activity": activity_frame}, surface_id="bad-x")

    non_numeric_y = _chart()
    non_numeric_y[0]["y"] = ["program"]
    with pytest.raises(ValueError, match="y 'program' in source 'activity' is not numeric"):
        build_linked_surface(non_numeric_y, _sources(linked_source), {"activity": activity_frame}, surface_id="bad-y")


def test_build_linked_surface_snapshot_cap(linked_source) -> None:
    """Snapshots cap rows and mark the copied descriptor as truncated."""
    frame = pd.DataFrame({"day": pd.date_range("2026-09-01", periods=501), "visits": range(501)})
    envelope = build_linked_surface(_chart(), _sources(linked_source), {"activity": frame}, surface_id="capped")

    assert len(envelope.data_model["activity"]["rows"]) == 500
    descriptor = envelope.metadata.extensions.root["parrot_data_sources"]["activity"]
    assert descriptor["snapshot_truncated"] is True
    assert linked_source.snapshot_truncated is False


def test_build_linked_surface_no_snapshot_bakes(activity_frame, linked_source) -> None:
    """No-snapshot envelopes retain resolvable empty rows for baking."""
    envelope = build_linked_surface(
        _chart(), _sources(linked_source), {"activity": activity_frame}, surface_id="no-snapshot", snapshot=False
    )

    assert envelope.data_model == {"activity": {"rows": []}}
    descriptor = envelope.metadata.extensions.root["parrot_data_sources"]["activity"]
    assert descriptor["snapshot_at"] is None
    assert descriptor["snapshot_truncated"] is False
    assert bake_envelope(envelope)


def test_build_linked_surface_origin_tool(activity_frame, linked_source) -> None:
    """A linked descriptor is accepted through the builder's TOOL-origin path."""
    envelope = build_linked_surface(_chart(), _sources(linked_source), {"activity": activity_frame}, surface_id="tool")
    assert envelope.metadata.extensions.root["parrot_data_sources"]


def test_build_linked_surface_golden(activity_frame, linked_source) -> None:
    """The fixed-time snapshot envelope matches its byte-level fixture."""
    envelope = build_linked_surface(
        _chart(),
        _sources(linked_source, snapshot_at=FIXED_AT),
        {"activity": activity_frame.head(3)},
        surface_id="linked-chart",
    )
    assert _dump(envelope) == (ENVELOPES / "linked_chart.json").read_bytes()


def test_build_linked_surface_no_snapshot_golden(activity_frame, linked_source) -> None:
    """The no-snapshot envelope matches its byte-level fixture."""
    envelope = build_linked_surface(
        _chart(),
        _sources(linked_source),
        {"activity": activity_frame.head(3)},
        surface_id="linked-chart",
        snapshot=False,
    )
    assert _dump(envelope) == (ENVELOPES / "linked_no_snapshot.json").read_bytes()
