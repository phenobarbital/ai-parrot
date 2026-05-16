# GitHub PR Reviewer Agent

An autonomous AI-Parrot agent that reviews GitHub pull requests against the
acceptance criteria of the linked Jira ticket, requests changes when the PR
deviates from the ticket, and alerts the team through Telegram.

The agent is shipped as `parrot.bots.github_pr_reviewer.GitHubPRReviewer`
and follows the same pattern as `JiraSpecialist`: deployments subclass it
(one subclass per watched repository) and register the subclass with
`@register_agent`. Save the reference subclass below as
`agents/github_pr_reviewer.py` in your deployment (`agents/` is gitignored
on purpose):

```python
"""Default GitHubPRReviewer subclass registered with the agent registry."""
from parrot.bots.github_pr_reviewer import GitHubPRReviewer
from parrot.conf import (
    GITHUB_PR_REVIEW_PUBLIC_CHANNEL_ID,
    GITHUB_PR_REVIEW_REPOSITORY,
    GITHUB_PR_REVIEW_STALE_AFTER_HOURS,
    GITHUB_PR_REVIEW_TELEGRAM_CHAT_IDS,
    GITHUB_PR_REVIEW_WEBHOOK_PUBLIC_URL,
    GITHUB_PR_REVIEW_WEBHOOK_SECRET,
)
from parrot.registry import register_agent


@register_agent(name="github_pr_reviewer", at_startup=True)
class DefaultGitHubPRReviewer(GitHubPRReviewer):
    """Default reviewer wired from ``parrot.conf`` env vars."""

    agent_id: str = "github_pr_reviewer"

    def __init__(self, **kwargs):
        kwargs.setdefault(
            "repository",
            GITHUB_PR_REVIEW_REPOSITORY or "phenobarbital/ai-parrot",
        )
        kwargs.setdefault("alert_chat_ids", GITHUB_PR_REVIEW_TELEGRAM_CHAT_IDS)
        kwargs.setdefault("public_channel_id", GITHUB_PR_REVIEW_PUBLIC_CHANNEL_ID)
        kwargs.setdefault("webhook_public_url", GITHUB_PR_REVIEW_WEBHOOK_PUBLIC_URL)
        kwargs.setdefault("webhook_secret", GITHUB_PR_REVIEW_WEBHOOK_SECRET)
        kwargs.setdefault("stale_after_hours", GITHUB_PR_REVIEW_STALE_AFTER_HOURS)
        super().__init__(**kwargs)
```

---

## Architecture

```
GitHub                                Parrot app (aiohttp)
─────                                 ─────────────────────
PR opened ──▶ POST /api/v1/hooks/github
                          │
                          ▼
              GitHubWebhookHook
                (HMAC verify,
                 classify event,
                 emit HookEvent)
                          │
                          ▼
                  HookManager.callback
                          │
                          ▼  target_id="github_pr_reviewer"
              GitHubPRReviewer.handle_hook_event
                          │
        ┌──────────────────┼─────────────────────────┐
        ▼                  ▼                         ▼
  jira_get_issue     get_pull_request_diff     submit_pr_review
  (description +     (Accept: ...v3.diff,       (event=REQUEST_CHANGES
   acceptance         truncated to 50 KB)        + Markdown body)
   criteria)               │                         │
        │                  │                         ▼
        └──────────┬───────┘                Telegram bot.send_message
                   ▼                           ∀ alert_chat_ids
        self.ask(prompt, structured_output=PRReviewResult)
```

A separate path runs daily, driven by `@schedule_daily_report`:

```
APScheduler tick (HH:MM UTC)
       │
       ▼
GitHubPRReviewer.report_stale_pull_requests()
       │
       ├─ git_toolkit.list_pull_requests(state="open")
       └─ for each PR with age > stale_after_hours:
              bot.send_message(public_channel_id, formatted)
```

---

## Configuration

The agent reads its configuration from environment variables (via
`navconfig`). All variables are optional but most deployments will want to
set at least `GITHUB_TOKEN`, `GITHUB_PR_REVIEW_REPOSITORY`,
`GITHUB_PR_REVIEW_TELEGRAM_CHAT_IDS` and `GITHUB_PR_REVIEW_PUBLIC_CHANNEL_ID`.

| Variable                                  | Description                                                                 |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `GITHUB_TOKEN`                            | PAT with `repo` scope (and `admin:repo_hook` if you want auto-subscription) |
| `GITHUB_PR_REVIEW_REPOSITORY`             | Default `owner/name` watched by the bundled subclass                        |
| `GITHUB_PR_REVIEW_TELEGRAM_CHAT_IDS`      | Comma-separated chat IDs alerted on discrepancies                           |
| `GITHUB_PR_REVIEW_PUBLIC_CHANNEL_ID`      | Telegram chat/channel for the daily stale-PR summary                        |
| `GITHUB_PR_REVIEW_WEBHOOK_PUBLIC_URL`     | Public HTTPS URL of `/api/v1/hooks/github` (enables auto-subscription)      |
| `GITHUB_PR_REVIEW_WEBHOOK_SECRET`         | Shared secret used to sign and verify webhook deliveries                    |
| `GITHUB_PR_REVIEW_STALE_AFTER_HOURS`      | Hours an open PR must be unattended before the daily report (default 24)   |
| `JIRA_INSTANCE` / `JIRA_USERNAME` / …    | Jira credentials (same vars consumed by `JiraSpecialist`)                  |
| `JIRA_ACCEPTANCE_CRITERIA_FIELD`          | Custom field id for acceptance criteria (default `customfield_10100`)       |
| `GITHUB_PR_REVIEWER_DAILY_REPORT`         | Run-time of the daily stale-PR report, format `HH:MM` UTC (default `08:00`) |

`integrations_bots.yaml` exposes the agent over Telegram:

```yaml
agents:
  PRReviewerBot:
    chatbot_id: github_pr_reviewer
    welcome_message: "GitHub PR Reviewer is online."
```

The `GitHubWebhookHook` is added to your `HookManager` like any other hook:

```python
from parrot.core.hooks import GitHubWebhookHook
from parrot.core.hooks.models import GitHubWebhookConfig

hook = GitHubWebhookHook(GitHubWebhookConfig(
    url="/api/v1/hooks/github",
    secret_token=GITHUB_PR_REVIEW_WEBHOOK_SECRET,
    target_type="agent",
    target_id="github_pr_reviewer",
))
hook_manager.register(hook)
hook.setup_routes(app)
```

---

## GitHub webhook setup

There are two ways to register the webhook on the repository:

1. **Automatic (recommended).** Set `GITHUB_PR_REVIEW_WEBHOOK_PUBLIC_URL`
   and use a PAT with `admin:repo_hook`. On startup `post_configure()`
   calls `GitToolkit.ensure_webhook()`. The call is idempotent: if a hook
   with the same URL already exists it is reused.
2. **Manual.** Leave `GITHUB_PR_REVIEW_WEBHOOK_PUBLIC_URL` unset (or use a
   PAT that lacks `admin:repo_hook` — the call falls back gracefully) and
   configure the webhook in GitHub UI:
   - Payload URL: `https://<your-host>/api/v1/hooks/github`
   - Content type: `application/json`
   - Secret: same value as `GITHUB_PR_REVIEW_WEBHOOK_SECRET`
   - Events: select **Pull requests** only.

Only `pull_request` deliveries with action `opened`, `reopened` or
`synchronize` are processed; everything else returns 200 and is ignored.

---

## Public methods

### `handle_hook_event(event: HookEvent) -> dict | None`

Routes hook events emitted by `GitHubWebhookHook`. Ignores events for
repositories other than the one this instance watches (`self.repository`),
so a deployment that runs several `GitHubPRReviewer` subclasses against a
single webhook endpoint is safe.

Invoked automatically by the orchestrator. Returns the same dict produced
by `review_pull_request`.

### `review_pull_request(payload: dict) -> dict`

The core review primitive. Useful for manual triggers and tests.

Steps:
1. Extract a `<JIRA_PROJECT>-\d+` key from `pr_body` + `pr_title`.
2. `jira_get_issue` → description + acceptance criteria.
3. `get_pull_request_diff` (truncated to `max_diff_bytes`).
4. `self.ask(prompt, structured_output=PRReviewResult)`.
5. If discrepancies are found:
   - `submit_pr_review(event="REQUEST_CHANGES", body=...)`
   - `_notify_telegram_alert` → send a Markdown alert to every
     `alert_chat_ids`.

Return values:

| `status`              | When it happens                                          |
| --------------------- | -------------------------------------------------------- |
| `"reviewed"`          | Review ran. See `approve`, `discrepancies`, `summary`.   |
| `"no_ticket"`         | PR did not reference a `<JIRA_PROJECT>-\d+` key.         |
| `"ticket_not_found"`  | Jira returned a non-`ok` envelope.                       |
| `"error"`             | Internal precondition failed (e.g. missing PR number).   |

### `report_stale_pull_requests() -> dict`

Decorated with `@schedule_daily_report`. Lists every open PR on
`self.repository`, computes the age from `created_at`, and announces
each PR older than `stale_after_hours` to `public_channel_id` via
Telegram. Returns counts:

```python
{
    "status": "ok",
    "repository": "owner/name",
    "open_count": 17,
    "stale_count": 4,
    "announced": 4,
    "stale": [...],
}
```

Override the run-time per deployment via the `<AGENT_ID>_DAILY_REPORT`
environment variable, format `HH:MM` (UTC). For the default subclass that
is `GITHUB_PR_REVIEWER_DAILY_REPORT=09:30`.

### `GitToolkit.ensure_webhook(webhook_url, repository=None, secret=None, events=None) -> dict`

Public on the toolkit. Used by `post_configure` for auto-subscription but
also callable from your own scripts. Status values: `"created"`,
`"already_exists"`, `"no_permission"`, `"error"`.

---

## Watching multiple repositories

A single subclass watches one repository. To watch several, subclass once
per repo. Each subclass needs its own `agent_id` and registration name:

```python
@register_agent(name="github_pr_reviewer_navigator", at_startup=True)
class NavigatorPRReviewer(GitHubPRReviewer):
    agent_id: str = "github_pr_reviewer_navigator"

    def __init__(self, **kwargs):
        kwargs.setdefault("repository", "phenobarbital/navigator")
        kwargs.setdefault("jira_project", "NAV")
        kwargs.setdefault("alert_chat_ids", GITHUB_PR_REVIEW_TELEGRAM_CHAT_IDS)
        kwargs.setdefault("public_channel_id", GITHUB_PR_REVIEW_PUBLIC_CHANNEL_ID)
        super().__init__(**kwargs)
```

Wire each subclass to its own `GitHubWebhookHook` (e.g.
`/api/v1/hooks/github/navigator`) targeting the matching `agent_id`, or
share one endpoint and let the `repository` guard inside
`handle_hook_event` route events to the right instance.

---

## Troubleshooting

- **HTTP 401 from `/api/v1/hooks/github`**: signature mismatch. Check that
  `GITHUB_PR_REVIEW_WEBHOOK_SECRET` matches the secret configured in the
  GitHub UI. The hook uses `X-Hub-Signature-256` (HMAC-SHA256).
- **`status="no_permission"` in startup logs**: the PAT lacks
  `admin:repo_hook`. Either upgrade the token or fall back to manual setup.
- **`status="no_ticket"`**: the PR body / title did not include a
  `<JIRA_PROJECT>-\d+` reference. Educate authors or change
  `jira_project=` for the agent.
- **`status="ticket_not_found"`**: the Jira instance returned no ticket.
  Verify `JIRA_INSTANCE`, the credentials, and that the bot user can read
  the target project.
- **Diff truncated**: PRs larger than `max_diff_bytes` (default 50 KB) are
  truncated. The LLM is instructed to acknowledge truncation. Bump the
  limit on the constructor if you need more context, but watch token cost.
- **No Telegram alerts**: confirm the bot is exposed in
  `integrations_bots.yaml`, that `set_wrapper()` was called by the
  `TelegramAgentWrapper`, and that `alert_chat_ids` is non-empty.
- **Daily report did not run**: check
  `scheduler_manager.register_bot_schedules(agent)` was called for this
  agent at startup, and inspect the scheduler logs for the job named
  `github_pr_reviewer.report_stale_pull_requests`.
