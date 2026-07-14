"""Pydantic data models for the LLM Wiki feature (FEAT-260).

Defines all shared data structures used across the wiki package:
- WikiPageCategory: Karpathy's wiki page type taxonomy
- WikiConfig: per-wiki-instance configuration
- SourceManifestEntry: tracks an ingested source document
- WikiSearchResult: unified result from combined search
- WikiLintReport: extended lint report with wiki-specific checks

Design notes:
- All models follow the same Pydantic v2 pattern used throughout ai-parrot.
- WikiConfig.search_weights is validated to ensure all values are in [0, 1]
  and their sum is approximately 1.0 (within 0.01 tolerance).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class WikiPageCategory(str, Enum):
    """Karpathy's wiki page type taxonomy.

    Attributes:
        SUMMARY: High-level summary of a source document or topic.
        ENTITY: Named entity page (person, organisation, product, etc.).
        CONCEPT: Abstract concept or idea extracted from sources.
        COMPARISON: Side-by-side comparison of two or more topics.
        OVERVIEW: Broad overview spanning multiple related topics.
        SYNTHESIS: LLM-synthesised insight across several sources.
        ANSWER: Direct answer to a query, filed as a wiki page.
    """

    SUMMARY = "summary"
    ENTITY = "entity"
    CONCEPT = "concept"
    COMPARISON = "comparison"
    OVERVIEW = "overview"
    SYNTHESIS = "synthesis"
    ANSWER = "answer"


class WikiConfig(BaseModel):
    """Configuration for a single wiki instance.

    Attributes:
        wiki_name: Unique identifier / human-readable name for the wiki.
        storage_dir: Root directory where all wiki data is persisted.
        source_dir: Optional dedicated directory for raw source documents.
            Defaults to ``{storage_dir}/sources`` when omitted.
        page_categories: Ordered list of page categories that this wiki
            supports.  Defaults to all seven WikiPageCategory values.
        search_weights: Relative weighting applied to each search backend
            during combined-search score merging.  Keys must be
            ``"pageindex"`` and ``"graphindex"``; values must sum to ~1.0.
        lightweight_model: Optional model identifier for the fast CoT
            (analysis) step of TwoStepIngester.  Falls back to ``model``
            when ``None``.
        model: Optional model identifier for the heavyweight generation
            step of TwoStepIngester.
        sync_graph: When ``True``, wiki writes also mirror pages into
            GraphIndex.  Off by default — the WikiStore SQLite plane is
            the wiki's retrieval backend.
    """

    wiki_name: str = Field(..., description="Unique wiki name / identifier")
    storage_dir: Path = Field(..., description="Root storage directory")
    source_dir: Optional[Path] = Field(
        default=None,
        description="Raw sources directory; defaults to storage_dir/sources",
    )
    page_categories: list[WikiPageCategory] = Field(
        default_factory=lambda: list(WikiPageCategory),
        description="Supported page categories (all by default)",
    )
    search_weights: dict[str, float] = Field(
        default_factory=lambda: {"pageindex": 0.6, "graphindex": 0.4},
        description="Score weights per search backend; must sum to ~1.0",
    )
    lightweight_model: Optional[str] = Field(
        default=None,
        description="LLM model for fast CoT analysis step",
    )
    model: Optional[str] = Field(
        default=None,
        description="LLM model for heavyweight generation step",
    )
    sync_graph: bool = Field(
        default=False,
        description=(
            "Mirror wiki pages into GraphIndex on write. Off by default — "
            "the WikiStore SQLite plane is the retrieval backend."
        ),
    )

    @field_validator("search_weights")
    @classmethod
    def validate_search_weights(cls, v: dict[str, float]) -> dict[str, float]:
        """Ensure each weight is in [0, 1] and the total is approximately 1.

        Args:
            v: The raw search_weights mapping.

        Returns:
            The validated mapping unchanged.

        Raises:
            ValueError: If any weight is outside [0, 1] or the sum deviates
                from 1.0 by more than 0.01.
        """
        for key, weight in v.items():
            if not (0.0 <= weight <= 1.0):
                raise ValueError(
                    f"search_weights['{key}'] = {weight} is outside [0, 1]"
                )
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"search_weights values must sum to ~1.0 (got {total:.4f})"
            )
        return v


class SourceManifestEntry(BaseModel):
    """Tracks an ingested source document in the wiki's source manifest.

    Attributes:
        source_id: Stable deterministic identifier for the source (e.g.,
            SHA-1 of the URI path).
        source_uri: Absolute URI / path to the original source file.
        file_hash: SHA-1 hex digest of the source file contents at ingest time.
        mtime: File modification timestamp (``os.stat().st_mtime``) at
            ingest time, used for quick staleness pre-check.
        ingested_at: ISO-8601 UTC timestamp of when the ingest completed.
        pages_generated: Ordered list of wiki page IDs that were created or
            updated during this ingest.
        status: Lifecycle status.  ``"ingested"`` after a successful ingest;
            may be ``"stale"`` or ``"error"`` as appropriate.
    """

    source_id: str = Field(..., description="Stable source identifier")
    source_uri: str = Field(..., description="Absolute path or URI")
    file_hash: str = Field(..., description="SHA-1 hex digest at ingest time")
    mtime: float = Field(..., description="File mtime at ingest time")
    ingested_at: str = Field(..., description="ISO-8601 UTC ingest timestamp")
    pages_generated: list[str] = Field(
        default_factory=list,
        description="Wiki page IDs produced by this ingest",
    )
    status: str = Field(
        default="ingested",
        description="Source lifecycle status",
    )


class WikiSearchResult(BaseModel):
    """Unified search result returned by combined (PageIndex + GraphIndex) search.

    Attributes:
        node_id: Stable node/page identifier in the underlying index.
        title: Human-readable page or node title.
        score: Normalised relevance score in [0, 1] after weight application.
        source: Which backend produced this result — ``"pageindex"`` or
            ``"graphindex"``.
        snippet: Short excerpt or summary extracted from the page content.
        category: Optional WikiPageCategory if the page has one.
    """

    node_id: str = Field(..., description="Stable node/page identifier")
    title: str = Field(..., description="Page or node title")
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalised relevance score in [0, 1]",
    )
    source: str = Field(
        ...,
        description="Search backend: 'pageindex' or 'graphindex'",
    )
    snippet: str = Field(
        default="",
        description="Short content excerpt or summary",
    )
    category: Optional[WikiPageCategory] = Field(
        default=None,
        description="Wiki page category if known",
    )


class WikiLintReport(BaseModel):
    """Extended lint report combining OKF checks with wiki-specific checks.

    Attributes:
        okf_report: Raw dictionary returned by OKFToolkit.lint_knowledge_base().
        orphan_sources: Source IDs present in the manifest but with no
            corresponding wiki pages.
        stale_sources: Source IDs whose file hash or mtime has changed since
            the last ingest.
        uncovered_sources: Source IDs that were never ingested at all.
        cross_ref_issues: List of dicts describing broken cross-references
            between wiki pages.
        total_issues: Aggregate count of all issues across all checks.
    """

    okf_report: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw output from lint_knowledge_base()",
    )
    orphan_sources: list[str] = Field(
        default_factory=list,
        description="Source IDs with no wiki pages",
    )
    stale_sources: list[str] = Field(
        default_factory=list,
        description="Source IDs whose content has changed",
    )
    uncovered_sources: list[str] = Field(
        default_factory=list,
        description="Source IDs that were never ingested",
    )
    cross_ref_issues: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Broken cross-reference descriptors",
    )
    total_issues: int = Field(
        default=0,
        description="Aggregate issue count",
    )

    @model_validator(mode="after")
    def compute_total_issues(self) -> WikiLintReport:
        """Recompute total_issues from the individual issue lists.

        Returns:
            The model instance with an updated ``total_issues`` count.
        """
        self.total_issues = (
            len(self.orphan_sources)
            + len(self.stale_sources)
            + len(self.uncovered_sources)
            + len(self.cross_ref_issues)
        )
        return self
