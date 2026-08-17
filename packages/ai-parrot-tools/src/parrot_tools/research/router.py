"""
ResearchRouter — cross-category dispatch tool (FEAT-426 Module 4).

A standalone `AbstractTool` (not a toolkit method) that classifies a
natural-language research question into one or both of the two research
categories (`open_data`, `academic`) and dispatches concurrently to the
relevant toolkit methods.

Two framework traps apply here and are both deliberately guarded against:

1. `AbstractTool` does **not** infer an args schema from `_execute` — an
   explicit `args_schema` is mandatory, or every parameter the LLM
   supplies is silently discarded (`abstract.py:629`). See
   `ResearchRouterArgs` below.
2. Tools have **no back-reference to the calling agent's LLM**
   (`abstract.py:265`, documented framework invariant). The classifier
   client is injected through the constructor instead — see the
   `db.py`-style `llm=` pattern.

See spec §2 "Error Contract" and §3 Module 4.
"""
import asyncio
import json
import re
from typing import Any, Optional

from parrot.clients.base import AbstractClient
from parrot.clients.factory import LLMFactory
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from pydantic import BaseModel, Field

from .academic import AcademicResearchToolkit
from .open_data import OpenDataToolkit

VALID_CATEGORIES = ("open_data", "academic")

# Keyword heuristics used when `llm is None` or classification fails.
_OPEN_DATA_KEYWORDS = (
    "gdp", "indicator", "population", "country", "statistics", "economy",
    "economic", "trade", "inflation", "unemployment", "dataset", "oecd",
    "world bank", "eu open data",
)
_ACADEMIC_KEYWORDS = (
    "paper", "papers", "study", "studies", "doi", "author", "journal",
    "research", "publication", "preprint", "arxiv", "pubmed", "crossref",
    "citation", "literature",
)

_CLASSIFIER_PROMPT_TEMPLATE = (
    "Classify the following research question into one or both of these "
    'categories: "open_data" (economic/statistical indicators — World '
    'Bank, EU Open Data, OECD) and "academic" (academic literature — '
    "Crossref, PubMed, Semantic Scholar, arXiv).\n\n"
    "Question: {query}\n\n"
    'Respond with ONLY a JSON array of category names, e.g. ["open_data"] '
    'or ["open_data", "academic"]. No other text.'
)


class ResearchRouterArgs(AbstractToolArgsSchema):
    """Explicit args schema — REQUIRED, see module docstring trap #1."""

    query: str = Field(description="Natural-language research question")
    categories: list[str] | None = Field(
        default=None,
        description="Restrict to: open_data, academic. Omit to auto-classify.",
    )
    max_results: int = Field(default=10, ge=1, le=50)


class ResearchRouter(AbstractTool):
    """Answer a research question by dispatching to the right toolkit(s).

    Classifies the query into `open_data` and/or `academic` using an
    explicitly injected LLM client (constructor `llm=`), falling back to
    keyword heuristics when `llm` is `None` or classification fails.
    Dispatches concurrently to the selected toolkit(s) and merges the
    results into a single, always-successful `ToolResult` — per-category
    failures are recorded in the payload rather than raised (spec §2
    Error Contract).
    """

    name: str = "research"
    description: str = (
        "Answer a research question using authoritative sources: World Bank, "
        "EU Open Data, OECD (economic/statistical indicators) and Crossref, "
        "PubMed, Semantic Scholar, arXiv (academic literature). Returns "
        "structured results with citations."
    )
    args_schema: type[BaseModel] = ResearchRouterArgs

    def __init__(
        self,
        open_data: Optional["OpenDataToolkit"] = None,
        academic: Optional["AcademicResearchToolkit"] = None,
        llm: AbstractClient | str | None = None,
        **kwargs,
    ):
        """Initialize the router with injected toolkits and classifier LLM.

        Args:
            open_data: `OpenDataToolkit` instance. Constructed if omitted.
            academic: `AcademicResearchToolkit` instance. Constructed if
                omitted.
            llm: The classifier client — an `AbstractClient` instance, a
                string model spec resolved via `LLMFactory.create()`, or
                `None` to use keyword heuristics only. Tools have no
                back-reference to the calling agent's LLM by design, so
                it must be injected here explicitly.
            **kwargs: Forwarded to `AbstractTool.__init__`.
        """
        super().__init__(**kwargs)
        self.open_data = open_data or OpenDataToolkit()
        self.academic = academic or AcademicResearchToolkit()
        self.llm = LLMFactory.create(llm) if isinstance(llm, str) else llm

    async def _execute(
        self,
        query: str,
        categories: list[str] | None = None,
        max_results: int = 10,
        **kwargs,
    ) -> ToolResult:
        """Classify, dispatch, and merge — always returns a successful `ToolResult`.

        Args:
            query: Natural-language research question.
            categories: Optional explicit category restriction — bypasses
                classification entirely when given.
            max_results: Maximum results per dispatched category.

        Returns:
            A `ToolResult(success=True, status="success", ...)` whose
            payload records the selected categories, how they were
            selected, per-category results, and per-category failures.
        """
        invalid = []
        if categories is not None:
            classification = "explicit"
            selected = []
            for c in categories:
                if c in VALID_CATEGORIES:
                    selected.append(c)
                else:
                    invalid.append(c)
        else:
            selected, classification = await self._classify(query)

        results: dict = {}
        failures: dict = {}

        if selected:
            dispatched = await asyncio.gather(
                *(self._dispatch_category(c, query, max_results) for c in selected),
                return_exceptions=True,
            )
            for category, outcome in zip(selected, dispatched):
                if isinstance(outcome, Exception):
                    self.logger.error(
                        "ResearchRouter: %s dispatch failed: %s", category, outcome
                    )
                    failures[category] = str(outcome)
                else:
                    results[category] = outcome

        if invalid:
            failures["invalid_categories"] = (
                f"Unknown categor{'y' if len(invalid) == 1 else 'ies'}: "
                f"{', '.join(invalid)}. Valid options: {', '.join(VALID_CATEGORIES)}"
            )

        return ToolResult(
            success=True,
            status="success",
            result={
                "query": query,
                "categories": selected,
                "classification": classification,
                "results": results,
                "failures": failures,
            },
            metadata={"max_results": max_results},
        )

    async def _dispatch_category(
        self, category: str, query: str, max_results: int
    ) -> Any:
        """Run every method of the toolkit for `category` and collect results.

        Any per-method exception propagates to the caller's
        `asyncio.gather(..., return_exceptions=True)`, which records it as
        a category-level failure without ever raising into the agent loop.
        """
        if category == "open_data":
            return {
                "search_world_bank": (
                    await self.open_data.search_world_bank(
                        query, max_results=max_results
                    )
                ).model_dump(),
                "search_eu_open_data": (
                    await self.open_data.search_eu_open_data(
                        query, max_results=max_results
                    )
                ).model_dump(),
                "search_oecd_data": (
                    await self.open_data.search_oecd_data(
                        query, max_results=max_results
                    )
                ).model_dump(),
            }
        if category == "academic":
            return {
                "search_crossref": (
                    await self.academic.search_crossref(
                        query, max_results=max_results
                    )
                ).model_dump(),
                "search_pubmed": (
                    await self.academic.search_pubmed(
                        query, max_results=max_results
                    )
                ).model_dump(),
                "search_semantic_scholar": (
                    await self.academic.search_semantic_scholar(
                        query, max_results=max_results
                    )
                ).model_dump(),
                "search_arxiv": (
                    await self.academic.search_arxiv(
                        query, max_results=max_results
                    )
                ).model_dump(),
            }
        raise ValueError(f"Unknown category: {category}")

    async def _classify(self, query: str) -> tuple[list[str], str]:
        """Classify `query` into one or both categories.

        Returns:
            A `(categories, classification)` tuple where `classification`
            is `"llm"` on success or `"heuristic"` on fallback (no `llm`
            configured, or classification failed/produced no valid
            categories).
        """
        if self.llm is not None:
            try:
                categories = await self._classify_with_llm(query)
                if categories:
                    return categories, "llm"
            except Exception as e:  # noqa: BLE001 — fall back, never raise
                self.logger.warning(
                    "ResearchRouter: LLM classification failed, "
                    "falling back to heuristics: %s", e
                )

        return self._classify_with_heuristics(query), "heuristic"

    async def _classify_with_llm(self, query: str) -> list[str]:
        """Ask the injected LLM to classify `query`; parse defensively."""
        prompt = _CLASSIFIER_PROMPT_TEMPLATE.format(query=query)
        response = await self.llm.ask(prompt)
        text = self._extract_text(response)
        return self._parse_categories(text)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract plain text from an `AIMessage`, dict, or string response."""
        output = getattr(response, "output", None)
        if output is not None:
            return str(output)
        if isinstance(response, dict) and "content" in response:
            return str(response["content"])
        return str(response)

    @staticmethod
    def _parse_categories(text: str) -> list[str]:
        """Extract a JSON array of valid category names from free-form text."""
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        return [c for c in parsed if c in VALID_CATEGORIES]

    @staticmethod
    def _classify_with_heuristics(query: str) -> list[str]:
        """Keyword-based fallback classifier — ambiguous queries get both."""
        q = query.lower()
        matches_open_data = any(kw in q for kw in _OPEN_DATA_KEYWORDS)
        matches_academic = any(kw in q for kw in _ACADEMIC_KEYWORDS)

        if matches_open_data and not matches_academic:
            return ["open_data"]
        if matches_academic and not matches_open_data:
            return ["academic"]
        # Ambiguous (both or neither matched) — search both categories.
        return list(VALID_CATEGORIES)
