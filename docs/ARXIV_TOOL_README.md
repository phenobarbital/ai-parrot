# ArxivTool for AI-Parrot

A comprehensive tool for searching and retrieving academic papers from arXiv.org, designed to integrate seamlessly with the AI-Parrot framework.

## Features

- 🔍 **Keyword Search**: Search papers by keywords, titles, or abstracts
- 👤 **Author Search**: Find papers by specific authors
- 📁 **Category Filtering**: Filter papers by arXiv categories (cs.AI, math.CO, etc.)
- 📊 **Flexible Sorting**: Sort by relevance, submission date, or last update
- 📄 **Rich Metadata**: Returns title, authors, publication date, summary, PDF links, and more
- 🔧 **Easy Integration**: Works with AI-Parrot's tool manager, agent registry, and toolkit patterns
- ⚡ **Async Support**: Fully asynchronous for high-performance applications

## Installation

```bash
pip install arxiv
```

Or add to your `requirements.txt`:
```
arxiv>=2.1.0
```

## Quick Start

```python
from arxiv_tool import ArxivTool
import asyncio

async def main():
    # Initialize the tool
    tool = ArxivTool()
    
    # Search for papers
    result = await tool.run(
        query="large language models",
        max_results=5
    )
    
    # Process results
    if result.status == "success":
        for paper in result.result['papers']:
            print(f"{paper['title']}")
            print(f"Authors: {', '.join(paper['authors'])}")
            print(f"Published: {paper['published']}")
            print(f"PDF: {paper['pdf_url']}\n")

asyncio.run(main())
```

## Tool Schema

### Input Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | Search query string (keywords, author, category) |
| `max_results` | int | 5 | Maximum number of results (1-100) |
| `sort_by` | str | "relevance" | Sort criterion: "relevance", "lastUpdatedDate", "submittedDate" |
| `sort_order` | str | "descending" | Sort direction: "ascending", "descending" |

### Output Format

```python
{
    "query": str,           # Original search query
    "count": int,          # Number of papers found
    "papers": [            # List of paper objects
        {
            "title": str,
            "authors": List[str],
            "published": str,        # Format: "YYYY-MM-DD"
            "updated": str,          # Format: "YYYY-MM-DD"
            "summary": str,
            "arxiv_id": str,         # e.g., "2301.00234"
            "pdf_url": str,
            "categories": List[str],
            "primary_category": str,
            "comment": Optional[str],
            "journal_ref": Optional[str]
        }
    ],
    "message": str         # Status message
}
```

## Advanced Search Queries

ArxivTool supports the full arXiv API query syntax. Here are some powerful patterns:

### 1. Keyword Search
```python
# Simple keyword search
result = await tool.run(query="machine learning")

# Multiple keywords (implicit AND)
result = await tool.run(query="neural networks deep learning")

# Boolean operators
result = await tool.run(query="quantum AND computing")
result = await tool.run(query="AI OR robotics")
result = await tool.run(query="machine learning ANDNOT supervised")
```

### 2. Field-Specific Search

```python
# Search in titles only
result = await tool.run(query="ti:transformer")

# Search in abstracts
result = await tool.run(query="abs:\"convolutional neural network\"")

# Search by author
result = await tool.run(query="au:LeCun")
result = await tool.run(query="au:Goodfellow AND au:Bengio")

# Search by category
result = await tool.run(query="cat:cs.AI")  # Artificial Intelligence
result = await tool.run(query="cat:cs.LG")  # Machine Learning
result = await tool.run(query="cat:math.CO") # Combinatorics
```

### 3. Combined Queries

```python
# Author + keyword
result = await tool.run(query="au:Hinton AND ti:neural")

# Category + keyword
result = await tool.run(query="cat:cs.CV AND object detection")

# Complex query
result = await tool.run(
    query="(au:LeCun OR au:Bengio) AND cat:cs.AI AND ti:deep"
)
```

### 4. Date-Based Search

```python
# Papers from 2023
result = await tool.run(
    query="submittedDate:[202301010000 TO 202312312359] AND machine learning"
)

# Recent papers (last 30 days)
from datetime import datetime, timedelta
end_date = datetime.now()
start_date = end_date - timedelta(days=30)
query = f"submittedDate:[{start_date.strftime('%Y%m%d%H%M')} TO {end_date.strftime('%Y%m%d%H%M')}]"
result = await tool.run(query=query)
```

## Popular arXiv Categories

### Computer Science
- `cs.AI` - Artificial Intelligence
- `cs.LG` - Machine Learning
- `cs.CV` - Computer Vision
- `cs.CL` - Computation and Language (NLP)
- `cs.NE` - Neural and Evolutionary Computing
- `cs.RO` - Robotics
- `cs.CR` - Cryptography and Security

### Mathematics
- `math.CO` - Combinatorics
- `math.ST` - Statistics Theory
- `math.OC` - Optimization and Control

### Physics
- `physics.comp-ph` - Computational Physics
- `quant-ph` - Quantum Physics

[Full list of categories](https://arxiv.org/category_taxonomy)

## Integration Patterns

### 1. With Agent Registry

```python
from parrot.registry import register_agent
from parrot.bots.bot import AbstractBot
from arxiv_tool import ArxivTool

@register_agent(name="ResearchBot", priority=10)
class ResearchBot(AbstractBot):
    async def configure(self):
        await super().configure()
        arxiv_tool = ArxivTool()
        self.tool_manager.register(arxiv_tool, tool_name="arxiv_search")
```

### 2. With Toolkit Pattern

```python
from parrot.tools.toolkit import AbstractToolkit
from arxiv_tool import ArxivTool

class ResearchToolkit(AbstractToolkit):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.arxiv = ArxivTool()
    
    async def search_papers(self, query: str, max_results: int = 5) -> dict:
        """Search for papers on arXiv."""
        result = await self.arxiv.run(query=query, max_results=max_results)
        return result.result
```

### 3. With LLM Tool Calling

```python
from parrot.clients.openai import OpenAIClient
from arxiv_tool import ArxivTool

client = OpenAIClient(api_key="your-key")
arxiv_tool = ArxivTool()

response = await client.chat(
    messages=[{"role": "user", "content": "Find papers about GPT-4"}],
    tools=[arxiv_tool.get_tool_schema()],
    tool_choice="auto"
)
```

### 4. Standalone Usage

```python
from arxiv_tool import ArxivTool

tool = ArxivTool()

# Direct execution
result = await tool.run(
    query="reinforcement learning",
    max_results=10,
    sort_by="submittedDate"
)

# Access tool schema for LLM registration
schema = tool.get_tool_schema()
```

## Examples

### Example 1: Literature Review Assistant

```python
async def literature_review(topic: str, num_papers: int = 10):
    """Gather papers for a literature review."""
    tool = ArxivTool()
    
    result = await tool.run(
        query=topic,
        max_results=num_papers,
        sort_by="relevance"
    )
    
    papers = result.result['papers']
    
    # Generate markdown report
    report = f"# Literature Review: {topic}\n\n"
    report += f"Found {len(papers)} relevant papers:\n\n"
    
    for i, paper in enumerate(papers, 1):
        report += f"## {i}. {paper['title']}\n\n"
        report += f"**Authors:** {', '.join(paper['authors'])}\n\n"
        report += f"**Published:** {paper['published']}\n\n"
        report += f"**arXiv ID:** [{paper['arxiv_id']}]({paper['pdf_url']})\n\n"
        report += f"**Summary:** {paper['summary']}\n\n"
        report += "---\n\n"
    
    return report
```

### Example 2: Track Researcher's Publications

```python
async def track_researcher(author_name: str):
    """Track recent publications by a researcher."""
    tool = ArxivTool()
    
    result = await tool.run(
        query=f"au:{author_name}",
        max_results=20,
        sort_by="submittedDate",
        sort_order="descending"
    )
    
    papers = result.result['papers']
    
    print(f"Recent papers by {author_name}:")
    for paper in papers[:5]:  # Show 5 most recent
        print(f"\n{paper['published']}: {paper['title']}")
        print(f"Categories: {', '.join(paper['categories'])}")
```

### Example 3: Category Monitor

```python
async def monitor_category(category: str, days: int = 7):
    """Monitor recent papers in a specific category."""
    tool = ArxivTool()
    
    from datetime import datetime, timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    query = (
        f"cat:{category} AND "
        f"submittedDate:[{start_date.strftime('%Y%m%d0000')} "
        f"TO {end_date.strftime('%Y%m%d2359')}]"
    )
    
    result = await tool.run(
        query=query,
        max_results=50,
        sort_by="submittedDate"
    )
    
    return result.result['papers']
```

### Example 4: Comparative Analysis

```python
async def compare_research_trends(topics: list):
    """Compare publication trends across multiple topics."""
    tool = ArxivTool()
    
    results = {}
    for topic in topics:
        result = await tool.run(
            query=topic,
            max_results=100,
            sort_by="submittedDate"
        )
        results[topic] = result.result['count']
    
    # Analyze trends
    print("Publication counts by topic:")
    for topic, count in sorted(results.items(), key=lambda x: x[1], reverse=True):
        print(f"{topic}: {count} papers")
```

## Error Handling

```python
from arxiv_tool import ArxivTool

async def safe_search():
    tool = ArxivTool()
    
    try:
        result = await tool.run(query="machine learning", max_results=5)
        
        if result.status == "success":
            papers = result.result['papers']
            if not papers:
                print("No papers found")
            else:
                for paper in papers:
                    print(paper['title'])
        else:
            print(f"Search failed: {result.error}")
            
    except ImportError:
        print("arxiv package not installed")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
```

## Performance Tips

1. **Limit Results**: Don't request more papers than you need
   ```python
   result = await tool.run(query="AI", max_results=10)  # Not 100
   ```

2. **Use Specific Queries**: More specific queries return better results faster
   ```python
   # Good
   result = await tool.run(query="ti:transformer AND cat:cs.AI")
   
   # Less efficient
   result = await tool.run(query="machine learning")
   ```

3. **Cache Results**: Store frequently accessed papers
   ```python
   cache = {}
   
   async def cached_search(query: str):
       if query in cache:
           return cache[query]
       result = await tool.run(query=query)
       cache[query] = result
       return result
   ```

## Testing

```python
# Run the included tests
python arxiv_tool.py

# Or use pytest
pytest test_arxiv_tool.py
```

## API Reference

See the [arXiv API documentation](https://info.arxiv.org/help/api/user-manual.html) for complete query syntax details.

## Contributing

Contributions are welcome! Areas for improvement:
- Add support for arXiv bulk data downloads
- Implement paper recommendation based on citations
- Add author collaboration network analysis
- Support for arXiv RSS feeds

## License

This tool is part of the AI-Parrot framework. See the main project license.

## Credits

Built on top of the excellent [arxiv](https://github.com/lukasschwab/arxiv.py) Python package by Lukas Schwab.

---

**Author**: AI-Parrot Development Team  
**Last Updated**: October 2025  
**Version**: 1.0.0
