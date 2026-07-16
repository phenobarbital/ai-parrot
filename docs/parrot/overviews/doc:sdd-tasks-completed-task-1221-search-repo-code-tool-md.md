---
type: Wiki Overview
title: 'TASK-1221: `search_repo_code` LLM tool'
id: doc:sdd-tasks-completed-task-1221-search-repo-code-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 5. Wraps GitHub Code Search API
---

# TASK-1221: `search_repo_code` LLM tool

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1217
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. Wraps GitHub Code Search API
(`GET /search/code`) with the `repo:<owner>/<name>` qualifier
auto-injected, so the reviewer's LLM can scope-safely look for
references across the repo's default branch.

---

## Scope

- Add `async def search_repo_code(...)` decorated with
  `@tool_schema(SearchRepoCodeInput)` to `GitToolkit`.
- Sync helper `_search_repo_code_sync(repository, query, max_results) ->
  SearchCodeResult`.
- Build the search URL: `GET /search/code?q=<query>+repo:<owner>/<name>&per_page=<max_results>`.
- On `403` with header `X-RateLimit-Remaining: 0`, return
  `SearchCodeResult(error='rate_limited', total_count=0, items=[])`
  rather than raising.
- On `422` (invalid query), raise `GitToolkitError` with the GitHub
  error message.
- `items` is the raw GitHub `items[]` array — no transformation beyond
  passing it through.
- Unit tests: scope qualifier injection, rate-limit handling, ceiling
  enforcement.

**NOT in scope**:
- Cross-org search — explicitly out of scope per spec §1 Non-Goals.
- Pagination beyond the first page (`per_page` ≤ 100 is the cap).

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
import requests                          # gittoolkit.py:35
from .decorators import tool_schema      # gittoolkit.py:39
```

After TASK-1217 lands:
- `SearchRepoCodeInput`, `SearchCodeResult`

### Existing Signatures to Use

```python
# gittoolkit.py — _request handles 30s timeout + standard headers.
@staticmethod
def _request(method, url, token, *, expected, **kwargs) -> requests.Response:  # line 708
    # Raises GitToolkitError on any non-`expected` status. For search we need
    # to handle 403 manually — pass expected=200 and catch the raised
    # GitToolkitError, OR pass requests through manually for this call.
    # Recommended: detect 403 before the helper raises (use a try/except).
```

```python
# GitHub Code Search API response shape (verified at the GitHub docs):
# {
#   "total_count": 42,
#   "incomplete_results": false,
#   "items": [
#     {"name": "x.py", "path": "src/x.py", "sha": "...",
#      "html_url": "...", "score": 1.2, "repository": {...}},
#     ...
#   ]
# }
```

### Does NOT Exist

- ~~`Repository.search_code()`~~ — PyGithub method not used.
- ~~`GET /search/code/repos/{owner}/{name}`~~ — there is no
  repo-scoped variant; scoping is done via the `repo:` qualifier in `q`.
- ~~`SearchCodeResult.next_page_url`~~ — not in the schema; no
  pagination support.

---

## Implementation Notes

### Pattern to Follow

```python
def _search_repo_code_sync(self, repository, query, max_results):
    repo = self._resolve_repository(repository)
    token = self._resolve_token()
    q = f"{query} repo:{repo}"
    url = "https://api.github.com/search/code"
    params = {"q": q, "per_page": min(max_results, 100)}

    # Manual call to detect rate-limit before the helper raises.
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "parrot-gittoolkit",
    }
    response = requests.get(url, headers=headers, params=params, timeout=30)
    if response.status_code == 403 and response.headers.get(
        "X-RateLimit-Remaining"
    ) == "0":
        return SearchCodeResult(
            repository=repo, query=query, total_count=0,
            items=[], error="rate_limited",
        )
    if response.status_code != 200:
        raise GitToolkitError(
            f"GitHub Code Search failed: {response.status_code} "
            f"{response.text}"
        )
    payload = response.json()
    return SearchCodeResult(
        repository=repo, query=query,
        total_count=int(payload.get("total_count", 0)),
        items=list(payload.get("items", [])),
    )
```

### Key Constraints

- Always inject `repo:<owner>/<name>` — never let the LLM call this with
  a different repo. Validate by asserting the qualifier appears in the
  outgoing URL in tests.
- `max_results` is capped server-side via `per_page`; the input model
  also caps it at 100 (TASK-1217 acceptance criterion).
- The search API has its own auth quota separate from REST — that's why
  rate-limit handling matters here even though other tools work fine.

### References in Codebase

- `gittoolkit.py:708` — `_request` (we bypass it for the 403 case but
  follow the same header pattern).
- `gittoolkit.py:729` — `_get_stats_with_polling` (similar bespoke
  request loop for a special-cased endpoint).

---

## Acceptance Criteria

- [ ] `search_repo_code` returns a `SearchCodeResult`.
- [ ] Test `test_search_repo_code_scopes_to_repo` asserts the request
  URL's `q=` includes `repo:owner/name`.
- [ ] Test `test_search_repo_code_rate_limited` asserts a 403 with
  `X-RateLimit-Remaining: 0` returns `error='rate_limited'` and does
  NOT raise.
- [ ] Test `test_search_respects_max_results` asserts the cap is
  applied.
- [ ] `ruff check` passes.

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_search_repo_code_scopes_to_repo(responses_mock, git_toolkit_pat):
    responses_mock.add(
        responses.GET,
        "https://api.github.com/search/code",
        json={"total_count": 1, "items": [{"path": "src/x.py", "name": "x.py"}]},
        status=200,
    )
    result = await git_toolkit_pat.search_repo_code(
        query="def my_function", repository="owner/repo"
    )
    assert result.total_count == 1
    # Verify scoping
    called = responses_mock.calls[0].request
    assert "repo:owner/repo" in called.url


@pytest.mark.asyncio
async def test_search_repo_code_rate_limited(responses_mock, git_toolkit_pat):
    responses_mock.add(
        responses.GET,
        "https://api.github.com/search/code",
        json={"message": "API rate limit exceeded"},
        status=403,
        headers={"X-RateLimit-Remaining": "0"},
    )
    result = await git_toolkit_pat.search_repo_code(
        query="def x", repository="owner/repo"
    )
    assert result.error == "rate_limited"
    assert result.items == []
```

---

## Agent Instructions

1. Verify TASK-1217 completed.
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
