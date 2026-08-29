"""Tests for FEAT-473 TASK-2562 — compat shim + attach_structured_artifact helper."""

from __future__ import annotations

from typing import Any

import pytest
from parrot.models.outputs import OutputMode, StructuredChartConfig
from parrot.outputs.a2ui.adapters.structured import (
    chart_to_surface,
    config_to_component_props,
)
from parrot.outputs.a2ui.artifacts import (
    DeepLink,
    RenderedArtifact,
    attach_structured_artifact,
)
from parrot.outputs.a2ui.compat import artifact_definition_to_legacy, is_legacy_artifact
from parrot.outputs.a2ui.serialization import serialize


class _FakeResponse:
    """Minimal AIMessage-shaped stand-in (avoids pulling in bot/agent machinery)."""

    def __init__(self, *, output: dict | None = None, a2ui_envelope: dict | None = None) -> None:
        self.output = output
        self.artifacts: list[dict[str, Any]] = []
        self.artifact_id: str | None = None
        self.a2ui_envelope = a2ui_envelope


@pytest.fixture
def chart_cfg() -> StructuredChartConfig:
    return StructuredChartConfig(type="bar", x="a", y=["b"], stacked=True)


@pytest.fixture
def v2_artifact_entry(chart_cfg) -> dict:
    surface = chart_to_surface(chart_cfg, [{"a": 1, "b": 2}], surface_id="structured_chart-abc123")
    envelope = serialize(surface)
    response = _FakeResponse(a2ui_envelope=envelope)
    attach_structured_artifact(response, OutputMode.STRUCTURED_CHART)
    return response.artifacts[0]


def test_artifact_definition_to_legacy(v2_artifact_entry, chart_cfg):
    legacy = artifact_definition_to_legacy(v2_artifact_entry)
    expected = config_to_component_props(chart_cfg)  # camelCase config, no data/datasets
    assert legacy == expected
    assert "id" not in legacy and "component" not in legacy and "catalogId" not in legacy and "data" not in legacy


def test_is_legacy_artifact():
    assert is_legacy_artifact({}) is True
    assert is_legacy_artifact({"schemaVersion": 1}) is True
    assert is_legacy_artifact({"schemaVersion": 2}) is False


def test_attach_structured_artifact_v2_and_fallback(v2_artifact_entry):
    assert v2_artifact_entry["schemaVersion"] == 2
    assert v2_artifact_entry["surfaceId"] == v2_artifact_entry["artifactId"] == "structured_chart-abc123"

    fallback_response = _FakeResponse(output={"type": "bar", "x": "a", "y": ["b"], "stacked": True})
    art_id = attach_structured_artifact(fallback_response, OutputMode.STRUCTURED_CHART)
    assert art_id == fallback_response.artifact_id == fallback_response.artifacts[0]["artifactId"]
    assert "schemaVersion" not in fallback_response.artifacts[0]
    assert fallback_response.artifacts[0]["definition"] == {"type": "bar", "x": "a", "y": ["b"], "stacked": True}


def test_attach_ignores_non_structured_modes():
    response = _FakeResponse(output={"anything": True})
    assert attach_structured_artifact(response, OutputMode.DEFAULT) is None
    assert response.artifacts == []
    assert response.artifact_id is None


def test_attach_returns_none_without_output_or_envelope():
    response = _FakeResponse()
    assert attach_structured_artifact(response, OutputMode.STRUCTURED_TABLE) is None
    assert response.artifacts == []


def test_existing_artifacts_models_untouched():
    """DeepLink/RenderedArtifact (FEAT-470) are unaffected by this task's additions."""
    link = DeepLink(action_label="Open", url="https://x", token_id="t1", expires_at="2026-01-01T00:00:00Z")
    assert link.token_id == "t1"
    artifact = RenderedArtifact(
        artifact_id="a1", mime_type="application/pdf", content=b"x", filename="f.pdf", title="T", surface="pdf"
    )
    assert artifact.content == b"x"
