# TASK-4341: Inject bounded base-branch context into review prompts

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4340
**Assigned-to**: unassigned

## Context

Implement spec §3 M6 within the approved external-plane design. Inject bounded base-branch context into review prompts.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Use the current successful refresh store and actual branch/build timestamp from wiring — never query the host repository wiki or trust a foreign payload.
- Derive query text from PR title and changed paths, search the external plane and pack ranked results using wiki helpers.
- Reserve room for the complete snapshot caveat; remeasure the entire final block with estimate_tokens after truncation — both existing helpers can overshoot.
- Splice context only when present into the existing question assembly and keep the absent-context question byte-identical; test tiny budgets, failures and unicode.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Inject bounded base-branch context into review prompts |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict, Optional
from parrot.knowledge.wiki.context import pack_results, truncate_to_tokens
from parrot.knowledge.wiki.store import estimate_tokens
from parrot.knowledge.wiki.search import WikiCombinedSearch
from unittest.mock import AsyncMock, MagicMock
import pytest
from pathlib import Path
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1031
    async def _ask_llm_for_review(
        self,
        *,
        payload: Dict[str, Any],
        ticket_key: str,
        ticket: Dict[str, Any],
        diff_text: str,
        diff_truncated: bool,
        diff_available: bool,
    ) -> PRReviewResult:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/context.py:209
def pack_results(
    results: Iterable[Any],
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> PackedContext:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/context.py:274
def truncate_to_tokens(text: str, max_tokens: int | None) -> tuple[str, bool]:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:338
def estimate_tokens(text: str) -> int:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py:47
    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        default_weights: Optional[dict[str, float]] = None,
        store: Optional[BaseWikiStore] = None,
        embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        normalize_store_rows: bool = True,
    ) -> None:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py:91
    async def search(
        self,
        query: str,
        mode: str = "combined",
        top_k: int = 10,
        tree_name: Optional[str] = None,
        weights: Optional[dict[str, float]] = None,
        include_archived: bool = False,
    ) -> list[WikiSearchResult]:
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
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._ask_llm_for_review",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/context.py#pack_results",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/context.py#truncate_to_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#estimate_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/search.py#WikiCombinedSearch.search"
  ]
}
```

## Implementation Notes

pack_results intentionally includes an oversized first stub; truncate_to_tokens appends a marker and treats max_tokens<=0 as unlimited. Neither alone enforces AC-8. Return None if the full mandatory caveat cannot fit; trim only the body and remeasure until the whole block fits. Never truncate away the caveat. Preserve diff/ticket clamp behavior. Do not use DevLoopWikiSearch additional ledger/schema appends, which can exceed the budget.

**Parallelism**: Consumes the cache/store state and toolkit wiring from TASK-4340; also serializes shared writers of github_reviewer.py and test_github_reviewer.py after TASK-4340.

## Implementation Blueprint

### Steps (in order)

1. Use the current successful refresh store and actual branch/build timestamp from wiring — never query the host repository wiki or trust a foreign payload.
2. Derive query text from PR title and changed paths, search the external plane and pack ranked results using wiki helpers.
3. Reserve room for the complete snapshot caveat; remeasure the entire final block with estimate_tokens after truncation — both existing helpers can overshoot.
4. Splice context only when present into the existing question assembly and keep the absent-context question byte-identical; test tiny budgets, failures and unicode.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

```python
# Anchor:             "Compare them and return a PRReviewResult JSON object."
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/src/parrot/bots/github_reviewer.py:1069)
```

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py  (modifies :1031 question assembly)
_WIKI_CONTEXT_HEADER = (
    "=== Codebase context (knowledge graph) ===\n"
    "SNAPSHOT OF BRANCH {branch} AT {built_at} — it does NOT contain this "
    "PR's changes. A symbol introduced by this PR is EXPECTED to be absent "
    "here; never report such a symbol as nonexistent on that basis."
)

async def _build_wiki_context(self, payload: Dict[str, Any], diff_text: str) -> Optional[str]:
    """Ranked, token-budgeted context for this PR, or None.

    Query is derived from the PR title plus the paths touched by the diff.
    Hard-capped at GITHUB_REVIEW_WIKI_CONTEXT_TOKENS, truncated with the
    wiki's own budgeting helpers (verified: context.py pack_results /
    truncate_to_tokens, used the same way by DevLoopWikiSearch —
    wiki_search.py:101). Never raises."""
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
async def test_wiki_context_respects_token_budget(tmp_path: Path) -> None:
    """Block never exceeds `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_wiki_context_carries_base_branch_label(tmp_path: Path) -> None:
    """Header names the branch and the "PR symbols may be absent" caveat."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

async def test_review_prompt_unchanged_without_context(tmp_path: Path) -> None:
    """With no plane, the question is byte-identical to today's."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

### Mechanical prompt splice

Before the existing `question = (` block, obtain optional context. Insert the
conditional fragment immediately before the verified final instruction line:

```python
wiki_context = await self._build_wiki_context(payload, diff_text)
wiki_block = f"{wiki_context}\n\n" if wiki_context else ""
# Inside question's adjacent string expressions, before the final instruction:
f"{wiki_block}"
```

**Why**: An empty fragment preserves the existing question bytes; context is
kept separate from the existing ticket and diff clamps.

### FILL IN checklist

- [ ] Use the current successful refresh store and actual branch/build timestamp from wiring — never query the host repository wiki or trust a foreign payload.
- [ ] Derive query text from PR title and changed paths, search the external plane and pack ranked results using wiki helpers.
- [ ] Reserve room for the complete snapshot caveat; remeasure the entire final block with estimate_tokens after truncation — both existing helpers can overshoot.
- [ ] Splice context only when present into the existing question assembly and keep the absent-context question byte-identical; test tiny budgets, failures and unicode.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-2: With `GITHUB_REVIEW_WIKI_ENABLED` unset, the reviewer's behaviour and review prompt are byte-identical to today's.
- [ ] AC-7: Enrichment never acts on a repository other than `self.repository`, whatever the payload says.
- [ ] AC-8: The injected context block never exceeds `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS` and always carries the base-branch snapshot caveat.
- [ ] AC-9: Clone failure, build failure, build timeout, missing `wikitoolkit` binary, and a plane without a last-good marker each degrade to the diff-only review, with one log line and no exception escaping.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification

- `test_wiki_context_respects_token_budget`: Block never exceeds `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS`.
- `test_wiki_context_carries_base_branch_label`: Header names the branch and the "PR symbols may be absent" caveat.
- `test_review_prompt_unchanged_without_context`: With no plane, the question is byte-identical to today's.

## Agent Instructions

1. Use `$sdd-start TASK-4341` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Implemented by gpt-5.6-terra (codex); merged with 2 failing tests in test_github_reviewer.py. Orchestrator fixed: (a) token-budget loop returned None for multi-byte text because truncate_to_tokens is a chars/4 heuristic -> added proportional char-cut fallback; (b) test expectation for diff-only prompt had one newline too few vs unchanged production prompt. Final: 83 passed.
