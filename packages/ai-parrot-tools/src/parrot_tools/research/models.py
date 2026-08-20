"""
Shared Pydantic data models for AI-Parrot research toolkits (FEAT-426).

These models are the common contract between ``OpenDataToolkit``,
``AcademicResearchToolkit``, and ``ResearchRouter``: every toolkit method
returns a :class:`ResearchResult`, and every successful result carries a
:class:`Citation`.

See ``sdd/specs/research-tools-for-agents.spec.md`` §2 "Data Models" for the
normative definitions.
"""
from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Machine-readable citation. Present on every successful result."""

    source_name: str = Field(
        description="Human-readable name of the source, e.g. 'World Bank Open Data'"
    )
    source_url: str = Field(description="Direct URL to the data/paper")
    access_date: str = Field(description="ISO-8601 date the API call was made")
    formatted_citation: str = Field(description="Human-readable citation string")
    data_vintage: str | None = Field(
        default=None,
        description="Best-effort: source publish/update date, when exposed",
    )
    doi: str | None = Field(default=None, description="DOI, if applicable")
    license: str | None = Field(default=None, description="Data/content license")


class IndicatorValue(BaseModel):
    """A single economic/statistical indicator observation."""

    indicator_id: str = Field(description="e.g. 'NY.GDP.MKTP.KD.ZG'")
    indicator_name: str
    country: str = Field(description="ISO-3166 code")
    country_name: str
    year: str
    value: float | None = Field(default=None, description="None for missing observations")
    unit: str | None = None
    source_note: str | None = None


class PaperResult(BaseModel):
    """A single academic paper/article result."""

    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    published_date: str | None = None
    doi: str | None = None
    url: str | None = None
    journal: str | None = None
    citation_count: int | None = None
    fields_of_study: list[str] | None = None
    open_access: bool | None = None
    source: str = Field(
        description="'crossref' | 'pubmed' | 'semantic_scholar' | 'arxiv'"
    )


class DatasetResult(BaseModel):
    """A single open dataset result."""

    title: str
    description: str | None = None
    publisher: str | None = None
    url: str | None = None
    keywords: list[str] | None = None
    format: str | None = None
    last_modified: str | None = None
    source: str = Field(description="'eu_open_data' | 'oecd'")


class ResearchResult(BaseModel):
    """Unified container returned by every research toolkit method.

    Failures are represented here as DATA — never as an exception and never
    as ``ToolResult(status="error")``. See spec §2 "Error Contract".
    """

    query: str
    source: str = Field(description="toolkit + method identifier")
    result_type: str = Field(description="'indicators' | 'papers' | 'datasets'")
    status: str = Field(
        default="success",
        description="'success' | 'partial' | 'no_data' | 'error'",
    )
    error_message: str | None = None
    total_results: int | None = None
    indicators: list[IndicatorValue] | None = None
    papers: list[PaperResult] | None = None
    datasets: list[DatasetResult] | None = None
    # Required in practice for status="success" (enforced by test, not by the
    # type) — Optional so that no_data/error results need not fabricate one.
    citation: Citation | None = None
    raw_metadata: dict[str, Any] | None = None
