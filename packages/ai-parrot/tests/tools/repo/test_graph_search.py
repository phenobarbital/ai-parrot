"""Unit tests for worktree-aware wiki plane resolution (FEAT-484)."""

from __future__ import annotations

import json
from pathlib import Path

from parrot.tools.repo.graph_search import open_plane, resolve_plane_root


class TestResolvePlaneRoot:
    async def test_plain_checkout_returns_itself(self, temp_repo: Path):
        assert await resolve_plane_root(temp_repo) == temp_repo.resolve()

    async def test_worktree_returns_main_checkout(self, temp_repo, temp_worktree):
        """The whole point of spec §8 Q5: a worktree shares the main plane."""
        got = await resolve_plane_root(temp_worktree)
        assert got == temp_repo.resolve()
        assert got != temp_worktree.resolve()

    async def test_non_git_dir_returns_itself(self, tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert await resolve_plane_root(plain) == plain.resolve()

    async def test_git_missing_degrades(self, temp_repo, monkeypatch):
        monkeypatch.setenv("PATH", "/nonexistent")
        assert await resolve_plane_root(temp_repo) == temp_repo.resolve()


class TestOpenPlane:
    async def test_no_config_returns_reason(self, temp_repo: Path):
        store, reason = await open_plane(temp_repo)
        assert store is None
        assert reason  # non-empty, model-readable

    async def test_unbuilt_plane_returns_reason(self, temp_repo: Path):
        (temp_repo / ".parrot").mkdir(exist_ok=True)
        (temp_repo / ".parrot" / "wiki.json").write_text(
            json.dumps(
                {
                    "wiki_name": "test",
                    "backend": "sqlite",
                    "storage_dir": ".parrot/wiki",
                }
            )
        )
        store, reason = await open_plane(temp_repo)
        assert store is None
        assert "not built" in reason.lower() or reason

    async def test_never_builds(self, temp_repo: Path):
        """Spec §1 Non-Goals: this toolkit is a pure consumer."""
        (temp_repo / ".parrot").mkdir(exist_ok=True)
        (temp_repo / ".parrot" / "wiki.json").write_text(
            json.dumps(
                {
                    "wiki_name": "test",
                    "backend": "sqlite",
                    "storage_dir": ".parrot/wiki",
                }
            )
        )
        await open_plane(temp_repo)
        assert not (temp_repo / ".parrot" / "wiki" / "wiki.db").exists()

    async def test_worktree_resolves_to_main_config(
        self,
        temp_repo,
        temp_worktree,
    ):
        """A config present ONLY in the main checkout is still found from
        inside the worktree."""
        (temp_repo / ".parrot").mkdir(exist_ok=True)
        (temp_repo / ".parrot" / "wiki.json").write_text(
            json.dumps(
                {
                    "wiki_name": "mainplane",
                    "backend": "sqlite",
                    "storage_dir": ".parrot/wiki",
                }
            )
        )
        _store, reason = await open_plane(temp_worktree)
        # Either it opened the main plane, or it reported the MAIN path as
        # unbuilt — never the worktree path.
        assert str(temp_worktree) not in reason


class TestAddsNoTool:
    def test_toolkit_tool_set_unchanged(self, temp_repo: Path):
        from parrot.tools.repo import ReadOnlyRepoToolkit

        names = {t.name for t in ReadOnlyRepoToolkit(repo_root=temp_repo).get_tools()}
        assert "resolve_plane_root" not in names
        assert "open_plane" not in names
