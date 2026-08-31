"""Unit tests for graph-backed `search_code` / `related_code` (FEAT-484)."""
from __future__ import annotations

import pathlib

import pytest
from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoSearchResult


@pytest.fixture
def graph_toolkit(temp_repo: pathlib.Path, stub_wiki_store) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)


class TestSearchCodeHappyPath:
    async def test_queries_plane_not_grep(
        self, graph_toolkit, stub_wiki_store, monkeypatch,
    ):
        """Spec §5: no grep subprocess on the happy path."""
        async def _boom(*a, **k):
            raise AssertionError("grep subprocess spawned on the happy path")
        monkeypatch.setattr(graph_toolkit, "_run_argv", _boom)

        out = await graph_toolkit.search_code("alpha")
        assert isinstance(out, RepoSearchResult)
        assert out.degraded is False
        assert stub_wiki_store.fts_calls == 1
        assert out.hits

    async def test_field_mapping(self, graph_toolkit):
        out = await graph_toolkit.search_code("alpha")
        hit = out.hits[0]
        assert hit.page_id == "file:pkg/sub/mod.py"   # from node_id
        assert hit.path == "pkg/sub/mod.py"           # from title
        assert hit.summary                             # from snippet
        assert hit.outline == []                       # not available
        assert hit.approx_tokens >= 0                  # from token_count

    async def test_respects_token_budget(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(
            repo_root=temp_repo, wiki_store=stub_wiki_store,
            search_budget_tokens=50,
        )
        out = await tk.search_code("alpha")
        assert out.total_tokens <= 50

    async def test_top_k_clamped(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(
            repo_root=temp_repo, wiki_store=stub_wiki_store, max_search_hits=2,
        )
        out = await tk.search_code("alpha", top_k=100)
        assert len(out.hits) <= 2


class TestSearchMode:
    def test_mode_in_tool_schema(self, graph_toolkit):
        """§8 Q2: the model can see and set `mode`."""
        tool = next(t for t in graph_toolkit.get_tools()
                    if t.name == "search_code")
        schema = str(getattr(tool, "args_schema", "")) + str(tool.__dict__)
        assert "mode" in schema

    async def test_mode_forwarded(self, temp_repo, stub_wiki_store, monkeypatch):
        seen = {}
        from parrot.knowledge.wiki import search as search_mod

        class _Spy(search_mod.WikiCombinedSearch):
            async def search(self, query, mode="combined", **kw):
                seen["mode"] = mode
                return []
        monkeypatch.setattr(search_mod, "WikiCombinedSearch", _Spy)
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        await tk.search_code("alpha", mode="combined")
        assert seen["mode"] == "combined"

    async def test_mode_defaults_to_constructor(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(
            repo_root=temp_repo, wiki_store=stub_wiki_store,
            default_search_mode="combined",
        )
        out = await tk.search_code("alpha")
        assert isinstance(out, RepoSearchResult)

    async def test_vector_degrades_not_empty(self, graph_toolkit):
        """No embedder ships — vector must degrade to lexical, not return []."""
        out = await graph_toolkit.search_code("alpha", mode="vector")
        assert out.degraded is True
        assert out.degraded_reason
        assert out.hits, "vector mode returned nothing instead of degrading"


class TestDegradation:
    async def test_degrades_when_plane_missing(self, temp_repo, caplog):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo)   # no store, no plane
        out = await tk.search_code("def alpha")
        assert out.degraded is True
        assert out.degraded_reason
        assert any("degrading" in r.message.lower() or "degrad" in r.message.lower()
                   for r in caplog.records)

    async def test_degrades_when_plane_raises(self, temp_repo, broken_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo,
                                 wiki_store=broken_wiki_store)
        out = await tk.search_code("def alpha")
        assert out.degraded is True
        assert "failed" in out.degraded_reason.lower() or out.degraded_reason

    async def test_direct_grep_is_not_degraded(self, graph_toolkit):
        """TASK-2639's contract must survive: grep_files alone is not degraded."""
        out = await graph_toolkit.grep_files("def alpha")
        assert out.degraded is False


class TestRelatedCode:
    async def test_returns_neighbors(self, graph_toolkit):
        out = await graph_toolkit.related_code("file:pkg/sub/mod.py")
        assert isinstance(out, RepoSearchResult)
        assert out.hits

    async def test_degrades_without_plane(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo)
        out = await tk.related_code("file:whatever")
        assert out.degraded is True


class TestNoDevFlowImport:
    def test_package_does_not_import_dev_flow(self):
        pkg = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")
        for f in pkg.rglob("*.py"):
            src = f.read_text()
            assert "dev_flow" not in src, f
            assert "dev_loop" not in src, f
