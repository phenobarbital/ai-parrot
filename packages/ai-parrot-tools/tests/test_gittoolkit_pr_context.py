"""Tests for FEAT-182 — GitToolkit On-Demand Code Retrieval.

Covers Pydantic models (TASK-1217), _FileBlobCache (TASK-1218),
get_file_content_at_ref (TASK-1219), compare_pr_versions (TASK-1220),
and search_repo_code (TASK-1221).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from pydantic import ValidationError

from parrot_tools.gittoolkit import (
    ComparePRVersionsInput,
    FileContentResult,
    GetFileContentInput,
    GitToolkit,
    SearchRepoCodeInput,
    _FileBlobCache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_toolkit_pat(monkeypatch):
    """A GitToolkit instance using a fake PAT — no real network calls."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-pat")
    return GitToolkit(
        default_repository="owner/repo",
        default_branch="main",
        github_token="test-pat",
    )


def _make_response(status_code: int = 200, json_data=None, text: str = "", headers=None):
    """Build a fake requests.Response."""

    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.headers = headers or {}

        def json(self):
            return self._json

    return _Resp()


# ---------------------------------------------------------------------------
# TASK-1217 — Pydantic model validation
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_get_file_content_requires_path_and_ref(self):
        with pytest.raises(ValidationError):
            GetFileContentInput()  # path and ref are required

    def test_get_file_content_path_required(self):
        with pytest.raises(ValidationError):
            GetFileContentInput(ref="main")

    def test_get_file_content_ref_required(self):
        with pytest.raises(ValidationError):
            GetFileContentInput(path="a.py")

    def test_get_file_content_line_bounds_start(self):
        with pytest.raises(ValidationError):
            GetFileContentInput(path="a.py", ref="main", start_line=0)

    def test_get_file_content_line_bounds_end(self):
        with pytest.raises(ValidationError):
            GetFileContentInput(path="a.py", ref="main", end_line=0)

    def test_get_file_content_valid_with_lines(self):
        m = GetFileContentInput(path="a.py", ref="main", start_line=10, end_line=20)
        assert m.start_line == 10
        assert m.end_line == 20

    def test_compare_pr_versions_requires_pr_number(self):
        with pytest.raises(ValidationError):
            ComparePRVersionsInput(path="x.py")

    def test_compare_pr_versions_pr_number_ge_1(self):
        with pytest.raises(ValidationError):
            ComparePRVersionsInput(pr_number=0, path="x.py")

    def test_search_max_results_ceiling(self):
        with pytest.raises(ValidationError):
            SearchRepoCodeInput(query="x", max_results=200)

    def test_search_max_results_floor(self):
        with pytest.raises(ValidationError):
            SearchRepoCodeInput(query="x", max_results=0)

    def test_search_default_max_results(self):
        m = SearchRepoCodeInput(query="x")
        assert m.max_results == 20

    def test_file_content_result_defaults(self):
        r = FileContentResult(
            exists=True,
            path="a.py",
            ref="main",
            repository="owner/repo",
        )
        assert r.truncated is False
        assert r.error is None
        assert r.content is None


# ---------------------------------------------------------------------------
# TASK-1218 — _FileBlobCache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blob_cache_miss_returns_none(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    cache = _FileBlobCache()
    result = await cache.get("owner/repo", "deadbeef")
    assert result is None


@pytest.mark.asyncio
async def test_blob_cache_miss_then_hit(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    cache = _FileBlobCache()
    assert await cache.get("owner/repo", "deadbeef") is None
    await cache.set("owner/repo", "deadbeef", b"hello world")
    assert await cache.get("owner/repo", "deadbeef") == b"hello world"


@pytest.mark.asyncio
async def test_blob_cache_lru_fallback(monkeypatch):
    """LRU is per-instance; a new instance starts empty."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    cache = _FileBlobCache()
    await cache.set("o/r", "s1", b"x")
    # Same process, different instance: no shared state without Redis.
    cache2 = _FileBlobCache()
    assert await cache2.get("o/r", "s1") is None


@pytest.mark.asyncio
async def test_blob_cache_case_insensitive_key(monkeypatch):
    """Cache key normalises repository to lowercase."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    cache = _FileBlobCache()
    await cache.set("Owner/Repo", "sha1", b"data")
    assert await cache.get("owner/repo", "sha1") == b"data"


# ---------------------------------------------------------------------------
# TASK-1219 — get_file_content_at_ref
# ---------------------------------------------------------------------------


class TestGetFileContentAtRef:
    def _make_contents_response(self, content_b64: str, sha: str = "abc123", size: int = 6):
        return _make_response(
            200,
            json_data={
                "sha": sha,
                "content": content_b64,
                "encoding": "base64",
                "size": size,
                "name": "file.py",
                "path": "path/to/file.py",
            },
        )

    def _make_commits_response(self, login: str = "alice"):
        return _make_response(
            200,
            json_data=[{"commit": {}, "author": {"login": login}}],
        )

    def test_get_file_content_full_file(self, git_toolkit_pat):
        import base64
        content = base64.b64encode(b"hello\n").decode("ascii")

        responses = [
            self._make_contents_response(content, sha="sha1"),
            self._make_commits_response("alice"),
        ]
        call_index = [0]

        def _fake_request(method, url, *args, **kwargs):
            resp = responses[call_index[0]]
            call_index[0] += 1
            return resp

        with patch("parrot_tools.gittoolkit.requests.request", side_effect=_fake_request):
            result = asyncio.run(
                git_toolkit_pat.get_file_content_at_ref(
                    path="path/to/file.py", ref="main", repository="owner/repo"
                )
            )

        assert result.exists is True
        assert result.content == "hello\n"
        assert result.sha == "sha1"
        assert result.commit_author == "alice"
        assert result.truncated is False
        assert result.error is None

    def test_get_file_content_line_slice(self, git_toolkit_pat):
        import base64
        lines = "\n".join(f"line{i}" for i in range(1, 31)) + "\n"
        content = base64.b64encode(lines.encode()).decode("ascii")

        responses = [
            self._make_contents_response(content, sha="sha2"),
            self._make_commits_response(),
        ]
        call_index = [0]

        def _fake_request(method, url, *args, **kwargs):
            resp = responses[call_index[0]]
            call_index[0] += 1
            return resp

        with patch("parrot_tools.gittoolkit.requests.request", side_effect=_fake_request):
            result = asyncio.run(
                git_toolkit_pat.get_file_content_at_ref(
                    path="file.py",
                    ref="main",
                    repository="owner/repo",
                    start_line=10,
                    end_line=20,
                )
            )

        assert result.exists is True
        assert result.truncated is True
        # Lines 10-20 inclusive = 11 lines
        assert result.content is not None
        assert len(result.content.splitlines()) == 11

    def test_get_file_content_404(self, git_toolkit_pat):
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(404, json_data={"message": "Not Found"}),
        ):
            result = asyncio.run(
                git_toolkit_pat.get_file_content_at_ref(
                    path="missing.py", ref="main", repository="owner/repo"
                )
            )

        assert result.exists is False
        assert result.content is None
        assert result.error is None

    def test_get_file_content_large_file(self, git_toolkit_pat):
        """When file is too large, return error='file_too_large'."""
        big_size = 2 * 1024 * 1024  # 2 MB
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(
                200,
                json_data={
                    "sha": "bigsha",
                    "size": big_size,
                    "message": "This API returns blobs up to 1 MB in size.",
                    # No 'content' key — GitHub omits it for large files
                },
            ),
        ):
            result = asyncio.run(
                git_toolkit_pat.get_file_content_at_ref(
                    path="big.bin", ref="main", repository="owner/repo"
                )
            )

        assert result.exists is True
        assert result.error == "file_too_large"
        assert result.content is None
        assert result.size_bytes == big_size

    def test_get_file_content_cache_populated_by_first_call(self, git_toolkit_pat, monkeypatch):
        """After the first HTTP call, the blob is stored in the in-process cache."""
        import base64
        monkeypatch.delenv("REDIS_URL", raising=False)
        content = base64.b64encode(b"cached\n").decode("ascii")

        responses = [
            _make_response(
                200,
                json_data={"sha": "cachehit", "content": content, "encoding": "base64", "size": 7},
            ),
            _make_response(200, json_data=[{"author": {"login": "bob"}}]),
        ]
        call_index = [0]

        def _fake_request(method, url, *args, **kwargs):
            resp = responses[min(call_index[0], len(responses) - 1)]
            call_index[0] += 1
            return resp

        with patch("parrot_tools.gittoolkit.requests.request", side_effect=_fake_request):
            r1 = asyncio.run(
                git_toolkit_pat.get_file_content_at_ref(
                    path="a.py", ref="main", repository="owner/repo"
                )
            )

        assert r1.content == "cached\n"
        assert r1.sha == "cachehit"
        assert r1.commit_author == "bob"

        # Verify that the blob is now in the in-process cache
        cached = asyncio.run(git_toolkit_pat._blob_cache.get("owner/repo", "cachehit"))
        assert cached == b"cached\n"


# ---------------------------------------------------------------------------
# TASK-1220 — compare_pr_versions
# ---------------------------------------------------------------------------


class TestComparePRVersions:
    def _setup_mocks(self, pr_json, base_json, head_json):
        responses = [
            _make_response(200, json_data=pr_json),
            _make_response(200, json_data=base_json),
            _make_response(200, json_data=[{"author": {"login": "user"}}]),
            _make_response(200, json_data=head_json),
            _make_response(200, json_data=[{"author": {"login": "user"}}]),
        ]
        call_index = [0]

        def _fake(method, url, *args, **kwargs):
            resp = responses[call_index[0]]
            call_index[0] = min(call_index[0] + 1, len(responses) - 1)
            return resp

        return _fake

    def test_compare_pr_versions_happy(self, git_toolkit_pat, monkeypatch):
        import base64
        monkeypatch.delenv("REDIS_URL", raising=False)

        pr_json = {"base": {"sha": "base-sha"}, "head": {"sha": "head-sha"}}
        base_json = {
            "sha": "blob-base",
            "content": base64.b64encode(b"foo\n").decode(),
            "encoding": "base64",
            "size": 4,
        }
        head_json = {
            "sha": "blob-head",
            "content": base64.b64encode(b"bar\n").decode(),
            "encoding": "base64",
            "size": 4,
        }

        with patch(
            "parrot_tools.gittoolkit.requests.request",
            side_effect=self._setup_mocks(pr_json, base_json, head_json),
        ):
            result = asyncio.run(
                git_toolkit_pat.compare_pr_versions(
                    pr_number=42, path="x.py", repository="owner/repo"
                )
            )

        assert result.base.content == "foo\n"
        assert result.head.content == "bar\n"
        assert result.base_sha == "base-sha"
        assert result.head_sha == "head-sha"
        assert result.pr_number == 42

    def test_compare_pr_versions_added_file(self, git_toolkit_pat, monkeypatch):
        """When file is new in head, base.exists=False."""
        import base64
        monkeypatch.delenv("REDIS_URL", raising=False)

        pr_json = {"base": {"sha": "base-sha"}, "head": {"sha": "head-sha"}}

        responses = [
            _make_response(200, json_data=pr_json),
            _make_response(404, json_data={"message": "Not Found"}),  # base: file not found
            _make_response(
                200,
                json_data={
                    "sha": "blob-head",
                    "content": base64.b64encode(b"new\n").decode(),
                    "encoding": "base64",
                    "size": 4,
                },
            ),
            _make_response(200, json_data=[{"author": {"login": "user"}}]),
        ]
        call_index = [0]

        def _fake(method, url, *args, **kwargs):
            resp = responses[call_index[0]]
            call_index[0] = min(call_index[0] + 1, len(responses) - 1)
            return resp

        with patch("parrot_tools.gittoolkit.requests.request", side_effect=_fake):
            result = asyncio.run(
                git_toolkit_pat.compare_pr_versions(
                    pr_number=1, path="new_file.py", repository="owner/repo"
                )
            )

        assert result.base.exists is False
        assert result.head.exists is True
        assert result.head.content == "new\n"


# ---------------------------------------------------------------------------
# TASK-1221 — search_repo_code
# ---------------------------------------------------------------------------


class TestSearchRepoCode:
    def test_search_scopes_to_repo(self, git_toolkit_pat):
        called_with = {}

        def _fake_get(url, headers=None, params=None, timeout=30):
            called_with["url"] = url
            called_with["params"] = params
            return _make_response(
                200,
                json_data={"total_count": 1, "items": [{"path": "src/x.py", "name": "x.py"}]},
            )

        with patch("parrot_tools.gittoolkit.requests.get", side_effect=_fake_get):
            result = asyncio.run(
                git_toolkit_pat.search_repo_code(query="def my_function", repository="owner/repo")
            )

        assert result.total_count == 1
        q_param = called_with["params"]["q"]
        assert "repo:owner/repo" in q_param
        assert "def my_function" in q_param

    def test_search_rate_limited(self, git_toolkit_pat):
        def _fake_get(url, headers=None, params=None, timeout=30):
            return _make_response(
                403,
                json_data={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0"},
            )

        with patch("parrot_tools.gittoolkit.requests.get", side_effect=_fake_get):
            result = asyncio.run(
                git_toolkit_pat.search_repo_code(query="def x", repository="owner/repo")
            )

        assert result.error == "rate_limited"
        assert result.items == []
        assert result.total_count == 0

    def test_search_respects_max_results(self, git_toolkit_pat):
        called_with = {}

        def _fake_get(url, headers=None, params=None, timeout=30):
            called_with["params"] = params
            return _make_response(
                200,
                json_data={"total_count": 0, "items": []},
            )

        with patch("parrot_tools.gittoolkit.requests.get", side_effect=_fake_get):
            asyncio.run(
                git_toolkit_pat.search_repo_code(
                    query="def x", repository="owner/repo", max_results=50
                )
            )

        assert called_with["params"]["per_page"] == 50

    def test_search_default_max_results(self, git_toolkit_pat):
        called_with = {}

        def _fake_get(url, headers=None, params=None, timeout=30):
            called_with["params"] = params
            return _make_response(200, json_data={"total_count": 0, "items": []})

        with patch("parrot_tools.gittoolkit.requests.get", side_effect=_fake_get):
            asyncio.run(
                git_toolkit_pat.search_repo_code(query="foo", repository="owner/repo")
            )

        assert called_with["params"]["per_page"] == 20
