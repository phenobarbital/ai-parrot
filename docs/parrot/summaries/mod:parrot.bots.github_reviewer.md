---
type: Wiki Summary
title: parrot.bots.github_reviewer
id: mod:parrot.bots.github_reviewer
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GitHub Code Reviewer agent.
relates_to:
- concept: class:parrot.bots.github_reviewer.Discrepancy
  rel: defines
- concept: class:parrot.bots.github_reviewer.GitHubReviewer
  rel: defines
- concept: class:parrot.bots.github_reviewer.PRReviewResult
  rel: defines
- concept: class:parrot.bots.github_reviewer.WeeklyActivitySummary
  rel: defines
- concept: class:parrot.bots.github_reviewer.WeeklyLLMSummarizationError
  rel: defines
- concept: mod:parrot.bots
  rel: references
- concept: mod:parrot.core.hooks.github_webhook
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.scheduler
  rel: references
- concept: mod:parrot_tools.gittoolkit
  rel: references
- concept: mod:parrot_tools.jiratoolkit
  rel: references
---

# `parrot.bots.github_reviewer`

GitHub Code Reviewer agent.

Reviews GitHub artefacts against the acceptance criteria of the linked
Jira ticket. Today the agent only handles pull requests; future revisions
are expected to layer additional code-review duties on top of the same
class. Designed to be subclassed per repository (mirrors the
:class:`~parrot.bots.jira_specialist.JiraSpecialist` pattern).

Workflow:

* On ``github.pr_opened`` / ``pr_reopened`` / ``pr_synchronize`` events
  emitted by :class:`~parrot.core.hooks.github_webhook.GitHubWebhookHook`,
  :meth:`handle_hook_event` is invoked by the orchestrator. It extracts the
  ``NAV-xxx`` (or any configured project prefix) key from the PR body /
  title, pulls the ticket from Jira, fetches the PR diff, asks the LLM for a
  structured comparison and either submits a ``REQUEST_CHANGES`` review
  with Telegram alerts (when discrepancies are found) or posts an
  ``APPROVE`` review (when all acceptance criteria are satisfied).
  Re-deliveries with the same ``head_sha`` are deduplicated in-memory so
  pushing multiple commits to a still-failing PR does not produce a
  storm of reviews and alerts.
* :meth:`report_stale_pull_requests` is decorated with
  :func:`schedule_daily_report` so it runs once a day and reports every open
  PR older than 24h to a public Telegram channel.

Authentication, toolkit wiring and the LLM model selection follow the same
pattern as :class:`JiraSpecialist` so a deployment that already runs
JiraSpecialist needs no extra plumbing beyond a new ``@register_agent``
subclass per watched repository.

## Classes

- **`Discrepancy(BaseModel)`** — Single mismatch between the PR and the Jira acceptance criteria.
- **`PRReviewResult(BaseModel)`** — LLM-produced summary of a PR review.
- **`WeeklyActivitySummary(BaseModel)`** — Structured input to the templated/LLM renderer for the weekly digest.
- **`WeeklyLLMSummarizationError(RuntimeError)`** — Raised when the LLM summarizer fails; caller falls back to templated output.
- **`GitHubReviewer(Agent)`** — Reviews GitHub PRs against linked Jira ticket acceptance criteria.
