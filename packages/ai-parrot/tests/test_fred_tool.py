
import pytest
import os
from parrot.tools.fred_api import FredAPITool

@pytest.mark.asyncio
async def test_fred_api_tool_fedfunds():
    """Test fetching FEDFUNDS series from FredAPITool."""
    tool = FredAPITool()
    
    # Check if API key is present in env, otherwise skip or warn
    if not os.environ.get("FRED_API_KEY"):
        pytest.skip("FRED_API_KEY not found in environment")

    result = await tool._execute(series_id="FEDFUNDS", params={"limit": 1})
    
    assert result.success is True
    assert result.status == "success"
    assert result.result is not None
    assert "observations" in result.result

@pytest.mark.asyncio
async def test_fred_api_tool_no_key():
    """Test FredAPITool error handling when no API key is provided."""
    # Temporarily unset env var if it exists
    original_key = os.environ.get("FRED_API_KEY")
    if original_key:
        del os.environ["FRED_API_KEY"]
    
    try:
        tool = FredAPITool()
        result = await tool._execute(series_id="FEDFUNDS")
        assert result.success is False
        assert "API Key not found" in result.error
    finally:
        if original_key:
            os.environ["FRED_API_KEY"] = original_key

