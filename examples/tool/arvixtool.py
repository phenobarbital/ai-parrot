"""
ArxivTool Integration Guide for AI-Parrot
==========================================

This guide demonstrates how to integrate and use the ArxivTool in your AI-Parrot
agents and chatbots.
"""
import asyncio
from parrot.tools.arxiv_tool import ArxivTool
from parrot.tools.toolkit import AbstractToolkit

# ============================================================================
# BASIC USAGE
# ============================================================================


async def basic_search_example():
    """Basic example of using ArxivTool directly."""

    # Initialize the tool
    arxiv_tool = ArxivTool()

    # Simple keyword search
    result = await arxiv_tool.execute(
        query="large language models",
        max_results=5
    )

    if result.status == "success":
        papers = result.result['papers']
        print(f"Found {len(papers)} papers:")
        for paper in papers:
            print(f"\n{paper['title']}")
            print(f"Authors: {', '.join(paper['authors'])}")
            print(f"Published: {paper['published']}")
            print(f"Summary: {paper['summary'][:200]}...")

    return result


# ============================================================================
# USING WITH TOOLKIT PATTERN
# ============================================================================
class AcademicResearchToolkit(AbstractToolkit):
    """
    A toolkit for academic research that includes arXiv search.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.arxiv = ArxivTool()

    async def search_papers(
        self,
        query: str,
        max_results: int = 5
    ) -> dict:
        """
        Search for academic papers on arXiv.

        Args:
            query: Search query (keywords, author, or category)
            max_results: Maximum number of results to return

        Returns:
            Dictionary with paper results
        """
        result = await self.arxiv.execute(
            query=query,
            max_results=max_results
        )
        return result.result

    async def search_by_author(
        self,
        author_name: str,
        max_results: int = 5
    ) -> dict:
        """
        Search for papers by a specific author.

        Args:
            author_name: Author's name
            max_results: Maximum number of results

        Returns:
            Dictionary with paper results
        """
        query = f"au:{author_name}"
        result = await self.arxiv.execute(
            query=query,
            max_results=max_results,
            sort_by="submittedDate"
        )
        return result.result

    async def search_by_category(
        self,
        category: str,
        max_results: int = 5
    ) -> dict:
        """
        Search for papers in a specific arXiv category.

        Args:
            category: arXiv category (e.g., 'cs.AI', 'math.CO')
            max_results: Maximum number of results

        Returns:
            Dictionary with paper results
        """
        query = f"cat:{category}"
        result = await self.arxiv.execute(
            query=query,
            max_results=max_results,
            sort_by="submittedDate",
            sort_order="descending"
        )
        return result.result


# ============================================================================
# ADVANCED SEARCH PATTERNS
# ============================================================================

async def advanced_search_examples():
    """Demonstrate advanced arXiv search patterns."""

    arxiv_tool = ArxivTool()

    # 1. Boolean operators
    print("1. Boolean search (AND):")
    result = await arxiv_tool.execute(
        query="quantum AND computing",
        max_results=3
    )

    # 2. Author search
    print("\n2. Search by author:")
    result = await arxiv_tool.execute(
        query="au:Goodfellow",
        max_results=3
    )

    # 3. Category search
    print("\n3. Search by category (Computer Science - AI):")
    result = await arxiv_tool.execute(
        query="cat:cs.AI",
        max_results=3,
        sort_by="submittedDate"
    )

    # 4. Title search
    print("\n4. Search in titles only:")
    result = await arxiv_tool.execute(
        query="ti:transformer",
        max_results=3
    )

    # 5. Abstract search
    print("\n5. Search in abstracts:")
    result = await arxiv_tool.execute(
        query="abs:\"deep learning\"",
        max_results=3
    )

    # 6. Combined search
    print("\n6. Complex query (author + category):")
    result = await arxiv_tool.execute(
        query="au:LeCun AND cat:cs.CV",
        max_results=3
    )

    # 7. Date range (all papers from 2023)
    print("\n7. Papers from specific time period:")
    result = await arxiv_tool.execute(
        query="submittedDate:[202301010000 TO 202312312359] AND ti:GPT",
        max_results=3
    )

if __name__ == "__main__":
    print("ArxivTool Integration Examples")
    print("=" * 80)

    # Run basic example
    print("\n1. Basic Search Example:")
    asyncio.run(basic_search_example())

    # Run advanced examples
    print("\n2. Advanced Search Patterns:")
    asyncio.run(advanced_search_examples())
