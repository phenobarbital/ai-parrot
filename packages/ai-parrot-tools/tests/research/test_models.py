"""Unit tests for FEAT-426 shared research Pydantic models."""
import pytest
from parrot_tools.research.models import (
    Citation,
    DatasetResult,
    IndicatorValue,
    PaperResult,
    ResearchResult,
)
from pydantic import ValidationError


class TestCitation:
    def test_citation_required_fields(self):
        """Citation requires source_name, source_url, access_date, formatted_citation."""
        citation = Citation(
            source_name="World Bank Open Data",
            source_url="https://api.worldbank.org/v2/...",
            access_date="2026-08-17",
            formatted_citation="World Bank Open Data. Retrieved 2026-08-17.",
        )
        assert citation.source_name == "World Bank Open Data"
        assert citation.data_vintage is None
        assert citation.doi is None
        assert citation.license is None

        with pytest.raises(ValidationError):
            Citation(source_name="X")  # missing required fields


class TestResearchResult:
    def test_research_result_defaults(self):
        """`status` defaults to "success"; `citation` may be None."""
        result = ResearchResult(
            query="gdp growth", source="open_data.search_world_bank",
            result_type="indicators",
        )
        assert result.status == "success"
        assert result.citation is None
        assert result.error_message is None

    def test_research_result_with_indicators(self):
        indicator = IndicatorValue(
            indicator_id="NY.GDP.MKTP.KD.ZG",
            indicator_name="GDP growth (annual %)",
            country="USA",
            country_name="United States",
            year="2023",
            value=2.5,
        )
        result = ResearchResult(
            query="gdp growth", source="open_data.search_world_bank",
            result_type="indicators", indicators=[indicator],
        )
        assert result.indicators[0].value == 2.5

    def test_research_result_with_papers(self):
        paper = PaperResult(title="A Paper", source="crossref")
        result = ResearchResult(
            query="quantum computing", source="academic.search_crossref",
            result_type="papers", papers=[paper],
        )
        assert result.papers[0].source == "crossref"

    def test_research_result_with_datasets(self):
        dataset = DatasetResult(title="A Dataset", source="eu_open_data")
        result = ResearchResult(
            query="air quality", source="open_data.search_eu_open_data",
            result_type="datasets", datasets=[dataset],
        )
        assert result.datasets[0].source == "eu_open_data"
