# CSVLoader Usage Examples - Row-by-row JSON Documents

import json
import asyncio
import pandas as pd
from parrot.loaders.csv import CSVLoader

# Basic usage - one document per row
async def basic_csv_loading(df):
    loader = CSVLoader(source=df)
    documents = await loader.load()

    print(f"Created {len(documents)} documents from CSV rows")

    # Show first document
    if documents:
        print("\nFirst document:")
        print("Content:", documents[0].page_content)
        print("Metadata keys:", list(documents[0].metadata.keys()))

        # Parse JSON content
        json_data = json.loads(documents[0].page_content)
        print("Row data:", json_data["data"])
        if "row_index" in json_data:
            print("Row index:", json_data["row_index"])

# Configure CSV reading options
async def configured_csv_loading():
    loader = CSVLoader(
        "data.csv",

        # CSV format options
        separator=";",  # Semicolon separated
        encoding="utf-8",
        header=0,  # First row as header

        # Row filtering
        max_rows=1000,  # Only process first 1000 rows
        skip_rows=2,    # Skip first 2 data rows
        skip_empty_rows=True,
        skip_na_rows=False,  # Keep rows with some NaN values
        fill_na_value="N/A",  # Fill NaN with "N/A"

        # JSON formatting
        json_indent=None,  # Compact JSON
        json_ensure_ascii=False,

        # Content options
        include_row_index=True,
        include_headers_in_content=True,
        row_prefix="Record",
    )

    documents = await loader._load("data.csv")

    print(f"Loaded {len(documents)} documents with custom configuration")

    # Show sample document with headers
    if documents:
        sample_doc = json.loads(documents[0].page_content)
        print("Sample document structure:")
        print(f"- Row name: {sample_doc.get('row_name')}")
        print(f"- Headers: {sample_doc.get('headers')}")
        print(f"- Data: {sample_doc['data']}")

# Auto-detect CSV format
async def auto_detect_csv():
    # Let the loader auto-detect separator and encoding
    loader = CSVLoader(
        "unknown_format.csv",
        separator=None,  # Auto-detect
        encoding="utf-8"
    )

    # Get CSV info first
    csv_info = loader.get_csv_info("unknown_format.csv")
    print("CSV Analysis:")
    print(f"- Separator detected: '{csv_info['separator_detected']}'")
    print(f"- Total rows: {csv_info['total_rows']}")
    print(f"- Columns: {csv_info['column_headers']}")
    print(f"- Data types: {csv_info['data_types']}")
    print(f"- Numeric columns: {csv_info['numeric_columns']}")

    # Load documents
    documents = await loader._load("unknown_format.csv")
    print(f"Created {len(documents)} documents")

# Process large CSV with estimation
async def large_csv_processing():
    csv_file = "large_dataset.csv"

    loader = CSVLoader(
        csv_file,
        max_rows=5000,  # Limit processing
        skip_empty_rows=True,
        skip_na_rows=True,  # Skip rows with all NaN
    )

    # Estimate document count before processing
    estimated_docs = loader.estimate_documents_count(csv_file)
    print(f"Estimated documents to create: {estimated_docs}")

    # Get detailed info
    csv_info = loader.get_csv_info(csv_file)
    print(f"CSV has {csv_info['total_rows']} total rows")

    # Process
    documents = await loader._load(csv_file)
    print(f"Actually created: {len(documents)} documents")

    # Show configuration used
    config = loader.get_configuration_summary()
    print("Configuration:", config)

# Different CSV formats handling
async def handle_different_formats():
    csv_files = [
        {"file": "comma_separated.csv", "sep": ","},
        {"file": "semicolon_separated.csv", "sep": ";"},
        {"file": "tab_separated.tsv", "sep": "\t"},
        {"file": "pipe_separated.csv", "sep": "|"},
    ]

    all_documents = []

    for csv_config in csv_files:
        loader = CSVLoader(
            csv_config["file"],
            separator=csv_config["sep"],
            skip_empty_rows=True,
        )

        try:
            documents = await loader._load(csv_config["file"])
            all_documents.extend(documents)
            print(f"✓ Loaded {len(documents)} documents from {csv_config['file']}")
        except Exception as e:
            print(f"✗ Failed to load {csv_config['file']}: {e}")

    print(f"Total documents from all CSVs: {len(all_documents)}")

# Custom data processing
async def custom_data_processing():
    loader = CSVLoader(
        "sales_data.csv",

        # Only process specific columns
        usecols=["date", "product", "sales_amount", "region"],

        # Specify data types
        dtype={
            "product": str,
            "region": str,
            "sales_amount": float
        },

        # Fill missing values
        fill_na_value="Unknown",

        # Clean JSON output
        json_indent=2,
        include_row_index=True,
        row_prefix="Sale",
    )

    documents = await loader._load("sales_data.csv")

    print(f"Processed {len(documents)} sales records")

    # Analyze the data
    if documents:
        sample_record = json.loads(documents[0].page_content)
        print("Sample sales record:")
        print(json.dumps(sample_record, indent=2))

        # Show metadata
        metadata = documents[0].metadata['doc_metadata']
        print(f"CSV info: {metadata['csv_info']['total_rows']} total rows")
        print(f"Columns: {metadata['csv_info']['column_headers']}")

# Export documents in different formats
async def export_documents():
    loader = CSVLoader(
        "products.csv",
        include_headers_in_content=True,
        json_indent=2
    )

    documents = await loader._load("products.csv")

    # Save each document as separate JSON file
    for i, doc in enumerate(documents):
        row_data = json.loads(doc.page_content)
        filename = f"product_{row_data['row_index']}.json"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(doc.page_content)

        print(f"Saved {filename}")

    # Create combined output
    all_rows = []
    for doc in documents:
        row_data = json.loads(doc.page_content)
        all_rows.append(row_data)

    with open("all_products.json", "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2, ensure_ascii=False)

    print(f"Saved combined file with {len(all_rows)} records")

# Process CSV with metadata analysis
async def metadata_analysis():
    loader = CSVLoader(
        "survey_responses.csv",
        skip_empty_rows=True,
        fill_na_value=None,  # Keep NaN as null
        include_row_index=True,
    )

    documents = await loader._load("survey_responses.csv")

    # Analyze document metadata
    if documents:
        first_doc = documents[0]
        csv_info = first_doc.metadata['doc_metadata']['csv_info']

        print("CSV Analysis:")
        print(f"- Total rows processed: {len(documents)}")
        print(f"- Original CSV rows: {csv_info['total_rows']}")
        print(f"- Columns: {csv_info['total_columns']}")
        print(f"- Column headers: {csv_info['column_headers']}")
        print(f"- Has numeric data: {csv_info['has_numeric_data']}")

        if csv_info['has_numeric_data']:
            print(f"- Numeric columns: {csv_info['numeric_columns']}")

        # Analyze individual documents
        row_stats = {
            "complete_rows": 0,
            "partial_rows": 0,
            "total_columns": csv_info['total_columns']
        }

        for doc in documents:
            doc_metadata = doc.metadata['doc_metadata']
            if doc_metadata['empty_columns'] == 0:
                row_stats["complete_rows"] += 1
            else:
                row_stats["partial_rows"] += 1

        print(f"- Complete rows (no missing data): {row_stats['complete_rows']}")
        print(f"- Partial rows (some missing data): {row_stats['partial_rows']}")

# Handle errors and edge cases
async def robust_csv_processing():
    problematic_files = [
        "empty.csv",
        "malformed.csv",
        "wrong_encoding.csv",
        "mixed_separators.csv"
    ]

    for csv_file in problematic_files:
        print(f"\nProcessing {csv_file}:")

        try:
            loader = CSVLoader(
                csv_file,
                separator=None,  # Auto-detect
                skip_empty_rows=True,
                skip_na_rows=False,
            )

            # Try to get info first
            csv_info = loader.get_csv_info(csv_file)
            if "error" in csv_info:
                print(f"  Error analyzing file: {csv_info['error']}")
                continue

            print(f"  Info: {csv_info['total_rows']} rows, {csv_info['total_columns']} columns")

            # Try to load
            documents = await loader._load(csv_file)
            print(f"  ✓ Successfully created {len(documents)} documents")

        except FileNotFoundError:
            print(f"  ✗ File not found")
        except pd.errors.EmptyDataError:
            print(f"  ✗ File is empty or has no valid data")
        except pd.errors.ParserError as e:
            print(f"  ✗ Parser error: {e}")
        except UnicodeDecodeError as e:
            print(f"  ✗ Encoding error: {e}")
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")

# Create searchable knowledge base from CSV
async def create_knowledge_base():
    """Example: Convert customer data CSV to searchable knowledge base"""

    loader = CSVLoader(
        "customers.csv",

        # Process all relevant columns
        usecols=["customer_id", "name", "email", "company", "industry", "notes"],

        # Clean data
        skip_empty_rows=True,
        fill_na_value="",

        # Rich JSON output
        json_indent=2,
        include_row_index=True,
        include_headers_in_content=True,
        row_prefix="Customer",
    )

    documents = await loader._load("customers.csv")

    print(f"Created knowledge base with {len(documents)} customer records")

    # Show sample customer record
    if documents:
        customer = json.loads(documents[0].page_content)
        print("\nSample customer record:")
        print(json.dumps(customer, indent=2))

        # This JSON content can now be:
        # 1. Indexed in a vector database for semantic search
        # 2. Used by LLMs for customer information retrieval
        # 3. Processed further by other AI-parrot components

        print(f"\nRecord is ready for:")
        print("- Vector database indexing")
        print("- LLM context injection")
        print("- Semantic search")
        print("- RAG applications")

# Performance comparison: different configurations
async def performance_comparison():
    csv_file = "large_dataset.csv"

    configs = [
        {
            "name": "Minimal processing",
            "config": {
                "skip_empty_rows": False,
                "skip_na_rows": False,
                "json_indent": None,
                "include_row_index": False,
                "include_headers_in_content": False,
            }
        },
        {
            "name": "Standard processing",
            "config": {
                "skip_empty_rows": True,
                "skip_na_rows": False,
                "json_indent": 2,
                "include_row_index": True,
                "include_headers_in_content": False,
            }
        },
        {
            "name": "Full processing",
            "config": {
                "skip_empty_rows": True,
                "skip_na_rows": True,
                "fill_na_value": "N/A",
                "json_indent": 2,
                "include_row_index": True,
                "include_headers_in_content": True,
            }
        }
    ]

    for config_info in configs:
        print(f"\nTesting: {config_info['name']}")

        loader = CSVLoader(csv_file, max_rows=1000, **config_info["config"])

        import time
        start_time = time.time()

        try:
            documents = await loader._load(csv_file)
            end_time = time.time()

            print(f"  Documents created: {len(documents)}")
            print(f"  Processing time: {end_time - start_time:.2f} seconds")

            if documents:
                sample_size = len(documents[0].page_content)
                print(f"  Average document size: ~{sample_size} characters")

        except Exception as e:
            print(f"  Error: {e}")

# Run examples
if __name__ == "__main__":
    # Create sample CSV for testing
    sample_data = {
        'id': [1, 2, 3, 4, 5],
        'name': ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve'],
        'age': [25, 30, 35, None, 28],
        'department': ['Engineering', 'Sales', 'Marketing', 'Engineering', 'HR'],
        'salary': [70000, 60000, 55000, 75000, 50000]
    }
    df = pd.DataFrame(sample_data)
    # df.to_csv('sample_employees.csv', index=False)
    # print("Created sample CSV for testing")
    # Run basic example
    asyncio.run(basic_csv_loading(df))
