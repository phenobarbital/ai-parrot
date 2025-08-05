import pandas as pd
import numpy as np
from parrot.tools.dftohtml import DfToHtmlTool

# Example usage and testing
async def example_usage():
    """Example of how to use the DfToHtmlTool."""


    # Create sample data
    np.random.seed(42)
    sample_data = {
        'Product': ['Laptop', 'Mouse', 'Keyboard', 'Monitor', 'Webcam'],
        'Price': [999.99, 29.99, 79.99, 299.99, 89.99],
        'Rating': [4.5, 4.2, 4.7, 4.3, 4.1],
        'Stock': [15, 50, 30, 8, 25],
        'Category': ['Electronics', 'Accessories', 'Accessories', 'Electronics', 'Electronics']
    }
    df = pd.DataFrame(sample_data)

    # Initialize the tool
    tool = DfToHtmlTool(
        output_dir="./static/tables",
        base_url="http://localhost:8000/static"
    )

    # Test 1: Basic conversion without saving
    print("=== Test 1: Basic HTML conversion ===")
    result1 = await tool.execute(dataframe=df)
    print(f"Status: {result1.status}")
    print(f"Rows: {result1.result['rows']}, Columns: {result1.result['columns']}")
    print(f"HTML length: {len(result1.result['html'])} characters")

    # Test 2: Save to file with custom styling
    print("\n=== Test 2: Save with custom styling ===")
    custom_css = """
    .dataframe th { background-color: #2c3e50 !important; }
    .dataframe tbody tr:hover { background-color: #3498db !important; color: white; }
    """

    result2 = await tool.execute(
        dataframe=df,
        filename="products_table",
        table_id="products",
        custom_css=custom_css,
        max_rows=3
    )
    print(f"Status: {result2.status}")
    if 'file_path' in result2.result:
        print(f"File saved: {result2.result['file_path']}")
        print(f"File URL: {result2.result['file_url']}")

    print("\n === Test 3: Use Boostrap for styling ===")
    result = await tool.execute(
        dataframe=df,
        css_classes="table table-dark table-striped",
        max_rows=100,
        include_bootstrap=True,
        custom_css="tr:hover { transform: scale(1.02); }",
        filename="products_table_bootstrap",
        output_dir="./static/tables",
        base_url="http://localhost:8000/static"
    )
    if 'file_path' in result.result:
        print(f"File saved: {result.result['file_path']}")
        print(f"File URL: {result.result['file_url']}")

    # Test 3: Error handling with invalid input
    print("\n=== Test 4: Error handling ===")
    result3 = await tool.execute(dataframe="not a dataframe")
    print(f"Status: {result3.status}")
    print(f"Error: {result3.error}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
