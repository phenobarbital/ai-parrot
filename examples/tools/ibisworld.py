"""
Example usage of IBISWorld Tool for searching and extracting content
from IBISWorld industry research articles.
"""
import asyncio
from parrot.tools.ibisworld import IBISWorldTool


async def basic_search():
    """Basic IBISWorld search with content extraction."""
    tool = IBISWorldTool()

    # Search for restaurant industry information
    result = await tool.execute(
        query="restaurant industry trends",
        max_results=3,
        extract_content=True,
        include_tables=True
    )

    if result.status == "success":
        data = result.result
        print(f"Found {data['total_results']} results from IBISWorld")
        print(f"Search query: {data['search_query']}\n")

        for idx, item in enumerate(data['results'], 1):
            print(f"\n{'='*80}")
            print(f"Result {idx}: {item['title']}")
            print(f"URL: {item['link']}")
            print(f"Snippet: {item['snippet']}")

            # Display extracted content if available
            if 'extracted_content' in item and item['has_content']:
                content = item['extracted_content']
                print(f"\n--- Extracted Content ---")
                print(f"Title: {content.get('title', 'N/A')}")

                # Display content preview (first 500 characters)
                article_content = content.get('content', '')
                if article_content:
                    print(f"\nContent Preview:\n{article_content[:500]}...")

                # Display metadata
                metadata = content.get('metadata', {})
                if metadata:
                    print(f"\nMetadata:")
                    for key, value in metadata.items():
                        print(f"  {key}: {value}")

                # Display statistics
                statistics = content.get('statistics', {})
                if statistics:
                    print(f"\nKey Statistics:")
                    for key, value in list(statistics.items())[:5]:  # Show first 5
                        print(f"  {key}: {value}")

                # Display tables
                tables = content.get('tables', [])
                if tables:
                    print(f"\nFound {len(tables)} table(s)")
                    for table_idx, table in enumerate(tables, 1):
                        print(f"  Table {table_idx}: {len(table['rows'])} rows")
    else:
        print(f"Error: {result.error}")


async def search_without_content_extraction():
    """Quick search without full content extraction."""
    tool = IBISWorldTool()

    # Fast search - just get search results
    result = await tool.execute(
        query="automotive manufacturing",
        max_results=5,
        extract_content=False  # Skip content extraction for faster results
    )

    if result.status == "success":
        data = result.result
        print(f"Quick search found {data['total_results']} results")
        for idx, item in enumerate(data['results'], 1):
            print(f"{idx}. {item['title']}")
            print(f"   {item['link']}\n")


async def specific_industry_research():
    """Search for specific industry with detailed extraction."""
    tool = IBISWorldTool()

    # Search for healthcare industry
    result = await tool.execute(
        query="healthcare services industry analysis",
        max_results=2,
        extract_content=True,
        include_tables=True
    )

    if result.status == "success":
        data = result.result
        print(f"Healthcare Industry Research Results:\n")

        for item in data['results']:
            if 'extracted_content' in item:
                content = item['extracted_content']

                print(f"Title: {content.get('title', 'N/A')}")
                print(f"URL: {item['link']}\n")

                # Show full content
                article_content = content.get('content', '')
                if article_content:
                    print("Full Content:")
                    print(article_content)
                    print("\n" + "="*80 + "\n")

                # Show all tables
                tables = content.get('tables', [])
                for table in tables:
                    print(f"\nTable with {len(table['rows'])} rows:")
                    if table['headers']:
                        print("Headers:", " | ".join(table['headers']))
                    for row in table['rows'][:5]:  # Show first 5 rows
                        print(" | ".join(str(cell) for cell in row))


async def main():
    """Run example searches."""
    print("="*80)
    print("IBISWorld Tool Examples")
    print("="*80)

    print("\n1. Basic Search with Content Extraction:")
    print("-" * 80)
    await basic_search()

    print("\n\n2. Quick Search (No Content Extraction):")
    print("-" * 80)
    await search_without_content_extraction()

    # Uncomment to run specific industry research
    # print("\n\n3. Specific Industry Research:")
    # print("-" * 80)
    # await specific_industry_research()


if __name__ == "__main__":
    asyncio.run(main())
