"""Unit tests for `ResearchRouter` (FEAT-426 TASK-2242).

Uses stub `OpenDataToolkit`/`AcademicResearchToolkit` implementations
(real `ResearchResult` instances, no network) so the router's
classification/dispatch/merge logic is exercised in isolation.
"""
import pytest
from parrot_tools.research.models import ResearchResult
from parrot_tools.research.router import ResearchRouter


class _StubOpenData:
    async def search_world_bank(self, query, max_results=10):
        return ResearchResult(
            query=query, source="open_data.search_world_bank",
            result_type="indicators", status="success",
        )

    async def search_eu_open_data(self, query, max_results=10):
        return ResearchResult(
            query=query, source="open_data.search_eu_open_data",
            result_type="datasets", status="success",
        )

    async def search_oecd_data(self, query, max_results=10):
        return ResearchResult(
            query=query, source="open_data.search_oecd_data",
            result_type="datasets", status="success",
        )


class _StubAcademic:
    async def search_crossref(self, query, max_results=10):
        return ResearchResult(
            query=query, source="academic.search_crossref",
            result_type="papers", status="success",
        )

    async def search_pubmed(self, query, max_results=10):
        return ResearchResult(
            query=query, source="academic.search_pubmed",
            result_type="papers", status="success",
        )

    async def search_semantic_scholar(self, query, max_results=10):
        return ResearchResult(
            query=query, source="academic.search_semantic_scholar",
            result_type="papers", status="success",
        )

    async def search_arxiv(self, query, max_results=10):
        return ResearchResult(
            query=query, source="academic.search_arxiv",
            result_type="papers", status="success",
        )


class _RaisingOpenData(_StubOpenData):
    async def search_world_bank(self, query, max_results=10):
        raise RuntimeError("boom")


class _SpyLLM:
    def __init__(self):
        self.called = False

    async def ask(self, prompt):
        self.called = True
        return "[]"


class _FakeLLM:
    def __init__(self, text: str):
        self.text = text

    async def ask(self, prompt):
        return self.text


@pytest.fixture
def stub_toolkits():
    return {"open_data": _StubOpenData(), "academic": _StubAcademic()}


@pytest.fixture
def stub_toolkits_one_raising():
    return {"open_data": _RaisingOpenData(), "academic": _StubAcademic()}


@pytest.fixture
def spy_llm():
    return _SpyLLM()


@pytest.fixture
def fake_llm_returns_academic():
    return _FakeLLM('["academic"]')


@pytest.fixture
def fake_llm_garbage():
    return _FakeLLM("not json at all")


class TestResearchRouter:
    async def test_params_reach_execute(self, stub_toolkits):
        """REGRESSION — without an explicit args_schema these are dropped."""
        r = await ResearchRouter(**stub_toolkits).execute(
            query="renewables", categories=["open_data"], max_results=3
        )
        assert r.result["query"] == "renewables"
        assert r.result["categories"] == ["open_data"]
        assert r.metadata["max_results"] == 3

    async def test_heuristic_fallback_without_llm(self, stub_toolkits):
        r = await ResearchRouter(**stub_toolkits, llm=None).execute(
            query="GDP of Brazil"
        )
        assert r.success is True
        assert r.result["classification"] == "heuristic"

    async def test_explicit_categories_skip_llm(self, stub_toolkits, spy_llm):
        await ResearchRouter(**stub_toolkits, llm=spy_llm).execute(
            query="x", categories=["academic"]
        )
        assert spy_llm.called is False

    async def test_llm_classification_used(
        self, stub_toolkits, fake_llm_returns_academic
    ):
        r = await ResearchRouter(
            **stub_toolkits, llm=fake_llm_returns_academic
        ).execute(query="recent papers on CRISPR")
        assert r.result["categories"] == ["academic"]
        assert r.result["classification"] == "llm"

    async def test_malformed_llm_output_falls_back(
        self, stub_toolkits, fake_llm_garbage
    ):
        r = await ResearchRouter(**stub_toolkits, llm=fake_llm_garbage).execute(
            query="x"
        )
        assert r.success is True and r.result["classification"] == "heuristic"

    async def test_partial_failure_still_successful(self, stub_toolkits_one_raising):
        r = await ResearchRouter(**stub_toolkits_one_raising).execute(
            query="x", categories=["open_data", "academic"]
        )
        assert r.success is True and r.status == "success"
        assert r.result["failures"]

    async def test_invalid_category_reported(self, stub_toolkits):
        r = await ResearchRouter(**stub_toolkits).execute(
            query="x", categories=["bogus"]
        )
        assert "bogus" in str(r.result)

    def test_no_bot_backreference(self):
        router = ResearchRouter()
        assert not any(hasattr(router, a) for a in ("bot", "agent", "_bot"))

    async def test_dispatch_runs_concurrently(self, stub_toolkits):
        r = await ResearchRouter(**stub_toolkits).execute(
            query="x", categories=["open_data", "academic"]
        )
        assert set(r.result["results"].keys()) == {"open_data", "academic"}
