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
    GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID,
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
        kwargs.setdefault("management_chat_id", GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID)
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

A separate path runs daily — two reports on `@schedule_daily_report`, plus
the Jira ticket summary on its own timezone-aware cron:

```
APScheduler tick (HH:MM UTC)
       │
       ▼
GitHubReviewer.report_stale_pull_requests()
       │
       ├─ git_toolkit.list_pull_requests(state="open")
       ├─ collect every PR with age > stale_after_hours
       └─ bot.send_message(public_channel_id, one digest with all of them)

GitHubReviewer.today_pr()
       │
       ├─ git_toolkit.list_pull_requests(state="open")
       ├─ collect every still-open PR created < 24h ago
       └─ nothing collected → silent; otherwise one digest message
          to management_chat_id

GitHubReviewer.report_jira_tickets()   (own cron: 10:00 America/New_York)
       │
       ├─ jira_toolkit.jira_search_issues("project = <JIRA> AND updated >= -14d")
       ├─ bucket per assignee by statusCategory (open / in progress / closed)
       ├─ derive the 24h column from each ticket's `updated` (no 2nd call)
       └─ no activity → silent; otherwise one monospace table message
          to management_chat_id

GitHubReviewer.report_monthly_jira_tickets()  (own cron: 1st, 10:00 NY)
       │                                      /monthly_jira_tickets = same,
       │                                      answered in the asking chat
       ├─ the same search over 30 days, totals per assignee
       ├─ top 9 wedges + "Others (n)" → altair pie → PNG
       └─ no activity → silent; otherwise send_photo (table as caption)
          to management_chat_id
```

---

## Configuration

The agent reads its configuration from environment variables (via
`navconfig`). All variables are optional but most deployments will want to
set at least `GITHUB_TOKEN`, `GITHUB_REVIEW_REPOSITORY`,
`GITHUB_REVIEW_TELEGRAM_CHAT_IDS`, `GITHUB_REVIEW_PUBLIC_CHANNEL_ID` and
`GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID`.

| Variable                                  | Description                                                                 |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `GITHUB_TOKEN`                            | PAT with `repo` scope; auto-subscription also needs hook write (`admin:repo_hook` classic / `repository_hooks=write` fine-grained) **and the admin role on the repo** |
| `GITHUB_REVIEW_REPOSITORY`             | Default `owner/name` watched by the bundled subclass                        |
| `GITHUB_REVIEW_TELEGRAM_CHAT_IDS`      | Comma-separated chat IDs alerted on discrepancies                           |
| `GITHUB_REVIEW_PUBLIC_CHANNEL_ID`      | Telegram chat/channel for the daily stale-PR summary                        |
| `GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID`   | Telegram chat/channel for the management reports — `today_pr()`, the weekly activity digest, `report_jira_tickets()` and the monthly ticket pie; falls back to the public channel when unset |
| `GITHUB_REVIEW_WEBHOOK_PUBLIC_URL`     | Public HTTPS URL of `/api/v1/hooks/github` (enables auto-subscription)      |
| `GITHUB_REVIEW_WEBHOOK_SECRET`         | Shared secret used to sign and verify webhook deliveries                    |
| `GITHUB_REVIEW_STALE_AFTER_HOURS`      | Hours an open PR must be unattended before the daily report (default 24)   |
| `GITHUB_REVIEW_MIN_CHECK_PASS_RATIO`   | Share of a PR's **completed** CI checks that must be green for `/review_pr` to approve it (default `0.8`) |
| `GITHUB_REVIEW_REQUIRE_CHECKS`         | Refuse a PR whose head commit declares **no** checks at all, instead of only warning (default `false`) |
| `GITHUB_REVIEW_GOOGLE_API_KEY`         | Google credential the reviewer bills its LLM traffic to; unset falls back to `GOOGLE_API_KEY` |
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

### Its own Google API key

The reviewer runs on Gemini (`gemini-3.7-flash` by default) and would
otherwise bill the process-wide `GOOGLE_API_KEY`, which makes its usage
impossible to meter or rotate apart from every other agent in the same
process. Set `GITHUB_REVIEW_GOOGLE_API_KEY` to give it a key of its own:

```bash
GITHUB_REVIEW_GOOGLE_API_KEY=AIza...reviewer
```

Resolution order, applied once in `__init__` (before `configure()` builds the
client):

1. the constructor's `google_api_key=` argument;
2. `GITHUB_REVIEW_GOOGLE_API_KEY`;
3. nothing is injected — the Google client resolves `GOOGLE_API_KEY` itself,
   exactly as it did before this knob existed.

The key is injected into the agent's `llm_kwargs` as `api_key`, into a **new**
dict so it never leaks into a caller-supplied or persisted configuration, and
its value is never logged. Three cases leave the agent untouched: an LLM that
is not a Google provider (logged as a warning — the key is configured but
cannot apply), a caller that already passed `api_key`, `credentials_file`,
`credentials` or `vertexai`, and `vertexai=true` deployments, which
authenticate through service-account credentials rather than an API key.

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

The reviewer's plane is always isolated from the ai-parrot wiki plane.
Private repositories use the same authentication as the rest of the toolkit
(GitHub App or token); the token is scrubbed from logs. The `git` and
`wikitoolkit` executables must be available locally.

**Read-only tool surface.** Once a build completes, `_attach_wiki_toolkits()`
registers exactly eight tools and nothing else:

| Tool | Purpose |
|---|---|
| `code_symbol_lookup(query)` | Find a function/class/method by name or qualname |
| `code_outline(path)` | List a file's symbols before reading it whole |
| `code_blast_radius(symbol)` | Every symbol that transitively calls/extends/implements it |
| `wiki_search_compact(wiki_name, query)` | Token-budgeted page stubs for a question |
| `wiki_read_page(wiki_name, page_id)` | One page in full |
| `wiki_expand(wiki_name, page_id, rel?)` | The page's graph neighbourhood |
| `wiki_find_related(wiki_name, page_id, depth?)` | Multi-hop neighbours |
| `wiki_browse_pages(wiki_name, category?)` | Stubs by category |

`LLMWikiToolkit` publishes about twenty-five more coroutines — ingest,
create/update/delete page, create/delete wiki, remember, reingest, export,
rebuild index. All of them are withheld through `exclude_tools`, computed by
introspection (`_read_only_excludes()`) so a write tool added by a future
release is excluded by default rather than silently exposed. Note that
`confine_sources=True` is **not** this guarantee: it only forces
`ingest_source` to take an http(s) URL.

The same helper narrows `CodeStructuralToolkit`, whose three tools are already
read-only, for the same future-proofing reason.

**Prompt.** The system prompt describes those eight tools — including the
`wiki_name` every `wiki_*` call takes and the `file:` / `dir:` / `sym:` page-id
formats — only once they are actually registered, so a reviewer whose clone or
build failed is never told about tools it does not have. This section is
separate from the per-review `=== Codebase context ===` block, which carries
pre-searched graph results under `GITHUB_REVIEW_WIKI_CONTEXT_TOKENS`.

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

### `review_pr(target: str) -> str` — Telegram command `/review_pr`

On-demand strict gate, exposed as a Telegram command (not a schedule):

```
/review_pr https://github.com/owner/repo/pull/123
/review_pr owner/repo#123
/review_pr 123                  # the configured repository
```

Declared with `parse_mode="raw"`, so a pasted URL arrives intact — keyword
parsing would mangle it. The reply goes to whoever asked; the consequences
below land on GitHub and Telegram.

It runs the same review pipeline as `review_pull_request` (ticket →
acceptance criteria → diff → wiki-assisted LLM comparison) and then adds a
**CI gate**, which `review_pull_request` does not have:

| Gate      | Passes when                                                                             |
| --------- | --------------------------------------------------------------------------------------- |
| Jira      | the review approved the PR and raised no `blocker`/`major` discrepancy                   |
| Tests     | the declared checks are green, or at least `GITHUB_REVIEW_MIN_CHECK_PASS_RATIO` of the **completed** ones are |

Checks are read from both GitHub APIs — the Checks API (`check-runs`, where
GitHub Actions reports) and the legacy Commit Status API — because a repo may
use either. Checks still running are counted but excluded from the ratio, so a
half-finished pipeline does not read as half-failing.

Three outcomes:

| `status`      | What happens on GitHub                                                      |
| ------------- | --------------------------------------------------------------------------- |
| `"approved"`  | `APPROVE` review. Nothing else is touched.                                  |
| `"deferred"`  | `COMMENT` review explaining the wait. **The PR is left exactly as it is** — no draft, no notification. Happens when checks are still running, or when the CI status could not be read at all (an outage or a missing token scope is not test evidence, and not the developer's fault). |
| `"blocked"`   | The PR is **converted to a draft** (GraphQL `convertPullRequestToDraft`, the only API that can), a comment explains every blocking reason, a `REQUEST_CHANGES` review is submitted, and the assignee is notified. |

A blocked PR produces three notifications, each independent so one failure
cannot swallow the others:

1. **Private DM** to the Jira assignee — resolved against `conf.JIRA_USERS` by
   e-mail (`jira_username` / `username`), Jira `accountId`
   (`jira_account_id` / `id`) or display name (`name`). No roster match → no
   DM, logged at INFO.
2. **Public channel** (`GITHUB_REVIEW_PUBLIC_CHANNEL_ID`), mentioning the
   assignee. The mention is a real `@username` when the roster entry carries
   `telegram_username`, otherwise a `tg://user?id=…` link — which notifies the
   person in a group exactly like an `@mention` and is the only way to mention
   someone whose Telegram username is unknown.
3. The PR comment itself `@`-pings the PR's **GitHub** author.

`"no_ticket"`, `"ticket_not_found"` and `"error"` behave as in
`review_pull_request`; a PR that is not open is refused before any review runs.

The webhook path deliberately keeps its gentler behaviour —
`review_pull_request` never drafts a PR — so the two do not share
orchestration, only helpers. A drafted PR is cleared by fixing the reasons,
pushing, and marking it ready for review (or by running `/review_pr` again).

**Permissions**: converting to draft needs the same `pull_requests: write` the
reviewer already uses to submit reviews. Reading CI needs **two independent**
permissions, because the two APIs are separate:

| API | Fine-grained PAT permission | Classic PAT |
| --- | --------------------------- | ----------- |
| `check-runs` (GitHub Actions and most CI apps) | **Checks** → Read-only | `repo` |
| `commits/{sha}/status` (Travis, Jenkins, custom scripts) | **Commit statuses** → Read-only | `repo` |

A 403/404 on one of them does **not** discard the other: the denial is listed
in `denied`, explained in `reason` (naming the missing permission), and the
verdict only becomes "unknown" when the evidence really is. Three cases:

- **One API denied, the other has checks** → the verdict proceeds on the
  partial picture, with a non-blocking warning saying part of it is missing.
- **One API denied and nothing else visible** → `deferred`. Zero visible checks
  behind a denial is *not* "this repo has no CI": the evidence may exist and
  simply be invisible, so the PR is never approved and never drafted on it.
  `GITHUB_REVIEW_REQUIRE_CHECKS` does not turn this into a blocker either — a
  missing token scope is not the developer's fault.
- **Both denied** → `deferred`, same reasoning.

A 500 (an outage, not a permission answer) still raises and is reported as
"CI status could not be read".

So a fine-grained PAT without **Checks** on an Actions-only repository defers
every verdict, and the PR comment names the exact permission to grant. That is
the designed signal, not a silent pass.

### `report_stale_pull_requests() -> dict`

Decorated with `@schedule_daily_report`. Lists every open PR on
`self.repository`, computes the age from `created_at`, and announces
every PR older than `stale_after_hours` to `public_channel_id` as a
**single** Telegram digest message (numbered list, one line per PR).
The digest is split into as few messages as still fit only when it
would exceed Telegram's 4096-character limit, in which case each part
carries its own header and a `(part n/m)` marker. Returns counts:

```python
{
    "status": "ok",
    "repository": "owner/name",
    "open_count": 17,
    "stale_count": 4,
    "announced": 4,       # stale PRs covered by a successful send
    "messages_sent": 1,   # Telegram messages it took
    "stale": [...],
}
```

Override the run-time per deployment via the `<AGENT_ID>_DAILY_REPORT`
environment variable, format `HH:MM` (UTC). For the default subclass that
is `GITHUB_REVIEWER_DAILY_REPORT=09:30`.

### `today_pr(window_hours: int | None = None) -> dict`

Also decorated with `@schedule_daily_report`, so it fires at the same
`<AGENT_ID>_DAILY_REPORT` time as the stale-PR report, as a separate
APScheduler job (`auto_<bot>_today_pr`).

Lists **open** PRs only (`state="open"`, double-checked per payload so a
closed or merged PR can never slip in) and keeps those created less than
`window_hours` ago — 24h by default. A PR opened and merged the same day
is therefore *not* reported: the digest is a review queue, not an
activity log. The survivors go out to the **management channel**
(`management_chat_id` — `GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID`) as a
**single** Telegram digest opening with `Review Today's Pull Requests`.
Like the stale digest it only splits when it would exceed Telegram's
4096-character limit.

**When no open PR was created in the window — or the repo has no PRs at
all — the method terminates silently**: no Telegram message,
`today_count: 0`, and an INFO log line.

```python
{
    "status": "ok",
    "repository": "owner/name",
    "window_hours": 24,
    "today_count": 3,
    "announced": 3,       # PRs covered by a successful send
    "messages_sent": 1,
    "today": [...],       # number/title/html_url/user/age_hours/state ("open")
}
```

### `report_jira_tickets(recent_hours=None, window_days=None) -> dict`

The Jira-side counterpart of `report_stale_pull_requests()`, over the same
`jira_project` the reviewer already resolves PR tickets against. One JQL
search — `project = <JIRA_PROJECT> AND updated >= -{window_days}d` — is
bucketed per assignee into **open / in progress / closed** and reported in
**two columns**: the last `recent_hours` (24h by default) and the last
`window_days` (14 days by default). The short column is derived locally from
each ticket's `updated` stamp, so the whole report costs a single Jira
round-trip.

Buckets come from Jira's `status.statusCategory.key`
(`new` / `indeterminate` / `done`), not from status names, so a workflow that
renamed "In Progress" to "Doing" still reports it as in progress. Jira Server
instances that omit the category fall back to matching the status name, and an
unrecognised status counts as open — a ticket is never dropped from the digest.

Scope is **activity, not backlog**: a ticket nobody touched inside
`window_days` appears in neither column.

The digest is one Telegram message to the **management channel**
(`management_chat_id` — `GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID`), with a
monospace `<pre>` table:

```
Jira tickets by assignee on NAV
8 tickets with activity in the last 14d
O = open · P = in progress · C = closed

                 last 24h      last 14d
Assignee          O   P   C     O   P   C
-----------------------------------------
Jesus Lara        1   1   1     1   1   3
Carolina Marti…   1   0   0     1   0   1
Unassigned        1   0   0     1   0   0
TOTAL             3   1   1     3   1   4
```

Rows are sorted by long-window volume; the name column is clamped so the table
stays aligned. A project with enough assignees to exceed Telegram's
4096-character limit is split into as few messages as still fit, each with its
own header and `(part n/m)` marker — the `TOTAL` row rides on the last part
only. **When no ticket was touched in the window the method terminates
silently**, like `today_pr()`.

```python
{
    "status": "ok",
    "project": "NAV",
    "jql": "project = NAV AND updated >= -14d ORDER BY updated DESC",
    "recent_hours": 24,
    "window_days": 14,
    "ticket_count": 8,
    "assignees": [
        {
            "assignee": "Jesus Lara",
            "recent": {"open": 1, "in_progress": 1, "closed": 1, "total": 3},
            "window": {"open": 1, "in_progress": 1, "closed": 3, "total": 5},
        },
        # ... one row per assignee, sorted by the long-window total
    ],
    "totals": {"recent": {...}, "window": {...}},
    "announced": 3,       # assignee rows covered by a successful send
    "messages_sent": 1,
}
```

Scheduled **daily at 10:00 `America/New_York`** with
`@schedule(schedule_type=ScheduleType.CRON, hour=10, minute=0,
timezone="America/New_York")`, so it does **not** read
`<AGENT_ID>_DAILY_REPORT` and does not share the stale-PR tick. The timezone
is a zone name, not a fixed offset, so the job tracks DST by itself: 14:00 UTC
while New York is on EDT, 15:00 UTC on EST. `ScheduleType.DAILY` could not
express this — it builds a `CronTrigger` with no timezone, which can only fire
on the scheduler's own (UTC) clock. Change the hour in
`_TICKET_REPORT_HOUR` / `_TICKET_REPORT_TIMEZONE` (module level in
`github_reviewer.py`) to move it.

Without a working `jira_toolkit` it returns `{"status": "error", "reason":
"jira_toolkit not configured"}` and sends nothing.

### `report_monthly_jira_tickets(window_days=None) -> dict`

The same JQL and bucketing as `report_jira_tickets()`, over **30 days**
instead of 14, delivered as a **pie chart of each assignee's share** of the
month's ticket activity plus the ranking behind it.

Wedges come from each assignee's long-window total, biggest first; the tail
past `_TICKET_PIE_MAX_SLICES` (9) is folded into a single `Others (n)` wedge,
because a pie with forty slivers reads as a colour wheel rather than a report.
Assignees with no ticket in the window are dropped. Scope is **activity, not
backlog**, exactly as in the daily digest, and a month with no activity exits
silently.

The PNG is rendered by `parrot_tools.chart.generate_chart("pie", …,
output_format="png")` (altair), which needs the optional **`vl-convert-python`**
dependency (`ai-parrot-tools[charts]`). Without it the chart tool writes a
Vega-Lite JSON spec, which Telegram cannot display, so the report degrades to
the text table alone — a missing chart never costs the numbers.

Delivery goes to the **management channel** (`management_chat_id` —
`GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID`). The table rides as the photo's caption
when it fits Telegram's 1024-character cap, so the channel shows one item
instead of two; otherwise it follows as its own message. If the photo fails to
send, the digest still goes out on its own.

```
Jira tickets by assignee — last 30 days on NAV
41 tickets with activity, 4 assignee(s)

Ana Pérez              18  43.9%
Bob Smith              12  29.3%
Carla Nuñez             7  17.1%
Unassigned              4   9.8%
--------------------------------
TOTAL                  41 100.0%
```

```python
{
    "status": "ok",
    "project": "NAV",
    "window_days": 30,
    "ticket_count": 41,
    "wedges": 4,                     # slices drawn ("Others" counts as one)
    "chart": "chart_c84d26f0.png",   # None when PNG export was unavailable
    "messages_sent": 1,
}
```

Scheduled **monthly, on the 1st at 10:00 `America/New_York`** with
`@schedule(schedule_type=ScheduleType.CRON, day=1, hour=10, minute=0,
timezone="America/New_York")` — the same timezone-aware cron as the daily
ticket digest, and for the same reason: there is no monthly report type, and a
report-marked schedule would have its config re-resolved from
`<AGENT_ID>_DAILY_REPORT` and fire on the scheduler's UTC clock. Move it with
`_TICKET_MONTH_REPORT_DAY` / `_TICKET_REPORT_HOUR` / `_TICKET_REPORT_TIMEZONE`.

### `monthly_jira_tickets(window_days=None) -> ChartReply`

The on-demand twin of the report above, exposed to Telegram as
**`/monthly_jira_tickets`** (`@telegram_command`, keyword parsing — so
`/monthly_jira_tickets window_days=60` works; Telegram passes arguments as
strings and the value is coerced, falling back to 30 when unusable). The
wrapper discovers it at bot startup and publishes it in the command menu; no
extra configuration is needed.

It **sends nothing itself**. It returns a `ChartReply` — `output` (the ranking
text) and `charts` (`[{"path", "title", "chart_type", "format"}]`) — which is
duck-typed to what `parrot.integrations.parser.parse_response()` reads off an
`AIMessage`. The channel wrapper does the delivery: Telegram as a photo via
`bot.send_photo`, MS Teams as a card image. That is why the method never needs
to know which chat asked, and why the same reply works on any channel.

Its text is **Markdown-fenced on purpose**: the wrapper runs it through
Markdown→HTML, and the fence makes that pass escape the assignee names, so a
display name like `A & <b>B</b>` cannot reach Telegram as broken entities.
(The scheduled report talks to the Bot API directly, so it escapes into a
`<pre>` block itself.)

Jira failures come back as a one-line notice in `output`, not an exception.

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
        kwargs.setdefault("management_chat_id", GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID)
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
  agent at startup, and inspect the scheduler logs for the jobs named
  `github_reviewer.report_stale_pull_requests` and
  `github_reviewer.today_pr` (both daily, same `HH:MM`).
  `github_reviewer.report_jira_tickets` is a separate cron job and ignores
  that env var — it fires at 10:00 `America/New_York`.
- **`today_pr()` sent nothing**: that is its documented behaviour when no
  *open* PR was created inside the window (a PR opened and already merged
  does not count) — look for the INFO line *"no open PR created on … in
  the last 24h; staying silent"*.
- **`report_jira_tickets()` sent nothing**: either no ticket was touched
  inside the window (INFO line *"no … ticket touched in the last 14d;
  staying silent"*) or `jira_toolkit` is `None` — the latter returns
  `{"status": "error", "reason": "jira_toolkit not configured"}` and is
  logged at startup by `_build_jira_toolkit()`.

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
activity digest to the management channel
(`GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID`, falling back to
`GITHUB_REVIEW_PUBLIC_CHANNEL_ID` when that is not set) — not to the public
channel that gets the stale-PR nag.

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
| `GITHUB_REVIEW_STATS_RETRY_DELAY` | `900` | Seconds to wait before re-running the report when GitHub's stats cache is still cold (see below) |
| `GITHUB_REVIEW_STATS_RETRY_MAX` | `3` | How many deferred re-runs to attempt before leaving it to the next scheduled run |

### Cold stats cache (`202 Accepted`)

GitHub computes `/stats/*` lazily. The first request for a repository whose
cache is cold returns `202 Accepted` and only *starts* the computation, which
on a large repository takes minutes — longer than the toolkit's in-call 202
budget (`_get_stats_with_polling`, 7 attempts over ~63s). `/stats/contributors`
usually warms in seconds while `/stats/code_frequency` lags well behind it, so
a partial 202 is the normal case, not an edge case.

When that budget runs out the toolkit raises `StatsNotReadyError` (a
`GitToolkitError` subclass, so existing handlers still catch it) and
`report_weekly_activity()` **defers instead of failing**:

- it logs a warning *without* a traceback — a stack trace here would describe
  documented GitHub behaviour, not a defect;
- it returns `status="stats_pending"` with `retry_scheduled`, `retry_in` and
  `attempt`, and posts **nothing** to Telegram;
- it arms a single deferred re-run `GITHUB_REVIEW_STATS_RETRY_DELAY` seconds
  later (never two at once), up to `GITHUB_REVIEW_STATS_RETRY_MAX` times. The
  attempt that timed out is what warms GitHub's cache, so the deferred run
  normally gets `200`.

A completed run resets the budget, and `shutdown()` cancels a pending deferral
so it never outlives the agent.

**Partial digest once the deferrals are spent.** The two stats calls are
gathered with `return_exceptions=True`, so a pending `code_frequency` no longer
discards contributor stats that already arrived. When the deferral budget is
exhausted and the contributor slices are usable, the digest goes out anyway:

- `code_frequency` feeds exactly one figure — the week-over-week **line** delta.
  The commits delta is summed from the contributor slices, so it stays real.
- `WeeklyActivitySummary.code_freq_available` is then `False`, the line delta
  renders as `n/a` instead of `▲ new` (its `prev_total_*` zeros are *unknown*,
  not measured), both the templated and the LLM output carry a "Partial data"
  notice, and the result dict reports `partial: true`.
- Pending **contributor** stats never degrade — they carry the whole digest, so
  that case still defers and publishes nothing.
- A non-202 failure of either call is still `status="error"` with its traceback.

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
       │     └─ StatsNotReadyError (persistent 202) → _defer_weekly_report()
       │            → status="stats_pending", re-run armed, nothing sent
       ├─ _build_weekly_summary(contributors, code_freq, ...)
       ├─ [optional] _llm_summarize_weekly(summary)  ← only if use_llm_summary=True
       └─ bot.send_message(management_chat_id, html, parse_mode="HTML")
```

### Privacy note

The report names individual contributors by their GitHub login. Operators
are responsible for informing contributors that their activity is being
aggregated and broadcast, and for ensuring that access to the destination
Telegram channel is appropriately restricted.
