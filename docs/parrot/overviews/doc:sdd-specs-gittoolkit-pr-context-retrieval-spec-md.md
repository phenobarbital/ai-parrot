---
type: Wiki Overview
title: 'Feature Specification: GitToolkit On-Demand Code Retrieval for GithubReviewer'
id: doc:sdd-specs-gittoolkit-pr-context-retrieval-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: reviews pull requests by passing the **flat unified diff** of the PR to the
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: GitToolkit On-Demand Code Retrieval for GithubReviewer

**Feature ID**: FEAT-182
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`GithubReviewer` (`packages/ai-parrot/src/parrot/bots/github_reviewer.py:239`)
reviews pull requests by passing the **flat unified diff** of the PR to the
LLM and asking it to compare against the linked Jira acceptance criteria.
The LLM has no way to:

- Inspect the **full body of a changed file** (only the diff hunk +
  context lines is visible).
- Compare a function/class against its **previous version on the base
  branch** beyond what the diff window shows.
- Discover **callers, sibling files, or related code** that would explain
  whether the change is locally consistent with the rest of the repo.

Result: reviews are shallow on non-trivial PRs. False positives erode trust
("the PR doesn't import X" when X is imported one file over), and real
bugs that require cross-file inspection slip through silently.

The fix is to extend `GitToolkit` with three on-demand code-retrieval
tools and let the reviewer's LLM **pull additional context when it needs
it**, ReAct-style, bounded by a hard cap on tool calls per review.

### Goals

- Add three new `@tool_schema` methods on `GitToolkit`:
  `get_file_content_at_ref`, `compare_pr_versions`, `search_repo_code`.
- Add a SHA-keyed shared blob cache (Redis-backed when `REDIS_URL` is set,
  in-memory LRU fallback) that fronts file-fetch calls in `GitToolkit`.
- Upgrade `GithubReviewer._ask_llm_for_review` to a bounded tool-calling
  ReAct loop so the LLM can pull additional context before producing
  `PRReviewResult`.
- Cap the loop at **5 tool calls per review** by default; configurable via
  `max_review_tool_calls` kwarg.
- Emit an audit log line every time the iteration cap is hit so the cap
  can be tuned post-deployment.
- Inherit auth from `GitToolkit` (FEAT-179) for both `pat` and `github_app`
  modes — no new auth surface.
- No breaking changes to existing `GitToolkit` methods or the public
  `GithubReviewer` API.

### Non-Goals (explicitly out of scope)

- A single polymorphic `get_repo_context(action, ...)` tool — rejected in
  brainstorm Option B (poor LLM ergonomics, contradicts existing toolkit
  style). See `sdd/proposals/gittoolkit-pr-context-retrieval.brainstorm.md`.
- A PyGithub-first wrapper layer — rejected in brainstorm Option C
  (introduces sync-API mixing inconsistent with the rest of `gittoolkit.py`).
- Cross-org / multi-repo code search — scope is restricted to the PR's
  own repo via the `repo:<owner>/<name>` qualifier.
- Cross-repo file fetching for "internal library" context — the new tools
  resolve to the PR's repository only.
- Migration to an async HTTP client (httpx/aiohttp) — the toolkit keeps
  the existing `requests` + `asyncio.to_thread` pattern.

---

## 2. Architectural Design

### Overview

Three independent `@tool_schema` async methods are added to `GitToolkit`.
Each is a thin wrapper over the existing `_request()` REST plumbing plus
an in-class `_FileBlobCache` helper. The cache is keyed by
`(repository, content_sha)` and backed by `CachePartition` from
`parrot.bots.database.cache` — Redis when `REDIS_URL` is set, in-memory
LRU otherwise.

`GithubReviewer._ask_llm_for_review` is upgraded to a tool-calling loop:
the LLM is invoked with the diff + Jira AC in the question (as today) but
now has access to the three new tools and may call them up to
`max_review_tool_calls` times (default 5) before being forced to emit
`PRReviewResult`. The system prompt gains a short "Tool Use Guide"
paragraph naming the tools and when each is appropriate.

When the iteration cap is reached, the reviewer emits a `WARNING`-level
log line with `pr_number`, `tool_call_count`, and the names of the tools
that were called.

### Component Diagram

```
GithubReviewer.review_pull_request
        │
        ├─ _fetch_diff()  ─────────────────────────────┐
        │                                              │
        └─ _ask_llm_for_review()  (tool-calling loop)  │
                  │                                    │
                  ├─ LLM emits tool call ──────────────┘
                  │     │
                  │     ▼
                  │   GitToolkit
                  │     ├─ get_file_content_at_ref ──→ _FileBlobCache ──→ GitHub Contents API
                  │     ├─ compare_pr_versions ─────→ _FileBlobCache ──→ GitHub Contents API (×2)
                  │     └─ search_repo_code  ────────────────────────→ GitHub Code Search API
                  │
                  ▼
            PRReviewResult (after ≤5 tool calls)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GitToolkit` (`parrot_tools.gittoolkit`) | extends | 3 new `@tool_schema` methods + `_FileBlobCache` private helper + 3 new Pydantic input models |
| `GitHubReviewer` (`parrot.bots.github_reviewer`) | modifies | New `max_review_tool_calls` kwarg; `_ask_llm_for_review` switches to tool-calling loop; system prompt gains Tool-Use Guide section |
| `CachePartition` (`parrot.bots.database.cache`) | depends on (no change) | Reused as the Redis-with-LRU storage backend for `_FileBlobCache` |
| `_GitHubAppTokenProvider` (`gittoolkit.py:387`) | depends on (no change) | New tools call `_resolve_token()` and inherit App-auth transparently |
| `tool_manager.register_toolkit` | depends on (no change) | New `@tool_schema` methods become LLM tools automatically when `_attach_toolkit` runs |
| `navconfig` | extends | New optional env vars (`GITHUB_REVIEWER_MAX_TOOL_CALLS`, `GITHUB_REVIEWER_BLOB_CACHE_TTL`); existing `REDIS_URL` is reused |

### Data Models

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py — additions

class GetFileContentInput(BaseModel):
    """Input payload for ``get_file_content_at_ref``."""
    path: str = Field(description="File path inside the repository.")
    ref: str = Field(description="Branch name, tag, or commit SHA.")
    repository: Optional[str] = Field(default=None)
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)


class ComparePRVersionsInput(BaseModel):
    """Input payload for ``compare_pr_versions``."""
    pr_number: int = Field(ge=1)
    path: str
    repository: Optional[str] = Field(default=None)


class SearchRepoCodeInput(BaseModel):
    """Input payload for ``search_repo_code``."""
    query: str = Field(description="Code Search query (without repo: qualifier — added automatically).")
    repository: Optional[str] = Field(default=None)
    max_results: int = Field(default=20, ge=1, le=100)


class FileContentResult(BaseModel):
    """Return payload for ``get_file_content_at_ref``."""
    exists: bool
    path: str
    ref: str
    repository: str
    content: Optional[str] = None       # decoded UTF-8 text; None if exists=False
    encoding: Optional[str] = None       # 'utf-8' or 'base64' (for binaries)
    size_bytes: Optional[int] = None
    sha: Optional[str] = None            # blob SHA (cache key component)
    commit_author: Optional[str] = None  # last-modifying commit author login
    truncated: bool = False              # True iff start_line/end_line slicing was applied
    error: Optional[str] = None          # 'file_too_large' | 'rate_limited' | None


class CompareVersionsResult(BaseModel):
    """Return payload for ``compare_pr_versions``."""
    repository: str
    pr_number: int
    path: str
    base_sha: str
    head_sha: str
    base: FileContentResult
    head: FileContentResult


class SearchCodeResult(BaseModel):
    """Return payload for ``search_repo_code``."""
    repository: str
    query: str
    total_count: int
    items: List[Dict[str, Any]]   # raw GitHub items — path, name, score, html_url
    error: Optional[str] = None   # 'rate_limited' | None
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py

class GitToolkit(AbstractToolkit):
    # ...existing methods unchanged...

    @tool_schema(GetFileContentInput)
    async def get_file_content_at_ref(
        self,
        path: str,
        ref: str,
        repository: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> FileContentResult:
        """Return the contents of a file at a given ref. Used by review agents
        to inspect the full file body when the diff hunk is insufficient."""

    @tool_schema(ComparePRVersionsInput)
    async def compare_pr_versions(
        self,
        pr_number: int,
        path: str,
        repository: Optional[str] = None,
    ) -> CompareVersionsResult:
        """Return base + head versions of a single file in a pull request,
        as full content. Use when the LLM needs to diff full function bodies."""

    @tool_schema(SearchRepoCodeInput)
    async def search_repo_code(
        self,
        query: str,
        repository: Optional[str] = None,
        max_results: int = 20,
    ) -> SearchCodeResult:
        """Search code in the PR's repository via GitHub Code Search API.
        Scope is auto-restricted to repo:<owner>/<name>; default-branch only."""


# packages/ai-parrot/src/parrot/bots/github_reviewer.py

class GitHubReviewer(Agent):
    def __init__(
        self,
        repository: str,
        *,
        # ...existing kwargs...
        max_review_tool_calls: int = 5,   # NEW — cap on tool-calling loop
        **kwargs: Any,
    ) -> None: ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Pydantic input/output models

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
  (additions near existing input-model block)
- **Responsibility**: Define `GetFileContentInput`, `ComparePRVersionsInput`,
  `SearchRepoCodeInput`, `FileContentResult`, `CompareVersionsResult`,
  `SearchCodeResult`.
- **Depends on**: existing `pydantic.BaseModel`, `Field`.

### Module 2: `_FileBlobCache` helper

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
  (private class near other private helpers, ~`_GitHubAppTokenProvider`)
- **Responsibility**: SHA-keyed cache wrapping `CachePartition` from
  `parrot.bots.database.cache`. Public surface: `async get(repo, sha) → bytes | None`
  and `async set(repo, sha, content: bytes)`. Falls back to a local
  in-memory LRU when Redis isn't available.
- **Depends on**: `CachePartition`, `CacheManager`, `CachePartitionConfig`
  from `parrot.bots.database.cache`. Reads `REDIS_URL` and an optional
  `GITHUB_REVIEWER_BLOB_CACHE_TTL` (default 604800 = 7 days) from
  `navconfig`.

### Module 3: `get_file_content_at_ref` tool

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: Async public method + sync `_get_file_content_sync`
  helper. Hits `GET /repos/{owner}/{name}/contents/{path}?ref=<ref>`,
  decodes base64 to UTF-8 (falls back to `encoding='base64'` for binaries),
  applies optional `start_line` / `end_line` slicing, returns
  `FileContentResult`. Reads via `_FileBlobCache` first; on cache miss
  also fetches `commit_author` from
  `GET /repos/{owner}/{name}/commits?path=<path>&sha=<ref>&per_page=1`.
- **Depends on**: Modules 1, 2; existing `_request()`, `_resolve_repository()`,
  `_resolve_token()`.

### Module 4: `compare_pr_versions` tool

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: Async public method + sync helper. Internally:
  1. Fetch PR metadata once to resolve `base.sha` and `head.sha`.
  2. Call `_get_file_content_sync` twice (base + head). Cache hits short-circuit.
  3. Assemble `CompareVersionsResult`.
- **Depends on**: Modules 1, 3.

### Module 5: `search_repo_code` tool

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: Async public method + sync helper. Hits
  `GET /search/code?q=<query>+repo:<owner>/<name>&per_page=<max_results>`.
  Handles `403 X-RateLimit-Remaining=0` by returning
  `SearchCodeResult(error='rate_limited', ...)` rather than raising.
- **Depends on**: Module 1; existing `_request()`, `_resolve_repository()`,
  `_resolve_token()`.

### Module 6: `GithubReviewer` tool-calling loop

- **Path**: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
- **Responsibility**:
  - New `max_review_tool_calls: int = 5` kwarg on `__init__`.
  - `_ask_llm_for_review`: invoke the agent's tool-calling path
    (`self.ask(...)` with tools enabled) and cap iterations at
    `max_review_tool_calls + 1` so the final pass after exhaustion
    always produces a structured response.
  - On cap-hit, emit `self.logger.warning("GitHubReviewer: PR %s#%s hit "
    "tool-call cap (%d)", repo, pr_number, count)` so we have a signal
    to tune the cap.
  - Extend `_SYSTEM_PROMPT` with a Tool-Use Guide section: one short
    paragraph per tool stating when to call it and when NOT to.
- **Depends on**: Modules 3, 4, 5 (transitively via `GitToolkit`).

### Module 7: Tests

- **Path**:
  - `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` (new)
  - `packages/ai-parrot/tests/bots/test_github_reviewer.py` (extended)
- **Responsibility**: Unit tests per module (cache hit/miss, file slicing,
  rate-limit path, 404 path, large-file path); integration tests covering
  the reviewer's bounded tool-call loop, the cap-hit log line, and the
  preservation of existing review behavior on PRs where the LLM doesn't
  request additional context.
- **Depends on**: Modules 1–6.

### Module 8: Configuration & docs

- **Path**:
  - `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (kwarg + docstring)
  - `docs/github-reviewer.md`
  - `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` (method docstrings)
- **Responsibility**: Document the new env vars (`GITHUB_REVIEWER_MAX_TOOL_CALLS`,
  `GITHUB_REVIEWER_BLOB_CACHE_TTL`), the new kwarg, and the tool-use
  prompt section. Update `docs/github-reviewer.md` with a "Tool-Assisted
  Review" subsection.
- **Depends on**: Modules 3–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pydantic_models_validate_inputs` | 1 | `GetFileContentInput.ref` required; `start_line>=1`; `max_results<=100`. |
| `test_blob_cache_redis_hit` | 2 | When `REDIS_URL` set and key exists, returns bytes without HTTP. |
| `test_blob_cache_lru_fallback` | 2 | When `REDIS_URL` unset, LRU mode persists across calls in same process. |
| `test_blob_cache_miss_then_hit` | 2 | First call hits HTTP, second call hits cache. |
| `test_get_file_content_full_file` | 3 | Returns full decoded UTF-8 file with `exists=True`. |
| `test_get_file_content_line_slice` | 3 | `start_line=10, end_line=20` returns 11 lines + `truncated=True`. |
| `test_get_file_content_404` | 3 | Returns `exists=False, content=None, error=None`. |
| `test_get_file_content_large_file` | 3 | Returns `error='file_too_large', size_bytes=N` instead of raising. |
| `test_get_file_content_commit_author` | 3 | `commit_author` is populated from `/commits` follow-up call on cache miss. |
| `test_compare_pr_versions_happy` | 4 | Returns `base.sha != head.sha`, both `FileContentResult.exists=True`. |
| `test_compare_pr_versions_added_file` | 4 | When file is new in head, `base.exists=False`, `head.exists=True`. |
| `test_compare_pr_versions_uses_cache` | 4 | Reviewing the same PR twice only hits GitHub once per ref. |
| `test_search_repo_code_scopes_to_repo` | 5 | Request URL contains `repo:owner/name+<query>` qualifier. |
| `test_search_repo_code_rate_limited` | 5 | `403 X-RateLimit-Remaining: 0` → returns `error='rate_limited'`, no raise. |
| `test_search_respects_max_results` | 5 | Default 20, ceiling enforced server-side via `per_page`. |
| `test_attach_toolkit_registers_new_tools` | 6 | After `_attach_toolkit(git_toolkit, ...)`, `self.tools` contains 3 new entries. |
| `test_review_no_tool_calls_unchanged_behavior` | 6 | If LLM emits `PRReviewResult` without tool calls, current review pipeline produces the same output as today. |
| `test_review_with_tool_calls_within_cap` | 6 | LLM uses 3 tool calls, reviewer completes normally; `outcome.status == "reviewed"`. |
| `test_review_cap_hit_logs_warning` | 6 | LLM tries 6 calls → loop terminates at 5, `WARNING` log line emitted with `pr_number` and `tool_call_count`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_review_with_real_diff_fixture` | End-to-end: fixture diff + fixture Jira ticket → reviewer invokes mocked tools → produces `PRReviewResult` with the expected discrepancies. |
| `test_full_review_falls_back_when_tools_disabled` | Setting `max_review_tool_calls=0` reverts to today's one-shot behavior. |

### Test Data / Fixtures

```python
# packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py

@pytest.fixture
def git_toolkit_pat(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-pat")
    return GitToolkit(
        default_repository="phenobarbital/ai-parrot",
        default_branch="dev",
        github_token="test-pat",
    )

@pytest.fixture
def mock_contents_response(responses):
    # Per-test: register GET /repos/owner/name/contents/<path> response.
    ...

@pytest.fixture
def mock_search_response(responses):
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass:
  `pytest packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py -v`
- [ ] All extended reviewer tests pass:
  `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -v`
- [ ] `GitToolkit` exposes `get_file_content_at_ref`, `compare_pr_versions`,
  `search_repo_code` as `@tool_schema` async methods that are discovered
  by `tool_manager.register_toolkit`.
- [ ] All three tools work transparently under both `GITHUB_AUTH_TYPE=pat`
  and `GITHUB_AUTH_TYPE=github_app` (FEAT-179 compatibility).
- [ ] `_FileBlobCache` uses `REDIS_URL` when set (verified by patching
  `parrot.bots.database.cache.aioredis.from_url`), and falls back to
  in-memory LRU silently when Redis is unreachable.
- [ ] `compare_pr_versions` hits GitHub at most once per (repo, sha) tuple
  per process lifetime when the cache is enabled (verified by call counter).
- [ ] `search_repo_code` always injects `repo:<owner>/<name>` and never
  exposes other repos in results.
- [ ] `GithubReviewer.max_review_tool_calls` defaults to 5 and is
  configurable both via kwarg and via env var
  `GITHUB_REVIEWER_MAX_TOOL_CALLS`.
- [ ] When the LLM emits no tool calls, `review_pull_request` produces a
  `PRReviewResult` byte-for-byte identical to today's output for the same
  fixture (no regression).
- [ ] When the iteration cap is hit, the reviewer emits a `WARNING` log
  line containing `pr_number`, `tool_call_count`, and the list of tool
  names that were called.
- [ ] `FileContentResult.commit_author` is populated on cache misses; the
  field is part of the public Pydantic schema.
- [ ] No breaking change to existing `GitToolkit` public methods or
  `GithubReviewer.__init__` signature (only an *additive* kwarg).
- [ ] `docs/github-reviewer.md` includes a "Tool-Assisted Review"
  subsection documenting the three tools, the cap, and the env vars.
- [ ] `ruff check packages/ai-parrot-tools packages/ai-parrot` passes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Confirmed working (verified at the brainstorm/spec creation time):
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError
from parrot_tools.decorators import tool_schema
from parrot_tools.toolkit import AbstractToolkit
from parrot.bots.github_reviewer import (
    GitHubReviewer,
    PRReviewResult,
    Discrepancy,
)
from parrot.bots.database.cache import (
    CachePartition,
    CacheManager,
    CachePartitionConfig,
)

# In gittoolkit.py at module top (already present):
from github import Auth, GithubIntegration        # gittoolkit.py:36
import requests                                   # gittoolkit.py:35
from pydantic import BaseModel, Field, model_validator   # gittoolkit.py:37
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkitInput(BaseModel):                       # line 47
    default_repository: Optional[str]                   # line 50
    default_branch: str                                 # line 54
    github_token: Optional[str]                         # line 57
    auth_type: Literal["pat", "github_app"]             # line 61
    app_id: Optional[int]                               # line 68
    installation_id: Optional[int]                      # line 72
    private_key: Optional[str]                          # line 79
    private_key_path: Optional[str]                     # line 86

class GitToolkit(AbstractToolkit):
    @staticmethod
    def _request(method, url, token, *,                 # line 708
                 expected, **kwargs) -> requests.Response:
        # All new tools must route through this helper.

    def _prepare_github_context(self, repository,        # line 694
                                base_branch) -> _GitHubContext: ...

    def _resolve_repository(self, repository: Optional[str]) -> str:  # line 938

    def _resolve_token(self) -> str:                                    # line 946

    def _fetch_file_sha(self, ctx, path, ref, token) -> Optional[str]:  # line 792
        # Hits GET /repos/{owner}/{name}/contents/{path}?ref=<ref>
        # — the new tools extend this URL pattern.

    @tool_schema(GetPullRequestDiffInput)
    async def get_pull_request_diff(                                    # line 1025
        self, pr_number: int,
        repository: Optional[str] = None,
        max_bytes: int = 50_000,
    ) -> Dict[str, Any]: ...
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):                                            # line 239
    def __init__(self, repository: str, *,                              # line 384
                 jira_project: str = "NAV",
                 ...,
                 max_diff_bytes: int = 50_000,
                 max_ticket_bytes: int = 20_000,
                 ...): ...
    self.git_toolkit: Optional[GitToolkit] = None                       # line 431
    self._reviewed_shas: Dict[Tuple[str, int], str] = {}                # line 437

    def _attach_toolkit(self, toolkit: Any, name: str) -> None:         # line 517
        # Calls self.tool_manager.register_toolkit(toolkit) — any
        # @tool_schema method on the toolkit is exposed to the LLM
        # automatically. No wiring change needed for the 3 new tools.

    def _build_git_toolkit(self) -> Optional[GitToolkit]:               # line 535
        # Honours GITHUB_AUTH_TYPE: "pat" | "github_app"

    async def _fetch_diff(self, repo: str,                              # line 956
                          pr_number: int) -> Tuple[str, bool, bool]:
        # Returns (diff_text, truncated, available)

    async def _ask_llm_for_review(                                      # line 989
        self, *, payload, ticket_key, ticket,
        diff_text, diff_truncated, diff_available,
    ) -> PRReviewResult:
        # Currently a one-shot self.ask(..., structured_output=PRReviewResult).
        # No tool-calling loop today — this is what Module 6 changes.
```

```python
# packages/ai-parrot/src/parrot/bots/database/cache.py

…(truncated)…
