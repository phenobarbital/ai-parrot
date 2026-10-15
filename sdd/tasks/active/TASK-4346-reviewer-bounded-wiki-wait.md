# TASK-4346: Bound the reviewer's wiki wait and hold a read lease for the whole review

**Feature**: FEAT-672 — GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4345, TASK-4341 (done), TASK-4342 (done)
**Assigned-to**: unassigned
**discovered_from**: issue:93f2022d934a

---

## Context

Ledger issue `issue:93f2022d934a`. In `GitHubReviewer.review_pull_request`,
`await self._refresh_wiki_context(repo)` (github_reviewer.py:985) runs **before**
the Jira fetch and blocks the delivery for up to `lock_timeout` (600 s) plus the
build timeout (900 s). After it returns, the review reads the plane
(`_build_wiki_context` plus the LLM's wiki tool calls inside `self.ask`) with no
lock held, so a concurrent refresh or eviction can change the plane mid-review.

This task:
1. starts the refresh as a single in-flight background task that is reused
   across deliveries (and is the warm-up task), overlapped with the Jira and diff
   fetches, and awaited for at most `GITHUB_REVIEW_WIKI_WAIT` seconds. A refresh
   that is still running is **not** cancelled: it finishes for the next delivery.
2. holds `RepoWikiCache.read_lease` (TASK-4345) around `_ask_llm_for_review`,
   and builds no wiki context block when the lease is not obtained.

---

## Scope

- `conf.py`: add `GITHUB_REVIEW_WIKI_WAIT: int` (default `120`) after `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS`.
- `GitHubReviewer.__init__`: add `self._wiki_refresh_task: Optional[asyncio.Task[Optional[Path]]] = None`.
- Add `_start_wiki_refresh(repository) -> Optional[asyncio.Task]`: return `None` when
  the cache is off or `repository` is not this reviewer's (same guard as
  `_refresh_wiki_context`). Otherwise reuse a not-done in-flight task, or create a
  task named `github-reviewer-wiki-refresh:<repo_lc>` running
  `_refresh_wiki_context(self.repository)`, with the same failure-logging done
  callback that `_schedule_wiki_warmup` uses.
- `_schedule_wiki_warmup`: also store its task as `self._wiki_refresh_task`, so the
  first delivery reuses the warm-up instead of starting a second refresh.
- Add `_await_wiki_refresh(task) -> bool`: `asyncio.wait({task}, timeout=conf.GITHUB_REVIEW_WIKI_WAIT)`.
  Log one info line and return `False` when it is not done. Never cancel it.
- Add `_wiki_review_lease()` (async context manager yielding `bool`): `False` when the
  cache is off or `self._wiki_context_available` is false. Otherwise
  `async with self._wiki_cache.read_lease(self.repository, timeout=0.0) as paths: yield paths is not None`.
- `review_pull_request`: replace the blocking refresh (line 985) with
  `wiki_refresh = self._start_wiki_refresh(repo)`. After `_fetch_diff`, call
  `await self._await_wiki_refresh(wiki_refresh)`. Wrap the `_ask_llm_for_review`
  call in `async with self._wiki_review_lease() as wiki_leased:` and pass
  `use_wiki=wiki_leased`.
- `_ask_llm_for_review(..., use_wiki: bool = True)` forwards to
  `_build_wiki_context(payload, diff_text, enabled=use_wiki)`. `_build_wiki_context`
  gets `*, enabled: bool = True` and returns `None` when not enabled.
- `_shutdown_wiki_warmup`: also cancel and await `self._wiki_refresh_task` (once if it is the same task).
- Tests: add the new methods to the `_MinimalReviewer` stub (bind them like the
  existing `_refresh_wiki_context` binding at test line 81, and add
  `self._wiki_refresh_task = None` to its `__init__`).
- `docs/github-reviewer.md`: add a `GITHUB_REVIEW_WIKI_WAIT` row to the settings
  table. Extend the **Degradation** paragraph: the bounded wait, the read lease,
  and token-free private clones (TASK-4343).

**NOT in scope**: detaching wiki *tools* from the LLM when the lease is not held
(documented limitation: the prompt block is suppressed, but tools stay
registered); changes to `RepoWikiCache` (TASK-4345).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `GITHUB_REVIEW_WIKI_WAIT` |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Shared refresh task, bounded wait, read lease around the review |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Stub bindings + bounded-wait / reuse / lease / shutdown tests |
| `docs/github-reviewer.md` | MODIFY | Setting row + degradation notes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# github_reviewer.py already has: asyncio, Path, datetime, Optional, Any, Dict, conf
from parrot.knowledge.wiki.repo_cache import RepoWikiCache  # verified: github_reviewer.py:64
from contextlib import asynccontextmanager  # VERIFY whether github_reviewer.py already imports it; add if missing
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
#   self._wiki_built_at: Optional[datetime] = None        # line 506 (unique anchor for the new attribute)
async def _schedule_wiki_warmup(self) -> None:           # line 596 — creates named task + log_failure callback
async def _shutdown_wiki_warmup(self) -> None:           # line 617
async def _refresh_wiki_context(self, repository: str) -> Optional[Path]:  # line 632
        await self._refresh_wiki_context(repo)           # line 985 (occurrences: 1) — replaced
        diff_text, diff_truncated, diff_available = await self._fetch_diff(repo, pr_number)  # line 995
        result = await self._ask_llm_for_review(         # line 997 (occurrences: 1) — wrapped
async def _build_wiki_context(self, payload: Dict[str, Any], diff_text: str) -> Optional[str]:  # line 1177
async def _ask_llm_for_review(self, *, payload, ticket_key, ticket, diff_text,
                              diff_truncated: bool, diff_available: bool) -> PRReviewResult:  # line 1245
        wiki_context = await self._build_wiki_context(payload, diff_text)  # line 1272
```

```python
# RepoWikiCache.read_lease(repository, *, timeout=0.0) -> async CM yielding Optional[RepoCachePaths]
#   — ADDED by TASK-4345 (dependency)
```

```python
# packages/ai-parrot/src/parrot/conf.py
GITHUB_REVIEW_WIKI_CONTEXT_TOKENS: int = config.getint("GITHUB_REVIEW_WIKI_CONTEXT_TOKENS", fallback=4000)  # line 797
```

```python
# packages/ai-parrot/tests/bots/test_github_reviewer.py
class _MinimalReviewer:  # explicit method bindings (lines ~70-83) and __init__ wiki attrs (lines ~56-64)
```

### Does NOT Exist
- ~~`GitHubReviewer._wiki_refresh_task`~~, ~~`_start_wiki_refresh`~~, ~~`_await_wiki_refresh`~~, ~~`_wiki_review_lease`~~ — created here
- ~~`conf.GITHUB_REVIEW_WIKI_WAIT`~~ — created here
- ~~`conf.GITHUB_REVIEW_LOCK_TIMEOUT`~~ — does not exist; do not add it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/github_reviewer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_github_reviewer.py", "action": "MODIFY"},
    {"path": "docs/github-reviewer.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._schedule_wiki_warmup",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._shutdown_wiki_warmup",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._refresh_wiki_context",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.review_pull_request",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._build_wiki_context",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._ask_llm_for_review"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the setting, because the wait must be operator-tunable.
2. Add `_wiki_refresh_task` and `_start_wiki_refresh`, and make the warm-up share it, because concurrent deliveries must never start parallel refreshes.
3. Add `_await_wiki_refresh`, because the bounded wait is the delivery-latency fix. Never cancel the task, because cancelling a long build every delivery would mean it never completes.
4. Add `_wiki_review_lease` and the `use_wiki`/`enabled` flags, because the plane must not change while the LLM reads it.
5. Rewire `review_pull_request`: start the refresh before the ticket fetch and await it after the diff fetch, so the fetches overlap the refresh.
6. Extend shutdown, tests and docs.

### `conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'GITHUB_REVIEW_WIKI_CONTEXT_TOKENS: int' conf.py → line 797)
# AFTER — insert below line 797:
GITHUB_REVIEW_WIKI_WAIT: int = config.getint("GITHUB_REVIEW_WIKI_WAIT", fallback=120)
```

### `github_reviewer.py` (MODIFY) — `review_pull_request`
```python
# occurrences: 1 (verified: grep -c '        await self._refresh_wiki_context(repo)' → line 985)
        wiki_refresh = self._start_wiki_refresh(repo)
# ... unchanged ticket fetch (may return early; the background refresh keeps running) ...
        diff_text, diff_truncated, diff_available = await self._fetch_diff(repo, pr_number)
        await self._await_wiki_refresh(wiki_refresh)

        async with self._wiki_review_lease() as wiki_leased:
            result = await self._ask_llm_for_review(
                # FILL IN: existing keyword arguments unchanged, plus use_wiki=wiki_leased
            )
```

### `github_reviewer.py` (MODIFY) — new helpers (insert after `_refresh_wiki_context`)
```python
    def _start_wiki_refresh(self, repository: str) -> Optional[asyncio.Task[Optional[Path]]]:
        """Start (or reuse) the single in-flight wiki refresh for this reviewer's repository."""
        # FILL IN: guard like _refresh_wiki_context (cache None / foreign repository → None);
        #          reuse self._wiki_refresh_task if not done; else create the named task,
        #          attach the warm-up's log_failure-style callback, store and return it

    async def _await_wiki_refresh(self, task: Optional[asyncio.Task[Optional[Path]]]) -> bool:
        """Wait at most ``GITHUB_REVIEW_WIKI_WAIT`` seconds; never cancel the refresh."""
        if task is None:
            return False
        done, _pending = await asyncio.wait({task}, timeout=conf.GITHUB_REVIEW_WIKI_WAIT)
        if not done:
            self.logger.info(
                "GitHubReviewer: wiki refresh still running after %ss; reviewing without fresh wiki context.",
                conf.GITHUB_REVIEW_WIKI_WAIT,
            )
            return False
        return True

    @asynccontextmanager
    async def _wiki_review_lease(self) -> AsyncIterator[bool]:
        """Hold a shared read lease on the plane for the duration of one review."""
        if self._wiki_cache is None or not self._wiki_context_available:
            yield False
            return
        # FILL IN: async with self._wiki_cache.read_lease(self.repository, timeout=0.0) as paths:
        #              yield paths is not None
        #          — bounded by: exactly one yield; any lease exception → log warning and yield False
        #          (wiki enrichment must fail closed), but never swallow CancelledError
```
`AsyncIterator`: verify it is imported from `typing` in `github_reviewer.py`, and add it if missing.

### FILL IN checklist
- [ ] `_start_wiki_refresh` — single in-flight task, shared with warm-up
- [ ] `_await_wiki_refresh` — bounded, never cancels
- [ ] `_wiki_review_lease` — one yield, fail closed
- [ ] `_ask_llm_for_review(use_wiki=)` → `_build_wiki_context(enabled=)`
- [ ] `_shutdown_wiki_warmup` cancels the refresh task too
- [ ] stub bindings + tests; docs row and degradation paragraph

---

## Acceptance Criteria

- [ ] A refresh slower than `GITHUB_REVIEW_WIKI_WAIT` does not delay the review beyond the wait, and is not cancelled
- [ ] Two deliveries during one in-flight refresh trigger exactly one `ensure_fresh`
- [ ] The warm-up task is reused as the first delivery's refresh
- [ ] `_ask_llm_for_review` runs inside the read lease. Without the lease the prompt has no wiki block
- [ ] `_shutdown_wiki_warmup` cancels an in-flight refresh task
- [ ] With the feature disabled, the prompt and flow are unchanged (spec AC-2)
- [ ] All `test_github_reviewer.py` tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

---

## Test Specification

```python
class TestWikiBoundedWait:
    async def test_slow_refresh_does_not_block_review(self, monkeypatch): ...      # FILL IN (conf wait 0.05)
    async def test_refresh_task_reused_across_deliveries(self): ...               # FILL IN
    async def test_warmup_task_is_first_refresh(self): ...                         # FILL IN
    async def test_review_runs_inside_read_lease(self): ...                        # FILL IN: fake read_lease records enter/exit around ask
    async def test_no_lease_means_no_wiki_block(self): ...                         # FILL IN
    async def test_shutdown_cancels_inflight_refresh(self): ...                    # FILL IN
```

---

## Agent Instructions

Standard SDD task flow (see `sdd/templates/task.md` → Agent Instructions).

---

## Completion Note

*(Agent fills this in when done)*
