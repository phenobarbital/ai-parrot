
import asyncio
import io
import pandas as pd
from parrot.bots.agent import BasicAgent
from parrot.tools.pythonpandas import PythonPandasTool

class MockFile:
    def __init__(self, content, filename):
        self.content = content
        self.filename = filename
        
    def read(self):
        return self.content

async def test_file_upload():
    print("Testing file upload handling...")
    
    # Initialize agent
    agent = BasicAgent(name="TestAgent")
    
    # Create mock CSV content
    csv_content = b"col1,col2\n1,a\n2,b\n3,c"
    mock_files = {
        "test_data.csv": MockFile(csv_content, "test_data.csv")
    }
    
    # Call handle_files
    print("Uploading file...")
    added_files = await agent.handle_files(mock_files)
    
    print(f"Added files: {added_files}")
    
    # Verify DataFrame was added to agent
    if "test_data" in agent.dataframes:
        print("✅ DataFrame 'test_data' found in agent.dataframes")
        df = agent.dataframes["test_data"]
        print(f"DataFrame shape: {df.shape}")
        if df.shape == (3, 2):
            print("✅ DataFrame shape matches expected (3, 2)")
        else:
            print(f"❌ DataFrame shape mismatch: {df.shape}")
    else:
        print("❌ DataFrame 'test_data' NOT found in agent.dataframes")
        
    # Verify PythonPandasTool has the dataframe
    print("Checking for PythonPandasTool...")
    print(f"Tools in manager: {agent.tool_manager.list_tools()}")
    
    pandas_tool = agent.tool_manager.get_tool('python_repl_pandas')

    if pandas_tool:
        print("✅ PythonPandasTool found via get_tool('python_repl_pandas')")
        if "test_data" in pandas_tool.dataframes:
            print("✅ DataFrame 'test_data' found in PythonPandasTool")
        else:
            print("❌ DataFrame 'test_data' NOT found in PythonPandasTool")
            print(f"Available dataframes in tool: {list(pandas_tool.dataframes.keys())}")
    else:
        print("❌ PythonPandasTool NOT found in tool_manager")
        # Try looking in agent.tools again just in case
        pandas_tool = next((t for t in agent.tools if isinstance(t, PythonPandasTool)), None)
        if pandas_tool:
             print("⚠️ Found in agent.tools but not via get_tool (unexpected)")

if __name__ == "__main__":
    asyncio.run(test_file_upload())
