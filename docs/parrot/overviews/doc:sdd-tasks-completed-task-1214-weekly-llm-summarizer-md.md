---
type: Wiki Overview
title: 'TASK-1214: Implement optional `_llm_summarize_weekly` with safe fallback'
id: doc:sdd-tasks-completed-task-1214-weekly-llm-summarizer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When `self.use_llm_summary is True`, the orchestrator (TASK-1215) calls
---

# TASK-1214: Implement optional `_llm_summarize_weekly` with safe fallback

**Feature**: FEAT-180 — GitHub Repository Weekly Activity Report
**Spec**: `sdd/specs/github-repo-weekly-activity-report.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1212
**Assigned-to**: unassigned

---

## Context

When `self.use_llm_summary is True`, the orchestrator (TASK-1215) calls
this method to produce prose rather than the templated body. The LLM
receives only the structured `WeeklyActivitySummary` — never raw
GitHub data — so it cannot make up new numbers; it can only rephrase
the ones in the summary. Implements spec §3 Module 5.

A failure in the LLM path MUST NOT skip the weekly report. The
fallback is the templated output from TASK-1213; the caller (TASK-1215)
handles the fallback decision based on this method's return value.

---

## Scope

- Add `_llm_summarize_weekly(summary: WeeklyActivitySummary) -> str` on
  `GitHubReviewer`. Build a short, structured prompt from the
  `WeeklyActivitySummary` and call `self.ask(question=...)`.
- Use a tight system prompt biased toward concise reporting (3-5 short
  paragraphs max). Recommend including the JSON dump of the summary in
  the prompt — keeps the LLM grounded.
- Catch any exception from `self.ask(...)` and re-raise as
  `WeeklyLLMSummarizationError` (a new local exception class) so the
  orchestrator can fall back cleanly without swallowing real bugs.
- Do NOT escape HTML inside the LLM output — the orchestrator decides
  whether to send it raw or templated.

**NOT in scope**:

- The fallback decision logic — that lives in TASK-1215.
- Persisting LLM outputs.
- Variable temperature / sampling tuning beyond defaults.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Add `WeeklyLLMSummarizationError` exception + `_llm_summarize_weekly`. |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Add tests with a stub `ask` method. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at top of github_reviewer.py:
import json
from pydantic import BaseModel
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py
# Agent base class provides the LLM entry point:

class GitHubReviewer(Agent):
    async def ask(                   # inherited from Agent / AbstractBot
        self,
        question: str,
        *,
        structured_output: Optional[type] = None,
        **kwargs: Any,
    ) -> Any:
        """Returns either a response wrapper (with .output) or the value directly."""
```

The existing `_ask_llm_for_review` at line ~623 calls `self.ask(...)`
with `structured_output=PRReviewResult`. Use that as the I/O reference
— but do NOT use `structured_output` here; we want free-form prose.

### Does NOT Exist

- ~~`self.llm.invoke(...)`~~ — agents call through `self.ask`, not the
  raw client.
- ~~`Agent.summarize_text` / `Agent.run_with_prompt`~~ — no such
  shorthand; build the prompt yourself and pass to `ask`.
- ~~`temperature=` kwarg on `self.ask`~~ — verify before using. The
  default behaviour of `self.ask` is sufficient for this task.

---

## Implementation Notes

### Pattern to Follow

```python
class WeeklyLLMSummarizationError(RuntimeError):
    """Raised when the LLM summarizer fails; caller falls back to templated."""


_WEEKLY_LLM_SYSTEM_PROMPT = """\
You write concise, factual weekly engineering activity reports for a
software team. Given a structured JSON summary of last week's GitHub
activity, output a short English digest (3-5 short paragraphs total,
~150 words max). Lead with totals, highlight 1-2 notable contributors,
and call out anyone who has gone silent. Do not invent numbers; only
use values present in the input JSON. Do not include HTML tags or
markdown bullets. Plain prose only.
"""


async def _llm_summarize_weekly(
    self,
    summary: WeeklyActivitySummary,
) -> str:
    """Build a prose digest via the agent's LLM. Raises on any failure."""
    payload = summary.model_dump(mode="json")
    question = (
        "Summarize this week's GitHub activity. Output prose only.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )
    try:
        response = await self.ask(
            question=question,
            system_prompt_override=_WEEKLY_LLM_SYSTEM_PROMPT,
        )
    except Exception as exc:  # noqa: BLE001
        raise WeeklyLLMSummarizationError(
            f"LLM weekly summarization failed: {exc}"
        ) from exc

    output = getattr(response, "output", response)
    if isinstance(output, str):
        return output.strip()
    return str(output).strip()
```

**Note**: `system_prompt_override` is the kwarg name expected by
`Agent.ask` — verify against the actual signature before relying on it.
If the kwarg differs (`system_prompt`, `system`, `override_system`),
adapt to the real signature found in the codebase. If no override is
supported, embed the instructions inside the `question` itself.

### Key Constraints

- **Never crash silently**: on any exception, raise
  `WeeklyLLMSummarizationError`. The caller catches it and falls back.
- **No I/O beyond `self.ask`**: no Telegram, no logging at error level
  inside this method (the caller logs the fallback).
- **Plain prose** in the system prompt — don't ask for markdown or
  HTML; Telegram will render plain text fine inside `parse_mode="HTML"`
  as long as no forbidden tags appear, but we keep it simple.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:623` —
  `_ask_llm_for_review` is the I/O pattern to mirror (sans
  structured_output).

---

## Acceptance Criteria

- [ ] `WeeklyLLMSummarizationError(RuntimeError)` is defined.
- [ ] `_llm_summarize_weekly` exists and returns a `str`.
- [ ] Any exception from `self.ask(...)` is re-raised as
      `WeeklyLLMSummarizationError`.
- [ ] The prompt includes the summary serialized as JSON.
- [ ] Verified against the actual `Agent.ask` signature (see Note).
- [ ] Unit tests cover: success path returns LLM string; `self.ask`
      raising → `WeeklyLLMSummarizationError`; non-string output
      coerced to str.
- [ ] No regression in existing tests.

---

## Test Specification

```python
# tests/bots/test_github_reviewer.py — appended

class TestLLMSummarizeWeekly:
    def test_success_returns_llm_string(self):
        r = _MinimalReviewer()
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly

        async def fake_ask(*, question, **kwargs):
            class _Resp: ...
            resp = _Resp()
            resp.output = "Alice led with 12 commits..."
            return resp
        r.ask = fake_ask

        summary = self._summary()  # reuse fixture from TASK-1213 tests
        out = asyncio.run(r._llm_summarize_weekly(summary))
        assert "Alice" in out

    def test_raises_wrapped_error_on_failure(self):
        r = _MinimalReviewer()
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly

        async def fake_ask(**kwargs):
            raise RuntimeError("LLM down")
        r.ask = fake_ask

        with pytest.raises(WeeklyLLMSummarizationError, match="LLM down"):
            asyncio.run(r._llm_summarize_weekly(self._summary()))

    def test_coerces_non_string_output(self):
        # Stub returning a dict-shaped output is normalized via str()
        ...
```

---

## Agent Instructions

1. Read spec §3 Module 5, §7 Risks (LLM cost).
2. Dependencies: TASK-1212 done.
3. Verify the `Agent.ask` actual signature for `system_prompt_override`
   (or whatever kwarg is supported); adjust the implementation if it
   differs.
4. Update index → in-progress.
5. Implement + test.
6. Move file → completed, update index → done.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-18
**Notes**: Added _WEEKLY_LLM_SYSTEM_PROMPT as a module-level constant (not a class attribute)
so that methods bound to test stubs work correctly. Added _llm_summarize_weekly async method
that calls self.ask() with the system prompt and raises WeeklyLLMSummarizationError on failure.
Added _wrap_llm_prose_in_html_envelope helper. All 4 tests in TestLLMSummarizeWeekly pass.

**Deviations from spec**: _WEEKLY_LLM_SYSTEM_PROMPT placed at module level rather than as a
class attribute for testability — functionally equivalent.
