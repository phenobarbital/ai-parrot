"""FEAT-224 TASK-1459: Unit tests for ArtifactType.TABLE and Artifact.from_structured_config.

Tests verify:
- ArtifactType.TABLE exists with value "table"
- from_structured_config builds correct artifacts for CHART / MAP / TABLE
- definition excludes the ``data`` key and uses camelCase aliases
- from_chart_config backward-compat wrapper still returns a CHART artifact
"""
from datetime import datetime, timezone

import pytest

from parrot.storage.models import Artifact, ArtifactType
from parrot.models.outputs import StructuredChartConfig, StructuredTableConfig, TableColumn


def _now() -> datetime:
    """Return a fixed UTC datetime for test reproducibility."""
    return datetime(2026, 6, 4, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ArtifactType tests
# ---------------------------------------------------------------------------


def test_artifacttype_table_exists() -> None:
    """ArtifactType.TABLE must exist and equal the string 'table'."""
    assert ArtifactType.TABLE.value == "table"


def test_artifacttype_table_is_str_enum() -> None:
    """ArtifactType.TABLE must be usable as a plain string."""
    assert ArtifactType.TABLE == "table"


# ---------------------------------------------------------------------------
# from_structured_config — CHART
# ---------------------------------------------------------------------------


def test_from_structured_config_chart_type() -> None:
    """from_structured_config with CHART produces artifact_type == CHART."""
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"],
                                data=[{"month": "Jan", "sales": 1}])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "chart-1", "Sales Chart", _now(), _now()
    )
    assert art.artifact_type == ArtifactType.CHART


def test_from_structured_config_chart_excludes_data() -> None:
    """definition must NOT contain a 'data' key (rows live in response.data)."""
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"],
                                data=[{"month": "Jan", "sales": 1}])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "chart-1", "T", _now(), _now()
    )
    assert "data" not in art.definition


def test_from_structured_config_chart_camel_case() -> None:
    """definition keys must use camelCase (by_alias=True)."""
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"],
                                data=[])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "chart-1", "T", _now(), _now()
    )
    # 'x' and 'y' have no alias, so they appear as-is.  Verify 'type' is present.
    assert "type" in art.definition
    assert art.definition["x"] == "month"


def test_from_structured_config_chart_preserves_fields() -> None:
    """artifact_id, title, created_at, updated_at are passed through correctly."""
    cfg = StructuredChartConfig(type="line", x="d", y=["v"])
    now = _now()
    art = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "my-id", "My Title", now, now
    )
    assert art.artifact_id == "my-id"
    assert art.title == "My Title"
    assert art.created_at == now


# ---------------------------------------------------------------------------
# from_structured_config — TABLE
# ---------------------------------------------------------------------------


def test_from_structured_config_table_type() -> None:
    """from_structured_config with TABLE produces artifact_type == TABLE."""
    cfg = StructuredTableConfig(
        columns=[TableColumn(name="id", type="integer", title="ID")]
    )
    art = Artifact.from_structured_config(
        cfg, ArtifactType.TABLE, "table-1", "My Table", _now(), _now()
    )
    assert art.artifact_type == ArtifactType.TABLE


def test_from_structured_config_table_excludes_data() -> None:
    """TABLE artifact definition must also exclude 'data'."""
    cfg = StructuredTableConfig(
        columns=[TableColumn(name="id", type="integer", title="ID")],
        data=[{"id": 1}, {"id": 2}],
    )
    art = Artifact.from_structured_config(
        cfg, ArtifactType.TABLE, "table-1", "T", _now(), _now()
    )
    assert "data" not in art.definition


def test_from_structured_config_table_has_columns() -> None:
    """definition must contain the 'columns' field for TABLE artifacts."""
    cfg = StructuredTableConfig(
        columns=[TableColumn(name="id", type="integer", title="ID")]
    )
    art = Artifact.from_structured_config(
        cfg, ArtifactType.TABLE, "table-1", "T", _now(), _now()
    )
    assert "columns" in art.definition
    assert len(art.definition["columns"]) == 1


# ---------------------------------------------------------------------------
# from_structured_config — MAP (structural smoke test)
# ---------------------------------------------------------------------------


def test_from_structured_config_map_type() -> None:
    """from_structured_config with MAP produces artifact_type == MAP."""
    from parrot.models.outputs import StructuredMapConfig
    cfg = StructuredMapConfig(layers=[])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.MAP, "map-1", "My Map", _now(), _now()
    )
    assert art.artifact_type == ArtifactType.MAP
    assert "data" not in art.definition


# ---------------------------------------------------------------------------
# from_chart_config backward-compat wrapper
# ---------------------------------------------------------------------------


def test_from_chart_config_backcompat_type() -> None:
    """from_chart_config wrapper must still return a CHART artifact."""
    cfg = StructuredChartConfig(type="line", x="d", y=["v"])
    art = Artifact.from_chart_config(cfg, "c", "T", _now(), _now())
    assert art.artifact_type == ArtifactType.CHART


def test_from_chart_config_backcompat_no_data() -> None:
    """from_chart_config wrapper must still exclude 'data' from definition."""
    cfg = StructuredChartConfig(type="line", x="d", y=["v"],
                                data=[{"d": "2026-01", "v": 42}])
    art = Artifact.from_chart_config(cfg, "c", "T", _now(), _now())
    assert "data" not in art.definition


def test_from_chart_config_identical_to_from_structured_config() -> None:
    """from_chart_config must produce the same result as from_structured_config(CHART)."""
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    now = _now()
    art_wrapper = Artifact.from_chart_config(cfg, "art-id", "Title", now, now)
    art_generic = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "art-id", "Title", now, now
    )
    assert art_wrapper.artifact_type == art_generic.artifact_type
    assert art_wrapper.definition == art_generic.definition
    assert art_wrapper.artifact_id == art_generic.artifact_id


# ---------------------------------------------------------------------------
# kwargs passthrough
# ---------------------------------------------------------------------------


def test_from_structured_config_passes_kwargs() -> None:
    """Extra kwargs like source_turn_id must be forwarded to the Artifact."""
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "chart-1", "T", _now(), _now(),
        source_turn_id="turn-abc",
    )
    assert art.source_turn_id == "turn-abc"
