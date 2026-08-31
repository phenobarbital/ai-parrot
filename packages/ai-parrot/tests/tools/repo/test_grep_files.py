"""Unit tests for `grep_files` — bounded, gitignore-aware search (FEAT-484)."""
from __future__ import annotations

import asyncio
import pathlib

import pytest
from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoSearchResult


@pytest.fixture
def toolkit(temp_repo: pathlib.Path) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo)


class TestGrepFiles:
    async def test_finds_literal(self, toolkit):
        out = await toolkit.grep_files("def alpha")
        assert isinstance(out, RepoSearchResult)
        assert any("mod.py" in h.path for h in out.hits)

    async def test_respects_gitignore(self, toolkit):
        """build/ is gitignored — its match must not appear."""
        out = await toolkit.grep_files("def alpha")
        assert not any("build/" in h.path for h in out.hits)

    async def test_omits_secret_file_hits(self, toolkit):
        out = await toolkit.grep_files("SECRET_KEY")
        assert not any(h.path.endswith(".env") for h in out.hits)
        assert "hunter2" not in out.model_dump_json()

    async def test_no_matches_is_not_an_error(self, toolkit):
        """git grep exits 1 on no matches — that is success, not failure."""
        out = await toolkit.grep_files("zzz_definitely_absent_zzz")
        assert isinstance(out, RepoSearchResult)
        assert out.hits == []

    async def test_no_shell_injection(self, toolkit, temp_repo):
        canary = temp_repo / "pkg" / "sub" / "mod.py"
        out = await toolkit.grep_files("; rm -rf /")
        assert isinstance(out, RepoSearchResult)
        assert canary.exists(), "pattern was executed as a shell command"

    async def test_pattern_starting_with_dash_is_a_pattern(self, toolkit):
        out = await toolkit.grep_files("--upload-pack=evil")
        assert isinstance(out, RepoSearchResult)

    async def test_bounded_hits(self, temp_repo):
        for i in range(50):
            (temp_repo / f"f{i}.py").write_text("needle\n")
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, max_search_hits=5)
        out = await tk.grep_files("needle")
        assert len(out.hits) <= 5

    async def test_timeout_terminates_child(self, temp_repo, monkeypatch):
        """Force a hanging child and assert it is killed, not leaked."""
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, command_timeout=0.2)
        res = await tk._run_argv(["sleep", "30"])
        assert res["timed_out"] is True

    async def test_cancellation_terminates_child(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, command_timeout=30)
        task = asyncio.create_task(tk._run_argv(["sleep", "30"]))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # No orphan: give the loop a tick, then assert nothing is still running.
        await asyncio.sleep(0.1)

    async def test_non_git_dir_fallback(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "a.py").write_text("needle\n")
        tk = ReadOnlyRepoToolkit(repo_root=plain)
        out = await tk.grep_files("needle")
        assert isinstance(out, RepoSearchResult)
        assert any("a.py" in h.path for h in out.hits)


class TestNoShellAnywhere:
    def test_package_has_no_shell_true(self):
        pkg = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")
        for f in pkg.rglob("*.py"):
            src = f.read_text()
            assert "shell=True" not in src, f
            assert "subprocess.run" not in src, f
            assert "os.system" not in src, f
