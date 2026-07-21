"""FEAT-223 TASK-1458: Cross-renderer homologation + library-mode retention tests.

Proves that the shared StructuredOutputBase contract holds uniformly across all
three structured renderers (table / chart / map) and that library-specific
OutputModes have NOT been removed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# ── Satellite path wiring ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed",
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _resp(**kwargs):
    """Build a minimal AIMessage-like SimpleNamespace."""
    defaults = {"data": None, "code": None, "output": None, "response": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _assert_envelope(out, wrapped, resp, *, explanation=None):
    """Assert the shared envelope invariants that every structured renderer must satisfy."""
    assert out is not None, "output must not be None on success"
    assert "data" not in out, "data key must be excluded from output"
    assert resp.data is not None, "response.data must be populated after render"
    if explanation is not None:
        assert wrapped == explanation, f"expected wrapped={explanation!r}, got {wrapped!r}"


# ─────────────────────────────────────────────────────────────────────────────
# TestEnvelopeParity — table / chart / map all share the same envelope contract
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
class TestEnvelopeParity:
    """All three structured renderers must satisfy the same envelope invariants."""

    @pytest.mark.asyncio
    async def test_table_envelope(self):
        """StructuredTableRenderer: data excluded; rows in response.data; explanation wrapped."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.formats import get_renderer

        df = pd.DataFrame({"cat": ["A", "B"], "val": [1, 2]})
        resp = _resp(data=df, response="table explanation")
        out, wrapped = await get_renderer(OutputMode.STRUCTURED_TABLE)().render(resp)

        _assert_envelope(out, wrapped, resp, explanation="table explanation")
        assert isinstance(resp.data, list) and len(resp.data) == 2

    @pytest.mark.asyncio
    async def test_chart_envelope(self):
        """StructuredChartRenderer: data excluded; rows in response.data; explanation wrapped.

        FEAT-224: config is now supplied via response.output (not response.code).
        """
        from parrot.models.outputs import OutputMode, StructuredChartConfig
        from parrot.outputs.formats import get_renderer

        df = pd.DataFrame({"month": ["Jan", "Feb"], "sales": [100, 120]})
        cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
        resp = _resp(data=df, output=cfg, response="chart explanation")
        out, wrapped = await get_renderer(OutputMode.STRUCTURED_CHART)().render(resp)

        _assert_envelope(out, wrapped, resp, explanation="chart explanation")
        assert isinstance(resp.data, list) and len(resp.data) == 2

    @pytest.mark.asyncio
    async def test_map_conforms_to_same_envelope(self):
        """StructuredMapRenderer: data excluded; payloads in response.data; explanation wrapped."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.formats import get_renderer
        from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

        spatial = SpatialResult(
            layers={
                "places": SpatialLayerResult(
                    layer="places",
                    features=[
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
                            "properties": {"name": "Place A", "score": 9},
                        }
                    ],
                    total_count=1,
                    capped=False,
                    geodesic=True,
                )
            }
        )
        resp = _resp(data=spatial, response="map explanation")
        out, wrapped = await get_renderer(OutputMode.STRUCTURED_MAP)().render(resp)

        _assert_envelope(out, wrapped, resp, explanation="map explanation")
        assert isinstance(resp.data, list) and len(resp.data) >= 1

    @pytest.mark.asyncio
    async def test_all_three_exclude_data_key(self):
        """All three structured renderers exclude 'data' from output — the universal invariant."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.formats import get_renderer
        from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

        # table
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
        resp_t = _resp(data=df)
        out_t, _ = await get_renderer(OutputMode.STRUCTURED_TABLE)().render(resp_t)
        assert out_t is not None and "data" not in out_t

        # chart — FEAT-224: config via response.output (not response.code)
        from parrot.models.outputs import StructuredChartConfig
        df2 = pd.DataFrame({"x": ["A", "B"], "y": [10, 20]})
        cfg_obj = StructuredChartConfig(type="bar", x="x", y=["y"])
        resp_c = _resp(data=df2, output=cfg_obj)
        out_c, _ = await get_renderer(OutputMode.STRUCTURED_CHART)().render(resp_c)
        assert out_c is not None and "data" not in out_c

        # map
        spatial = SpatialResult(
            layers={
                "pts": SpatialLayerResult(
                    layer="pts",
                    features=[{
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                        "properties": {"id": 1},
                    }],
                    total_count=1, capped=False, geodesic=True,
                )
            }
        )
        resp_m = _resp(data=spatial)
        out_m, _ = await get_renderer(OutputMode.STRUCTURED_MAP)().render(resp_m)
        assert out_m is not None and "data" not in out_m


# ─────────────────────────────────────────────────────────────────────────────
# TestChartDeterminismIntegration — integration-level proof of TASK-1455 contract
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
class TestChartDeterminismIntegration:
    """Integration-level proof that StructuredChartRenderer rows come from the DataFrame."""

    @pytest.mark.asyncio
    async def test_rows_from_response_data_not_cfg_data(self):
        """Rows in response.data come from the injected DataFrame, not cfg.data.

        FEAT-224: config is now supplied via response.output (not response.code).
        """
        from parrot.models.outputs import OutputMode, StructuredChartConfig
        from parrot.outputs.formats import get_renderer

        df = pd.DataFrame({"region": ["N", "S", "E"], "revenue": [10, 20, 30]})
        # LLM emits no rows (data=[]) — real rows come from the DataFrame
        cfg = StructuredChartConfig(type="bar", x="region", y=["revenue"], data=[])
        resp = _resp(data=df, output=cfg)
        out, _ = await get_renderer(OutputMode.STRUCTURED_CHART)().render(resp)

        assert out is not None
        assert isinstance(resp.data, list) and len(resp.data) == 3
        assert resp.data[0]["region"] == "N"

    @pytest.mark.asyncio
    async def test_xy_in_real_columns(self):
        """x/y in the emitted config are always members of the real column set.

        FEAT-224: config is now supplied via response.output (not response.code).
        """
        from parrot.models.outputs import OutputMode, StructuredChartConfig
        from parrot.outputs.formats import get_renderer

        df = pd.DataFrame({"cat": ["A", "B"], "amount": [5, 10]})
        cfg = StructuredChartConfig(type="line", x="cat", y=["amount"], data=[])
        resp = _resp(data=df, output=cfg)
        out, _ = await get_renderer(OutputMode.STRUCTURED_CHART)().render(resp)

        assert out is not None
        cols = set(resp.data[0].keys())
        assert out["x"] in cols
        assert all(y in cols for y in out["y"])

    @pytest.mark.asyncio
    async def test_absent_xy_deterministic_fallback(self):
        """Absent LLM x/y → first categorical = x, first numeric = y.

        FEAT-224: config is now supplied via response.output (not response.code).
        """
        from parrot.models.outputs import OutputMode, StructuredChartConfig
        from parrot.outputs.formats import get_renderer

        df = pd.DataFrame({"grp": ["X", "Y"], "cnt": [5, 10]})
        cfg = StructuredChartConfig(type="bar", x="absent_col", y=["also_absent"], data=[])
        resp = _resp(data=df, output=cfg)
        out, _ = await get_renderer(OutputMode.STRUCTURED_CHART)().render(resp)

        assert out is not None
        assert out["x"] == "grp"
        assert out["y"] == ["cnt"]


# ─────────────────────────────────────────────────────────────────────────────
# TestOutputModeSymbols — ArtifactType.MAP + STRUCTURED_MAP exist
# ─────────────────────────────────────────────────────────────────────────────


def test_outputmode_structured_map_exists():
    """OutputMode.STRUCTURED_MAP exists with the correct string value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_MAP.value == "structured_map"
    assert OutputMode("structured_map") is OutputMode.STRUCTURED_MAP


def test_artifacttype_map_value():
    """ArtifactType.MAP = 'map' is present (added by TASK-1457)."""
    _wt_src = Path(__file__).resolve().parents[3] / "src"
    _spec = importlib.util.spec_from_file_location(
        "parrot.storage.models_parity",
        _wt_src / "parrot" / "storage" / "models.py",
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    assert hasattr(_mod.ArtifactType, "MAP")
    assert _mod.ArtifactType.MAP == "map"


def test_all_structured_modes_exist():
    """All three structured OutputMode members exist."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_TABLE.value == "structured_table"
    assert OutputMode.STRUCTURED_CHART.value == "structured_chart"
    assert OutputMode.STRUCTURED_MAP.value == "structured_map"


# ─────────────────────────────────────────────────────────────────────────────
# TestLibraryModesRemain — library-specific modes have NOT been removed
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
class TestLibraryModesRemain:
    """Remaining library-specific OutputModes still resolve to their renderers."""

    @pytest.mark.parametrize("mode_value,expected_cls", [
        ("echarts",     "EChartsRenderer"),
        ("table",       "TableRenderer"),
    ])
    def test_library_mode_still_resolves(self, mode_value, expected_cls):
        """Library-specific renderer still resolves via get_renderer."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.formats import get_renderer

        mode = OutputMode(mode_value)
        renderer_cls = get_renderer(mode)
        assert renderer_cls is not None, f"get_renderer({mode_value!r}) returned None"
        assert renderer_cls.__name__ == expected_cls, (
            f"Expected {expected_cls!r}, got {renderer_cls.__name__!r}"
        )

    def test_structured_modes_still_resolve(self):
        """The three structured modes also resolve (regression guard)."""
        from parrot.models.outputs import OutputMode
        from parrot.outputs.formats import get_renderer

        for mode in (
            OutputMode.STRUCTURED_TABLE,
            OutputMode.STRUCTURED_CHART,
            OutputMode.STRUCTURED_MAP,
        ):
            r = get_renderer(mode)
            assert r is not None, f"get_renderer({mode!r}) returned None"


# ─────────────────────────────────────────────────────────────────────────────
# TestConvergenceSerialization — ChartBlock + Artifact CHART definition
# ─────────────────────────────────────────────────────────────────────────────


class TestConvergenceSerialization:
    """StructuredChartConfig is the canonical chart shape for all three consumers."""

    def test_structured_chart_config_is_canonical(self):
        """StructuredChartConfig round-trips through model_dump(by_alias=True)."""
        from parrot.models.outputs import StructuredChartConfig

        cfg = StructuredChartConfig(
            type="bar", x="cat", y=["val"],
            title="Chart", show_legend=True,
            data=[{"cat": "A", "val": 1}],
        )
        dumped = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
        assert "data" not in dumped
        assert dumped["type"] == "bar"
        assert dumped["showLegend"] is True

    def test_chartblock_serializes_to_agnostic_shape(self):
        """ChartBlock.to_chart_config() returns a StructuredChartConfig with camelCase aliases."""
        from parrot.models.infographic import ChartBlock, ChartDataSeries, ChartType
        from parrot.models.outputs import StructuredChartConfig

        block = ChartBlock(
            chart_type=ChartType.LINE,
            labels=["Jan", "Feb"],
            series=[ChartDataSeries(name="revenue", values=[10, 20])],
            show_legend=True,
        )
        cfg = block.to_chart_config()
        assert isinstance(cfg, StructuredChartConfig)
        dumped = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
        assert "showLegend" in dumped
        assert "data" not in dumped

    def test_artifact_chart_definition_carries_converged_shape(self):
        """Artifact.from_chart_config stores StructuredChartConfig (camelCase, no data)."""
        from datetime import datetime, timezone
        from parrot.models.outputs import StructuredChartConfig
        import importlib.util as _ilu
        from pathlib import Path as _P
        _wt_src = _P(__file__).resolve().parents[3] / "src"
        _spec = _ilu.spec_from_file_location("parrot.storage.models_conv", _wt_src / "parrot" / "storage" / "models.py")
        _m = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        Artifact = _m.Artifact
        ArtifactType = _m.ArtifactType

        cfg = StructuredChartConfig(
            type="bar", x="m", y=["v"],
            show_legend=False,
            data=[{"m": "Jan", "v": 1}],
        )
        now = datetime.now(timezone.utc)
        art = Artifact.from_chart_config(cfg, artifact_id="p-001", title="T",
                                          created_at=now, updated_at=now)

        assert art.artifact_type == ArtifactType.CHART
        assert "data" not in art.definition
        assert art.definition.get("type") == "bar"
        assert "showLegend" in art.definition
