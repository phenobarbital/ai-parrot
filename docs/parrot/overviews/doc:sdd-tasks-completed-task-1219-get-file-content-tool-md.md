---
type: Wiki Overview
title: 'TASK-1219: `get_file_content_at_ref` LLM tool'
id: doc:sdd-tasks-completed-task-1219-get-file-content-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 3. The first of the three new `@tool_schema`
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1219: `get_file_content_at_ref` LLM tool

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1217, TASK-1218
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. The first of the three new `@tool_schema`
methods on `GitToolkit`. Fetches a file at a given ref (branch / tag /
commit SHA), with optional line slicing, behind the `_FileBlobCache`.

Prerequisite for TASK-1220 (`compare_pr_versions` calls this method
internally).

---

## Scope

- Add `async def get_file_content_at_ref(...)` decorated with
  `@tool_schema(GetFileContentInput)` to the `GitToolkit` class in
  `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`.
- Internal sync helper `_get_file_content_sync(repository, path, ref,
  start_line, end_line) -> FileContentResult`.
- HTTP call: `GET /repos/{owner}/{name}/contents/{path}?ref=<ref>`.
- On 404: return `FileContentResult(exists=False, ...)`. Do NOT raise.
- On `"too_large"` indicator (size > 1 MB GitHub Contents API limit):
  return `FileContentResult(error='file_too_large', size_bytes=N,
  exists=True, content=None)`.
- Decode `content` from base64 → UTF-8. If `UnicodeDecodeError`, keep
  base64 and set `encoding='base64'`.
- If `start_line` and/or `end_line` provided: slice and set
  `truncated=True`. Do NOT raise on out-of-range — clamp silently.
- On cache miss (after fetching): also call
  `GET /repos/{owner}/{name}/commits?path=<path>&sha=<ref>&per_page=1`
  to populate `commit_author` (best-effort; on failure, leave None).
- Cache writes: store the **decoded content bytes** keyed by
  `(repository, blob_sha)` from the response payload.
- Unit tests covering: full file, line slice, 404, large file,
  commit_author population, cache hit on second call.

**NOT in scope**:
- `compare_pr_versions` (TASK-1220).
- `search_repo_code` (TASK-1221).
- Wiring into `GithubReviewer` (TASK-1222).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add the tool + sync helper |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` | MODIFY | Add 5+ unit tests for this tool |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in gittoolkit.py:
import asyncio                           # gittoolkit.py:23
import base64                            # gittoolkit.py:24
import requests                          # gittoolkit.py:35
from .decorators import tool_schema      # gittoolkit.py:39
```

After TASK-1217 + TASK-1218 land, these are also in the same file:
- `GetFileContentInput`, `FileContentResult` (from TASK-1217)
- `_FileBlobCache` (from TASK-1218)

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):
    @staticmethod
    def _request(method, url, token, *,                    # line 708
                 expected, **kwargs) -> requests.Response:
        # Routes the call through the standard headers.
        # Default 30s timeout. Raises GitToolkitError on non-`expected` status.

    def _resolve_repository(self, repository: Optional[str]) -> str:  # line 938

    def _resolve_token(self) -> str:                                   # line 946

    def _fetch_file_sha(self, ctx, path, ref, token) -> Optional[str]: # line 792
        # Pattern reference: hits /repos/{owner}/{name}/contents/{path}?ref=<ref>
        # Returns the blob sha or None on 404.

# Example of existing async tool wiring (mirror this pattern):
    @tool_schema(GetPullRequestDiffInput)
    async def get_pull_request_diff(                                   # line 1025
        self, pr_number: int, repository: Optional[str] = None,
        max_bytes: int = 50_000,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._get_pull_request_diff_sync, repository, pr_number, max_bytes
        )

    def _get_pull_request_diff_sync(                                   # line 995
        self, repository: Optional[str], pr_number: int, max_bytes: int
    ) -> Dict[str, Any]:
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        response = self._request("GET", url, token, expected=200,
                                 headers={"Accept": "application/vnd.github.v3.diff"})
        # ...
```

### Does NOT Exist

- ~~`requests.async_get`~~ / ~~`httpx`~~ — use sync `requests` inside the
  sync helper, wrap with `asyncio.to_thread`.
- ~~`GitToolkit.get_file_content`~~ (without `_at_ref` suffix) — the
  method name is exactly `get_file_content_at_ref`.
- ~~`PyGithub.Repository.get_contents`~~ — rejected in brainstorm
  Option C. Do not import PyGithub helpers for this method.
- ~~`FileContentResult.last_modified`~~ / ~~`commit_message`~~ — only
  `commit_author` is in scope (per spec §8 resolved questions).

---

## Implementation Notes

### Pattern to Follow

```python
# Pseudocode — implementer must verify exact API response shape.
async def get_file_content_at_ref(
    self, path, ref, repository=None, start_line=None, end_line=None
) -> FileContentResult:
    return await asyncio.to_thread(
        self._get_file_content_sync,
        repository, path, ref, start_line, end_line,
    )

def _get_file_content_sync(self, repository, path, ref, start_line, end_line):
    repo = self._resolve_repository(repository)
    token = self._resolve_token()
    # 1. Resolve blob sha (cheap call) — needed for cache key.
    # 2. Try cache.get(repo, sha) first.
    # 3. If miss: GET /contents/{path}?ref=<ref>, decode, store in cache.
    # 4. Fetch commit_author via /commits?path=...&sha=ref&per_page=1.
    # 5. Apply line slicing if requested.
    # 6. Return FileContentResult.
```

### Key Constraints

- The `_FileBlobCache` instance must be a class-level singleton on
  `GitToolkit` (or per-instance) — coordinate with TASK-1218's choice.
- Reading the file twice (once for sha, once for content) is acceptable
  but optional: the Contents API returns both `sha` and `content` in one
  call, so a single GET suffices.
- Errors from the commits endpoint should NOT fail the tool — silently
  leave `commit_author=None`.
- Use the existing `_request("GET", url, token, expected=200, ...)`
  helper; never construct requests outside this wrapper.

### References in Codebase

- `gittoolkit.py:792` — `_fetch_file_sha` for the URL pattern.
- `gittoolkit.py:995` — `_get_pull_request_diff_sync` for the async-wrap
  + `_request` usage pattern.
- `gittoolkit.py:1025` — `get_pull_request_diff` for the `@tool_schema`
  decorator + `asyncio.to_thread` wrapper pattern.

---

## Acceptance Criteria

- [ ] `get_file_content_at_ref` is callable from a `GitToolkit` instance
  and returns a `FileContentResult`.
- [ ] Unit tests pass: `test_get_file_content_full_file`,
  `test_get_file_content_line_slice`, `test_get_file_content_404`,
  `test_get_file_content_large_file`, `test_get_file_content_commit_author`.
- [ ] On a cache hit (second call with the same sha), no HTTP call is
  made (verified via request mock counter).
- [ ] No regressions in existing tests:
  `pytest packages/ai-parrot-tools/tests/test_gittoolkit_pr_methods.py -v`.
- [ ] `ruff check packages/ai-parrot-tools/` passes.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py
import pytest
import responses
from parrot_tools.gittoolkit import GitToolkit

@pytest.mark.asyncio
async def test_get_file_content_full_file(responses_mock, git_toolkit_pat):
    responses_mock.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/contents/path/to/file.py",
        json={"sha": "abc", "content": "aGVsbG8K", "encoding": "base64", "size": 6},
        status=200,
    )
    # plus the commits endpoint mock
    result = await git_toolkit_pat.get_file_content_at_ref(
        path="path/to/file.py", ref="main", repository="owner/repo"
    )
    assert result.exists is True
    assert result.content == "hello\n"
    assert result.sha == "abc"


@pytest.mark.asyncio
async def test_get_file_content_404(responses_mock, git_toolkit_pat):
    responses_mock.add(
        responses.GET,
        "https://api.github.com/repos/owner/repo/contents/missing.py",
        status=404,
    )
    result = await git_toolkit_pat.get_file_content_at_ref(
        path="missing.py", ref="main", repository="owner/repo"
    )
    assert result.exists is False
    assert result.content is None
```

---

## Agent Instructions

1. Confirm TASK-1217 and TASK-1218 are in `sdd/tasks/completed/` before
   starting.
2. Implement per the pattern referenced above.
3. Write tests; mock HTTP via `responses`.
4. Update per-spec index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**:

**Deviations from spec**: none
