import asyncio
import pandas as pd
import numpy as np
from parrot.tools.pythonpandas import PythonPandasTool

async def example_usage():
    # Create tool with sample DataFrames
    df1 = pd.DataFrame({
        'id': range(1, 101),
        'name': [f'User_{i}' for i in range(1, 101)],
        'age': np.random.randint(18, 80, 100),
        'salary': np.random.normal(50000, 15000, 100),
        'department': np.random.choice(['IT', 'HR', 'Finance', 'Marketing'], 100)
    })

    df2 = pd.DataFrame({
        'product_id': range(1, 51),
        'product_name': [f'Product_{i}' for i in range(1, 51)],
        'price': np.random.uniform(10, 1000, 50),
        'category': np.random.choice(['Electronics', 'Clothing', 'Books'], 50)
    })

    tool = PythonPandasTool(
        dataframes={'employees': df1, 'products': df2},
        generate_guide=True
    )

    # Print the guide
    print(tool.get_dataframe_guide())

    # Test execution
    code = """
print("DataFrame shapes:")
print(f"df1 (employees): {df1.shape}")
print(f"df2 (products): {df2.shape}")

# Quick analysis
avg_salary = df1['salary'].mean()
execution_results['avg_salary'] = avg_salary
print(f"Average salary: ${avg_salary:.2f}")
"""
    result = tool.execute_sync(code)
    print("\nExecution result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(example_usage())
