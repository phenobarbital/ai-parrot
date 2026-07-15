---
type: Wiki Entity
title: GitHubReviewer
id: class:parrot.bots.github_reviewer.GitHubReviewer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Reviews GitHub PRs against linked Jira ticket acceptance criteria.
relates_to:
- concept: class:parrot.bots.agent.Agent
  rel: extends
---

# GitHubReviewer

Defined in [`parrot.bots.github_reviewer`](../summaries/mod:parrot.bots.github_reviewer.md).

```python
class GitHubReviewer(Agent)
```

Reviews GitHub PRs against linked Jira ticket acceptance criteria.

Like :class:`JiraSpecialist`, this class is abstract by convention:
deployments should subclass it (one subclass per repository) and apply
``@register_agent`` on the subclass.

Args:
    repository: Target GitHub repository in ``"owner/name"`` format.
    jira_project: Jira project key whose tickets the PRs reference
        (default ``"NAV"``). Used to build the regex that extracts the
        ticket key from the PR body / title.
    alert_chat_ids: Telegram chat IDs that should receive a private
        alert when a discrepancy is found.
    public_channel_id: Telegram chat / channel ID that receives the
        daily summary of stale (>24h) open PRs.
    webhook_public_url: Public HTTPS URL of the GitHub webhook
        endpoint (e.g. ``https://parrot.example.com/api/v1/hooks/github``).
        When set, :meth:`post_configure` calls
        :meth:`GitToolkit.ensure_webhook` to register it.
    webhook_secret: Shared secret GitHub will use to sign deliveries.
        Required for HMAC verification on the receiving end.
    stale_after_hours: How long an open PR must be unattended before
        being included in :meth:`report_stale_pull_requests`.
        Defaults to ``24``.
    max_diff_bytes: How much of the diff to feed the LLM. Larger diffs
        are truncated; the prompt instructs the LLM to acknowledge it.
    max_ticket_bytes: Per-field clamp applied to the Jira description
        and acceptance criteria text before they are spliced into the
        LLM prompt. Prevents one oversized ticket from blowing the
        context window. Defaults to ``20_000``.

Notes:
    Jira **per-user OAuth2 3LO** is unsupported by this agent: webhook
    deliveries arrive without a caller identity, so the resolver has
    no user whose tokens it could load. When ``JIRA_AUTH_TYPE`` is
    ``oauth2_3lo`` the agent falls back to service-account
    ``basic_auth`` using ``JIRA_USERNAME`` + ``JIRA_API_TOKEN``; if
    those are missing, ``self.jira_toolkit`` stays ``None`` and the
    reviewer disables itself with a clear error in the logs.

    Reviews are de-duplicated **in-memory** by ``(repo, pr_number,
    head_sha)``. Pushing eight commits to a still-failing PR will not
    produce eight reviews or eight Telegram alerts; the dedup cache
    resets when the process restarts.

    Note on prompt caching: This agent enables ``prompt_caching=True`` by
    default (FEAT-181). Prompt caching activates provider-side caching of
    the static system prompt prefix. The default model
    (``GEMINI_3_FLASH_PREVIEW``) requires ≥4096 tokens in the cacheable
    prefix for caching to take effect. If the system prompt + agent context
    document are below this threshold, caching silently skips with a
    ``PromptCacheSkippedEvent``. For guaranteed caching, use an Anthropic
    or OpenAI model.

## Methods

- `def setup_webhook_route(cls, app: Any, *, url: str='/api/v1/hooks/github', secret: Optional[str]=None, name: str='github_review_hook') -> GitHubWebhookHook` — Register the aiohttp route that receives GitHub webhook deliveries.
- `def set_wrapper(self, wrapper) -> None` — Called by :class:`TelegramAgentWrapper` so the agent can push
- `async def post_configure(self) -> None` — Wire :class:`GitToolkit` and :class:`JiraToolkit` once ``self.app``
- `async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]` — Route :class:`HookEvent` instances from :class:`GitHubWebhookHook`.
- `async def review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]` — Run a single PR review and return a summary dict.
- `async def report_stale_pull_requests(self) -> Dict[str, Any]` — Scan open PRs on the configured repo and announce stale ones.
- `async def report_weekly_activity(self) -> Dict[str, Any]` — Compose and send the weekly contributor-activity digest.
