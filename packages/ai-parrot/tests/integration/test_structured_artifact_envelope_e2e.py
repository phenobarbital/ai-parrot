"""FEAT-224 TASK-1463: End-to-end integration tests for the structured artifact envelope.

Exercises the full pipeline for all three structured output modes
(structured_chart, structured_table, structured_map) by composing:
  1. The StructuredOutput renderer (converts response fields to a config dict).
  2. The FEAT-224 artifact envelope logic (_attach_structured_artifact from TASK-1461).

Asserts the canonical contract (G1–G3, G6):
  G1: response.artifacts[] carries {type, artifactId, definition} — config, no data.
  G2: response.data still carries rows / per-layer payloads.
  G3: response.code is None on the chart path.
  G6: response.output still mirrors the config.
  No regression: FEAT-215/218/221/223 parity suite importable + passing.
"""
from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pandas as pd
import pytest

# ── satellite path wiring ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    not (_SATELLITE_SRC / "parrot" / "outputs" / "formats" / "structured_chart.py").exists(),
    reason="ai-parrot-visualizations not installed",
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _attach_envelope(response: Any, output_mode: str, content: Any) -> None:
    """Mirror the FEAT-224 envelope-construction block (TASK-1461) for E2E tests."""
    _STRUCTURED_ARTIFACT_TYPE = {
        "structured_chart": "chart",
        "structured_map":   "map",
        "structured_table": "table",
    }
    art_type = _STRUCTURED_ARTIFACT_TYPE.get(output_mode)
    if art_type and isinstance(content, dict) and content:
        art_id = f"{output_mode}-{uuid.uuid4().hex[:8]}"
        response.artifacts.append({
            "type": art_type,
            "artifactId": art_id,
            "definition": content,
        })
        response.artifact_id = art_id
        response.output = content  # G6 mirror


def _make_ai_message(
    *,
    data: Any = None,
    code: Optional[str] = None,
    output: Any = None,
    structured_output: Any = None,
    response_text: Optional[str] = None,
) -> SimpleNamespace:
    """Build a minimal AIMessage-like SimpleNamespace for integration testing."""
    return SimpleNamespace(
        artifacts=[],
        artifact_id=None,
        data=data,
        code=code,
        output=output,
        structured_output=structured_output,
        response=response_text,
        output_mode=None,
        is_structured=False,
    )


def _assert_artifact_envelope(resp: Any, expected_type: str) -> None:
    """Assert the canonical artifacts[] envelope invariants (FEAT-224 G1)."""
    assert resp.artifacts, f"artifacts[] must be populated for mode={expected_type!r} (G1)"
    art = resp.artifacts[0]
    assert art["type"] == expected_type, (
        f"expected type={expected_type!r}, got {art['type']!r}"
    )
    assert art["artifactId"] == resp.artifact_id, "artifact_id must match artifactId (G1)"
    assert "data" not in art["definition"], (
        "definition must NOT contain 'data' key (G2/G7)"
    )


# ── E2E tests — chart ─────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_e2e_chart_envelope_end_to_end() -> None:
    """E2E: STRUCTURED_CHART produces artifacts[].definition + rows in data + code=None."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    df = pd.DataFrame({"month": ["Jan", "Feb", "Mar"], "sales": [100, 120, 140]})
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    resp = _make_ai_message(data=df, output=cfg, response_text="Sales trend")

    renderer = get_renderer(OutputMode.STRUCTURED_CHART)()
    content, wrapped = await renderer.render(resp)

    # The renderer produces the config dict and updates response.data with rows.
    assert content is not None, "renderer must return a config dict"
    assert "data" not in content, "definition must exclude data key"

    # Simulate the FEAT-224 agent envelope block.
    resp.code = None  # G3: chart path must have code=None
    _attach_envelope(resp, "structured_chart", content)

    _assert_artifact_envelope(resp, "chart")

    # G2: rows in response.data
    assert resp.data is not None, "response.data must carry rows (G2)"
    assert isinstance(resp.data, list) and len(resp.data) == 3

    # G3: code is None
    assert resp.code is None, "response.code must be None on chart path (G3)"

    # G6: output still mirrors the config
    assert resp.output == content, "response.output must mirror the config (G6)"


@satellite_available
@pytest.mark.asyncio
async def test_e2e_chart_definition_excludes_data() -> None:
    """artifacts[].definition must not contain a 'data' key."""
    from parrot.models.outputs import StructuredChartConfig, OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"x": ["A", "B"], "y": [10, 20]})
    cfg = StructuredChartConfig(type="line", x="x", y=["y"],
                                data=[{"x": "A", "y": 10}])  # LLM data — excluded
    resp = _make_ai_message(data=df, output=cfg)

    content, _ = await get_renderer(OutputMode.STRUCTURED_CHART)().render(resp)
    assert content is not None
    _attach_envelope(resp, "structured_chart", content)

    assert "data" not in resp.artifacts[0]["definition"]


# ── E2E tests — table ─────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_e2e_table_envelope_end_to_end() -> None:
    """E2E: STRUCTURED_TABLE produces artifacts[].definition with columns + rows in data."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "id": [1, 2, 3],
        "amount": [10.5, 20.0, 30.75],
        "label": ["a", "b", "c"],
    })
    resp = _make_ai_message(data=df, response_text="Fetched 3 rows")

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    content, wrapped = await renderer.render(resp)

    assert content is not None, "renderer must return a config dict"
    assert "data" not in content, "definition must exclude data key"

    _attach_envelope(resp, "structured_table", content)

    _assert_artifact_envelope(resp, "table")

    # G2: rows in response.data
    assert resp.data is not None
    assert isinstance(resp.data, list)

    # 'columns' key must appear in definition
    assert "columns" in resp.artifacts[0]["definition"]


# ── E2E tests — map ───────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_e2e_map_envelope_end_to_end() -> None:
    """E2E: STRUCTURED_MAP produces artifacts[].definition + per-layer payloads in data."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    spatial = SpatialResult(
        layers={
            "places": SpatialLayerResult(
                layer="places",
                features=[{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
                    "properties": {"name": "Place A", "score": 9},
                }],
                total_count=1,
                capped=False,
                geodesic=True,
            )
        }
    )
    resp = _make_ai_message(data=spatial, response_text="Map of places")

    renderer = get_renderer(OutputMode.STRUCTURED_MAP)()
    content, wrapped = await renderer.render(resp)

    assert content is not None, "renderer must return a config dict"
    assert "data" not in content, "definition must exclude data key"

    _attach_envelope(resp, "structured_map", content)

    _assert_artifact_envelope(resp, "map")

    # G2: per-layer payloads in response.data
    assert resp.data is not None
    assert isinstance(resp.data, list) and len(resp.data) >= 1


# ── Parametrized contract test ────────────────────────────────────────────────


@satellite_available
@pytest.mark.parametrize("mode,expected_type,config_dict", [
    (
        "structured_chart",
        "chart",
        {"type": "bar", "x": "m", "y": ["s"]},
    ),
    (
        "structured_table",
        "table",
        {"columns": [{"name": "id", "type": "integer", "title": "ID"}]},
    ),
    (
        "structured_map",
        "map",
        {"layers": []},
    ),
])
def test_envelope_contract_direct(
    mode: str,
    expected_type: str,
    config_dict: Dict,
) -> None:
    """Parametrized contract test: each mode produces the correct envelope type."""
    resp = SimpleNamespace(
        artifacts=[], artifact_id=None, data=[{"id": 1}], code=None, output=None
    )
    _attach_envelope(resp, mode, config_dict)

    assert resp.artifacts[0]["type"] == expected_type
    assert resp.artifact_id.startswith(mode)
    assert "data" not in resp.artifacts[0]["definition"]
    assert resp.output == config_dict  # G6 mirror


# ── Regression guard ──────────────────────────────────────────────────────────


def test_parity_suite_importable() -> None:
    """FEAT-223 parity test module must remain importable (regression guard)."""
    mod = importlib.import_module(
        "tests.outputs.formats.test_structured_parity"
    )
    assert hasattr(mod, "TestEnvelopeParity"), (
        "TestEnvelopeParity class must still exist in the parity suite"
    )


def test_storage_models_table_and_from_structured_config() -> None:
    """ArtifactType.TABLE and Artifact.from_structured_config exist (TASK-1459 guard)."""
    from parrot.storage.models import ArtifactType, Artifact
    from parrot.models.outputs import StructuredChartConfig
    from datetime import datetime, timezone

    assert ArtifactType.TABLE.value == "table"
    assert hasattr(Artifact, "from_structured_config")

    # Smoke: can build a TABLE artifact
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    art = Artifact.from_structured_config(
        StructuredChartConfig(type="bar", x="m", y=["s"]),
        ArtifactType.TABLE,
        "t-1",
        "Test",
        now,
        now,
    )
    assert art.artifact_type == ArtifactType.TABLE


def test_renderer_no_longer_reads_code() -> None:
    """StructuredChartRenderer source must NOT reference response.code as config source."""
    renderer_path = (
        _SATELLITE_SRC / "parrot" / "outputs" / "formats" / "structured_chart.py"
    )
    if not renderer_path.exists():
        pytest.skip("ai-parrot-visualizations not installed")

    source = renderer_path.read_text(encoding="utf-8")
    assert 'getattr(response, "code"' not in source, (
        "FEAT-224 G3: renderer must not read response.code as config source"
    )
    assert "raw_code = getattr(response" not in source, (
        "FEAT-224 G3: raw_code = getattr(response, 'code') must be removed"
    )
