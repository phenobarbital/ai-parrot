# IBISWorld Tool

A Parrot Tool for searching and extracting content from IBISWorld industry research articles.

## Overview

The IBISWorld Tool extends the Google Site Search functionality to provide specialized content extraction from IBISWorld.com. It searches within the IBISWorld domain and automatically extracts article content, statistics, tables, and metadata.

## Features

- **Site-Specific Search**: Searches exclusively within ibisworld.com using Google Custom Search API
- **Content Extraction**: Automatically extracts article text, titles, and metadata
- **Table Extraction**: Captures data tables and structured information
- **Statistics Parsing**: Identifies and extracts key statistics and metrics
- **Flexible Options**: Choose whether to extract full content or just get search results

## Requirements

- Google Custom Search API credentials (GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_ENGINE_ID)
- BeautifulSoup4 for HTML parsing
- aiohttp for async HTTP requests

## Installation

The tool is included in the ai-parrot framework. Ensure you have the required dependencies:

```bash
pip install beautifulsoup4 aiohttp lxml
```

## Usage

### Basic Usage

```python
import asyncio
from parrot.tools.ibisworld import IBISWorldTool

async def search_ibisworld():
    tool = IBISWorldTool()

    result = await tool.execute(
        query="restaurant industry trends",
        max_results=5,
        extract_content=True,
        include_tables=True
    )

    if result.status == "success":
        for item in result.result['results']:
            print(f"Title: {item['title']}")
            print(f"URL: {item['link']}")

            if 'extracted_content' in item:
                content = item['extracted_content']
                print(f"Content: {content['content'][:200]}...")
                print(f"Tables found: {len(content['tables'])}")

asyncio.run(search_ibisworld())
```

### Quick Search (No Content Extraction)

For faster results when you only need search result links:

```python
result = await tool.execute(
    query="automotive manufacturing",
    max_results=10,
    extract_content=False  # Skip content extraction
)
```

### With Table Extraction

Extract structured data from tables in articles:

```python
result = await tool.execute(
    query="healthcare industry statistics",
    max_results=3,
    extract_content=True,
    include_tables=True  # Extract tables from articles
)

for item in result.result['results']:
    if 'extracted_content' in item:
        tables = item['extracted_content']['tables']
        for table in tables:
            print(f"Table with {len(table['rows'])} rows")
            print(f"Headers: {table['headers']}")
```

## Arguments

### IBISWorldSearchArgs

- **query** (str, required): Search query for IBISWorld content
- **max_results** (int, optional): Maximum number of results to return (1-10, default: 5)
- **extract_content** (bool, optional): Extract full article content (default: True)
- **include_tables** (bool, optional): Include tables and structured data (default: True)

## Response Structure

### Success Response

```python
{
    'status': 'success',
    'result': {
        'query': 'original search query',
        'site': 'ibisworld.com',
        'search_query': 'original search query site:ibisworld.com',
        'total_results': 5,
        'source': 'IBISWorld',
        'domain': 'ibisworld.com',
        'content_extracted': True,
        'results': [
            {
                'title': 'Article Title',
                'link': 'https://ibisworld.com/...',
                'snippet': 'Search result snippet',
                'description': 'Search result description',
                'has_content': True,
                'extracted_content': {
                    'url': 'https://ibisworld.com/...',
                    'title': 'Full Article Title',
                    'content': 'Full article text...',
                    'metadata': {
                        'publication_date': '2024-01-15',
                        'author': 'Author Name',
                        # ... other meta tags
                    },
                    'tables': [
                        {
                            'table_id': 1,
                            'headers': ['Column 1', 'Column 2'],
                            'rows': [
                                ['Data 1', 'Data 2'],
                                ['Data 3', 'Data 4']
                            ]
                        }
                    ],
                    'statistics': {
                        'Market Size': '$XX billion',
                        'Growth Rate': 'X.X%',
                        # ... other statistics
                    }
                }
            }
        ]
    }
}
```

## Content Extraction Details

The tool extracts content using multiple strategies:

1. **Title Extraction**: Searches for article titles using common HTML patterns
2. **Main Content**: Identifies article content containers and extracts paragraphs
3. **Metadata**: Extracts publication dates, authors, and meta tags
4. **Tables**: Parses HTML tables with headers and data rows
5. **Statistics**: Identifies key-value pairs and numeric data

## Integration with Agents

Use with conversational agents or LLM-based systems:

```python
from parrot.agents import Agent
from parrot.tools.ibisworld import IBISWorldTool

agent = Agent(
    name="Industry Researcher",
    tools=[IBISWorldTool()],
    instructions="Research industry trends using IBISWorld"
)

response = await agent.run(
    "What are the latest trends in the restaurant industry?"
)
```

## Error Handling

The tool handles common errors gracefully:

- HTTP errors (403, 404, 500, etc.)
- Timeout errors
- Parsing errors
- Missing content

Errors are logged and included in the response:

```python
{
    'error': 'HTTP 403',
    'content': None
}
```

## Limitations

- Requires valid Google Custom Search API credentials
- Subject to Google API rate limits and quotas
- Content extraction accuracy depends on IBISWorld's HTML structure
- Some content may be behind paywalls or require authentication

## Configuration

Set environment variables or configure in your application:

```bash
export GOOGLE_SEARCH_API_KEY="your-api-key"
export GOOGLE_SEARCH_ENGINE_ID="your-cse-id"
```

## Examples

See `examples/tools/ibisworld.py` for complete working examples.

## License

Part of the AI-Parrot framework.
