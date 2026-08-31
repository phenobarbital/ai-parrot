"""Integration tests for `ReadOnlyRepoToolkit` (FEAT-484 spec §4)."""

from __future__ import annotations

import pathlib
import re
from pathlib import Path
from typing import Any

import pytest
from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoReadResult

PKG = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")


class _StubClient:
    """Minimal AbstractClient-shaped stub (base.py:355 + :1454)."""

    def __init__(self, transport: str):
        self.transport = transport
        self.tools: dict[str, Any] = {}

    def register(self, toolkit: ReadOnlyRepoToolkit) -> None:
        for tool in toolkit.get_tools():
            self.tools[tool.name] = tool

    async def _execute_tool(self, name: str, **kwargs: Any) -> Any:
        return await self.tools[name].execute(**kwargs)


class TestClientRegistration:
    async def test_registers_and_dispatches(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        client = _StubClient("generic")
        client.register(tk)
        assert client.tools
        out = await client._execute_tool("read_file", path="pkg/sub/mod.py")
        assert out is not None


class TestTransportAgnosticism:
    """Spec §4 guard: FEAT-482 registers this on NovaClient (Converse) AND
    BedrockMantleClient (OpenAI-compatible)."""

    async def test_same_toolkit_on_both_transports(
        self,
        temp_repo,
        stub_wiki_store,
    ):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        converse = _StubClient("converse")
        openai = _StubClient("openai")
        converse.register(tk)
        openai.register(tk)

        assert set(converse.tools) == set(openai.tools)

        a = await converse._execute_tool("read_file", path="pkg/sub/mod.py")
        b = await openai._execute_tool("read_file", path="pkg/sub/mod.py")
        # Compare the payload, not the whole ToolResult — `timestamp` is
        # generated fresh per call and would make this a flaky string diff.
        assert str(a.result) == str(b.result)

    def test_no_transport_branching_in_package(self):
        banned = re.compile(r"converse|openai|bedrock|nova|mantle", re.IGNORECASE)
        for f in PKG.rglob("*.py"):
            assert not banned.search(f.read_text()), f


class TestSearchThenRead:
    async def test_flow(self, temp_repo, stub_wiki_store):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, wiki_store=stub_wiki_store)
        found = await tk.search_code("alpha")
        assert found.hits
        path = found.hits[0].path
        read = await tk.read_file(path)
        assert isinstance(read, RepoReadResult)


class TestRealPlane:
    """Opt-in (spec §4) — skipped when the local plane is absent."""

    @pytest.mark.skipif(
        not pathlib.Path(".parrot/wiki/wiki.db").exists(),
        reason="no local wiki plane built",
    )
    async def test_real_query_excludes_build_artifacts(self):
        tk = ReadOnlyRepoToolkit(repo_root=Path.cwd())
        out = await tk.search_code("ReadOnlyRepoToolkit AbstractToolkit")
        assert out.degraded is False, out.degraded_reason
        assert not any("build/lib" in h.path for h in out.hits)


class TestWorktreeSharesPlane:
    async def test_worktree_resolves_main_plane(self, temp_repo, temp_worktree):
        from parrot.tools.repo.graph_search import resolve_plane_root

        assert await resolve_plane_root(temp_worktree) == temp_repo.resolve()
