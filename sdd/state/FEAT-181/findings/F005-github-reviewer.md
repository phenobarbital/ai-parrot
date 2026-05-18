---
id: F005
query_id: Q010
type: read
intent: GithubReviewer consumer that motivates this feature.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — GitHubReviewer uses legacy `system_prompt` + `ask()`; no repo-level context layer today

## Summary

`GitHubReviewer` (`parrot/bots/github_reviewer.py:222`) extends `Agent`
and currently passes a static `_SYSTEM_PROMPT` (lines 193-215) via
`kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)` (line 385) — i.e.
legacy path, not PromptBuilder. Each PR review composes a per-call user
question that splices Jira description + acceptance criteria + diff
(line 941-953) and calls `self.ask(question=..., structured_output=PRReviewResult)`
(line 956). There is NO `AGENT_CONTEXT.md`-like layer today: the agent
sees only the static system prompt + per-review question. Default model
is `GoogleModel.GEMINI_3_FLASH_PREVIEW` (line 269) — the provider with
the **highest** cache-minimum threshold. A second `_WEEKLY_LLM_SYSTEM_PROMPT`
(line 1472) is used for the weekly digest LLM summary via
`self.ask(question=..., system_prompt=self._WEEKLY_LLM_SYSTEM_PROMPT)`
(line 1508-1511).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 193-215
  symbol: `_SYSTEM_PROMPT`
  excerpt: |
    _SYSTEM_PROMPT = """\
    You are a strict but constructive Pull Request reviewer. For every review you
    receive a Jira ticket (description + acceptance criteria) and a GitHub pull
    request (title, body, diff). ...
    """

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 269
  symbol: model default
  excerpt: |
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 383-387
  symbol: system_prompt wiring
  excerpt: |
    kwargs.setdefault("injection_probability_threshold", 0.995)
    kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)
    super().__init__(**kwargs)

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 941-958
  symbol: per-review question assembly + `self.ask`
  excerpt: |
    question = (
        f"Review pull request {payload.get('repository')}#"
        f"{payload.get('pr_number')} against Jira ticket {ticket_key}.\n\n"
        ...
        f"Acceptance Criteria:\n{acceptance_criteria}\n\n"
        f"{header}\n{diff_block}\n\n"
        "Compare them and return a PRReviewResult JSON object."
    )
    response = await self.ask(question=question, structured_output=PRReviewResult)

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 1472-1511
  symbol: weekly summarizer with per-call `system_prompt=`
  excerpt: |
    _WEEKLY_LLM_SYSTEM_PROMPT = (
        "You write concise, factual weekly engineering activity reports..."
    )
    response = await self.ask(
        question=question,
        system_prompt=self._WEEKLY_LLM_SYSTEM_PROMPT,
    )

## Notes

The reviewer is the canonical consumer for the AGENT_CONTEXT.md
+ prompt-caching combo: same repo → same static context → many review
calls back-to-back. But Gemini-3-Flash's caching threshold (~4096+ tokens
minimum, with newer Flash variants reportedly requiring ≥32k) means a
short repo-context doc may simply not cache on the default model. The
feature must degrade gracefully rather than fail.
