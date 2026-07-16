---
type: Wiki Overview
title: 'TASK-1220: `compare_pr_versions` LLM tool'
id: doc:sdd-tasks-completed-task-1220-compare-pr-versions-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 4. Returns full base + head versions of a
---

# TASK-1220: `compare_pr_versions` LLM tool

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1217, TASK-1219
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. Returns full base + head versions of a
single file in a pull request, so the LLM can diff function bodies in
their entirety (not just the hunks the diff exposes).

Internally delegates to `get_file_content_at_ref` twice (once per ref),
so cache hits are automatic.

---

## Scope

- Add `async def compare_pr_versions(...)` decorated with
  `@tool_schema(ComparePRVersionsInput)` to `GitToolkit`.
- Sync helper `_compare_pr_versions_sync(repository, pr_number, path) ->
  CompareVersionsResult`.
- Flow:
  1. Fetch PR metadata: `GET /repos/{owner}/{name}/pulls/{pr_number}` →
     extract `base.sha` and `head.sha`.
  2. Call `_get_file_content_sync` twice (base + head) — cache short-circuits
     repeats.
  3. Assemble `CompareVersionsResult` with both `FileContentResult`s.
- Handle edge case: file added in head (base 404) → `base.exists=False`.
  Handle edge case: file deleted in head (head 404) → `head.exists=False`.
- Unit tests covering: happy path, added-file path, cache reuse on second
  call for same PR.

**NOT in scope**:
- Batch mode (multi-file in one call) — explicitly deferred per spec §8
  open question.
- `search_repo_code` (TASK-1221).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add tool + sync helper |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` | MODIFY | Add unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in gittoolkit.py:
import asyncio                           # gittoolkit.py:23
from .decorators import tool_schema      # gittoolkit.py:39
```

After TASK-1217 + TASK-1219 land:
- `ComparePRVersionsInput`, `CompareVersionsResult`, `FileContentResult`
- `GitToolkit.get_file_content_at_ref` / `_get_file_content_sync`

### Existing Signatures to Use

```python
# Pattern to mirror — existing sync helper that fetches PR metadata:
def _get_pull_request_sync(self,                                  # line 949
                           repository: Optional[str],
                           pr_number: int) -> Dict[str, Any]:
    repo = self._resolve_repository(repository)
    token = self._resolve_token()
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    response = self._request("GET", url, token, expected=200)
    return response.json()

# Public tool wiring pattern:
@tool_schema(GetPullRequestInput)
async def get_pull_request(self, pr_number: int,                  # line 957
                           repository: Optional[str] = None
                           ) -> Dict[str, Any]:
    return await asyncio.to_thread(
        self._get_pull_request_sync, repository, pr_number
    )
```

### Does NOT Exist

- ~~`PyGithub.PullRequest.get_files()`~~ — not used here (Option C
  rejected).
- ~~A "diff" field in the GitHub PR object that contains base/head
  content~~ — the PR object has `base.sha` and `head.sha` only.
- ~~`compare_pr_versions(..., paths=[...])`~~ — single-path only per
  spec scope. Batch is deferred.

---

## Implementation Notes

### Pattern to Follow

```python
def _compare_pr_versions_sync(self, repository, pr_number, path):
    pr = self._get_pull_request_sync(repository, pr_number)
    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    base = self._get_file_content_sync(repository, path, base_sha, None, None)
    head = self._get_file_content_sync(repository, path, head_sha, None, None)
    return CompareVersionsResult(
        repository=self._resolve_repository(repository),
        pr_number=pr_number,
        path=path,
        base_sha=base_sha,
        head_sha=head_sha,
        base=base,
        head=head,
    )
```

### Key Constraints

- Both file fetches must go through `_get_file_content_sync`, NOT a
  parallel custom implementation — this ensures cache reuse.
- The PR-metadata call is NOT cached (PR objects change as PRs accrue
  commits); only blob content is cached.
- 404 from a file fetch must NOT propagate — the existing tool already
  returns `FileContentResult(exists=False)`.

### References in Codebase

- `gittoolkit.py:949` — `_get_pull_request_sync` (reuse this for the
  PR metadata fetch).
- `gittoolkit.py:957` — `get_pull_request` (async wrapper pattern).

---

## Acceptance Criteria

- [ ] `compare_pr_versions` is callable and returns `CompareVersionsResult`.
- [ ] Unit tests pass: `test_compare_pr_versions_happy`,
  `test_compare_pr_versions_added_file`,
  `test_compare_pr_versions_uses_cache`.
- [ ] When the cache contains both refs, only the PR-metadata call hits
  GitHub on the second invocation.
- [ ] `ruff check packages/ai-parrot-tools/` passes.

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_compare_pr_versions_happy(responses_mock, git_toolkit_pat):
    # 1. PR metadata
    responses_mock.add(responses.GET,
        "https://api.github.com/repos/owner/repo/pulls/42",
        json={"base": {"sha": "base-sha"}, "head": {"sha": "head-sha"}},
        status=200)
    # 2. base file
    responses_mock.add(responses.GET,
        "https://api.github.com/repos/owner/repo/contents/x.py",
        json={"sha": "blob-base", "content": "Zm9vCg==", "encoding": "base64"},
        status=200,
        match=[responses.matchers.query_param_matcher({"ref": "base-sha"})])
    # 3. head file
    responses_mock.add(responses.GET,
        "https://api.github.com/repos/owner/repo/contents/x.py",
        json={"sha": "blob-head", "content": "YmFyCg==", "encoding": "base64"},
        status=200,
        match=[responses.matchers.query_param_matcher({"ref": "head-sha"})])
    result = await git_toolkit_pat.compare_pr_versions(
        pr_number=42, path="x.py", repository="owner/repo"
    )
    assert result.base.content == "foo\n"
    assert result.head.content == "bar\n"
    assert result.base_sha == "base-sha"
```

---

## Agent Instructions

1. Verify TASK-1217 + TASK-1219 completed.
2. Implement per pattern.
3. Tests + ruff.
4. Update index status.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**:

**Deviations from spec**: none
