# TASK-4340: Wire reviewer wiki lifecycle settings and toolkits

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4339
**Assigned-to**: unassigned

## Context

Implement spec §3 M5 within the approved external-plane design. Wire reviewer wiki lifecycle settings and toolkits.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Append the seven settings with the specified defaults and initialize optional state in GitHubReviewer.__init__ — disabled mode must be a no-op.
- Construct the cache after GitToolkit wiring, expand and resolve the cache directory, and detect missing wikitoolkit once — failures must leave the reviewer usable.
- Own a named warm-up task with a logging callback; override shutdown(**kwargs), cancel/await warm-up, then await super().shutdown(**kwargs) in finally — Agent already exposes this lifecycle.
- Refresh only self.repository after canonical identity comparison and before the review LLM call; prevent stale context after a failed refresh.
- Construct both toolkits against the external SQLite plane, register once through _attach_toolkit and sync to the current LLM — root alone would open the wrong plane.
- Extend the lightweight reviewer fixture and add local-origin integration coverage for cold cache, repeated/concurrent delivery, foreign payload and failed/partial build.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Wire reviewer wiki lifecycle settings and toolkits |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Wire reviewer wiki lifecycle settings and toolkits |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
from pathlib import Path
from typing import Any, Optional
from parrot import conf
from parrot.bots.agent import Agent
from navconfig import config
from parrot.knowledge.wiki.repo_cache import RepoWikiCache
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import create_wiki_store
from unittest.mock import AsyncMock, MagicMock
import pytest
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:430
    def __init__(
        self,
        repository: str,
        *,
        jira_project: str = "NAV",
        alert_chat_ids: Optional[List[ChatId]] = None,
        public_channel_id: Optional[ChatId] = None,
        webhook_public_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        stale_after_hours: int = 24,
        max_diff_bytes: int = 50_000,
        max_ticket_bytes: int = 20_000,
        silent_weeks_threshold: int = 3,
        top_n_contributors: int = 10,
        use_llm_summary: bool = False,
        max_review_tool_calls: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:503
    async def post_configure(self) -> None:
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:568
    def _attach_toolkit(self, toolkit: Any, name: str) -> None:
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:788
    async def review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
```

```python
# packages/ai-parrot/src/parrot/bots/agent.py:1242
    async def shutdown(self, **kwargs):
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py:44
    def __init__(
        self,
        root: Path | None = None,
        store: BaseWikiStore | None = None,
        config: WikiProjectConfig | None = None,
        **kwargs: Any,
    ) -> None:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:77
    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        okf_toolkit: Any,
        config: WikiConfig,
        agent_id: str = "agent",
        store: Optional[BaseWikiStore] = None,
        confine_sources: bool = False,
        **kwargs: Any,
    ) -> None:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:54
class WikiConfig(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:561
class WikiProjectConfig(BaseModel):
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2665
def create_wiki_store(
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore:
```

### Does NOT Exist

- `build_wiki()` or `run_build()` repository-scan API: use the CLI subprocess.
- `GitToolkit.checkout_ref()` and clone `sha=`/`ref=`: PR heads are out of scope.
- `WIKI_ROOT` or `PARROT_WIKI_ROOT`: pass explicit paths/config/store.
- `CodeStructuralToolkit(repository=...)`: constructor takes root/store/config.
- New repo_cache/repo_build symbols and seven GITHUB_REVIEW wiki settings are absent at planning time; rely on prerequisites before importing them.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/github_reviewer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.post_configure",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._attach_toolkit",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.review_pull_request",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.shutdown",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py#CodeStructuralToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py#LLMWikiToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store"
  ]
}
```

## Implementation Notes

Pass explicit WikiProjectConfig(storage_dir=str(paths.plane_dir), backend="sqlite") and/or the same injected store to CodeStructuralToolkit(root=clone_root); LLMWikiToolkit gets WikiConfig(storage_dir=paths.plane_dir, storage_backend="sqlite"), confine_sources=True and the same wiki name. Do not call DevLoopWikiSearch.from_project: it discovers the clone-local plane. Keep a private reference to the store, actual branch and successful build time for M6. Existing attached tools must not expose an incomplete plane after a failed refresh; gate their availability for that review using existing tool-manager mechanisms verified during implementation. Preserve disabled prompt bytes and avoid adding optional dependencies at module import time.

**Parallelism**: Consumes RepoWikiCache and its completed build-runner integration from TASK-4339; owns github_reviewer.py, conf.py and test_github_reviewer.py before the prompt task.

## Implementation Blueprint

### Steps (in order)

1. Append the seven settings with the specified defaults and initialize optional state in GitHubReviewer.__init__ — disabled mode must be a no-op.
2. Construct the cache after GitToolkit wiring, expand and resolve the cache directory, and detect missing wikitoolkit once — failures must leave the reviewer usable.
3. Own a named warm-up task with a logging callback; override shutdown(**kwargs), cancel/await warm-up, then await super().shutdown(**kwargs) in finally — Agent already exposes this lifecycle.
4. Refresh only self.repository after canonical identity comparison and before the review LLM call; prevent stale context after a failed refresh.
5. Construct both toolkits against the external SQLite plane, register once through _attach_toolkit and sync to the current LLM — root alone would open the wrong plane.
6. Extend the lightweight reviewer fixture and add local-origin integration coverage for cold cache, repeated/concurrent delivery, foreign payload and failed/partial build.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

```python
# Anchor:         self.git_toolkit = self._build_git_toolkit()
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/src/parrot/bots/github_reviewer.py:518)
# Anchor:         ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/src/parrot/bots/github_reviewer.py:824)
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py  (modifies :503, :518, :788)
class GitHubReviewer(Agent):
    _wiki_cache: Optional["RepoWikiCache"]
    _wiki_warmup_task: Optional[asyncio.Task]
    _wiki_toolkits_attached: bool

    def _build_wiki_cache(self) -> Optional["RepoWikiCache"]:
        """Build the cache from conf, or None when disabled/misconfigured.

        Fails closed and logs — mirrors _build_git_toolkit (verified:
        github_reviewer.py:588)."""

    async def _schedule_wiki_warmup(self) -> None:
        """Create, store and name the warm-up task; log its exception via a
        done-callback so a failure is never swallowed."""

    async def _shutdown_wiki_warmup(self) -> None:
        """Cancel and await the warm-up task (idempotent)."""

    async def _refresh_wiki_context(self, repository: str) -> Optional[Path]:
        """ensure_fresh() for THIS agent's repository only.

        ``review_pull_request`` reads ``payload.get("repository") or
        self.repository`` (verified: github_reviewer.py:809); enrichment
        ignores the payload value unless it canonicalizes to self.repository,
        so a manual payload can never select another cache entry."""

    def _attach_wiki_toolkits(self, clone_root: Path) -> None:
        """Attach CodeStructuralToolkit(root=clone_root) and a headless
        LLMWikiToolkit(None, None, None, WikiConfig(...), confine_sources=True)
        through _attach_toolkit(), exactly once per process."""
# FILL IN: complete method bodies and wiring using the ordered steps and acceptance criteria.
```

**Why**: Preserve the spec signatures and small edit surface; the implementation details are bounded by the task acceptance criteria.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)

```python
# Anchor: GITHUB_REVIEW_USE_LLM_SUMMARY: bool = config.getboolean("GITHUB_REVIEW_USE_LLM_SUMMARY", fallback=False)
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/src/parrot/conf.py:790)
```

```python
# packages/ai-parrot/src/parrot/conf.py  (appends after conf.py:790)
GITHUB_REVIEW_WIKI_ENABLED: bool = config.getboolean("GITHUB_REVIEW_WIKI_ENABLED", fallback=False)
GITHUB_REVIEW_CACHE_DIR: str = config.get(
    "GITHUB_REVIEW_CACHE_DIR", fallback="~/.cache/parrot/github-reviewer")
GITHUB_REVIEW_CLONE_BRANCH: str | None = config.get("GITHUB_REVIEW_CLONE_BRANCH", fallback=None)
GITHUB_REVIEW_CLONE_DEPTH: int | None = config.getint("GITHUB_REVIEW_CLONE_DEPTH", fallback=None)
GITHUB_REVIEW_CACHE_MAX_BYTES: int = config.getint(
    "GITHUB_REVIEW_CACHE_MAX_BYTES", fallback=5 * 1024**3)
GITHUB_REVIEW_BUILD_TIMEOUT: int = config.getint("GITHUB_REVIEW_BUILD_TIMEOUT", fallback=900)
GITHUB_REVIEW_WIKI_CONTEXT_TOKENS: int = config.getint(
    "GITHUB_REVIEW_WIKI_CONTEXT_TOKENS", fallback=4000)


# FILL IN: complete method bodies and wiring using the ordered steps and acceptance criteria.
```

**Why**: Preserve the spec signatures and small edit surface; the implementation details are bounded by the task acceptance criteria.

### `packages/ai-parrot/tests/bots/test_github_reviewer.py` (MODIFY)

```python
# Anchor: class _MinimalReviewer:
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/tests/bots/test_github_reviewer.py:34)
# Extend this test module; preserve existing fixtures and regression assertions.
```

```python
async def test_wiki_cache_disabled_by_default(tmp_path: Path) -> None:
    """`GITHUB_REVIEW_WIKI_ENABLED` unset ⇒ no cache, no warm-up task."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_warmup_task_is_owned_and_cancelled(tmp_path: Path) -> None:
    """Task stored, named, exception logged, cancelled on shutdown."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_enrichment_ignores_foreign_payload_repository(tmp_path: Path) -> None:
    """A payload naming another repo does not touch its cache entry."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_toolkits_attached_once(tmp_path: Path) -> None:
    """Repeated refreshes do not re-register tools."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_llm_wiki_toolkit_confines_sources(tmp_path: Path) -> None:
    """Constructed with `confine_sources=True`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

### Mechanical wiring details

Extend existing `__init__` state (do not replace the class or constructor):

```python
self._wiki_cache = None
self._wiki_warmup_task = None
self._wiki_toolkits_attached = False
```

After the verified GitToolkit construction anchor in `post_configure`, add:

```python
self._wiki_cache = self._build_wiki_cache()
await self._schedule_wiki_warmup()
```

At the verified pre-ticket anchor in `review_pull_request`, refresh with
`await self._refresh_wiki_context(repo)`. Disabled/foreign cases return immediately.
Add this override inside the existing class, before `_build_wiki_cache`:

```python
async def shutdown(self, **kwargs: Any) -> None:
    """Stop the owned wiki task before the inherited agent shutdown."""
    try:
        await self._shutdown_wiki_warmup()
    finally:
        await super().shutdown(**kwargs)
```

**Why**: The inherited hook is `BasicAgent.shutdown` at agent.py:1242; a helper
alone would never receive lifecycle cancellation. The cache constructor and
scheduling methods retain their disabled/missing-binary guards.

### FILL IN checklist

- [ ] Append the seven settings with the specified defaults and initialize optional state in GitHubReviewer.__init__ — disabled mode must be a no-op.
- [ ] Construct the cache after GitToolkit wiring, expand and resolve the cache directory, and detect missing wikitoolkit once — failures must leave the reviewer usable.
- [ ] Own a named warm-up task with a logging callback; override shutdown(**kwargs), cancel/await warm-up, then await super().shutdown(**kwargs) in finally — Agent already exposes this lifecycle.
- [ ] Refresh only self.repository after canonical identity comparison and before the review LLM call; prevent stale context after a failed refresh.
- [ ] Construct both toolkits against the external SQLite plane, register once through _attach_toolkit and sync to the current LLM — root alone would open the wrong plane.
- [ ] Extend the lightweight reviewer fixture and add local-origin integration coverage for cold cache, repeated/concurrent delivery, foreign payload and failed/partial build.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-2: With `GITHUB_REVIEW_WIKI_ENABLED` unset, the reviewer's behaviour and review prompt are byte-identical to today's.
- [ ] AC-3: The clone tracks the reviewed repository's own default branch (or `GITHUB_REVIEW_CLONE_BRANCH` when set) — never the `GIT_DEFAULT_BRANCH` fallback of `"main"` — and the branch is reported in the injected context header.
- [ ] AC-5: The warm-up task is stored on the agent, logs its own exceptions, and is cancelled and awaited on shutdown; no orphaned `git`/`wikitoolkit` child survives a reload.
- [ ] AC-7: Enrichment never acts on a repository other than `self.repository`, whatever the payload says.
- [ ] AC-9: Clone failure, build failure, build timeout, missing `wikitoolkit` binary, and a plane without a last-good marker each degrade to the diff-only review, with one log line and no exception escaping.
- [ ] AC-12: `LLMWikiToolkit` is constructed with `confine_sources=True`; `CodeStructuralToolkit` with an explicit `root=`.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification

- `test_wiki_cache_disabled_by_default`: `GITHUB_REVIEW_WIKI_ENABLED` unset ⇒ no cache, no warm-up task.
- `test_warmup_task_is_owned_and_cancelled`: Task stored, named, exception logged, cancelled on shutdown.
- `test_enrichment_ignores_foreign_payload_repository`: A payload naming another repo does not touch its cache entry.
- `test_toolkits_attached_once`: Repeated refreshes do not re-register tools.
- `test_llm_wiki_toolkit_confines_sources`: Constructed with `confine_sources=True`.

Integration cases in test_github_reviewer.py: test_fresh_clone_then_build_then_review,
test_second_delivery_reuses_clone, test_concurrent_deliveries_serialize,
test_build_failure_degrades_to_diff_only, test_partial_plane_is_not_attached.
Use a local bare origin, isolated cache_dir and fake executable in this file;
no network calls. Run actual local git clone/build for the successful cold-cache
case; mock only GitHub/Jira/LLM boundaries. Private token routing is covered by
test_gittoolkit_clone.py, including gh present but unauthenticated.

## Agent Instructions

1. Use `$sdd-start TASK-4340` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Implemented by gpt-5.6-terra (codex). test_github_reviewer.py: 80 passed. Engine black pass reformatted existing test_github_reviewer.py (noisy diff).
