import asyncio
import pandas as pd
from parrot.tools.quickeda import QuickEdaTool

# Example usage and testing
async def example_usage():
    """Example of how to use the QuickEdaTool."""
    import pandas as pd
    import numpy as np

    # Create sample dataset
    np.random.seed(42)
    n_samples = 1000

    sample_data = {
        'age': np.random.randint(18, 80, n_samples),
        'income': np.random.lognormal(10, 1, n_samples),
        'education': np.random.choice(['High School', 'Bachelor', 'Master', 'PhD'], n_samples),
        'city': np.random.choice(['New York', 'London', 'Tokyo', 'Sydney', 'Paris'], n_samples),
        'satisfaction': np.random.uniform(1, 10, n_samples),
        'experience_years': np.random.exponential(5, n_samples),
        'department': np.random.choice(['Engineering', 'Sales', 'Marketing', 'HR', 'Finance'], n_samples)
    }

    # Add some missing values
    df = pd.DataFrame(sample_data)
    df.loc[np.random.choice(df.index, 50, replace=False), 'income'] = np.nan
    df.loc[np.random.choice(df.index, 30, replace=False), 'satisfaction'] = np.nan

    # Add some correlations
    df['salary_category'] = pd.cut(df['income'], bins=3, labels=['Low', 'Medium', 'High'])

    # Initialize the tool
    tool = QuickEdaTool(
        output_dir="./static/eda_reports",
        base_url="http://localhost:8000/static"
    )

    # Test 1: Basic EDA without saving
    print("=== Test 1: Basic EDA analysis ===")
    result1 = await tool.execute(
        dataframe=df,
        title="Employee Dataset Analysis"
    )
    print(f"Status: {result1.status}")
    print(f"Dataset shape: {result1.result['dataset_shape']}")
    print(f"HTML length: {len(result1.result['html'])} characters")

    # Test 2: Customized EDA with file saving
    print("\n=== Test 2: Customized EDA with file saving ===")
    result2 = await tool.execute(
        dataframe=df,
        filename="employee_analysis",
        title="Comprehensive Employee Data Analysis",
        max_numeric_plots=3,
        max_categorical_plots=3,
        plot_style="darkgrid",
        color_palette="Set2",
        figure_size=(14, 8)
    )
    print(f"Status: {result2.status}")
    if 'file_path' in result2.result:
        print(f"File saved: {result2.result['file_path']}")
        print(f"File URL: {result2.result['file_url']}")
        print(f"File size: {result2.result['file_size']} bytes")

    # Test 3: Minimal EDA (only basic stats)
    print("\n=== Test 3: Minimal EDA ===")
    result3 = await tool.execute(
        dataframe=df,
        title="Quick Overview",
        include_correlations=False,
        include_distributions=False,
        include_value_counts=False
    )
    print(f"Status: {result3.status}")
    print(f"HTML length (minimal): {len(result3.result['html'])} characters")

    # Test 4: Error handling
    print("\n=== Test 4: Error handling ===")
    empty_df = pd.DataFrame()
    result4 = await tool.execute(dataframe=empty_df)
    print(f"Status: {result4.status}")
    print(f"Error: {result4.error}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
