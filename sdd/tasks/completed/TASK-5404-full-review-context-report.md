# TASK-5404: Add full-review value models, context gathering and report rendering

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5398, TASK-5403
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Add §2 review models plus a typed internal FullReviewContext, known-bot classification, context collection, deterministic verdict floor and report/chat rendering.
- Use the new GitToolkit reads with independent failure coverage notes, explicit Jira lookup or existing SDD fallback, checks and bounded wiki lease.
- Implement pure rendering helpers without posting comments or changing strict review behavior.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Full-review data and pure/context helpers |
| `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` | CREATE | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from parrot.integrations.core.queued import current_job_id, report_command_progress
from parrot.bots.github_reviewer import GitHubReviewer
import pytest
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2223
async def _fetch_ticket(self, ticket_key: str, *, fields: Optional[str]=None) -> Optional[Dict[str, Any]]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1578
async def _resolve_requirement(self, repo: str, payload: Dict[str, Any]) -> Tuple[Optional[str], Literal['jira', 'sdd_spec'], Optional[Dict[str, Any]]]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2268
async def _fetch_diff(self, repo: str, pr_number: int) -> Tuple[str, bool, bool]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2720
async def _fetch_checks(self, repo: str, pr_number: int, head_sha: str='') -> PRChecksSummary

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1191
async def _wiki_review_lease(self) -> AsyncIterator[bool]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1153
def _start_wiki_refresh(self, repository: str) -> Optional[asyncio.Task[Optional[Path]]]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:1177
async def _await_wiki_refresh(self, task: Optional[asyncio.Task[Optional[Path]]]) -> bool

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2301
async def _build_wiki_context(self, payload: Dict[str, Any], diff_text: str, *, enabled: bool=True) -> Optional[str]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:3433
def _format_command_reply(self, repo: str, pr_number: int, payload: Dict[str, Any], outcome: Dict[str, Any]) -> str

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:401
class ChartReply(BaseModel)

# packages/ai-parrot/tests/bots/test_github_reviewer.py:58
class _MinimalReviewer()
```

### Does NOT Exist

- FullPRReview, FullReviewContext and full-review rendering helpers are new.
- Existing PRReviewResult is the strict-gate model and must not be repurposed.

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
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_ticket",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._resolve_requirement",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_diff",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_checks",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._wiki_review_lease",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._start_wiki_refresh",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._await_wiki_refresh",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._build_wiki_context",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._format_command_reply",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#ChartReply",
    "sym:packages/ai-parrot/tests/bots/test_github_reviewer.py#_MinimalReviewer"
  ]
}
```

## Implementation Notes

- Exact model field skeleton is included below from spec §2; use it, adding docstrings without changing types.
- FullReviewContext is an internal Pydantic model whose fields are bounded above; this task owns its shape so the isolation/orchestration tasks consume one contract.

**Parallelism**: TASK-5398 supplies current_job_id and report_command_progress; TASK-5403 supplies all four GitToolkit.list_pull_request_* reads consumed by _gather_full_review_context.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

- Anchor `class ChartReply(BaseModel):`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/bots/github_reviewer.py:401.
- Anchor `def _format_command_reply(`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/bots/github_reviewer.py:3433.

```python
# BEFORE ChartReply: add all six §2 review models verbatim in field/type shape,
# with Google-style docstrings; FullReviewLLMError(RuntimeError) is separate.
# Add FullReviewContext(BaseModel) containing typed repo/PR/payload, ticket/source,
# diff + availability/truncation flags, files/comments/reviews/inline comments,
# checks/wiki context and coverage notes. Use Field(default_factory=...) for collections.
# Add _KNOWN_REVIEW_BOTS mapping the seven logins in M7; author_type=Bot also qualifies.
# BEFORE _format_command_reply, inside GitHubReviewer:
async def _gather_full_review_context(self, repo: str, pr_number: int, payload: Dict[str, Any],
                                      jira_key: Optional[str]) -> "FullReviewContext":
    """Collect bounded review evidence without writing to GitHub."""
    # FILL IN: AC2/AC3; read helpers and TASK-5403 PR reads, progress per §7.
    raise NotImplementedError
def _apply_verdict_floor(self, review: FullPRReview, *, ac_evaluated: bool) -> FullPRReview:
    """Prevent approval when AC evidence is missing or a criterion is not met."""
    # FILL IN: AC4; preserve findings and avoid mutating shared review objects.
    raise NotImplementedError
def _render_full_review_report(self, context: "FullReviewContext", review: FullPRReview) -> str:
    """Render the prescribed Claude headings, evidence and job attribution."""
    # FILL IN: AC5/AC6; keep complete text available separately from comment truncation.
    raise NotImplementedError
def _format_pr_review_reply(self, repo: str, pr_number: int, payload: Dict[str, Any],
                            outcome: Dict[str, Any]) -> str:
    """Render a bounded summary, or the complete report on dry-run/post failure."""
    # FILL IN: AC6/AC7; preserve the full report separately if the posting renderer caps it.
    raise NotImplementedError
```

**Why**: Full-review data and pure/context helpers. Add §2 review models plus a typed internal FullReviewContext, known-bot classification, context collection, deterministic verdict floor and report/chat rendering.

### `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` (CREATE)

```python
"""Regression coverage for Add full-review value models, context gathering and report rendering."""
import pytest
from parrot.bots.github_reviewer import GitHubReviewer

async def test_verdict_floor_without_ac_and_with_not_met() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_report_has_claude_headings_and_bot_tables() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Add §2 review models plus a typed internal FullReviewContext, known-bot classification, context collection, deterministic verdict floor and report/chat rendering.

### Fixed model fields for the reviewer block above

```python
class CriterionAssessment(BaseModel):
    criterion: str
    status: Literal["met", "partial", "not_met", "unable_to_verify"]
    evidence: str

class DescriptionAlignment(BaseModel):
    addressed: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)

class CodeObservation(BaseModel):
    severity: Literal["info", "minor", "major", "blocker"]
    file: Optional[str] = None
    line: Optional[int] = None
    note: str

class BotFindingAssessment(BaseModel):
    bot: str
    file: Optional[str] = None
    finding: str
    assessment: Literal["agree", "disagree", "resolved", "false_positive"]
    comment: str = ""

class FullPRReview(BaseModel):
    criteria: List[CriterionAssessment] = Field(default_factory=list)
    description: DescriptionAlignment = Field(default_factory=DescriptionAlignment)
    code_observations: List[CodeObservation] = Field(default_factory=list)
    bot_findings: List[BotFindingAssessment] = Field(default_factory=list)
    verdict: Literal["approved", "needs_attention", "does_not_meet"]
    recommended_action: Literal["APPROVE", "REQUEST_CHANGES", "CONVERT_TO_DRAFT"]
    summary: str = ""

class FullReviewLLMError(RuntimeError):
    """The full-review LLM call failed or returned no structured result."""
```

### FILL IN checklist

- [ ] packages/ai-parrot/src/parrot/bots/github_reviewer.py — finish the scoped behavior/test branches above, bounded by AC1–AC7.
- [ ] packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py — finish the scoped behavior/test branches above, bounded by AC1–AC7.

## Acceptance Criteria

- [ ] AC1: Models preserve every field and Literal value from §2; FullReviewLLMError is a distinct RuntimeError.
- [ ] AC2: Explicit unreadable Jira key is distinguishable from no linked requirement; never silently substitute another ticket.
- [ ] AC3: Each context read failure yields an empty collection plus coverage note; wiki refresh/wait/build runs under the existing lease.
- [ ] AC4: approved is floored to needs_attention for missing evaluated AC or any not_met criterion; missing AC cannot authorize auto-draft.
- [ ] AC5: Report includes every M7 Claude heading, criterion table/score, description subsections, per-bot finding tables, action, PR state, coverage/truncation notes and current job ID.
- [ ] AC6: Posting text is capped at 65000 characters with a note; retain complete report for dry-run or posting-failure chat fallback.
- [ ] AC7: Chat summary includes verdict, ticket, AC count, <=5 findings, report link and draft outcome.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_verdict_floor_without_ac_and_with_not_met` | M7 | `approved` downgraded to `needs_attention` in both cases; auto-draft never fires without AC |
| `test_report_has_claude_headings_and_bot_tables` | M7 | rendered report contains every heading in §3 M7 and one table per bot that commented |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5404`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
