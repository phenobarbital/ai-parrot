"""Unit tests for `ReadOnlyRepoToolkit` — `read_file` / `list_files` (FEAT-484)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from parrot.tools.repo import ReadOnlyRepoToolkit
from parrot.tools.repo.models import RepoReadResult, RepoToolError

WRITE_SHAPED = re.compile(
    r"write|edit|patch|apply|run|exec|delete|remove|create|mkdir|chmod",
    re.IGNORECASE,
)


@pytest.fixture
def toolkit(temp_repo: Path) -> ReadOnlyRepoToolkit:
    return ReadOnlyRepoToolkit(repo_root=temp_repo)


class TestReadOnlyByConstruction:
    @pytest.mark.parametrize("kwargs", [
        {},
        {"enable_web_search": True},
        {"deny_secret_files": False},
        {"enable_web_search": True, "deny_secret_files": False},
    ])
    def test_no_write_tool_under_any_config(self, temp_repo: Path, kwargs):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, **kwargs)
        names = [t.name for t in tk.get_tools()]
        assert not [n for n in names if WRITE_SHAPED.search(n)], names

    def test_expected_tool_set(self, toolkit):
        # Snapshot as of TASK-2642: TASK-2643 adds the opt-in `web_search`
        # entry to this set (only when enable_web_search=True).
        assert {t.name for t in toolkit.get_tools()} == {
            "read_file", "list_files", "grep_files",
            "git_log", "git_show", "git_blame",
            "search_code", "related_code",
        }


class TestReadFile:
    async def test_reads_file(self, toolkit):
        out = await toolkit.read_file("pkg/sub/mod.py")
        assert isinstance(out, RepoReadResult)
        assert "def alpha" in out.content

    async def test_line_range_inclusive(self, toolkit):
        out = await toolkit.read_file("pkg/sub/mod.py", start=1, end=1)
        assert out.content.strip() == "def alpha():"

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd",
                                     "escape/secret.txt"])
    async def test_rejects_outside_without_raising(self, toolkit, bad):
        out = await toolkit.read_file(bad)
        assert isinstance(out, RepoToolError)
        assert out.error == "path_outside_root"

    @pytest.mark.parametrize("secret", [".env", "config/.env", "server.pem"])
    async def test_rejects_secret(self, toolkit, secret):
        out = await toolkit.read_file(secret)
        assert isinstance(out, RepoToolError) and out.error == "secret_file"

    async def test_allows_example(self, toolkit):
        assert isinstance(await toolkit.read_file(".env.example"), RepoReadResult)

    async def test_deny_flag_off_reads_env(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, deny_secret_files=False)
        out = await tk.read_file(".env")
        assert isinstance(out, RepoReadResult) and "hunter2" in out.content

    async def test_deny_flag_off_still_confines(self, temp_repo):
        """The flag governs the deny-list ONLY — never containment."""
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, deny_secret_files=False)
        out = await tk.read_file("escape/secret.txt")
        assert isinstance(out, RepoToolError)

    async def test_not_found(self, toolkit):
        out = await toolkit.read_file("nope.py")
        assert isinstance(out, RepoToolError) and out.error == "not_found"

    async def test_truncates_at_byte_bound(self, temp_repo):
        tk = ReadOnlyRepoToolkit(repo_root=temp_repo, max_result_bytes=1000)
        out = await tk.read_file("big.txt")
        assert out.truncated is True
        assert len(out.content.encode()) < 200_000
        assert out.total_bytes == 200_000
        assert "truncated" in out.content.lower()


class TestListFiles:
    async def test_lists_and_respects_depth(self, toolkit):
        shallow = await toolkit.list_files(".", depth=1)
        assert not any("sub/mod.py" in f for f in shallow["files"])
        deep = await toolkit.list_files(".", depth=5)
        assert any("mod.py" in f for f in deep["files"])

    async def test_omits_secrets(self, toolkit):
        out = await toolkit.list_files(".", depth=5)
        assert not any(f.endswith(".env") for f in out["files"])
        assert not any(f.endswith(".pem") for f in out["files"])
        assert any(f.endswith(".env.example") for f in out["files"])

    async def test_confined(self, toolkit):
        out = await toolkit.list_files("../..")
        assert isinstance(out, RepoToolError) or out.get("error")
