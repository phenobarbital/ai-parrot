# GitHub Reviewer Agent

An autonomous AI-Parrot agent that reviews GitHub pull requests against the
acceptance criteria of the linked Jira ticket, requests changes when the PR
deviates from the ticket, and alerts the team through Telegram.

> **Scope.** Today the agent only handles PR review; the `GitHubReviewer`
> name is intentionally generic so future revisions can add other code-review
> duties (security scans, style checks, release gating, etc.) without
> another rename.

The agent is shipped as `parrot.bots.github_reviewer.GitHubReviewer`
and follows the same pattern as `JiraSpecialist`: deployments subclass it
(one subclass per watched repository) and register the subclass with
`@register_agent`. Save the reference subclass below as
`agents/github_reviewer.py` in your deployment (`agents/` is gitignored
on purpose):

```python
"""Default GitHubReviewer subclass registered with the agent registry."""
from parrot.bots.github_reviewer import GitHubReviewer
from parrot.conf import (
    GITHUB_REVIEW_PUBLIC_CHANNEL_ID,
    GITHUB_REVIEW_REPOSITORY,
    GITHUB_REVIEW_STALE_AFTER_HOURS,
    GITHUB_REVIEW_TELEGRAM_CHAT_IDS,
    GITHUB_REVIEW_WEBHOOK_PUBLIC_URL,
    GITHUB_REVIEW_WEBHOOK_SECRET,
)
from parrot.registry import register_agent


@register_agent(name="github_reviewer", at_startup=True)
class DefaultGitHubReviewer(GitHubReviewer):
    """Default reviewer wired from ``parrot.conf`` env vars."""

    agent_id: str = "github_reviewer"

    def __init__(self, **kwargs):
        kwargs.setdefault(
            "repository",
            GITHUB_REVIEW_REPOSITORY or "phenobarbital/ai-parrot",
        )
        kwargs.setdefault("alert_chat_ids", GITHUB_REVIEW_TELEGRAM_CHAT_IDS)
        kwargs.setdefault("public_channel_id", GITHUB_REVIEW_PUBLIC_CHANNEL_ID)
        kwargs.setdefault("webhook_public_url", GITHUB_REVIEW_WEBHOOK_PUBLIC_URL)
        kwargs.setdefault("webhook_secret", GITHUB_REVIEW_WEBHOOK_SECRET)
        kwargs.setdefault("stale_after_hours", GITHUB_REVIEW_STALE_AFTER_HOURS)
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
                          ▼  target_id="github_reviewer"
              GitHubReviewer.handle_hook_event
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
GitHubReviewer.report_stale_pull_requests()
       │
       ├─ git_toolkit.list_pull_requests(state="open")
       └─ for each PR with age > stale_after_hours:
              bot.send_message(public_channel_id, formatted)
```

---

## Configuration

The agent reads its configuration from environment variables (via
`navconfig`). All variables are optional but most deployments will want to
set at least `GITHUB_TOKEN`, `GITHUB_REVIEW_REPOSITORY`,
`GITHUB_REVIEW_TELEGRAM_CHAT_IDS` and `GITHUB_REVIEW_PUBLIC_CHANNEL_ID`.

| Variable                                  | Description                                                                 |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `GITHUB_TOKEN`                            | PAT with `repo` scope; auto-subscription also needs hook write (`admin:repo_hook` classic / `repository_hooks=write` fine-grained) **and the admin role on the repo** |
| `GITHUB_REVIEW_REPOSITORY`             | Default `owner/name` watched by the bundled subclass                        |
| `GITHUB_REVIEW_TELEGRAM_CHAT_IDS`      | Comma-separated chat IDs alerted on discrepancies                           |
| `GITHUB_REVIEW_PUBLIC_CHANNEL_ID`      | Telegram chat/channel for the daily stale-PR summary                        |
| `GITHUB_REVIEW_WEBHOOK_PUBLIC_URL`     | Public HTTPS URL of `/api/v1/hooks/github` (enables auto-subscription)      |
| `GITHUB_REVIEW_WEBHOOK_SECRET`         | Shared secret used to sign and verify webhook deliveries                    |
| `GITHUB_REVIEW_STALE_AFTER_HOURS`      | Hours an open PR must be unattended before the daily report (default 24)   |
| `JIRA_INSTANCE` / `JIRA_USERNAME` / …    | Jira credentials (same vars consumed by `JiraSpecialist`)                  |
| `JIRA_ACCEPTANCE_CRITERIA_FIELD`          | Custom field id for acceptance criteria (default `customfield_10100`)       |
| `GITHUB_REVIEWER_DAILY_REPORT`         | Run-time of the daily stale-PR report, format `HH:MM` UTC (default `08:00`) |
| `GITHUB_REVIEW_WIKI_ENABLED`           | Opt in to codebase context from a local clone and wiki; default `false`     |
| `GITHUB_REVIEW_CACHE_DIR`              | Cache root; default `~/.cache/parrot/github-reviewer`                       |
| `GITHUB_REVIEW_CLONE_BRANCH`           | Branch to track; default is the remote's default `HEAD` branch              |
| `GITHUB_REVIEW_CLONE_DEPTH`            | Clone depth; default is full history                                        |
| `GITHUB_REVIEW_CACHE_MAX_BYTES`        | Soft cache cap, default 5 GiB, enforced by LRU eviction                     |
| `GITHUB_REVIEW_BUILD_TIMEOUT`          | Wiki build timeout in seconds; default `900`                                |
| `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS`    | Token budget of the injected context block; default `4000`                  |
| `GITHUB_REVIEW_WIKI_WAIT`              | Max seconds a delivery waits for the wiki refresh before reviewing without fresh context; default `120` |

`integrations_bots.yaml` exposes the agent over Telegram:

```yaml
agents:
  ReviewerBot:
    chatbot_id: github_reviewer
    welcome_message: "GitHub Reviewer is online."
```

The `GitHubWebhookHook` is added to your `HookManager` like any other hook:

```python
from parrot.core.hooks import GitHubWebhookHook
from parrot.core.hooks.models import GitHubWebhookConfig

hook = GitHubWebhookHook(GitHubWebhookConfig(
    url="/api/v1/hooks/github",
    secret_token=GITHUB_REVIEW_WEBHOOK_SECRET,
    target_type="agent",
    target_id="github_reviewer",
))
hook_manager.register(hook)
hook.setup_routes(app)
```

---

## Codebase context (local clone + wiki)

When `GITHUB_REVIEW_WIKI_ENABLED=true` the reviewer keeps a local clone of each
watched repository and a `wikitoolkit` graph built from it, and adds a
token-budgeted context block to the review question. It is off by default.

**Snapshot caveat.** The wiki describes the **base-branch snapshot**, not the
pull request: PR heads are not checked out. A symbol added by the PR can
therefore be absent from this context, and the block is labelled accordingly so
the model does not report it as nonexistent.

**Cache layout** (per repository slug `owner-repo`, lowercased, under
`GITHUB_REVIEW_CACHE_DIR`):

```
<cache>/repos/<slug>/        git clone (tracks the remote default branch unless
                             GITHUB_REVIEW_CLONE_BRANCH is set)
<cache>/planes/<slug>/       wiki plane, built with `wikitoolkit build
                             --storage-dir <plane>` (a run-scoped flag, never
                             persisted into project settings); builds are lean
<cache>/locks/<slug>.lock    cross-process lock (plus an in-process asyncio lock)
```

The reviewer's plane is always isolated from the ai-parrot wiki plane, and the
full wiki tools exposed to the model are confined to the cloned sources.
Private repositories use the same authentication as the rest of the toolkit
(GitHub App or token); the token is scrubbed from logs. The `git` and
`wikitoolkit` executables must be available locally.

**Recovery.** A cache entry whose origin URL or branch does not match is
re-cloned exactly once; a second failure degrades instead of looping. A marker
is written before each build; if a build was interrupted the marker stays in
`started` (incomplete) and the next run rebuilds with `--force`.

**Eviction.** The cache is trimmed by least-recently-used order down to
`GITHUB_REVIEW_CACHE_MAX_BYTES`. Locked entries and the entry being refreshed
are never evicted; a single entry larger than the cap is warned about rather
than thrashed. A full clone is roughly 620 MB and the plane roughly 538 MB, so
the 5 GiB default holds about four ai-parrot-sized repositories. Raise the cap
when watching more, or repositories are re-cloned on every rotation.

**Degradation.** Clone failure, build failure, build timeout
(`GITHUB_REVIEW_BUILD_TIMEOUT`), a missing `wikitoolkit` binary, or a plane
without a last-good marker never block a review: one log line is emitted and the
review falls back to the diff-only prompt.

A delivery waits at most `GITHUB_REVIEW_WIKI_WAIT` seconds for the refresh, which
overlaps the Jira and diff fetches. A refresh still running after that is not
cancelled: it is shared by later deliveries (one in-flight refresh per reviewer,
the warm-up task included) and finishes for the next review. While a review
runs, it holds a shared read lease on the repository entry, so a refresh or
eviction cannot change the clone or plane underneath it; if the lease cannot be
obtained, the prompt carries no wiki block (the wiki tools stay registered, a
known limitation). Private clones and pulls authenticate through the git
subprocess environment, so the token is never written to `.git/config`
(requires git 2.31 or newer).

## GitHub webhook setup

There are two ways to register the webhook on the repository:

1. **Automatic (recommended).** Set `GITHUB_REVIEW_WEBHOOK_PUBLIC_URL`
   and use a token that can write repository hooks. On startup
   `post_configure()` calls `GitToolkit.ensure_webhook()`. The call is
   idempotent: if a hook with the same URL already exists it is reused.
   Note that the permission is not enough on its own — GitHub requires the
   **admin** role on the repository for `/hooks`, and a fine-grained token
   never exceeds the role its owner holds.
2. **Manual.** Leave `GITHUB_REVIEW_WEBHOOK_PUBLIC_URL` unset (or use a
   token that cannot write hooks — the call falls back gracefully) and
   configure the webhook in GitHub UI:
   - Payload URL: `https://<your-host>/api/v1/hooks/github`
   - Content type: `application/json`
   - Secret: same value as `GITHUB_REVIEW_WEBHOOK_SECRET`
   - Events: select **Pull requests** only.

Only `pull_request` deliveries with action `opened`, `reopened` or
`synchronize` are processed; everything else returns 200 and is ignored.

---

## Public methods

### `handle_hook_event(event: HookEvent) -> dict | None`

Routes hook events emitted by `GitHubWebhookHook`. Ignores events for
repositories other than the one this instance watches (`self.repository`),
so a deployment that runs several `GitHubReviewer` subclasses against a
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
is `GITHUB_REVIEWER_DAILY_REPORT=09:30`.

### `GitToolkit.ensure_webhook(webhook_url, repository=None, secret=None, events=None) -> dict`

Public on the toolkit. Used by `post_configure` for auto-subscription but
also callable from your own scripts. Status values: `"created"`,
`"already_exists"`, `"no_permission"`, `"error"`.

Failure results (`no_permission`, `error`) also carry the HTTP context of
the refused call, so a caller can log the real cause instead of guessing:

| Key                   | Meaning                                                        |
| --------------------- | -------------------------------------------------------------- |
| `operation`           | `"list"` or `"create"` — which `/hooks` call failed            |
| `status_code`         | HTTP status returned by GitHub (`None` if no request was made)  |
| `api_message`         | GitHub's own `message` field, e.g. *Resource not accessible…*   |
| `required_permission` | The `x-accepted-github-permissions` header, e.g. `repository_hooks=write` |
| `message`             | Full raw error string (unchanged, always present)              |

---

## Watching multiple repositories

A single subclass watches one repository. To watch several, subclass once
per repo. Each subclass needs its own `agent_id` and registration name:

```python
@register_agent(name="github_reviewer_navigator", at_startup=True)
class NavigatorReviewer(GitHubReviewer):
    agent_id: str = "github_reviewer_navigator"

    def __init__(self, **kwargs):
        kwargs.setdefault("repository", "phenobarbital/navigator")
        kwargs.setdefault("jira_project", "NAV")
        kwargs.setdefault("alert_chat_ids", GITHUB_REVIEW_TELEGRAM_CHAT_IDS)
        kwargs.setdefault("public_channel_id", GITHUB_REVIEW_PUBLIC_CHANNEL_ID)
        super().__init__(**kwargs)
```

Wire each subclass to its own `GitHubWebhookHook` (e.g.
`/api/v1/hooks/github/navigator`) targeting the matching `agent_id`, or
share one endpoint and let the `repository` guard inside
`handle_hook_event` route events to the right instance.

---

## Troubleshooting

- **HTTP 401 from `/api/v1/hooks/github`**: signature mismatch. Check that
  `GITHUB_REVIEW_WEBHOOK_SECRET` matches the secret configured in the
  GitHub UI. The hook uses `X-Hub-Signature-256` (HMAC-SHA256).
- **`status="no_permission"` in startup logs**: GitHub refused `/hooks`.
  The log line now quotes the status, GitHub's own message and the
  `x-accepted-github-permissions` header, e.g. *HTTP 403; Resource not
  accessible by personal access token; endpoint wants
  `repository_hooks=write`*. Two distinct causes produce it:
  - **Missing permission** — grant hook write (classic `admin:repo_hook`,
    or fine-grained *Repository permissions → Webhooks: Read & Write*; the
    identically named *Organization permissions → Webhooks* does **not**
    count). On an org that reviews token grants, a permission added to an
    existing token stays *pending approval* while the already-approved ones
    keep working, which looks exactly like this.
  - **Missing role** — `/hooks` requires **admin** on the repository, and a
    fine-grained token cannot grant more than its owner holds. Check
    `GET /repos/<owner>/<repo>` → `permissions.admin`; if it is `false`, no
    token setting will fix it, so either raise the user's role or fall back
    to manual setup.
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
  `github_reviewer.report_stale_pull_requests`.

---

## Tool-Assisted Review

`GitHubReviewer` exposes three on-demand code-retrieval tools to the LLM so
it can pull additional repository context during a PR review when the diff
alone is insufficient.

The tools are registered automatically during `post_configure()` via
`_attach_toolkit(git_toolkit, "Git")`. If the LLM is confident in its verdict
from the diff alone it returns `PRReviewResult` directly without calling any
tools.

### Tools

- **`get_file_content_at_ref(path, ref, start_line?, end_line?)`** —
  full file body at a given commit, branch, or tag. Supports line slicing for
  large files via `start_line` / `end_line`. Results are SHA-keyed in a
  two-tier cache (in-process LRU + optional Redis) so repeated requests for
  the same ref within a session cost no extra HTTP calls.
- **`compare_pr_versions(pr_number, path)`** — base and head versions of a
  single file in the PR, both as full content. Use when the diff hunk is too
  small to see the full before/after of a refactored function or class.
- **`search_repo_code(query)`** — GitHub Code Search restricted to the PR's
  own repository on its default branch. Use when you suspect a changed symbol
  has callers or related code that are not shown in the diff. Note: rate-limited
  to 30 requests/minute; returns `error='rate_limited'` instead of raising when
  the quota is exceeded.

### Configuration

| Env var | Default | Purpose |
|---|---|---|
| `GITHUB_REVIEWER_MAX_TOOL_CALLS` | `5` | Hard cap on tool calls per review session |
| `GITHUB_REVIEWER_BLOB_CACHE_TTL` | `604800` | SHA-keyed blob cache TTL in seconds (7 days) |
| `REDIS_URL` | unset | Optional Redis URL for shared cross-process blob cache |

The `max_review_tool_calls` constructor kwarg takes priority over the env var:

```python
reviewer = MyReviewer(
    repository="owner/repo",
    max_review_tool_calls=10,   # overrides GITHUB_REVIEWER_MAX_TOOL_CALLS
)
```

Setting `max_review_tool_calls=0` reverts to the original one-shot review
behaviour (no tool calls attempted; `max_iterations=1` is passed to `ask()`).

### Cap-hit telemetry

When the LLM exhausts its tool-call budget the reviewer emits a single
`WARNING` log line:

```
GitHubReviewer: PR <repo>#<pr_number> hit tool-call cap (count=<N>, tools=<names>)
```

If this warning fires frequently in production, consider raising
`GITHUB_REVIEWER_MAX_TOOL_CALLS` (or the constructor kwarg). The cap exists
to bound LLM token cost and latency on every review.

---

## Weekly activity report

Every Monday at 09:00 UTC (configurable), the agent posts a contributor
activity digest to the same Telegram channel used for the daily stale-PR
report (`GITHUB_REVIEW_PUBLIC_CHANNEL_ID`).

The digest is produced by `report_weekly_activity()`, decorated with
`@schedule_weekly_report`.

### Schedule override

```bash
export PARROT_REVIEWER_WEEKLY_REPORT="MON 09:00"
```

Format is `DDD HH:MM` (UTC). Day abbreviations: `MON`, `TUE`, `WED`, `THU`,
`FRI`, `SAT`, `SUN`.

### Knobs

| Env var | Default | Notes |
|---|---|---|
| `GITHUB_REVIEW_SILENT_WEEKS_THRESHOLD` | `3` | Consecutive zero-commit weeks before a contributor is flagged silent |
| `GITHUB_REVIEW_USE_LLM_SUMMARY` | `false` | Re-phrase numbers as prose via the agent's LLM (templated output is always the source of truth; LLM failures fall back automatically) |
| `GITHUB_REVIEW_WEEKLY_LOOKBACK_WEEKS` | `4` | Reserved — not yet wired in v1; planned for future per-threshold window control |

### Sample output (templated)

```
Weekly activity — owner/repo
Period: 2026-05-10 → 2026-05-16

20 commits (▼ -26%)
2,446 added / 510 removed (▼ -38%)

Top contributors
1. alice — 12 commits, 1,834 / 421
2. bob — 8 commits, 612 / 89

Silent contributors
charlie — silent 3 weeks

Posted by the GitHubReviewer agent.
```

### Architecture note

```
APScheduler tick (DDD HH:MM UTC)
       │
       ▼
GitHubReviewer.report_weekly_activity()
       │
       ├─ git_toolkit.get_contributor_stats(repository)
       ├─ git_toolkit.get_code_frequency(repository)
       ├─ _build_weekly_summary(contributors, code_freq, ...)
       ├─ [optional] _llm_summarize_weekly(summary)  ← only if use_llm_summary=True
       └─ bot.send_message(public_channel_id, html, parse_mode="HTML")
```

### Privacy note

The report names individual contributors by their GitHub login. Operators
are responsible for informing contributors that their activity is being
aggregated and broadcast, and for ensuring that access to the destination
Telegram channel is appropriately restricted.
