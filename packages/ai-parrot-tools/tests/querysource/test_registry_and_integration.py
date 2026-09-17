"""Registry integrity after the hard cut + integration tests against the real querysource (skipped when absent)."""
import importlib
import importlib.util
import pytest
from parrot_tools import TOOL_REGISTRY
from .conftest import PIPELINE

HAS_QS = importlib.util.find_spec("querysource") is not None


def test_registry_has_no_stale_qsource_keys():
    assert TOOL_REGISTRY["querysource"] == "parrot_tools.querysource.toolkit.QuerysourceToolkit"
    assert "q_source" not in TOOL_REGISTRY and "qsource" not in TOOL_REGISTRY
    with pytest.raises(ImportError):
        importlib.import_module("parrot_tools.qsource")


@pytest.mark.skipif(not HAS_QS, reason="querysource not installed")
async def test_component_catalog_real_registry():
    from parrot_tools.querysource import QuerysourceToolkit
    docs = await QuerysourceToolkit(dsn="postgres://unused").list_components(category="Operators")
    names = {d.name for d in docs}
    assert {"Concat", "Join"} <= names and all(d.json_schema is not None for d in docs if d.name == "Concat")


@pytest.mark.skipif(not HAS_QS, reason="querysource not installed")
def test_validate_pipeline_real_registry_structural():
    from querysource.queries.multi.registry import ComponentRegistry
    result = ComponentRegistry.validate_pipeline(PIPELINE)
    assert result.valid and result.errors == []

    bad = dict(PIPELINE, Frobnicate=[{"x": 1}])
    bad_result = ComponentRegistry.validate_pipeline(bad)
    assert not bad_result.valid
    assert any(err.step == "Frobnicate" and "Unknown operator/transform" in err.message for err in bad_result.errors)
