import pytest
import pandas as pd
from parrot.tools.pythonpandas import PythonPandasTool

@pytest.mark.asyncio
class TestPythonPandasPreview:
    async def test_dataframe_preview_generation(self):
        """Test that new DataFrames generate a preview in the output."""
        tool = PythonPandasTool()
        code = """
import pandas as pd
new_df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
print('Done')
"""
        result = await tool._execute(code)
        
        # Check standard output
        assert "Done" in result
        
        # Check preview generation
        assert "🔍 [AUDIT] Preview of 'new_df'" in result
        # Simple checks for content presence
        assert "a" in result
        assert "b" in result
        assert "1" in result
        assert "4" in result

    async def test_dataframe_preview_no_spam(self):
        """Test that existing DataFrames are not previewed unless modified (new identity)."""
        tool = PythonPandasTool()
        # Pre-populate locals to simulate existing DataFrame
        tool.locals['existing_df'] = pd.DataFrame({'x': [1]})
        
        code = "print('Just checking')"
        result = await tool._execute(code)
        
        assert "Just checking" in result
        assert "Preview of 'existing_df'" not in result
        
        # Verify executed code is shown
        assert "📝 [AUDIT] Executed Code:" in result
        assert "print('Just checking')" in result
