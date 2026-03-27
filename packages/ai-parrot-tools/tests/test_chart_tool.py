import pytest
import shutil
import tempfile
from pathlib import Path
from parrot.tools.chart import ChartTool

@pytest.fixture
def chart_tool():
    """Fixture to create a ChartTool instance with a temporary output directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        tool = ChartTool(output_dir=output_dir, backend="matplotlib")
        yield tool

@pytest.mark.asyncio
async def test_chart_tool_instantiation(chart_tool):
    """Test that the ChartTool can be instantiated."""
    assert isinstance(chart_tool, ChartTool)
    assert chart_tool.backend == "matplotlib"

@pytest.mark.asyncio
async def test_generate_bar_chart(chart_tool):
    """Test generating a bar chart."""
    data = {
        "categories": ["Jan", "Feb", "Mar"],
        "values": [10, 20, 15]
    }
    
    result = await chart_tool.execute(
        chart_type="bar",
        title="Monthly Sales",
        data=data,
        x_label="Month",
        y_label="Sales"
    )
    
    assert result.success is True
    assert result.metadata is not None
    assert "chart_path" in result.metadata
    
    chart_path = Path(result.metadata["chart_path"])
    assert chart_path.exists()
    assert chart_path.suffix == ".png"
    assert chart_path.stat().st_size > 0

@pytest.mark.asyncio
async def test_generate_pie_chart(chart_tool):
    """Test generating a pie chart."""
    data = {
        "labels": ["Red", "Blue", "Green"],
        "values": [30, 50, 20]
    }
    
    result = await chart_tool.execute(
        chart_type="pie",
        title="Color Distribution",
        data=data
    )
    
    assert result.success is True
    assert result.metadata is not None
    assert "chart_path" in result.metadata
    
    chart_path = Path(result.metadata["chart_path"])
    assert chart_path.exists()

@pytest.mark.asyncio
async def test_generate_chart_invalid_type(chart_tool):
    """Test functionality with invalid chart type."""
    data = {"x": [1, 2], "y": [3, 4]}
    
    result = await chart_tool.execute(
        chart_type="invalid_type",
        title="Invalid",
        data=data
    )
    
    assert result.success is False
    assert "Unsupported chart type" in result.error

@pytest.mark.asyncio
async def test_chart_svg_format(chart_tool):
    """Test generating a chart in SVG format."""
    data = {
        "x": [1, 2, 3],
        "y": [4, 5, 6]
    }
    
    result = await chart_tool.execute(
        chart_type="line",
        title="Line Chart",
        data=data,
        output_format="svg"
    )
    
    assert result.success is True
    chart_path = Path(result.metadata["chart_path"])
    assert chart_path.exists()
    assert chart_path.suffix == ".svg"
