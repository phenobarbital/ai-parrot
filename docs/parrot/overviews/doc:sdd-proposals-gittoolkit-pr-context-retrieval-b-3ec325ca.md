---
type: Wiki Overview
title: 'Brainstorm: GitToolkit On-Demand Code Retrieval for GithubReviewer'
id: doc:sdd-proposals-gittoolkit-pr-context-retrieval-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: pull requests by passing the **flat unified diff** of the PR to the LLM and
  asking
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

# Brainstorm: GitToolkit On-Demand Code Retrieval for GithubReviewer

**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`GithubReviewer` (`packages/ai-parrot/src/parrot/bots/github_reviewer.py:239`) reviews
pull requests by passing the **flat unified diff** of the PR to the LLM and asking
it to compare against the linked Jira acceptance criteria. The LLM has no way to:

- Inspect the **full body of a changed file** (only the diff hunk + context lines is visible).
- Compare a function/class against its **previous version on the base branch** beyond
  what the diff window shows.
- Discover **callers, sibling files, or related code** that would explain whether
  the change is locally consistent with the rest of the repo.

Result: reviews are shallow on non-trivial PRs. The LLM frequently flags as
"discrepancy" things that are either (a) addressed elsewhere in the repo, or
(b) consistent with patterns the LLM cannot see. False positives erode trust in
the reviewer's verdicts, and real bugs that require cross-file inspection slip
through silently.

The fix is to extend `GitToolkit` with three on-demand code-retrieval tools and
let the reviewer's LLM **pull additional context when it needs it**, ReAct-style.

## Constraints & Requirements

- Must inherit auth from `GitToolkit` (FEAT-179 already supports `pat` and
  `github_app`). No new auth surface.
- Token budget: tools accept optional `start_line` / `end_line`. Full-file
  returns are allowed; the LLM owns its own budget.
- Hard cap of **≤5 tool calls per review** to bound cost and latency on big PRs.
- Search restricted to **the PR's own repo** (`repo:<owner>/<name>` qualifier).
  No cross-org search.
- Caching: **shared cache (Redis or in-memory fallback)** keyed by content SHA
  so identical blobs across reviews don't re-hit GitHub.
- No breaking changes to existing `GitToolkit` methods or `GithubReviewer` flow.
- Async-first; mirror the `asyncio.to_thread` + sync helper pattern already
  established in `GitToolkit`.

---

## Options Explored

### Option A: Three orthogonal tools + shared SHA-keyed cache

Add three independent `@tool_schema`-decorated methods to `GitToolkit`:

- **`get_file_content_at_ref(path, ref, repository=None, start_line=None, end_line=None)`**
  — returns the decoded file contents at a given commit SHA or branch ref.
  Optional line slicing for surgical reads.
- **`compare_pr_versions(pr_number, path, repository=None)`** — returns a
  structured `{base_content, head_content, base_sha, head_sha}` payload for a
  single file in a PR, so the LLM can diff function bodies in their full form.
- **`search_repo_code(query, repository=None, max_results=20)`** — wraps
  GitHub Code Search API (`/search/code`) with the `repo:` qualifier auto-injected.

Storage layer: a thin `_FileBlobCache` helper inside `GitToolkit` that wraps
the existing `CachePartition` pattern from
`parrot/bots/database/cache.py:53` (Redis-backed when `REDIS_URL` is set,
in-memory LRU fallback). Keys are `gitblob:<repo>:<sha>`; values are the
decoded file bytes. SHA immutability makes TTL ~infinite.

`GithubReviewer` changes:
- `_attach_toolkit` already wires every `@tool_schema` method into
  `tool_manager` — no change required for tool registration.
- Add a `max_review_tool_calls: int = 5` constructor kwarg to bound the
  ReAct loop.
- Update `_ask_llm_for_review` to use the agent's tool-calling path
  instead of (or in addition to) the structured-output one-shot call,
  so the LLM can interleave context fetches before producing
  `PRReviewResult`.
- Extend the system prompt with a short menu describing when to use each
  tool (e.g. "use `get_file_content_at_ref` when the diff hunk is too
  small to judge the change").

✅ **Pros:**
- Each tool has a tight schema → the LLM picks the right one with no
  decision overhead.
- Independent unit tests; mocks are trivial (one HTTP endpoint per tool).
- Matches the user's mental model from the brainstorm request verbatim.
- SHA-keyed cache is correct by construction — no invalidation logic needed.
- No new dependencies; `requests` + existing `PyGithub` already cover both
  REST and App-auth code paths.

❌ **Cons:**
- `compare_pr_versions` triggers ≥2 GitHub API calls (one per ref) — cache
  helps after the first review of the same SHA.
- `search_repo_code` inherits GitHub Code Search's quirks: only indexes the
  default branch, 30 req/min limit, 1000 result ceiling. Acceptable here
  because scope is single-repo.
- The LLM may make 2–3 calls for what feels like one logical operation
  (file_content × 2 + maybe a search). Bounded by the hard cap.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `requests` | HTTP to GitHub REST (existing) | already imported in `gittoolkit.py:35` |
| `PyGithub>=2.1` | Already a dep for `github_app` auth | optional — Option A can stay on raw REST |
| `redis.asyncio` | Optional shared cache backend | pattern in `parrot/bots/database/cache.py:637` |
| `pydantic` | Tool input schemas | already used (existing `*Input` models in `gittoolkit.py`) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:708` — `_request()`
  static helper for all REST calls (handles bearer, accept header, timeout,
  error coercion).
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:792` —
  `_fetch_file_sha()` and `/repos/{}/contents/{}` URL pattern; the new
  `get_file_content_at_ref` extends this pattern.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:39` —
  `tool_schema` decorator that turns async methods into LLM tools.
- `packages/ai-parrot/src/parrot/bots/database/cache.py:53` —
  `CachePartition` Redis-with-LRU-fallback class; can host the blob cache.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:517` —
  `_attach_toolkit` already iterates `tool_manager.register_toolkit(...)`,
  so new methods become tools with zero wiring change.

---

### Option B: Single polymorphic `get_repo_context(action, ...)` tool

One mega-tool on `GitToolkit` whose first argument selects the action:

```
action: Literal["file", "compare_pr", "search"]
```

The Pydantic input schema uses a discriminated union to validate
action-specific kwargs (`path` + `ref` for `file`; `pr_number` + `path` for
`compare_pr`; `query` for `search`).

✅ **Pros:**
- One tool name to teach the LLM and to document.
- Easier to gate behind a single feature flag.

❌ **Cons:**
- Wide tool schemas confuse LLMs more than they help — Anthropic and OpenAI
  docs both recommend many tight tools over one polymorphic one.
- Validation errors get harder to surface (the discriminated union must be
  hand-rolled in Pydantic 2 or duplicated as nested models).
- Anti-pattern relative to existing `GitToolkit` style — every other tool
  in the file is single-purpose (`create_pull_request`, `submit_pr_review`,
  `get_pull_request_diff`, etc.).

📊 **Effort:** Medium

📦 **Libraries / Tools:** Same as Option A.

🔗 **Existing Code to Reuse:** Same as Option A.

---

### Option C: PyGithub-first high-level wrapper

Lean on `PyGithub` (already a hard dep since FEAT-179) instead of
hand-rolling REST calls. Use:

- `Repository.get_contents(path, ref=...)` → file content + metadata.
- `Repository.compare(base, head)` → produces a rich diff object that
  already pairs base/head per file.
- `Repository.get_pulls(...) → PullRequest.get_files()` for per-file diff
  metadata.
- For search, PyGithub has `Github.search_code(query)` but it's known to be
  rate-limit-fragile.

`GithubReviewer` still exposes the same three tools, but their bodies are
~3-line PyGithub calls inside `asyncio.to_thread`.

✅ **Pros:**
- Less boilerplate per tool (no manual URL building or auth header plumbing).
- `Repository.compare()` is a natural fit for `compare_pr_versions` — one
  API call returns both versions and the diff hunks together.
- PyGithub already handles paging, rate-limit-aware retries, and error
  hierarchies.

❌ **Cons:**
- PyGithub is **synchronous** and not particularly thread-safe — every
  call needs `asyncio.to_thread`, doubling the wrapper layer.
- The existing `GitToolkit` uses raw `requests` for everything except App
  auth (the `Auth` + `GithubIntegration` flow at `gittoolkit.py:36`); mixing
  styles increases inconsistency.
- PyGithub's response objects are richer than we need and harder to mock
  in tests than raw JSON dicts.
- Lock-in: a future migration to a pure-async HTTP layer (httpx) becomes
  more painful.

📊 **Effort:** Low (less code) but Medium total once test scaffolding for
PyGithub mocks is in place.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `PyGithub>=2.1` | All GitHub calls | already a dep (FEAT-179) |
| `redis.asyncio` | Optional cache backend | same as A |
| `pydantic` | Tool input schemas | unchanged |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:36` — `from github
  import Auth, GithubIntegration` import already present.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:387` —
  `_GitHubAppTokenProvider` already produces tokens compatible with the
  PyGithub `Auth.Token(...)` constructor.

---

## Recommendation

**Option A** is recommended because:

1. **Consistency with existing `GitToolkit` style.** Every current tool in
   `gittoolkit.py` is single-purpose and uses raw REST via `_request()`.
   Option A extends that pattern; Option C diverges (PyGithub mix); Option
   B contradicts it (polymorphic tool).
2. **Better LLM ergonomics.** Three tight tool schemas with names that
   already match the LLM's vocabulary (`get_file_content_at_ref`,
   `compare_pr_versions`, `search_repo_code`) beats one polymorphic tool.
   This is the established guidance from both Anthropic and OpenAI tool-use
   docs.
3. **Predictable tests.** Each tool can be unit-tested against three
   `responses`-style fixtures (one per endpoint). Option C would require
   mocking PyGithub object graphs, which is verbose and brittle.
4. **The cache layer can be added cleanly as a private helper** without
   widening the public surface. Whether the cache is Redis-backed or
   in-memory is invisible to the LLM.
5. **Minimum delta in `GithubReviewer`.** `_attach_toolkit` already
   auto-registers new `@tool_schema` methods; the only material change is
   moving `_ask_llm_for_review` to a tool-calling path with a bounded
   iteration cap.

We are trading off the convenience of one-call `Repository.compare()` in
exchange for code style consistency and easier testability — an acceptable
trade because `compare_pr_versions` will be cache-hit on retries anyway.

---

## Feature Description

### User-Facing Behavior

Operators wiring a `GitHubReviewer` subclass see no breaking change. The
review verdicts on non-trivial PRs become **more accurate**: fewer false
positives ("the PR doesn't import X" when X is imported one file over), and
better catches of cross-file inconsistencies. Review bodies posted to
GitHub may quote additional file paths the LLM consulted; this is a
positive signal of due diligence.

A new optional kwarg on `GithubReviewer.__init__`:

```
max_review_tool_calls: int = 5
```

Lets per-deployment tuning of how aggressive the LLM is allowed to be when
pulling context.

### Internal Behavior

1. `GitToolkit` exposes three new `@tool_schema` async methods:
   `get_file_content_at_ref`, `compare_pr_versions`, `search_repo_code`.
   They share `_prepare_github_context` / `_resolve_repository` /
   `_resolve_token` (already in `gittoolkit.py`) and call `_request()`.
2. Each tool first consults the private `_FileBlobCache` (Redis when
   `REDIS_URL` is set, in-memory LRU otherwise) keyed by
   `(repo, content_sha)`. Cache hits short-circuit the HTTP call.
3. When `GithubReviewer._build_git_toolkit()` builds its toolkit, the new
   methods come along for free; `_attach_toolkit` registers them with the
   agent's `tool_manager` automatically.
4. `_ask_llm_for_review` is upgraded:
   - The prompt body still contains the PR diff + Jira AC as today.
   - The LLM is now run in **tool-using mode** (ReAct loop) with a hard
     `max_iterations = max_review_tool_calls + 1` so it can request files
     up to 5 times before being forced to emit the final
     `PRReviewResult`.
   - The system prompt gets a short "Tool Use Guide" paragraph naming the
     three tools and when to call each.
5. Each tool call is logged at INFO with `pr_number`, tool name, and
   target path/query for audit.

### Edge Cases & Error Handling

- **File doesn't exist at ref** (`404`): `get_file_content_at_ref` returns
  `{"exists": False, "path": ..., "ref": ...}` instead of raising; LLM can
  reason about deletions.
- **File too large** (GitHub returns blob over the Contents API limit,
  ~1 MB): respond with a structured error
  `{"error": "file_too_large", "size_bytes": N}`. LLM is instructed to
  fall back to `start_line`/`end_line` if available, otherwise skip.
- **Search rate-limit** (`403` with `X-RateLimit-Remaining: 0`): tool
  returns `{"error": "rate_limited", "retry_after": secs}` and the LLM
  is told to proceed without further searches.
- **Cache backend down**: log a warning, degrade silently to direct API
  calls.
- **PR is closed/merged when `compare_pr_versions` runs**: still works —
  the base and head SHAs from the PR object are immutable and point at
  valid commits.
- **Hard cap hit**: agent's tool loop terminates and forces a final
  structured response; reviewer logs a warning so we can tune the cap
  if it fires often.

---

## Capabilities

### New Capabilities

- `gittoolkit-pr-context-retrieval`: three new on-demand code-retrieval
  tools (`get_file_content_at_ref`, `compare_pr_versions`,
  `search_repo_code`) on `GitToolkit`, plus a SHA-keyed blob cache.

### Modified Capabilities

- `github-app-auth-gittoolkit` (FEAT-179): no contract change, but the new
  tools must work under both `pat` and `github_app` auth modes — handled
  transparently by reusing `_resolve_token()`.
- `github-reviewer` (de facto, in `parrot/bots/github_reviewer.py`):
  `_ask_llm_for_review` switches to tool-calling mode; new
  `max_review_tool_calls` kwarg on `__init__`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | extends | adds 3 `@tool_schema` methods + private `_FileBlobCache` + new Pydantic input models |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | modifies | new `max_review_tool_calls` kwarg; `_ask_llm_for_review` uses tool-calling loop; system prompt gains a tool-use guide section |
| `packages/ai-parrot/src/parrot/bots/database/cache.py` | depends on | `CachePartition` reused as Redis-with-LRU backend (no change to that module) |
| Configuration (`navconfig`) | extends | optional `GITHUB_REVIEWER_MAX_TOOL_CALLS` env var; existing `REDIS_URL` is reused, not introduced |
| `packages/ai-parrot-tools/tests/test_gittoolkit_*.py` | extends | new test module `test_gittoolkit_pr_context.py` for the three tools and the cache |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | modifies | new tests for tool-calling loop + iteration cap |

No breaking changes. No new top-level dependencies.

---

## Code Context

### User-Provided Code
*(none — user described scope conversationally)*

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkitInput(BaseModel):  # line 47
    default_repository: Optional[str]            # line 50
    default_branch: str                          # line 54
    github_token: Optional[str]                  # line 57
    auth_type: Literal["pat", "github_app"]      # line 61
    app_id: Optional[int]                        # line 68
    installation_id: Optional[int]               # line 72
    private_key: Optional[str]                   # line 79
    private_key_path: Optional[str]              # line 86

class GitToolkit(AbstractToolkit):
    @staticmethod
    def _request(method, url, token, *, expected, **kwargs) -> requests.Response:  # line 708
        ...

    def _prepare_github_context(self, repository, base_branch) -> _GitHubContext:   # line 694
        ...

    def _resolve_repository(self, repository: Optional[str]) -> str:                 # line 938
        ...

    def _resolve_token(self) -> str:                                                  # line 946
        ...

    def _fetch_file_sha(self, ctx, path, ref, token) -> Optional[str]:                # line 792
        # NB: hits GET /repos/{owner}/{name}/contents/{path}?ref=<ref>
        ...

    @tool_schema(GetPullRequestDiffInput)
    async def get_pull_request_diff(                                                  # line 1025
        self, pr_number: int, repository: Optional[str] = None,
        max_bytes: int = 50_000
    ) -> Dict[str, Any]: ...
```

```python
# From packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):                                       # line 239
    def __init__(self, repository: str, *,                          # line 384
                 jira_project: str = "NAV",
                 ...,
                 max_diff_bytes: int = 50_000,
                 max_ticket_bytes: int = 20_000,
                 ...): ...
    self.git_toolkit: Optional[GitToolkit] = None                   # line 431

    def _attach_toolkit(self, toolkit: Any, name: str) -> None:     # line 517
        # Calls self.tool_manager.register_toolkit(toolkit) — any
        # @tool_schema method on the toolkit is exposed to the LLM
        # automatically.

    def _build_git_toolkit(self) -> Optional[GitToolkit]:           # line 535
        # Honours GITHUB_AUTH_TYPE: "pat" | "github_app"

    async def _fetch_diff(self, repo: str,                          # line 956
                          pr_number: int) -> Tuple[str, bool, bool]:
        # Returns (diff_text, truncated, available)

    async def _ask_llm_for_review(                                  # line 989
        self, *, payload, ticket_key, ticket,
        diff_text, diff_truncated, diff_available
    ) -> PRReviewResult:
        # Currently a one-shot self.ask(..., structured_output=PRReviewResult).
        # No tool-calling loop today.
```

```python
# From packages/ai-parrot/src/parrot/bots/database/cache.py
class CachePartition:                                                # line 53
    # Async Redis-backed cache with in-memory LRU fallback.
    # Configurable TTL; namespace per partition.

class CacheManager:                                                  # line 611
    def __init__(self, redis_url: Optional[str] = None, ...): ...    # line 619
    def create_partition(self,
                         config: CachePartitionConfig) -> CachePartition:  # line 649
```

#### Verified Imports

```python
# Confirmed working:
from parrot_tools.gittoolkit import GitToolkit, GitToolkitError
from parrot_tools.decorators import tool_schema
from parrot_tools.toolkit import AbstractToolkit
from parrot.bots.github_reviewer import GitHubReviewer, PRReviewResult, Discrepancy
from parrot.bots.database.cache import CachePartition, CacheManager, CachePartitionConfig

# In gittoolkit.py at module top:
from github import Auth, GithubIntegration       # line 36
import requests                                  # line 35
from pydantic import BaseModel, Field, model_validator   # line 37
```

#### Key Attributes & Constants

- `GitToolkit._request` is a `@staticmethod` (gittoolkit.py:708) → new
  methods can call it without `self`.
- `GitHubReviewer.git_toolkit: Optional[GitToolkit]` (github_reviewer.py:431)
  — already nullable; reviewer disables itself gracefully if absent.
- `GitHubReviewer._reviewed_shas: Dict[Tuple[str, int], str]`
  (github_reviewer.py:437) — existing per-PR dedup map; we will not modify it.
- `_GitHubAppTokenProvider.get_token()` (gittoolkit.py:400) returns a fresh
  short-lived token; cached via thread-safe `_refresh()` (gittoolkit.py:420).
  All new tools must call `_resolve_token()` (gittoolkit.py:946) rather than
  cache tokens themselves.

### Does NOT Exist (Anti-Hallucination)

- ~~`GitToolkit.get_file_content`~~ — does not exist yet; this brainstorm
  proposes it as `get_file_content_at_ref`.
- ~~`GitToolkit.compare_branches`~~ / ~~`GitToolkit.diff_files`~~ — no such
  helpers today.
- ~~`GitHubReviewer.tool_loop`~~ / ~~`GitHubReviewer.run_react`~~ — the
  ReAct loop is on the base `Agent` class, not the reviewer.
- ~~`parrot.cache.RedisCache`~~ — no module under `parrot.cache`; the
  blob cache must reuse `parrot.bots.database.cache.CachePartition`.
- ~~`requests_async`~~ / ~~`httpx`~~ in `gittoolkit.py`~~ — the toolkit
  uses sync `requests` wrapped in `asyncio.to_thread`; do not introduce a
  new HTTP client.

---

## Parallelism Assessment

- **Internal parallelism**: limited. The three new tools all touch
  `gittoolkit.py` and share helpers (`_request`, `_resolve_token`,
  cache). One worktree, sequential tasks make sense.
- **Cross-feature independence**: no live spec is editing
  `gittoolkit.py` or `github_reviewer.py`. FEAT-179 (`github-app-auth-gittoolkit`)
  and FEAT-180 (`github-repo-weekly-activity-report`) are both merged. The
  in-flight FEAT-181 (`agnostic-prompt-caching-abstraction`, proposal stage)
  is unrelated — it touches LLM clients, not toolkits.
- **Recommended isolation**: `per-spec`.
- **Rationale**: All tasks edit the same two files; one worktree avoids
  merge churn. The blob cache, the three tools, the prompt update, and
  the reviewer's tool-loop wiring are tightly coupled and benefit from
  sequential review.

---

## Open Questions

- [x] Should the new tools be available to *all* agents that mount
  `GitToolkit`, or guarded behind a flag for `GithubReviewer` only? —
  *Owner: Jesus*: tools live on `GitToolkit` and are therefore available
  to any consumer of the toolkit — no flag. The hard cap on tool calls
  lives in `GithubReviewer`, not in the toolkit.
- [x] How to bound LLM cost on big PRs? — *Owner: Jesus*: hard cap of
  5 tool calls per review (configurable via `max_review_tool_calls`).
- [x] Search backend? — *Owner: Jesus*: GitHub Code Search API restricted
  to the PR's own repo.
- [x] Caching layer? — *Owner: Jesus*: SHA-keyed shared cache reusing
  `CachePartition`; Redis when `REDIS_URL` is set, in-memory LRU fallback.
- [ ] Should `compare_pr_versions` support comparing a **range** of files
  in one call (batch mode) or remain strictly single-file? Batching
  reduces tool-call count toward the cap but widens the schema. —
  *Owner: spec phase*
- [ ] Do we need a metric/log line every time a review hits the
  iteration cap, so we can tune it post-deployment? — *Owner: spec phase*: yes
- [ ] Should the new tools surface `last_modified` / `commit_author` /
  `commit_message` of the file at the ref for additional review signal,
  or keep the payload minimal? — *Owner: spec phase*: extract commit_author for additional review info
