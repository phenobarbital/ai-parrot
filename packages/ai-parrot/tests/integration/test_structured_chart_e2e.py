"""FEAT-473 TASK-2566 — STRUCTURED_CHART end-to-end A2UI conformance.

PandasAgent-style chart response → the satellite hook's dual-emit produces a
v1.0 envelope that validates against the catalog allowlist, and
``EChartsRenderer`` (the satellite A2UI renderer) consumes it successfully —
while the legacy G1-G3/G6 (FEAT-215/223/224) config/data contract keeps
passing unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

pytest.importorskip("jsonpointer")


@pytest.mark.asyncio
async def test_structured_chart_e2e_a2ui():
    from parrot.models.outputs import OutputMode, StructuredChartConfig
    from parrot.outputs.a2ui.catalog import validate_envelope
    from parrot.outputs.a2ui.catalog.base import ProducerOrigin
    from parrot.outputs.a2ui.models import A2UIAgentMessage
    from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"month": ["Jan", "Feb"], "sales": [100, 120]})
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"], data=[])
    resp = SimpleNamespace(code=None, data=df, output=cfg, response=None, a2ui_envelope=None, artifact_id=None)

    renderer = get_renderer(OutputMode.STRUCTURED_CHART)()
    out, _explanation = await renderer.render(resp)

    # Legacy FEAT-215/223/224 parity — G1-G3/G6 asserts.
    assert out is not None
    assert "data" not in out
    assert isinstance(resp.data, list) and len(resp.data) == 2
    assert resp.code is None
    assert out["surfaceId"] == resp.artifact_id

    # A2UI envelope validates against the catalog allowlist.
    envelope = resp.a2ui_envelope
    assert envelope is not None and envelope["version"] == "v1.0"
    surface = A2UIAgentMessage.model_validate(envelope).create_surface
    validate_envelope(surface, origin=ProducerOrigin.TOOL)  # must not raise

    # EChartsRenderer (satellite A2UI renderer) consumes it successfully.
    artifact = await EChartsRenderer().render(surface)
    assert artifact.mime_type == "application/json"
    assert artifact.metadata.get("degraded", []) == []
