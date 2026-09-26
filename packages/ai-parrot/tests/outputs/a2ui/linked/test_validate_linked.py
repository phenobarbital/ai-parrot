"""Surface-level linked-source validation (FEAT-598 M3, AC2)."""

from __future__ import annotations

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.models import Component, CreateSurface, Extensions, SurfaceMetadata


def _envelope(sources: dict, data_model: dict | None = None) -> CreateSurface:
    """Return a Chart surface with linked descriptors bound to activity rows."""
    return CreateSurface(
        surfaceId="linked-validation",
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
        dataModel=data_model or {},
        metadata=SurfaceMetadata(extensions=Extensions({"parrot_data_sources": sources})),
    )


def _codes(exc: CatalogValidationError) -> list[str]:
    """Return validation codes emitted by a catalog error."""
    return [issue["code"] for issue in exc.issues]


def _sources(linked_source, **changes: object) -> dict:
    """Return a JSON-ready source mapping with optional descriptor changes."""
    payload = linked_source.model_dump(mode="json", by_alias=True)
    payload.update(changes)
    return {"activity": payload}


def test_validate_linked_tool_origin_ok(linked_source) -> None:
    """A valid TOOL-origin descriptor passes surface validation."""
    validate_envelope(_envelope(_sources(linked_source)), origin=ProducerOrigin.TOOL)


def test_validate_linked_llm_origin_rejected(linked_source) -> None:
    """LLM-origin envelopes cannot carry linked descriptors."""
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(_envelope(_sources(linked_source)), origin=ProducerOrigin.LLM)
    assert "DATA_SOURCES_NOT_ALLOWED_FOR_LLM" in _codes(exc_info.value)


def test_validate_linked_target_unbound(linked_source) -> None:
    """A target without data-model or component-binding support is rejected."""
    source = linked_source.model_dump(mode="json", by_alias=True)
    source["target"] = "/unbound/rows"
    sources = {"unbound": source}
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(_envelope(sources), origin=ProducerOrigin.TOOL)
    assert "DATA_SOURCE_INVALID" in _codes(exc_info.value)


def test_validate_linked_locked_not_in_params(linked_source) -> None:
    """Locked names outside params are rejected during descriptor parsing."""
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(_envelope(_sources(linked_source, locked=["unknown"])), origin=ProducerOrigin.TOOL)
    assert "DATA_SOURCE_INVALID" in _codes(exc_info.value)


def test_validate_linked_join_with_unknown_key(linked_source) -> None:
    """Join references must name another source in the same surface."""
    sources = _sources(
        linked_source, transform={"ops": [{"op": "join", "with": "missing", "on": [{"left": "id", "right": "id"}]}]}
    )
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(_envelope(sources), origin=ProducerOrigin.TOOL)
    assert "DATA_SOURCE_INVALID" in _codes(exc_info.value)


def test_validate_linked_conditions_mismatch(linked_source) -> None:
    """Conditions remain a cache derived from the canonical request."""
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(
            _envelope(_sources(linked_source, conditions={"firstdate": "BAD"})), origin=ProducerOrigin.TOOL
        )
    assert "DATA_SOURCE_INVALID" in _codes(exc_info.value)


def test_validate_linked_ref_not_in_manifest(linked_source, monkeypatch) -> None:
    """A reference fails closed when no verified transform manifest is available."""
    from parrot.outputs.a2ui.linked import manifest

    monkeypatch.setattr(manifest, "load_manifest", lambda: None)
    sources = _sources(linked_source, transform={"ref": {"name": "group_by_day@1.0.0", "integrity": "sha384-hash"}})
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(_envelope(sources), origin=ProducerOrigin.TOOL)
    assert "TRANSFORM_REF_UNKNOWN" in _codes(exc_info.value)


def test_validate_linked_issues_reported_together(linked_source) -> None:
    """Independent source problems are aggregated into one validation error."""
    sources = _sources(linked_source, conditions={"firstdate": "BAD"})
    sources["activity"]["transform"] = {
        "ops": [{"op": "union", "sources": ["missing"]}],
    }
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(_envelope(sources), origin=ProducerOrigin.TOOL)
    assert _codes(exc_info.value).count("DATA_SOURCE_INVALID") >= 2


def test_envelope_without_descriptor_unchanged() -> None:
    """Existing chart envelopes with no linked descriptor remain valid."""
    envelope = _envelope({}, data_model={"activity": {"rows": []}})
    envelope.metadata = None
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)
