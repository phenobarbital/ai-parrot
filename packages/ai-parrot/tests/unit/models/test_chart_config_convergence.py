"""FEAT-223 TASK-1456: Chart config convergence tests.

Verifies that ChartBlock, StructuredChartConfig, and Artifact.CHART all speak
the same agnostic shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Prepend the worktree's core src so modified models take priority over the
# editable install from the main repo.
# File lives at: packages/ai-parrot/tests/unit/models/<file>.py
# parents[3] = packages/ai-parrot  → "src" gives packages/ai-parrot/src
_WT_CORE_SRC = Path(__file__).resolve().parents[3] / "src"
if _WT_CORE_SRC.exists() and str(_WT_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_WT_CORE_SRC))

# Load storage.models directly (bypasses the broken storage/__init__.py import chain)
def _load_storage_models():
    """Load parrot.storage.models without triggering the storage package __init__."""
    import importlib.util
    _models_path = _WT_CORE_SRC / "parrot" / "storage" / "models.py"
    _spec = importlib.util.spec_from_file_location("parrot.storage.models", _models_path)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules.setdefault("parrot.storage.models", _mod)
    if not hasattr(_mod, "Artifact"):
        _spec.loader.exec_module(_mod)
        sys.modules["parrot.storage.models"] = _mod
    return _mod


_storage_models = _load_storage_models()

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from parrot.models.infographic import ChartBlock, ChartDataSeries, ChartType, TableBlock
from parrot.models.outputs import StructuredChartConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_block() -> ChartBlock:
    return ChartBlock(
        chart_type=ChartType.BAR,
        title="Revenue by Month",
        description="Q1 breakdown",
        labels=["Jan", "Feb", "Mar"],
        series=[
            ChartDataSeries(name="revenue", values=[100, 120, 90]),
            ChartDataSeries(name="cost", values=[60, 70, 55]),
        ],
        stacked=False,
        show_legend=True,
        color_by_sign=False,
    )


@pytest.fixture
def sample_cfg() -> StructuredChartConfig:
    return StructuredChartConfig(
        type="bar",
        x="month",
        y=["revenue", "cost"],
        title="Revenue by Month",
        description="Q1 breakdown",
        stacked=False,
        show_legend=True,
        data=[
            {"month": "Jan", "revenue": 100, "cost": 60},
            {"month": "Feb", "revenue": 120, "cost": 70},
            {"month": "Mar", "revenue": 90, "cost": 55},
        ],
    )


# ── Impl-2 audit: StructuredChartConfig new fields ────────────────────────────


def test_structured_chart_config_has_positive_color():
    """`StructuredChartConfig` now carries `positive_color` (alias positiveColor)."""
    cfg = StructuredChartConfig(
        type="bar", x="m", y=["v"], positive_color="#00C853", data=[]
    )
    assert cfg.positive_color == "#00C853"
    dumped = cfg.model_dump(by_alias=True)
    assert "positiveColor" in dumped
    assert dumped["positiveColor"] == "#00C853"


def test_structured_chart_config_has_axis_labels():
    """`StructuredChartConfig` now carries xAxisLabel / yAxisLabel."""
    cfg = StructuredChartConfig(
        type="bar", x="m", y=["v"],
        x_axis_label="Month", y_axis_label="Amount (USD)", data=[]
    )
    assert cfg.x_axis_label == "Month"
    assert cfg.y_axis_label == "Amount (USD)"
    dumped = cfg.model_dump(by_alias=True)
    assert dumped["xAxisLabel"] == "Month"
    assert dumped["yAxisLabel"] == "Amount (USD)"


# ── ChartBlock.to_chart_config ────────────────────────────────────────────────


class TestChartBlockToConfig:
    def test_serializes_agnostic_config(self, sample_block):
        """ChartBlock.to_chart_config() returns a StructuredChartConfig."""
        cfg = sample_block.to_chart_config()
        assert isinstance(cfg, StructuredChartConfig)

    def test_camelcase_dump(self, sample_block):
        """The converted config dumps with camelCase aliases."""
        cfg = sample_block.to_chart_config()
        dumped = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
        assert "showLegend" in dumped
        assert "colorBySign" in dumped

    def test_type_preserved(self, sample_block):
        cfg = sample_block.to_chart_config()
        assert cfg.type == "bar"

    def test_y_cols_are_series_names(self, sample_block):
        cfg = sample_block.to_chart_config()
        assert set(cfg.y) == {"revenue", "cost"}

    def test_rows_built_from_labels_series(self, sample_block):
        cfg = sample_block.to_chart_config()
        assert len(cfg.data) == 3
        assert cfg.data[0]["revenue"] == 100
        assert cfg.data[1]["cost"] == 70

    def test_presentation_fields_preserved(self, sample_block):
        cfg = sample_block.to_chart_config()
        assert cfg.title == "Revenue by Month"
        assert cfg.description == "Q1 breakdown"
        assert cfg.stacked is False
        assert cfg.show_legend is True

    def test_color_by_sign_fields_round_trip(self):
        block = ChartBlock(
            chart_type=ChartType.BAR,
            labels=["A"],
            series=[ChartDataSeries(name="v", values=[1])],
            color_by_sign=True,
            positive_color="#00C853",
            negative_color="#D32F2F",
        )
        cfg = block.to_chart_config()
        assert cfg.color_by_sign is True
        assert cfg.positive_color == "#00C853"
        assert cfg.negative_color == "#D32F2F"

    def test_axis_labels_round_trip(self):
        block = ChartBlock(
            chart_type=ChartType.LINE,
            labels=["Jan", "Feb"],
            series=[ChartDataSeries(name="sales", values=[10, 20])],
            x_axis_label="Month",
            y_axis_label="Sales",
        )
        cfg = block.to_chart_config()
        assert cfg.x_axis_label == "Month"
        assert cfg.y_axis_label == "Sales"
        # x column name should be x_axis_label when set
        assert cfg.x == "Month"


# ── ChartBlock.from_chart_config ──────────────────────────────────────────────


class TestChartBlockFromConfig:
    def test_creates_chart_block(self, sample_cfg):
        block = ChartBlock.from_chart_config(sample_cfg)
        assert isinstance(block, ChartBlock)

    def test_labels_from_data(self, sample_cfg):
        block = ChartBlock.from_chart_config(sample_cfg)
        assert block.labels == ["Jan", "Feb", "Mar"]

    def test_series_from_y_cols(self, sample_cfg):
        block = ChartBlock.from_chart_config(sample_cfg)
        names = {s.name for s in block.series}
        assert names == {"revenue", "cost"}

    def test_series_values_correct(self, sample_cfg):
        block = ChartBlock.from_chart_config(sample_cfg)
        revenue_series = next(s for s in block.series if s.name == "revenue")
        assert revenue_series.values == [100, 120, 90]

    def test_presentation_preserved(self, sample_cfg):
        block = ChartBlock.from_chart_config(sample_cfg)
        assert block.title == "Revenue by Month"
        assert block.stacked is False
        assert block.show_legend is True

    def test_unknown_type_defaults_to_bar(self):
        cfg = StructuredChartConfig(
            type="horizontalBar", x="m", y=["v"],
            data=[{"m": "A", "v": 1}],
        )
        block = ChartBlock.from_chart_config(cfg)
        assert block.chart_type == ChartType.BAR


class TestChartBlockNormalizesLLMShapes:
    """``ChartBlock`` accepts the record-oriented shapes LLMs actually emit.

    ``labels`` + ``series[].values`` is column-oriented; a model handed a
    DataFrame reaches for row records instead. Rejecting that burned agent
    retries on a purely notational mismatch (an LLM would send
    ``chart.data=[{...}]`` or ``series[].data``, get "Field required" for
    ``labels``/``series``, and often fail the whole render).
    """

    def test_records_under_data_become_labels_and_series(self):
        block = ChartBlock.model_validate({
            "type": "chart", "chart_type": "line", "title": "MRR trend",
            "data": [
                {"month": "Nov", "mrr": 1150804.33, "new_mrr": 48121.42},
                {"month": "Dec", "mrr": 1204934.63, "new_mrr": 74855.18},
            ],
        })
        assert block.labels == ["Nov", "Dec"]
        assert {s.name for s in block.series} == {"mrr", "new_mrr"}
        mrr = next(s for s in block.series if s.name == "mrr")
        assert mrr.values == [1150804.33, 1204934.63]

    def test_series_data_key_is_accepted_as_values(self):
        block = ChartBlock.model_validate({
            "type": "chart", "chart_type": "line", "labels": ["Nov", "Dec"],
            "series": [{"name": "MRR", "data": [1150804.33, 1204934.63]}],
        })
        assert block.series[0].values == [1150804.33, 1204934.63]

    def test_explicit_x_field_wins_over_first_key(self):
        block = ChartBlock.model_validate({
            "type": "chart", "chart_type": "bar", "x_field": "plan",
            "data": [{"mrr": 1.0, "plan": "Team"}, {"mrr": 2.0, "plan": "Pro"}],
        })
        assert block.labels == ["Team", "Pro"]
        assert [s.name for s in block.series] == ["mrr"]

    def test_records_under_rows_are_also_accepted(self):
        block = ChartBlock.model_validate({
            "type": "chart", "chart_type": "bar",
            "rows": [{"plan": "Team", "mrr": 1.0}],
        })
        assert block.labels == ["Team"]

    def test_canonical_shape_is_untouched(self):
        block = ChartBlock.model_validate({
            "type": "chart", "chart_type": "pie", "labels": ["a", "b"],
            "series": [{"name": "s", "values": [1, 2]}],
        })
        assert block.labels == ["a", "b"]
        assert block.series[0].values == [1, 2]

    def test_still_rejects_a_chart_with_no_data_at_all(self):
        with pytest.raises(ValidationError):
            ChartBlock.model_validate({"type": "chart", "chart_type": "line"})

    def test_still_rejects_records_with_only_an_x_column(self):
        with pytest.raises(ValidationError):
            ChartBlock.model_validate({
                "type": "chart", "chart_type": "line",
                "data": [{"month": "Nov"}, {"month": "Dec"}],
            })


class TestTableBlockNormalizesLLMShapes:
    """``TableBlock`` accepts records under ``data``, like ``ChartBlock`` does.

    Same failure, same turn cost: a model handed a DataFrame writes
    ``table.data=[{...}]`` and got "Field required" for ``columns``/``rows``.
    """

    def test_records_under_data_become_columns_and_rows(self):
        block = TableBlock.model_validate({
            "type": "table", "title": "Monthly detail",
            "data": [
                {"month": "Nov", "mrr": 1150804.33},
                {"month": "Dec", "mrr": 1204934.63},
            ],
        })
        assert block.columns == ["month", "mrr"]
        assert block.rows == [["Nov", 1150804.33], ["Dec", 1204934.63]]

    def test_dict_rows_without_columns_are_accepted(self):
        block = TableBlock.model_validate({
            "type": "table", "rows": [{"plan": "Team", "mrr": 1.0}],
        })
        assert block.columns == ["plan", "mrr"]
        assert block.rows == [["Team", 1.0]]

    def test_existing_dict_rows_with_columns_path_still_works(self):
        block = TableBlock.model_validate({
            "type": "table", "columns": ["month", "mrr"],
            "rows": [{"month": "Dec", "mrr": 1.2}],
        })
        assert block.rows == [["Dec", 1.2]]

    def test_canonical_shape_is_untouched(self):
        block = TableBlock.model_validate({
            "type": "table", "columns": ["a", "b"], "rows": [[1, 2]],
        })
        assert block.columns == ["a", "b"]
        assert block.rows == [[1, 2]]

    def test_still_rejects_a_table_with_no_data_at_all(self):
        with pytest.raises(ValidationError):
            TableBlock.model_validate({"type": "table", "title": "empty"})


# ── Round-trip ────────────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_roundtrip_chartblock_to_config(self, sample_block):
        """ChartBlock → StructuredChartConfig → ChartBlock preserves rows + presentation."""
        cfg = sample_block.to_chart_config()
        reconstructed = ChartBlock.from_chart_config(cfg)

        assert reconstructed.labels == sample_block.labels
        orig_names = {s.name for s in sample_block.series}
        recon_names = {s.name for s in reconstructed.series}
        assert orig_names == recon_names
        assert reconstructed.title == sample_block.title
        assert reconstructed.stacked == sample_block.stacked

    def test_roundtrip_config_to_chartblock_and_back(self, sample_cfg):
        """StructuredChartConfig → ChartBlock → StructuredChartConfig round-trips cleanly."""
        block = ChartBlock.from_chart_config(sample_cfg)
        cfg2 = block.to_chart_config()

        assert cfg2.type == sample_cfg.type
        assert set(cfg2.y) == set(sample_cfg.y)
        assert len(cfg2.data) == len(sample_cfg.data)


# ── Artifact.from_chart_config / as_chart_config ─────────────────────────────


class TestArtifactChartDefinition:
    @pytest.fixture(autouse=True)
    def _models(self):
        self.Artifact = _storage_models.Artifact
        self.ArtifactType = _storage_models.ArtifactType

    def test_artifact_chart_definition_is_converged_shape(self, sample_cfg):
        """Artifact CHART definition carries StructuredChartConfig (no 'data' key)."""
        now = datetime.now(timezone.utc)
        artifact = self.Artifact.from_chart_config(
            cfg=sample_cfg,
            artifact_id="test-001",
            title="Revenue Chart",
            created_at=now,
            updated_at=now,
        )

        assert artifact.artifact_type == self.ArtifactType.CHART
        assert artifact.definition is not None
        assert "data" not in artifact.definition, "data key must be excluded from definition"
        assert artifact.definition.get("type") == "bar"
        assert artifact.definition.get("x") == "month"
        assert artifact.definition.get("y") == ["revenue", "cost"]

    def test_as_chart_config_parses_back(self, sample_cfg):
        """Artifact.as_chart_config() parses the definition back to StructuredChartConfig."""
        now = datetime.now(timezone.utc)
        artifact = self.Artifact.from_chart_config(
            cfg=sample_cfg, artifact_id="test-002",
            title="T", created_at=now, updated_at=now,
        )
        cfg2 = artifact.as_chart_config()
        assert isinstance(cfg2, StructuredChartConfig)
        assert cfg2.type == "bar"
        assert set(cfg2.y) == {"revenue", "cost"}

    def test_as_chart_config_returns_none_for_non_chart(self):
        """as_chart_config() returns None for non-CHART artifact types."""
        now = datetime.now(timezone.utc)
        artifact = self.Artifact(
            artifact_id="test-003",
            artifact_type=self.ArtifactType.CANVAS,
            title="Canvas",
            created_at=now,
            updated_at=now,
            definition={"some": "canvas data"},
        )
        assert artifact.as_chart_config() is None

    def test_as_chart_config_returns_none_when_no_definition(self):
        """as_chart_config() returns None when definition is absent."""
        now = datetime.now(timezone.utc)
        artifact = self.Artifact(
            artifact_id="test-004",
            artifact_type=self.ArtifactType.CHART,
            title="Empty Chart",
            created_at=now,
            updated_at=now,
            definition=None,
        )
        assert artifact.as_chart_config() is None

    def test_from_chart_config_uses_camel_case_aliases(self, sample_cfg):
        """Artifact definition uses camelCase aliases so frontend receives correct keys."""
        now = datetime.now(timezone.utc)
        cfg = StructuredChartConfig(
            type="line", x="month", y=["v"],
            show_legend=True, color_by_sign=True,
            data=[{"month": "A", "v": 1}],
        )
        artifact = self.Artifact.from_chart_config(
            cfg=cfg, artifact_id="test-005",
            title="T", created_at=now, updated_at=now,
        )
        assert "showLegend" in artifact.definition
        assert "colorBySign" in artifact.definition
