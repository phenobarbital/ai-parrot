# JiraSpecialist — Daily Standup Lanes

`JiraSpecialist` (`parrot/bots/jira_specialist.py`) runs the team's daily
standup over Telegram. There are **two independent lanes**; both read the same
developer roster and share the same Redis bookkeeping.

| Lane | Entry point | How the developer answers |
|---|---|---|
| Button-driven | `dispatch_daily_tickets()` | Inline keyboard — one tap picks today's ticket |
| HITL (conversational) | `dispatch_morning_standup()` / `dispatch_eod_standup()` | `ask_human` conversation in their private chat |

Both lanes end at `escalate_non_responders()`, which posts **one** list of
whoever stayed silent to the shared channel.

---

## The roster

The developers are resolved by `_standup_roster()`, in this order:

1. **`JIRA_DEVELOPERS`** — a list of dicts in the application's own
   `settings/settings.py`. It is a developers-only roster, so *every* entry is
   taken as-is. navconfig does not expose this list, so it is imported from the
   app settings module directly (guarded: a bare library install just gets an
   empty roster and falls through).
2. **`STANDUP_DEVELOPERS`** (navconfig) or **`JIRA_USERS`** (`parrot.conf`) —
   mixed rosters that also hold managers and QA, so only entries flagged
   `is_developer: true` count.

A roster entry looks like:

```python
JIRA_DEVELOPERS = [
    {
        "id": "35",                                  # roster id, used in Redis keys
        "name": "Jesus Lara",
        "username": "jlara@example.com",
        "jira_username": "jlara@example.com",
        "jira_account_id": "557058:5c136372-...",    # used in the morning JQL
        "telegram_chat_id": "286137732",             # private chat
        "manager_chat_id": "286137732",              # only used without a channel
    },
]
```

`jira_account_id` matters: the morning check-in builds its JQL with
`assignee = "<accountId>"` instead of `currentUser()`, and falls back to
`jira_username` when the entry has no account id.

Malformed entries are skipped with a warning — one bad row never takes the
whole fan-out down.

---

## HITL lane

```
SCHEDULER → dispatch_morning_standup()
    → for every developer, inside their own Telegram chat scope:
        → mark standup:dispatched:<date>:<id> in Redis
        → run the "Morning check-in" prompt section (private ask_human flow)
        → on success, mark standup:responded:<date>:<id>

SCHEDULER → dispatch_eod_standup()
    → same fan-out with the "End-of-day wrap" prompt section
      (collects done_today / plan_tomorrow / blockers, comments on Jira)
    → writes NO response bookkeeping: the two lanes share one
      standup:responded key per day, so EOD must not overwrite the
      morning answer

/standup  → standup_command()
    → resolves the caller from the live Telegram chat id and runs ONLY
      their morning standup. `/standup developer_id=35` targets someone else.
```

Developers are run concurrently and one failure never cancels the others; the
summary dict reports `developers`, `ok`, `errors` and the per-developer
`results`. Redis is bookkeeping only — an outage is logged and the standup
conversations still happen.

> **Cadence (temporary).** `dispatch_morning_standup` and
> `dispatch_eod_standup` are currently decorated with
> `@schedule(schedule_type=ScheduleType.INTERVAL, minutes=2)` so the lane can
> be exercised end-to-end. Swap both for `@schedule_daily_report` (timing from
> `{AGENT_ID}_DAILY_REPORT`, `HH:MM` UTC) once validated.

---

## Non-responder digest

`escalate_non_responders()` compares the `standup:dispatched:*` and
`standup:responded:*` keys for today, then:

1. nudges every silent developer in their **private** chat, and
2. posts **a single message** listing all of them to the shared channel —
   managers read it there instead of receiving one DM each.

The channel comes from `JIRA_TELEGRAM_PUBLIC_CHANNEL_ID`:

```bash
# Telegram channel/group id — negative for channels
JIRA_TELEGRAM_PUBLIC_CHANNEL_ID=-1001234567890
```

Resolution order is `manager_chat_id=` argument → the agent's
`public_channel_id` attribute → the env var. With **no** channel configured the
legacy behaviour is kept as a fallback: non-responders are grouped by
`manager_chat_id` and each manager gets their own list.

The returned summary carries `date`, `total_dispatched`, `responded`,
`non_responders`, `escalated_to`, `channel_id` and `messages_sent`. A developer
who was never dispatched to is never escalated, and when everybody answered
nothing is sent at all.

Message wording lives in the localized catalog
(`parrot/bots/jira_messages.py`, key `escalation`), so it follows the bot's
`language`.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `no developers configured` | Neither `JIRA_DEVELOPERS` nor an `is_developer`-flagged `STANDUP_DEVELOPERS` / `JIRA_USERS` entry was found. |
| Nobody is ever escalated | Only the lanes that write `standup:dispatched:*` feed the escalation — the EOD lane deliberately does not. |
| `N non-responder(s) but nowhere to escalate` | No channel **and** no `manager_chat_id` on the roster entries. Set `JIRA_TELEGRAM_PUBLIC_CHANNEL_ID`. |
| `/standup` answers "not in the standup roster" | The caller's chat id does not match any entry's `telegram_chat_id`. |
| `No wrapper attached` | `set_wrapper()` has not been called — the agent is not bound to a Telegram bot yet. |
