"""Unit tests for the local git history tools (FEAT-484)."""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.git_tools import InvalidRefError, parse_log, validate_ref
from parrot.tools.repo.models import RepoToolError


@pytest.fixture
def toolkit(temp_repo: pathlib.Path) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo)


class TestValidateRef:
    @pytest.mark.parametrize(
        "ref",
        [
            "HEAD",
            "HEAD~3",
            "main",
            "origin/main",
            "v1.2.3",
            "a" * 40,
            "HEAD^",
            "refs/heads/dev",
        ],
    )
    def test_accepts(self, ref):
        assert validate_ref(ref) == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            "   ",
            "--upload-pack=/bin/sh",
            "-x",
            "--output=/tmp/x",
            "HEAD; rm -rf /",
            "a b",
            "$(whoami)",
            "`id`",
        ],
    )
    def test_rejects(self, ref):
        with pytest.raises(InvalidRefError):
            validate_ref(ref)


class TestParseLog:
    def test_handles_awkward_subjects(self):
        us, rs = "\x1f", "\x1e"
        raw = us.join(["sha1", "A U Thor", "2026-01-01T00:00:00+00:00", "fix: a | b\twith tab"]) + rs
        [rec] = parse_log(raw)
        assert rec["subject"] == "fix: a | b\twith tab"


class TestGitLog:
    async def test_returns_commits(self, toolkit):
        out = await toolkit.git_log()
        assert len(out["commits"]) == 2
        assert out["commits"][0]["subject"] == "second"

    async def test_limit(self, toolkit):
        out = await toolkit.git_log(limit=1)
        assert len(out["commits"]) == 1

    async def test_path_filter(self, toolkit):
        out = await toolkit.git_log(path="pkg/sub/mod.py")
        assert len(out["commits"]) >= 1

    async def test_path_outside_root(self, toolkit):
        out = await toolkit.git_log(path="../../etc")
        assert isinstance(out, RepoToolError)
        assert out.error == "path_outside_root"


class TestGitShow:
    async def test_shows_head(self, toolkit):
        out = await toolkit.git_show("HEAD")
        assert not isinstance(out, RepoToolError)

    @pytest.mark.parametrize(
        "bad",
        [
            "--upload-pack=/bin/sh",
            "-x",
            "--output=/tmp/pwned",
            "",
        ],
    )
    async def test_rejects_argv_injection(self, toolkit, bad):
        out = await toolkit.git_show(bad)
        assert isinstance(out, RepoToolError)

    async def test_bounded(self, temp_repo):
        big = temp_repo / "huge.txt"
        big.write_text("y" * 300_000)
        # Test-fixture setup only (not the async tool under test); the
        # toolkit itself never calls subprocess.run — see TestNoMutatingGit.
        subprocess.run(["git", "add", "-A"], cwd=temp_repo, check=True)  # noqa: ASYNC221
        subprocess.run(["git", "commit", "-qm", "huge"], cwd=temp_repo, check=True)  # noqa: ASYNC221
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, max_result_bytes=2000)
        out = await tk.git_show("HEAD")
        assert len(str(out)) < 100_000


class TestGitBlame:
    async def test_blames(self, toolkit):
        out = await toolkit.git_blame("pkg/sub/mod.py")
        assert not isinstance(out, RepoToolError)

    async def test_refuses_secret(self, toolkit):
        out = await toolkit.git_blame(".env")
        assert isinstance(out, RepoToolError) and out.error == "secret_file"


class TestDegradesOutsideGit:
    @pytest.fixture
    def plain(self, tmp_path: pathlib.Path) -> pathlib.Path:
        d = tmp_path / "plain"
        d.mkdir()
        (d / "a.py").write_text("x = 1\n")
        return d

    async def test_all_three_degrade(self, plain):
        tk = ReadOnlyRepoToolkit(repo_root=plain)
        assert isinstance(await tk.git_log(), RepoToolError)
        assert isinstance(await tk.git_show("HEAD"), RepoToolError)
        assert isinstance(await tk.git_blame("a.py"), RepoToolError)


class TestNoMutatingGit:
    def test_package_has_no_mutating_subcommand(self):
        banned = re.compile(r'"(commit|checkout|push|fetch|reset|rebase|merge|apply|clean|rm|add)"')
        pkg = pathlib.Path("packages/ai-parrot/src/parrot/tools/repo")
        for f in pkg.rglob("*.py"):
            assert not banned.search(f.read_text()), f
