---
type: Wiki Overview
title: 'TASK-1222: GithubReviewer tool-calling loop with iteration cap'
id: doc:sdd-tasks-completed-task-1222-reviewer-tool-calling-loop-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 6. Switches
relates_to:
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1222: GithubReviewer tool-calling loop with iteration cap

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1219, TASK-1220, TASK-1221
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. Switches
`GithubReviewer._ask_llm_for_review` from a one-shot
`self.ask(..., structured_output=PRReviewResult)` call to a bounded
tool-calling ReAct loop. The three new `GitToolkit` tools are already
wired up by `_attach_toolkit` (no change needed there) — the loop in
this task is what lets the LLM actually call them.

---

## Scope

- Add `max_review_tool_calls: int = 5` kwarg to
  `GitHubReviewer.__init__` and store as `self.max_review_tool_calls`.
  Also read `GITHUB_REVIEWER_MAX_TOOL_CALLS` from navconfig as a default
  override (kwarg > env > 5).
- Rewrite `_ask_llm_for_review` to use the agent's tool-calling path
  with `max_iterations=self.max_review_tool_calls + 1`. The +1 ensures
  the final pass (after tool exhaustion) can still emit the
  `PRReviewResult` JSON.
- After the loop, if the LLM consumed the full budget without producing
  a structured response, log a `WARNING` line:
  ```
  GitHubReviewer: PR <repo>#<pr_number> hit tool-call cap
  (count=<N>, tools=<names>)
  ```
- Extend the module-level `_SYSTEM_PROMPT` constant in
  `github_reviewer.py` with a short **Tool Use Guide** section: one
  paragraph per tool describing when to call it and when NOT to.
- Preserve byte-identical behavior for PRs where the LLM emits
  `PRReviewResult` without any tool calls (no-regression criterion).
- Extend reviewer test suite with:
  - `test_review_no_tool_calls_unchanged_behavior`
  - `test_review_with_tool_calls_within_cap`
  - `test_review_cap_hit_logs_warning`
  - `test_attach_toolkit_registers_new_tools` (verifies that
    `_attach_toolkit(git_toolkit, ...)` results in
    `self.tools` containing entries for the 3 new tool names).

**NOT in scope**:
- Adding new tools to `GitToolkit` (TASKs 1219-1221).
- Integration tests against real GitHub (TASK-1223).
- `docs/github-reviewer.md` updates (TASK-1223).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | New kwarg, rewritten `_ask_llm_for_review`, extended `_SYSTEM_PROMPT` |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | 4 new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in github_reviewer.py at module top:
from navconfig import config             # used at github_reviewer.py:420
from parrot_tools.gittoolkit import GitToolkit
# (verify exact import path in current file — may be slightly different;
#  if so, mirror what's already there)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):                                        # line 239
    def __init__(self, repository: str, *,                          # line 384
                 jira_project: str = "NAV",
                 alert_chat_ids: Optional[List[ChatId]] = None,
                 # ...other kwargs...
                 max_diff_bytes: int = 50_000,
                 max_ticket_bytes: int = 20_000,
                 # ...
                 **kwargs: Any) -> None:
        kwargs.setdefault("injection_probability_threshold", 0.995)
        kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)          # line 402
        super().__init__(**kwargs)
        # add: self.max_review_tool_calls = int(
        #         max_review_tool_calls
        #         if max_review_tool_calls is not None
        #         else config.get("GITHUB_REVIEWER_MAX_TOOL_CALLS",
        #                         fallback=5)
        #      )

    def _attach_toolkit(self, toolkit, name: str) -> None:          # line 517
        # ALREADY iterates tools = self.tool_manager.register_toolkit(toolkit)
        # and extends self.tools — no change needed for the 3 new tools to
        # become visible to the LLM.

    async def _ask_llm_for_review(                                  # line 989
        self, *, payload, ticket_key, ticket,
        diff_text, diff_truncated, diff_available,
    ) -> PRReviewResult:
        # Currently: response = await self.ask(question=question,
        #                                       structured_output=PRReviewResult)
        # New: must allow tool calls during the conversation but still
        # ultimately return a PRReviewResult.
```

```python
# Inspect Agent's tool-calling API in parrot/bots/agent.py before writing:
# The agent's `ask` method already supports tools when tools are attached.
# Confirm whether there is a `max_iterations` kwarg on `ask` or whether
# it's a class attribute. If neither, set self.max_iterations before the
# call and restore after.
```

### Does NOT Exist

- ~~`GitHubReviewer.run_react`~~ / ~~`GitHubReviewer.tool_loop`~~ — no
  such helper. Tool-calling lives on the base `Agent` via `self.ask(...)`.
- ~~`PRReviewResult.tools_used`~~ — not a field; the count and names
  come from the agent's tool-call telemetry. If the base `Agent` does
  not expose a tool-call history, capture call counts via a thin
  wrapper around the tool methods or via the LLM client's `tool_use`
  blocks.
- ~~`config.set(...)`~~ — navconfig is read-only at runtime.

---

## Implementation Notes

### Pattern to Follow

```python
async def _ask_llm_for_review(self, *, payload, ticket_key, ticket,
                              diff_text, diff_truncated, diff_available
                              ) -> PRReviewResult:
    # Build `question` exactly as today.
    # Then:
    previous_max = getattr(self, "max_iterations", None)
    self.max_iterations = self.max_review_tool_calls + 1
    try:
        response = await self.ask(
            question=question,
            structured_output=PRReviewResult,
        )
    finally:
        if previous_max is not None:
            self.max_iterations = previous_max

    # Detect cap-hit using the agent's tool-call telemetry (TBD by
    # implementer — check parrot/bots/agent.py for the exact attribute).
    tool_count = ...  # from agent telemetry
    tool_names = ...  # from agent telemetry
    if tool_count >= self.max_review_tool_calls:
        self.logger.warning(
            "GitHubReviewer: PR %s#%s hit tool-call cap (count=%d, tools=%s)",
            payload.get("repository"), payload.get("pr_number"),
            tool_count, tool_names,
        )
    # then return the structured response as today
```

The exact way to read tool-call telemetry depends on the base `Agent`
class. The implementer must `read` `packages/ai-parrot/src/parrot/bots/agent.py`
first and pick the cleanest path (likely an attribute like
`response.tool_calls` or `self.last_tool_call_count`). If no such
attribute exists, add a minimal counter inside the reviewer (intercept
tool calls via a `BaseHook` if the framework supports it, otherwise
count via the response's `messages` log).

### `_SYSTEM_PROMPT` Tool Use Guide section (add to the constant)

```
## Tool Use Guide

When reviewing the PR diff, you have three tools to pull additional
context from the repository. Use them sparingly — the cap is 5 calls
per review.

- `get_file_content_at_ref(path, ref, start_line?, end_line?)` —
  fetch the full body of a file at a given commit, branch, or tag.
  Use when the diff hunk shows a small change to a function whose
  full body or class context is needed to judge whether the change
  is correct. Prefer `start_line`/`end_line` slicing on large files.

- `compare_pr_versions(pr_number, path)` — fetch both the base and
  head versions of a single file in the PR. Use when the diff hunk
  is too small to see the full before/after of a refactored function
  or class.

- `search_repo_code(query)` — search the PR's repository for a
  string or symbol on the default branch only. Use when you suspect
  a change has callers or related code elsewhere that the diff does
  not show. Note: this only indexes the default branch and is
  rate-limited.

If you are confident in your verdict from the diff alone, do not call
any tools — return the PRReviewResult directly.
```

### Key Constraints

- The no-regression criterion (`test_review_no_tool_calls_unchanged_behavior`)
  is the most important property. Any change that risks altering the
  output for tool-free reviews must be rejected.
- Cap-hit log MUST be `WARNING` (not `ERROR`, not `INFO`).
- The kwarg name is exactly `max_review_tool_calls`.

---

## Acceptance Criteria

- [ ] `GitHubReviewer.__init__` accepts `max_review_tool_calls: int = 5`
  with env-var override.
- [ ] `test_review_no_tool_calls_unchanged_behavior` passes — identical
  output to today's behavior on a tool-free LLM response.
- [ ] `test_review_with_tool_calls_within_cap` passes.
- [ ] `test_review_cap_hit_logs_warning` passes — `caplog` captures a
  `WARNING` line containing `pr_number`, `count=`, and `tools=`.
- [ ] `test_attach_toolkit_registers_new_tools` passes.
- [ ] No regression in existing `test_github_reviewer.py` tests.
- [ ] `_SYSTEM_PROMPT` ends with the Tool Use Guide section above.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  passes.

---

## Test Specification

```python
import logging
import pytest

@pytest.mark.asyncio
async def test_review_no_tool_calls_unchanged_behavior(reviewer, monkeypatch):
    """When the LLM emits PRReviewResult with no tool calls, the review
    output is identical to today's structured-output path."""
    # Patch self.ask to return a canned PRReviewResult with no tool_calls.
    # Run review_pull_request and assert outcome matches fixture.
    ...

@pytest.mark.asyncio
async def test_review_cap_hit_logs_warning(reviewer, caplog):
    """When the LLM exhausts the tool-call budget, a WARNING is logged."""
    caplog.set_level(logging.WARNING)
    # Patch self.ask to simulate 5 tool calls + final structured response.
    await reviewer.review_pull_request(fixture_payload)
    assert any("hit tool-call cap" in r.message for r in caplog.records)
```

---

## Agent Instructions

1. Verify TASK-1219, TASK-1220, TASK-1221 are completed.
2. `read packages/ai-parrot/src/parrot/bots/agent.py` to choose the
   correct tool-call telemetry path — DO NOT guess.
3. Update `_SYSTEM_PROMPT`, `__init__`, and `_ask_llm_for_review`.
4. Run reviewer tests + ruff.
5. Update per-spec index status to `done`.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-18
**Notes**:
- Extended `_SYSTEM_PROMPT` with Tool Use Guide section covering all 3 new tools.
- Added `max_review_tool_calls: Optional[int] = None` kwarg to `__init__`, reading `GITHUB_REVIEWER_MAX_TOOL_CALLS` from navconfig (fallback=5).
- Modified `_ask_llm_for_review` to pass `max_iterations=self.max_review_tool_calls + 1` to `self.ask()`.
- Cap-hit detection reads `getattr(response, "tool_calls", None)` and emits WARNING log when `count >= max_review_tool_calls`.
- Added 4 new tests in `TestReviewToolCallingLoop` — all pass.
- Fixed pre-existing ruff F841 (`sorted_weeks` unused var).
- 4 pre-existing failures in `TestLLMSummarizeWeekly` remain — not introduced by this task.

**Deviations from spec**: none
