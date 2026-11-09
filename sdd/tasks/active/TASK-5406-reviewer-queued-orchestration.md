# TASK-5406: Queue strict reviews and orchestrate full PR reviews with guarded writes

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5405, TASK-5398
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Add the two configuration keys, max_full_review_tool_calls initialization, both prepare hooks and queued command decorators.
- Implement pr_review/full_review_pull_request using prior context/report/isolation helpers.
- Keep strict review_pr body and verdict text unchanged, including its existing alerts; update only registration expectations.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Review tool-call and runtime defaults |
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Prepare hooks, queued decorators and guarded review pipeline |
| `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` | MODIFY | Task-owned regression coverage |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Update strict registration assertions, preserving behavior coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import Any, Dict, Optional
from parrot import conf
from parrot.integrations.core.queued import CommandUsageError, PreparedCommand, current_job_id, queued_command, report_command_progress
from parrot.bots.github_reviewer import GitHubReviewer
import pytest
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:749
def __init__(self, repository: str, *, jira_project: str='NAV', sdd_feature_prefix: str='FEAT', enable_sdd_spec_fallback: bool=True, max_spec_scan_files: int=500, alert_chat_ids: Optional[List[ChatId]]=None, public_channel_id: Optional[ChatId]=None, management_chat_id: Optional[ChatId]=None, webhook_public_url: Optional[str]=None, webhook_secret: Optional[str]=None, stale_after_hours: int=24, max_diff_bytes: int=50000, max_ticket_bytes: int=20000, silent_weeks_threshold: int=3, top_n_contributors: int=10, use_llm_summary: bool=False, max_review_tool_calls: Optional[int]=None, min_check_pass_ratio: Optional[float]=None, require_checks: Optional[bool]=None, google_api_key: Optional[str]=None, **kwargs: Any) -> None

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:3383
async def review_pr(self, target: str='', **kwargs: Any) -> str

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2609
def _parse_pr_target(cls, text: str) -> Tuple[Optional[str], Optional[int], Optional[str]]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:2642
async def _fetch_pr_payload(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:3114
async def strict_review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:3433
def _format_command_reply(self, repo: str, pr_number: int, payload: Dict[str, Any], outcome: Dict[str, Any]) -> str

# packages/ai-parrot/tests/bots/test_github_reviewer.py:5206
class TestReviewPRCommand()

# packages/ai-parrot/tests/bots/test_github_reviewer.py:58
class _MinimalReviewer()
```

### Does NOT Exist

- pr_review and both prepare hooks are new; full-review helper contracts arrive from TASK-5404/TASK-5405.
- Webhook job registration and cross-worker dedup are outside this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/github_reviewer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.review_pr",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._parse_pr_target",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_pr_payload",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.strict_review_pull_request",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._format_command_reply",
    "sym:packages/ai-parrot/tests/bots/test_github_reviewer.py#TestReviewPRCommand",
    "sym:packages/ai-parrot/tests/bots/test_github_reviewer.py#_MinimalReviewer"
  ]
}
```

## Implementation Notes

- Cover every M7 unit case from §4, including already-draft, closed/merged, missing AC, unreadable explicit ticket, failed comment posting and FullReviewLLMError.
- Draft outcome values: converted, already_draft, not_open, skipped_dry_run, not_applicable, failed. Conflicting --dry-run/--auto-draft must always select zero writes.

**Parallelism**: TASK-5405 supplies _ask_llm_for_full_review and serializes github_reviewer.py/full-review test edits; TASK-5398 supplies QueuedCommandService for the service-to-GitHub integration test and progress helpers.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)

- Anchor `GITHUB_REVIEW_WIKI_WAIT: int = config.getint("GITHUB_REVIEW_WIKI_WAIT", fallback=120)`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/conf.py:877.

```python
GITHUB_REVIEW_FULL_MAX_TOOL_CALLS: int = config.getint("GITHUB_REVIEW_FULL_MAX_TOOL_CALLS", fallback=15)
GITHUB_REVIEW_COMMAND_MAX_RUNTIME: int = config.getint("GITHUB_REVIEW_COMMAND_MAX_RUNTIME", fallback=1800)
```

**Why**: Review tool-call and runtime defaults. Add the two configuration keys, max_full_review_tool_calls initialization, both prepare hooks and queued command decorators.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

- Anchor `from parrot.integrations.telegram import telegram_command`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/bots/github_reviewer.py:77.
- Anchor `"review_pr",`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/bots/github_reviewer.py:3379.
- Anchor `def _format_command_reply(`; occurrences: **1** (`grep -cF`); packages/ai-parrot/src/parrot/bots/github_reviewer.py:3433.

```python
from parrot.integrations.core.queued import (
    CommandUsageError, PreparedCommand, current_job_id, queued_command, report_command_progress,
)
# __init__: set self.max_full_review_tool_calls next to max_review_tool_calls,
# following its existing kwargs/default validation using conf.GITHUB_REVIEW_FULL_MAX_TOOL_CALLS.
# REPLACE only review_pr's decorator (preserve body/signature):
@queued_command("review_pr", description="Review a PR against its Jira ticket and draft it if it does not comply",
                parse_mode="raw", prepare="_prepare_review_pr",
                max_runtime=conf.GITHUB_REVIEW_COMMAND_MAX_RUNTIME,
                max_concurrent=2, concurrency_group="github_review")
# existing async def review_pr(self, target: str = "", **kwargs: Any) -> str body stays unchanged.

# BEFORE _format_command_reply, add:
async def _prepare_review_pr(self, raw: str) -> PreparedCommand:
    """Validate the existing strict PR grammar locally and reserve its dedup key."""
    # FILL IN: AC1/AC2; use _parse_pr_target and preserve existing usage text.
    raise NotImplementedError
async def _prepare_pr_review(self, raw: str) -> PreparedCommand:
    """Parse full-review grammar and flags without performing I/O."""
    # FILL IN: AC1/AC2; Jira regex ^[A-Za-z][A-Za-z0-9]+-\d+$.
    raise NotImplementedError
@queued_command("pr_review", description="Full PR review against its Jira ticket; posts the report on the PR (background)",
                parse_mode="raw", aliases=("pr-review",), prepare="_prepare_pr_review",
                max_runtime=conf.GITHUB_REVIEW_COMMAND_MAX_RUNTIME,
                max_concurrent=2, concurrency_group="github_review")
async def pr_review(self, target: str = "", jira_key: Optional[str] = None, auto_draft: bool = False,
                    dry_run: bool = False, **kwargs: Any) -> str:
    """Fetch the PR, run full review and return the chat reply; propagate LLM failure."""
    # FILL IN: AC3-AC6; _fetch_pr_payload then full_review_pull_request and reply helper.
    raise NotImplementedError
async def full_review_pull_request(self, payload: Dict[str, Any], *, jira_key: Optional[str] = None,
                                   auto_draft: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Review with isolated reads, then perform only explicitly guarded GitHub writes."""
    # FILL IN: AC3-AC7; gather -> isolated LLM -> verdict floor -> render -> guarded comment/draft.
    # Status: reviewed|ticket_not_found|error. Required keys per M7:
    # status, verdict, report, comment, draft, jira_key, requirement_source,
    # criteria_met, criteria_total, reason. Retain full report separately from capped comment.
    raise NotImplementedError
```

**Why**: Prepare hooks, queued decorators and guarded review pipeline. Add the two configuration keys, max_full_review_tool_calls initialization, both prepare hooks and queued command decorators.

### `packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py` (MODIFY)

Created by TASK-5404; planned anchor `async def test_report_has_claude_headings_and_bot_tables() -> None:` occurs 1 time(s) in its blueprint. File does not exist on dev yet: verify actual count/line after the dependency lands before editing; this is dependency evidence, not a claimed current-source grep.

```python
# Preserve existing fixtures and tests; append the cases below.
"""Regression coverage for Queue strict reviews and orchestrate full PR reviews with guarded writes."""
import pytest

async def test_prepare_pr_review_grammar() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_full_review_posts_report_comment() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_full_review_dry_run_writes_nothing() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_pr_review_end_to_end_stubbed_github() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Add the two configuration keys, max_full_review_tool_calls initialization, both prepare hooks and queued command decorators.

### `packages/ai-parrot/tests/bots/test_github_reviewer.py` (MODIFY)

- Anchor `class TestReviewPRCommand`; occurrences: **1** (`grep -cF`); packages/ai-parrot/tests/bots/test_github_reviewer.py:5206.

```python
# Within TestReviewPRCommand replace the Telegram metadata assertion test:
async def test_review_pr_is_a_queued_command(self) -> None:
    """Strict review remains raw but is now dispatched through the shared queue."""
    spec = GitHubReviewer.review_pr._queued_command
    assert spec.command == "review_pr"
    assert spec.parse_mode == "raw"
    assert spec.concurrency_group == "github_review"
    assert spec.description
# FILL IN: add _prepare_review_pr usage-error coverage; leave strict body tests intact.
```

**Why**: Update strict registration assertions, preserving behavior coverage. Add the two configuration keys, max_full_review_tool_calls initialization, both prepare hooks and queued command decorators.

### FILL IN checklist

- [ ] packages/ai-parrot/src/parrot/conf.py — finish the scoped behavior/test branches above, bounded by AC1–AC8.
- [ ] packages/ai-parrot/src/parrot/bots/github_reviewer.py — finish the scoped behavior/test branches above, bounded by AC1–AC8.
- [ ] packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py — finish the scoped behavior/test branches above, bounded by AC1–AC8.
- [ ] packages/ai-parrot/tests/bots/test_github_reviewer.py — finish the scoped behavior/test branches above, bounded by AC1–AC8.

## Acceptance Criteria

- [ ] AC1: Grammar is <PR> [JIRA-KEY] [--auto-draft] [--dry-run]; normalize leading en/em dash flags, uppercase matching Jira keys, reject all other tokens without network access.
- [ ] AC2: Both commands use raw mode, github_review group, cap 2 and configured runtime; dedup keys are separately pr_review:repo#n and review_pr:repo#n.
- [ ] AC3: Default successful full review posts one report comment; never submit APPROVE/REQUEST_CHANGES. Dry-run wins and performs no GitHub writes.
- [ ] AC4: auto-draft requires evaluated AC, does_not_meet, open PR and not already draft; closed/merged PRs still get reviews and state in report.
- [ ] AC5: Explicit missing ticket returns ticket_not_found with no writes; LLM failure propagates FullReviewLLMError so the job ends FAILED and writes nothing.
- [ ] AC6: Outcomes contain every M7 key/status/draft state; failed comment post keeps reviewed status with comment.error and complete report in chat.
- [ ] AC7: Progress stages match §7; new config defaults are 15 tool calls and 1800 runtime seconds.
- [ ] AC8: Existing strict tests pass after changing only _telegram_command metadata assertions to _queued_command; service-to-stubbed-GitHub integration posts the comment and delivers a notice.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer_pr_review.py -q`
- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_review_pr_is_a_queued_command` | M7 | `review_pr._queued_command.command == "review_pr"`, `parse_mode == "raw"`, group `github_review` (replaces the `_telegram_command` assertion in `TestReviewPRCommand`) |
| `test_prepare_review_pr_usage_error` | M7 | unparsable target → `CommandUsageError` with the existing usage text |
| `test_prepare_pr_review_grammar` | M7 | URL + key + flags parsed; `—auto-draft` normalized; unknown token → usage error; dedup key and label |
| `test_full_review_posts_report_comment` | M7 | default run → `add_pr_comment` once with the rendered report; no `submit_pr_review` |
| `test_full_review_dry_run_writes_nothing` | M7 | `dry_run=True` → no `add_pr_comment`, no `convert_pr_to_draft`; reply carries the report |
| `test_full_review_auto_draft_only_on_does_not_meet` | M7 | `does_not_meet` + `auto_draft` → `convert_pr_to_draft`; `needs_attention` → not called |
| `test_full_review_llm_failure_writes_nothing` | M7 | `_ask_llm_for_full_review` raises `FullReviewLLMError` → it propagates; no GitHub write |
| `test_explicit_ticket_not_found_posts_nothing` | M7 | explicit key unreadable → status `ticket_not_found`, no comment |
| `test_comment_failure_returns_full_report_in_chat` | M7 | `add_pr_comment` raises → status `reviewed`, `comment.error` set, reply includes the report |
| `test_pr_review_end_to_end_stubbed_github` | M2 + M7: `GitHubReviewer` minimal stub (the `_MinimalReviewer` pattern, `test_github_reviewer.py:58`) with AsyncMock toolkits and a stubbed `_ask_llm_for_full_review` → service run → comment posted → chat notice rendered |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5406`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
