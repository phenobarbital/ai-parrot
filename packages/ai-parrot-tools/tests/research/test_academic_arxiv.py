"""Unit tests for `AcademicResearchToolkit.search_arxiv` (FEAT-426 TASK-2240).

Exercises `AcademicResearchToolkit` against a fake `arxiv` module patched
onto `parrot_tools.research.academic.arxiv` — real network access to
arxiv.org is never exercised in these tests (spec goal G6). This is
independent of whether the real `arxiv` package happens to be installed
(it is an existing extra: `arxiv = ["arxiv>=3.0.0"]`).

`packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` (the standalone
`ArxivTool`) is never imported or modified by this task.
"""
import types
from datetime import UTC, datetime

import pytest
from parrot_tools.research import academic as academic_module
from parrot_tools.research.academic import AcademicResearchToolkit


class _FakeAuthor:
    def __init__(self, name):
        self.name = name


class _FakeArxivResult:
    def __init__(
        self, title, authors, published, pdf_url, entry_id, categories, summary=""
    ):
        self.title = title
        self.authors = authors
        self.published = published
        self.pdf_url = pdf_url
        self.entry_id = entry_id
        self.categories = categories
        self.summary = summary


def _make_fake_arxiv_module(results=None):
    results = results if results is not None else []
    query_capture: list = []

    class _FakeSearch:
        def __init__(self, query=None, max_results=None, sort_by=None, sort_order=None):
            self.query = query
            self.max_results = max_results
            self.sort_by = sort_by
            self.sort_order = sort_order
            query_capture.append(query)

    class _FakeClient:
        def results(self, search):
            return results

    class _SortCriterion:
        Relevance = "relevance"
        LastUpdatedDate = "lastUpdatedDate"
        SubmittedDate = "submittedDate"

    class _SortOrder:
        Ascending = "ascending"
        Descending = "descending"

    fake_module = types.SimpleNamespace(
        Search=_FakeSearch, Client=_FakeClient,
        SortCriterion=_SortCriterion, SortOrder=_SortOrder,
    )
    return fake_module, query_capture


class _QueryContainmentProxy:
    """Lazily checks substring containment against the last captured query."""

    def __init__(self, captured: list):
        self._captured = captured

    def __contains__(self, item):
        if not self._captured:
            return False
        return item in self._captured[-1]


@pytest.fixture
def mock_arxiv(monkeypatch):
    fake_result = _FakeArxivResult(
        title="Attention Is All You Need Revisited",
        authors=[_FakeAuthor("Jane Doe"), _FakeAuthor("John Smith")],
        published=datetime(2023, 5, 1, tzinfo=UTC),
        pdf_url="https://arxiv.org/pdf/2301.00001",
        entry_id="http://arxiv.org/abs/2301.00001v1",
        categories=["cs.LG", "cs.AI"],
        summary="We revisit the transformer architecture.",
    )
    fake_module, _ = _make_fake_arxiv_module(results=[fake_result])
    monkeypatch.setattr(academic_module, "arxiv", fake_module)
    return fake_module


@pytest.fixture
def capture_arxiv_query(monkeypatch):
    fake_module, query_capture = _make_fake_arxiv_module(results=[])
    monkeypatch.setattr(academic_module, "arxiv", fake_module)
    return _QueryContainmentProxy(query_capture)


class TestArxiv:
    async def test_maps_papers(self, mock_arxiv):
        r = await AcademicResearchToolkit().search_arxiv("transformers")
        assert r.status == "success" and r.papers[0].source == "arxiv"
        assert r.papers[0].url and r.citation.source_name == "arXiv"

    async def test_category_filter_applied(self, capture_arxiv_query):
        await AcademicResearchToolkit().search_arxiv("x", category="cs.AI")
        assert "cat:cs.AI" in capture_arxiv_query

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(academic_module, "arxiv", None)
        r = await AcademicResearchToolkit().search_arxiv("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message

    async def test_no_results_is_no_data(self, monkeypatch):
        fake_module, _ = _make_fake_arxiv_module(results=[])
        monkeypatch.setattr(academic_module, "arxiv", fake_module)
        r = await AcademicResearchToolkit().search_arxiv("zzzz nonsense")
        assert r.status == "no_data"

    async def test_arxiv_tool_file_untouched(self):
        """Sanity check: this task must never import/edit `arxiv_tool.py`."""
        import parrot_tools.arxiv_tool as arxiv_tool_module

        assert hasattr(arxiv_tool_module, "ArxivTool")
