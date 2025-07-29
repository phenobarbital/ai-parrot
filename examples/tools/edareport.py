import asyncio
import pandas as pd
import numpy as np
from parrot.tools.edareport import EdaReportTool


# Example usage and testing
async def example_usage():
    """Example of how to use the EdaReportTool."""

    # Create sample dataset with various data types and issues
    np.random.seed(42)
    n_samples = 1000

    sample_data = {
        'age': np.random.randint(18, 80, n_samples),
        'income': np.random.lognormal(10, 1, n_samples),
        'education': np.random.choice(['High School', 'Bachelor', 'Master', 'PhD'], n_samples),
        'city': np.random.choice(['New York', 'London', 'Tokyo', 'Sydney', 'Paris'], n_samples),
        'satisfaction': np.random.uniform(1, 10, n_samples),
        'experience_years': np.random.exponential(5, n_samples),
        'department': np.random.choice(['Engineering', 'Sales', 'Marketing', 'HR', 'Finance'], n_samples),
        'is_remote': np.random.choice([True, False], n_samples),
        'join_date': pd.date_range('2020-01-01', periods=n_samples, freq='D')[:n_samples]
    }

    # Create DataFrame with missing values and duplicates
    df = pd.DataFrame(sample_data)

    # Add missing values
    df.loc[np.random.choice(df.index, 50, replace=False), 'income'] = np.nan
    df.loc[np.random.choice(df.index, 30, replace=False), 'satisfaction'] = np.nan
    df.loc[np.random.choice(df.index, 20, replace=False), 'experience_years'] = np.nan

    # Add some duplicate rows
    df = pd.concat([df, df.sample(10)], ignore_index=True)

    # Initialize the tool
    tool = EdaReportTool(
        output_dir="./static/eda_profiling",
        base_url="http://localhost:8000/static"
    )

    # Test 1: Quick overview
    print("=== Test 1: Quick Overview ===")
    result1 = await tool.execute(
        dataframe=df,
        title="Employee Dataset - Quick Overview",
        df_name="employees",
        minimal=True,
        explorative=False
    )
    print(f"Status: {result1.status}")
    print(f"Generation time: {result1.result['generation_time_seconds']:.2f}s")
    print(f"Variables: {result1.result['statistics']['variables_count']}")
    print(f"Missing cells: {result1.result['statistics']['missing_cells_percentage']:.2f}%")

    # Test 2: Comprehensive analysis with file saving
    print("\n=== Test 2: Comprehensive Analysis ===")
    result2 = await tool.execute(
        dataframe=df,
        filename="employee_comprehensive_analysis",
        title="Employee Dataset - Comprehensive Analysis",
        df_name="employees_full",
        minimal=False,
        explorative=True,
        dark_mode=True,
        correlation_threshold=0.8
    )
    print(f"Status: {result2.status}")
    print(f"Generation time: {result2.result['generation_time_seconds']:.2f}s")
    if 'file_path' in result2.result:
        print(f"File saved: {result2.result['file_path']}")
        print(f"File URL: {result2.result['file_url']}")
        print(f"File size: {result2.result['file_size']} bytes")

    # Test 3: Using extended tool with presets
    print("\n=== Test 3: Using Presets ===")
    extended_tool = EdaReportTool(
        output_dir="./static/eda_profiling",
        base_url="http://localhost:8000/static"
    )

    # Apply comprehensive preset with custom title
    preset_config = extended_tool.apply_preset('comprehensive', title="Preset Analysis")

    result3 = await extended_tool.execute(
        dataframe=df,
        filename="employee_preset_analysis",
        df_name="employees_preset",
        **preset_config
    )
    print(f"Status: {result3.status}")
    print(f"Used preset configuration: comprehensive")
    print(f"Generation time: {result3.result['generation_time_seconds']:.2f}s")

    # Test 4: Sampling large dataset
    print("\n=== Test 4: Sampling Analysis ===")
    large_df = pd.concat([df] * 5, ignore_index=True)  # 5x larger dataset

    result4 = await tool.execute(
        dataframe=large_df,
        title="Large Dataset Sample Analysis",
        df_name="large_employees",
        sample_size=1000,
        minimal=True
    )
    print(f"Status: {result4.status}")
    print(f"Original shape: {result4.result['original_shape']}")
    print(f"Analyzed shape: {result4.result['dataset_shape']}")
    print(f"Sample size: {result4.result['config']['sample_size']}")


if __name__ == "__main__":
    asyncio.run(example_usage())
