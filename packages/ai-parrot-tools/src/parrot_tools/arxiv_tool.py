"""
ArxivTool - Search and retrieve papers from arXiv.org
"""
from typing import List, Dict, Any, Type
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
try:
    import arxiv
except ImportError:
    arxiv = None


class ArxivSearchArgsSchema(AbstractToolArgsSchema):
    """Schema for arXiv search arguments."""
    query: str = Field(
        description="Search query for arXiv papers. Can include keywords, author names, or arXiv categories."
    )
    max_results: int = Field(
        default=5,
        description="Maximum number of results to return (default: 5, max: 100)",
        ge=1,
        le=100
    )
    sort_by: str = Field(
        default="relevance",
        description="Sort order: 'relevance', 'lastUpdatedDate', or 'submittedDate'",
        pattern="^(relevance|lastUpdatedDate|submittedDate)$"
    )
    sort_order: str = Field(
        default="descending",
        description="Sort direction: 'ascending' or 'descending'",
        pattern="^(ascending|descending)$"
    )


class ArxivTool(AbstractTool):
    """
    Tool for searching academic papers on arXiv.org.

    This tool allows searching for papers by keywords, authors, categories, or any combination.
    Returns comprehensive paper information including:
    - Title
    - Authors
    - Publication date
    - Abstract/Summary
    - ArXiv ID
    - PDF URL
    - Categories

    Example queries:
    - "machine learning transformers"
    - "quantum computing"
    - "au:LeCun" (search by author)
    - "cat:cs.AI" (search by category)

    See https://info.arxiv.org/help/api/user-manual.html for advanced query syntax.
    """

    name: str = "arxiv_search"
    description: str = (
        "Search for academic papers on arXiv.org. "
        "Supports keyword search, author search, and category filtering. "
        "Returns paper title, authors, publication date, summary, and links."
    )
    args_schema: Type[BaseModel] = ArxivSearchArgsSchema
    return_direct: bool = False

    def __init__(self, **kwargs):
        """Initialize the arXiv tool."""
        super().__init__(**kwargs)

        if arxiv is None:
            raise ImportError(
                "The 'arxiv' package is required for ArxivTool. "
                "Install it with: pip install arxiv"
            )

    def _format_authors(self, authors: List[arxiv.Result.Author]) -> List[str]:
        """Format author list from arXiv result."""
        return [author.name for author in authors]

    def _format_paper(self, paper: arxiv.Result) -> Dict[str, Any]:
        """
        Format a single arXiv paper result into a structured dictionary.

        Args:
            paper: arXiv Result object

        Returns:
            Dictionary with paper information
        """
        return {
            "title": paper.title,
            "authors": self._format_authors(paper.authors),
            "published": paper.published.strftime("%Y-%m-%d") if paper.published else None,
            "updated": paper.updated.strftime("%Y-%m-%d") if paper.updated else None,
            "summary": paper.summary.replace("\n", " ").strip(),
            "arxiv_id": paper.entry_id.split("/")[-1],
            "pdf_url": paper.pdf_url,
            "categories": paper.categories,
            "primary_category": paper.primary_category,
            "comment": paper.comment if hasattr(paper, "comment") else None,
            "journal_ref": paper.journal_ref if hasattr(paper, "journal_ref") else None,
        }

    async def _execute(
        self,
        query: str,
        max_results: int = 5,
        sort_by: str = "relevance",
        sort_order: str = "descending",
        **kwargs
    ) -> Any:
        """
        Execute arXiv search with given parameters.

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            sort_by: Sort criterion (relevance, lastUpdatedDate, submittedDate)
            sort_order: Sort direction (ascending, descending)
            **kwargs: Additional arguments (ignored)

        Returns:
            List of paper dictionaries with metadata
        """
        try:
            # Map string sort criteria to arxiv.SortCriterion enum
            sort_criterion_map = {
                "relevance": arxiv.SortCriterion.Relevance,
                "lastUpdatedDate": arxiv.SortCriterion.LastUpdatedDate,
                "submittedDate": arxiv.SortCriterion.SubmittedDate,
            }

            # Map string sort order to arxiv.SortOrder enum
            sort_order_map = {
                "ascending": arxiv.SortOrder.Ascending,
                "descending": arxiv.SortOrder.Descending,
            }

            sort_criterion = sort_criterion_map.get(
                sort_by, arxiv.SortCriterion.Relevance
            )
            sort_direction = sort_order_map.get(
                sort_order, arxiv.SortOrder.Descending
            )

            # Create search client
            client = arxiv.Client()

            # Create search query
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=sort_criterion,
                sort_order=sort_direction
            )

            # Execute search and collect results
            papers = []
            papers.extend(
                self._format_paper(paper) for paper in client.results(search)
            )

            if not papers:
                self.logger.warning(f"No results found for query: {query}")
                return {
                    "query": query,
                    "count": 0,
                    "papers": [],
                    "message": "No papers found matching your query."
                }

            self.logger.info(
                f"Found {len(papers)} papers for query: '{query}'"
            )

            return {
                "query": query,
                "count": len(papers),
                "papers": papers,
                "message": f"Found {len(papers)} paper(s)"
            }

        except Exception as e:
            error_msg = f"Error searching arXiv: {str(e)}"
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
