import asyncio
from parrot.tools.abstract import ToolRegistry
from parrot.tools.pythonrepl import PythonREPLTool

# Usage examples
async def example_usage():
    """Example of how to use the enhanced PythonREPLTool."""

    # Create the tool
    repl_tool = PythonREPLTool()

    # Get tool schema
    print("Tool Schema:")
    schema = repl_tool.get_tool_schema()
    print(schema)
    print()

    # Get environment info
    print("Environment Info:")
    env_info = repl_tool.get_environment_info()
    for key, value in env_info.items():
        print(f"  {key}: {value}")
    print()

    # Execute some Python code
    print("Executing basic math:")
    result1 = await repl_tool.execute(code="2 + 2")
    print(f"Result: {result1}")
    print()

    # Execute pandas code
    print("Executing pandas code:")
    pandas_code = """
import pandas as pd
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
execution_results['sample_df'] = df
df.head()
"""
    result2 = await repl_tool.execute(code=pandas_code, debug=True)
    print(f"Result: {result2}")
    print()

    # Check execution results
    print("Checking execution results:")
    check_code = "list(execution_results.keys())"
    result3 = await repl_tool.execute(code=check_code)
    print(f"Stored results: {result3}")

    # Save execution results
    print("\nSaving execution results:")
    save_result = repl_tool.save_execution_results()
    print(f"Saved to: {save_result}")

    # Execute code that creates complex objects
    print('Executing code with complex data types:')
    code = """
import pandas as pd
import numpy as np

# Create various data types
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
series = pd.Series([1, 2, 3], name='my_series')
array = np.array([[1, 2], [3, 4]])

# Store in execution_results
execution_results['my_dataframe'] = df
execution_results['my_series'] = series
execution_results['my_array'] = array
execution_results['simple_dict'] = {'key': 'value'}

print("Data stored successfully!")
"""

    result = await repl_tool.execute(code=code)
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(example_usage())
