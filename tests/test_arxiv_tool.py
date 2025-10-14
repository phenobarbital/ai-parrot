"""
Test suite for ArxivTool
"""
import pytest
import asyncio
from datetime import datetime
from arxiv_tool import ArxivTool, ArxivSearchArgsSchema


class TestArxivSearchArgsSchema:
    """Test the Pydantic schema for arXiv search arguments."""
    
    def test_valid_schema(self):
        """Test valid schema instantiation."""
        schema = ArxivSearchArgsSchema(
            query="machine learning",
            max_results=10,
            sort_by="relevance",
            sort_order="descending"
        )
        assert schema.query == "machine learning"
        assert schema.max_results == 10
        assert schema.sort_by == "relevance"
        assert schema.sort_order == "descending"
    
    def test_default_values(self):
        """Test default values are applied correctly."""
        schema = ArxivSearchArgsSchema(query="test")
        assert schema.max_results == 5
        assert schema.sort_by == "relevance"
        assert schema.sort_order == "descending"
    
    def test_max_results_validation(self):
        """Test max_results validation constraints."""
        # Should fail - too low
        with pytest.raises(ValueError):
            ArxivSearchArgsSchema(query="test", max_results=0)
        
        # Should fail - too high
        with pytest.raises(ValueError):
            ArxivSearchArgsSchema(query="test", max_results=101)
        
        # Should pass
        schema = ArxivSearchArgsSchema(query="test", max_results=50)
        assert schema.max_results == 50
    
    def test_sort_by_validation(self):
        """Test sort_by field validation."""
        # Valid values
        for sort_by in ["relevance", "lastUpdatedDate", "submittedDate"]:
            schema = ArxivSearchArgsSchema(query="test", sort_by=sort_by)
            assert schema.sort_by == sort_by
        
        # Invalid value should fail
        with pytest.raises(ValueError):
            ArxivSearchArgsSchema(query="test", sort_by="invalid")
    
    def test_sort_order_validation(self):
        """Test sort_order field validation."""
        # Valid values
        for sort_order in ["ascending", "descending"]:
            schema = ArxivSearchArgsSchema(query="test", sort_order=sort_order)
            assert schema.sort_order == sort_order
        
        # Invalid value should fail
        with pytest.raises(ValueError):
            ArxivSearchArgsSchema(query="test", sort_order="invalid")


class TestArxivTool:
    """Test the ArxivTool functionality."""
    
    @pytest.fixture
    def arxiv_tool(self):
        """Create an ArxivTool instance for testing."""
        return ArxivTool()
    
    def test_tool_initialization(self, arxiv_tool):
        """Test tool is initialized correctly."""
        assert arxiv_tool.name == "arxiv_search"
        assert arxiv_tool.description is not None
        assert arxiv_tool.args_schema == ArxivSearchArgsSchema
        assert arxiv_tool.return_direct is False
    
    def test_tool_schema_generation(self, arxiv_tool):
        """Test get_tool_schema returns valid schema."""
        schema = arxiv_tool.get_tool_schema()
        
        assert "name" in schema
        assert schema["name"] == "arxiv_search"
        assert "description" in schema
        assert "parameters" in schema
        
        params = schema["parameters"]
        assert "properties" in params
        assert "query" in params["properties"]
        assert "max_results" in params["properties"]
        assert "sort_by" in params["properties"]
        assert "sort_order" in params["properties"]
    
    @pytest.mark.asyncio
    async def test_basic_search(self, arxiv_tool):
        """Test basic keyword search."""
        result = await arxiv_tool.run(
            query="machine learning",
            max_results=3
        )
        
        assert result.status == "success"
        assert result.result is not None
        assert "papers" in result.result
        assert "count" in result.result
        assert "query" in result.result
        
        papers = result.result["papers"]
        assert len(papers) > 0
        assert len(papers) <= 3
        
        # Check paper structure
        paper = papers[0]
        assert "title" in paper
        assert "authors" in paper
        assert "published" in paper
        assert "summary" in paper
        assert "arxiv_id" in paper
        assert "pdf_url" in paper
        assert "categories" in paper
    
    @pytest.mark.asyncio
    async def test_author_search(self, arxiv_tool):
        """Test searching by author."""
        result = await arxiv_tool.run(
            query="au:LeCun",
            max_results=3
        )
        
        assert result.status == "success"
        papers = result.result["papers"]
        assert len(papers) > 0
        
        # Verify author is in the results
        found_lecun = False
        for paper in papers:
            if any("lecun" in author.lower() for author in paper["authors"]):
                found_lecun = True
                break
        assert found_lecun
    
    @pytest.mark.asyncio
    async def test_category_search(self, arxiv_tool):
        """Test searching by category."""
        result = await arxiv_tool.run(
            query="cat:cs.AI",
            max_results=3
        )
        
        assert result.status == "success"
        papers = result.result["papers"]
        assert len(papers) > 0
        
        # Verify papers are from cs.AI category
        for paper in papers:
            assert "cs.AI" in paper["categories"] or paper["primary_category"] == "cs.AI"
    
    @pytest.mark.asyncio
    async def test_sort_by_date(self, arxiv_tool):
        """Test sorting by submission date."""
        result = await arxiv_tool.run(
            query="machine learning",
            max_results=5,
            sort_by="submittedDate",
            sort_order="descending"
        )
        
        assert result.status == "success"
        papers = result.result["papers"]
        
        # Check papers are sorted by date (most recent first)
        if len(papers) >= 2:
            dates = [datetime.strptime(p["published"], "%Y-%m-%d") for p in papers]
            for i in range(len(dates) - 1):
                assert dates[i] >= dates[i + 1]
    
    @pytest.mark.asyncio
    async def test_max_results_limit(self, arxiv_tool):
        """Test max_results parameter limits results."""
        for limit in [1, 3, 5, 10]:
            result = await arxiv_tool.run(
                query="neural networks",
                max_results=limit
            )
            
            assert result.status == "success"
            papers = result.result["papers"]
            assert len(papers) <= limit
    
    @pytest.mark.asyncio
    async def test_empty_results(self, arxiv_tool):
        """Test handling of queries with no results."""
        # Use a very specific query unlikely to return results
        result = await arxiv_tool.run(
            query="ti:xyzabc123nonexistent",
            max_results=5
        )
        
        assert result.status == "success"
        assert result.result["count"] == 0
        assert len(result.result["papers"]) == 0
        assert "No papers found" in result.result["message"]
    
    @pytest.mark.asyncio
    async def test_paper_metadata_completeness(self, arxiv_tool):
        """Test that returned papers have complete metadata."""
        result = await arxiv_tool.run(
            query="transformer",
            max_results=1
        )
        
        assert result.status == "success"
        paper = result.result["papers"][0]
        
        # Required fields
        assert paper["title"] is not None and len(paper["title"]) > 0
        assert paper["authors"] is not None and len(paper["authors"]) > 0
        assert paper["published"] is not None
        assert paper["summary"] is not None and len(paper["summary"]) > 0
        assert paper["arxiv_id"] is not None
        assert paper["pdf_url"] is not None and paper["pdf_url"].startswith("http")
        assert paper["categories"] is not None and len(paper["categories"]) > 0
        assert paper["primary_category"] is not None
        
        # Verify date format
        datetime.strptime(paper["published"], "%Y-%m-%d")
        
        # Verify PDF URL format
        assert "arxiv.org" in paper["pdf_url"]
    
    @pytest.mark.asyncio
    async def test_complex_query(self, arxiv_tool):
        """Test complex boolean queries."""
        result = await arxiv_tool.run(
            query="(ti:transformer OR ti:attention) AND cat:cs.AI",
            max_results=5
        )
        
        assert result.status == "success"
        papers = result.result["papers"]
        assert len(papers) > 0
        
        # Verify results match criteria
        for paper in papers:
            title_lower = paper["title"].lower()
            has_keyword = "transformer" in title_lower or "attention" in title_lower
            has_category = "cs.AI" in paper["categories"] or paper["primary_category"] == "cs.AI"
            assert has_keyword or has_category  # Due to relevance scoring, might not be exact
    
    @pytest.mark.asyncio
    async def test_concurrent_searches(self, arxiv_tool):
        """Test multiple concurrent searches."""
        queries = [
            "machine learning",
            "deep learning",
            "neural networks"
        ]
        
        tasks = [
            arxiv_tool.run(query=q, max_results=2)
            for q in queries
        ]
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 3
        for result in results:
            assert result.status == "success"
            assert len(result.result["papers"]) > 0
    
    def test_format_authors(self, arxiv_tool):
        """Test author formatting method."""
        # Create mock authors
        class MockAuthor:
            def __init__(self, name):
                self.name = name
        
        authors = [
            MockAuthor("John Doe"),
            MockAuthor("Jane Smith"),
            MockAuthor("Bob Wilson")
        ]
        
        formatted = arxiv_tool._format_authors(authors)
        assert formatted == ["John Doe", "Jane Smith", "Bob Wilson"]
    
    @pytest.mark.asyncio
    async def test_validate_args(self, arxiv_tool):
        """Test argument validation."""
        # Valid arguments
        validated = arxiv_tool.validate_args(
            query="test",
            max_results=5,
            sort_by="relevance",
            sort_order="descending"
        )
        assert validated.query == "test"
        
        # Invalid max_results
        with pytest.raises(ValueError):
            arxiv_tool.validate_args(
                query="test",
                max_results=200  # Too high
            )


class TestArxivToolIntegration:
    """Integration tests for ArxivTool with AI-Parrot components."""
    
    @pytest.mark.asyncio
    async def test_tool_result_format(self):
        """Test that tool returns proper ToolResult object."""
        tool = ArxivTool()
        result = await tool.run(query="AI", max_results=1)
        
        # ToolResult attributes
        assert hasattr(result, "status")
        assert hasattr(result, "result")
        assert hasattr(result, "error")
        assert hasattr(result, "metadata")
        assert hasattr(result, "timestamp")
        
        # Verify timestamp format
        datetime.fromisoformat(result.timestamp)
    
    @pytest.mark.asyncio
    async def test_tool_with_tool_manager(self):
        """Test integration with ToolManager (if available)."""
        try:
            from parrot.tools.manager import ToolManager
            
            manager = ToolManager()
            tool = ArxivTool()
            
            # Register tool
            manager.register(tool, tool_name="arxiv_search")
            
            # Retrieve tool
            retrieved_tool = manager.get_tool("arxiv_search")
            assert retrieved_tool is not None
            
            # Get schema
            schema = manager.extract_tool_schema(retrieved_tool, "arxiv_search")
            assert schema is not None
            assert schema["name"] == "arxiv_search"
            
        except ImportError:
            pytest.skip("ToolManager not available")


# Performance benchmarks (optional)
class TestArxivToolPerformance:
    """Performance tests for ArxivTool."""
    
    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_search_performance(self):
        """Benchmark search performance."""
        tool = ArxivTool()
        
        import time
        start = time.time()
        
        result = await tool.run(
            query="machine learning",
            max_results=10
        )
        
        elapsed = time.time() - start
        
        assert result.status == "success"
        assert elapsed < 5.0  # Should complete in under 5 seconds
        print(f"Search took {elapsed:.2f} seconds")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
