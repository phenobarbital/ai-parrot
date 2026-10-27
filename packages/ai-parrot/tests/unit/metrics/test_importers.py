from pathlib import Path
import pytest
from parrot.metrics.importers import import_kpi_table, parse_kpi_table
from parrot.metrics.models import KPICardShape, MapShape, ChartShape, DataTableShape

FIXTURE = Path(__file__).parent / "fixtures" / "kpi-table.md"


@pytest.fixture
def kpi_table_markdown() -> str:
    return FIXTURE.read_text()


def test_parse_kpi_table_twelve_rows(kpi_table_markdown):
    """Test that parse_kpi_table correctly parses 12 rows from the fixture."""
    rows = parse_kpi_table(kpi_table_markdown)
    assert len(rows) == 12
    
    # Check that backticks are stripped
    assert rows[0].transformer == "payroll_hero"
    assert rows[0].dataset_aliases == ["hours", "finance"]
    assert rows[0].recipe_path == "/payroll_hero/worked_hours_total"
    assert rows[0].output_mode == "`KPICard` hero"
    assert rows[0].filters == ["month", "pay_code", "cost_center"]


def test_import_kpi_table_twelve_rows(kpi_table_markdown):
    """Test that import_kpi_table creates 12 definitions with correct shapes and dimensions."""
    definitions = import_kpi_table(
        kpi_table_markdown,
        recipe_name="test_recipe",
        recipe_owner="test_owner",
        tenant=None
    )
    
    assert len(definitions) == 12
    
    # Check that all IDs are unique and pattern-valid
    ids = [d.id for d in definitions]
    assert len(ids) == len(set(ids))
    for id_val in ids:
        assert len(id_val) <= 63
        assert id_val.replace("_", "").isalnum()
        assert id_val.islower()
    
    # Check specific shapes
    # KPICard rows
    kpi_card_defs = [d for d in definitions if isinstance(d.default_shape, KPICardShape)]
    assert len(kpi_card_defs) == 4
    
    # Chart rows
    chart_defs = [d for d in definitions if isinstance(d.default_shape, ChartShape)]
    assert len(chart_defs) == 4
    for d in chart_defs:
        assert d.default_shape.chart_type == "line"
        assert d.default_shape.x == "month"
        assert d.default_shape.y == ["value"]
    
    # Table rows
    table_defs = [d for d in definitions if isinstance(d.default_shape, DataTableShape)]
    assert len(table_defs) == 3
    
    # Map row
    map_defs = [d for d in definitions if isinstance(d.default_shape, MapShape)]
    assert len(map_defs) == 1


def test_proximity_row_kept_as_map(kpi_table_markdown):
    """Test that the Proximity Staffing row is kept as a MapShape."""
    definitions = import_kpi_table(
        kpi_table_markdown,
        recipe_name="test_recipe",
        recipe_owner="test_owner",
        tenant=None
    )
    
    # Find the Proximity Staffing definition
    proximity_def = None
    for d in definitions:
        if "proximity" in d.name.lower():
            proximity_def = d
            break
    
    assert proximity_def is not None
    assert isinstance(proximity_def.default_shape, MapShape)
    assert proximity_def.default_shape.lat == "lat"
    assert proximity_def.default_shape.lon == "lon"
    # Check that the data model path was processed correctly
    assert proximity_def.source.data_model_path == "/proximity_staffing/coverage"
    # Check that description note was added
    assert "template variables" in proximity_def.description


def test_worked_hours_dimensions_and_time_binding(kpi_table_markdown):
    """Test that worked_hours_total has correct dimensions and time binding."""
    definitions = import_kpi_table(
        kpi_table_markdown,
        recipe_name="test_recipe",
        recipe_owner="test_owner",
        tenant=None
    )
    
    # Find the Worked Hours (total) definition
    worked_hours_def = None
    for d in definitions:
        if d.id == "worked_hours_total":
            worked_hours_def = d
            break
    
    assert worked_hours_def is not None
    
    # Check dimensions (should exclude 'month')
    dimension_names = [dim.column for dim in worked_hours_def.dimensions]
    assert "pay_code" in dimension_names
    assert "cost_center" in dimension_names
    assert "month" not in dimension_names
    
    # Check time binding (should have month placeholders)
    assert worked_hours_def.time.binding.start_placeholder == "month"
    assert worked_hours_def.time.binding.end_placeholder == "month"


def test_missing_header_raises():
    """Test that missing header raises ValueError."""
    bad_markdown = """
    | Bad | Header |
    |-----|--------|
    | Data| Row    |
    """
    
    with pytest.raises(ValueError, match="KPI table header not found"):
        parse_kpi_table(bad_markdown)


def test_round_trip_serialization(kpi_table_markdown):
    """Test that all definitions round-trip model_dump(mode="json")."""
    definitions = import_kpi_table(
        kpi_table_markdown,
        recipe_name="test_recipe",
        recipe_owner="test_owner",
        tenant=None
    )
    
    for definition in definitions:
        # This should not raise an exception
        dumped = definition.model_dump(mode="json")
        assert isinstance(dumped, dict)
        assert "id" in dumped
        assert "name" in dumped


def test_tenant_visibility(kpi_table_markdown):
    """Test that visibility is set correctly based on tenant."""
    # With tenant - should be "tenant"
    definitions_with_tenant = import_kpi_table(
        kpi_table_markdown,
        recipe_name="test_recipe",
        recipe_owner="test_owner",
        tenant="test_tenant"
    )
    assert definitions_with_tenant[0].visibility == "tenant"
    
    # Without tenant - should be "public"
    definitions_without_tenant = import_kpi_table(
        kpi_table_markdown,
        recipe_name="test_recipe",
        recipe_owner="test_owner",
        tenant=None
    )
    assert definitions_without_tenant[0].visibility == "public"