# FirefliesWikiAgent — autonomous meeting sync, wiki publication, and email digests

**Date**: 2026-08-23
**Status**: approved (design)
**Branch**: `feat-fireflies-wiki-agent`

## Problem

Fireflies.ai meeting transcripts currently reach an Obsidian vault through
`examples/agents/fireflies_obsidian_sync.py`, which is a manual, one-shot
script. Three things are missing:

1. The transcripts and their LLM summaries never reach the GraphIndex LLM
   Wiki, so meetings are not queryable alongside the rest of the knowledge
   graph.
2. Nobody is told what happened in yesterday's meetings unless they open
   the vault.
3. Recurring themes and unresolved issues across a week are never surfaced
   ahead of the Monday weekly meeting.

## Solution

A single registered agent, `FirefliesWikiAgent`, with three scheduled
methods. It subclasses the existing `FirefliesObsidianAgent` so all
transcript fetching, note authoring, and per-meeting LLM analysis is
inherited rather than reimplemented.

## Architecture

### Placement and identity

`agents/fireflies_wiki.py` — `class FirefliesWikiAgent(FirefliesObsidianAgent)`,
decorated `@register_agent(name="fireflies_wiki", at_startup=True)`.

Subclassing (rather than composing) inherits:

- `sync_fireflies_transcripts()` — Fireflies MCP fetch + Obsidian note write
- `summarize_pending_transcripts()` — per-note `## Analysis` generation
- `ObsidianToolkit` wiring and Fireflies MCP bootstrap in `configure()`
- the `YYYY-MM-DD-slug` note-title convention (`_make_note_title`)
- `NotificationMixin` (via `BasicAgent`) — `send_notification` / `send_email`

The subclass adds exactly: an LLM Wiki plane, an Anthropic Haiku client,
three scheduled methods, and their helpers.

> `agents/` is gitignored. The file must be committed with `git add -f`,
> the same situation as `agents/security_advisor.py`.

### LLM configuration

The agent pins **`claude-haiku-4-5`** via the project's `AbstractClient`
abstraction — never the Anthropic SDK directly (per `.agent/CONTEXT.md`:
"Never call provider SDKs directly — always go through AbstractClient").

Wiring is the standard `llm="anthropic:claude-haiku-4-5"` provider string
resolved by `LLMFactory` (`parrot/clients/factory.py` maps both `anthropic`
and `claude` to `AnthropicClient`), overridable via `FIREFLIES_WIKI_LLM`.

Rationale: all three jobs are semi-mechanical — condense already-written
Analysis blocks into bullets. Haiku 4.5 is $1/$5 per MTok against Opus 5's
$5/$25, with a 200K context window that comfortably holds a week of
meeting analyses.

Haiku 4.5 predates adaptive thinking and `output_config.effort`; both
parameters error on it. The agent therefore sends neither. If the model is
ever overridden to a 4.6+ model via `FIREFLIES_WIKI_LLM`, those parameters
remain unset — acceptable, since the defaults are sensible for this task
class.

> Note: `AnthropicClient._lightweight_model` is the dated snapshot
> `claude-haiku-4-5-20251001`. This design uses the undated alias
> `claude-haiku-4-5`, which resolves to the same family and is the
> canonical current ID.

### Wiki plane (built in `configure()`, best-effort)

```
configure()
  → super().configure(app)                    # Obsidian toolkit + Fireflies MCP
  → PageIndexToolkit(PageIndexLLMAdapter(LLMFactory.create(WIKI_MODEL)),
                     storage_dir=<storage>/pageindex)
  → await build_graph_memory_toolkit(<storage>/graph, agent_id=...)
  → LLMWikiToolkit(pi, gi, okf=None, WikiConfig(..., sync_graph=True))
```

`build_graph_memory_toolkit` (`parrot/knowledge/graphindex/factory.py`)
returns a write-enabled, persistence-backed `GraphIndexToolkit`. This is
what makes `ingest_obsidian_vault`'s Phase 1b (Obsidian `[[wikilink]]` →
GraphIndex nodes and edges) actually write; passing `None` for the graph
toolkit silently skips the graph bridge.

The PageIndex authoring plane needs its own LLM spec. It reads `WIKI_MODEL`
(the variable `wikitoolkit ingest` and `examples/dev_loop/server.py` already
use), falling back to `FIREFLIES_WIKI_LLM` when `WIKI_MODEL` is unset, so a
deployment that only configures this agent still gets a working authoring
plane rather than silently degrading to retrieval-only.

Every step is best-effort. On any failure `self._wiki` is set to `None`,
a warning is logged, and the agent still boots and still syncs to Obsidian.

### The three scheduled jobs

| Method | Trigger | Responsibility |
|---|---|---|
| `sync_meetings_to_wiki()` | daily 07:00 | sync → summarize → wiki ingest |
| `email_daily_meeting_digest()` | daily 08:00 | last-24h analyses → bullets → email |
| `email_weekly_insights()` | Mon 09:00 | last-7d analyses → insights → email |

#### 07:00 — `sync_meetings_to_wiki()`

Runs three steps, in this order:

1. `sync_fireflies_transcripts(limit=SYNC_LIMIT, skip_existing=True)`
2. `summarize_pending_transcripts(granularity="standard", limit=ANALYSIS_LIMIT)`
3. `self._wiki.ingest_obsidian_vault(wiki_name, vault_path, incremental=True,
   extract_entities=EXTRACT_ENTITIES)`

The order is load-bearing. Summarizing **before** the wiki ingest means the
page published to the wiki carries the transcript *and* its summary in a
single ingest pass, which is the stated requirement. It also guarantees the
08:00 digest finds its input already written into the vault.

`incremental=True` uses the source manifest's staleness check, so the job is
idempotent and self-healing: a run that failed yesterday is picked up today
without special-casing.

#### 08:00 — `email_daily_meeting_digest()`

1. `titles = self._notes_in_window(days=DAILY_WINDOW_DAYS)`
2. `analyses = await self._collect_analyses(titles)`
3. If empty → log, return `{"emailed": False, "reason": "no meetings"}`
4. LLM condenses the analyses into one consolidated bullet summary
5. `self._email(subject, body, DAILY_RECIPIENTS)`

#### Monday 09:00 — `email_weekly_insights()`

Same shape over a 7-day window, with a prompt framed for the weekly
meeting: recurring themes, decisions taken, unresolved/open issues, risks,
and follow-ups worth raising. Sent to `WEEKLY_RECIPIENTS`.

### Shared helpers

- `_notes_in_window(days) -> list[str]` — filters `_get_existing_meeting_titles()`
  by the `YYYY-MM-DD` title prefix. No LLM, no extra I/O. Malformed prefixes
  are ignored rather than raising.
- `_collect_analyses(titles) -> list[dict]` — reads each note via the
  Obsidian toolkit and partitions on `ANALYSIS_HEADING` (`## Analysis`),
  returning `{"note": title, "analysis": text}` for notes that have one.
- `_email(subject, body, recipients) -> bool` — wraps `send_notification`
  and **inspects the returned status**.
- `_ask_llm(prompt) -> str` — single-shot completion through the agent's
  configured client.

## Configuration

All values read via navconfig at module import time, because `@schedule`
evaluates its arguments at decoration time (the same constraint that makes
`agents/security_advisor.py` use module-level `_ADVISORY_HOUR`).

| Env var | Default | Meaning |
|---|---|---|
| `FIREFLIES_WIKI_TZ` | `UTC` | Timezone for all three triggers |
| `FIREFLIES_WIKI_SYNC_HOUR` / `_MINUTE` | `7` / `0` | Sync job time |
| `FIREFLIES_WIKI_DIGEST_HOUR` / `_MINUTE` | `8` / `0` | Daily digest time |
| `FIREFLIES_WIKI_WEEKLY_DAY` | `mon` | Weekly insights day |
| `FIREFLIES_WIKI_WEEKLY_HOUR` / `_MINUTE` | `9` / `0` | Weekly insights time |
| `FIREFLIES_WIKI_DAILY_RECIPIENTS` | — | Comma-separated addresses |
| `FIREFLIES_WIKI_WEEKLY_RECIPIENTS` | — | Comma-separated addresses |
| `FIREFLIES_WIKI_LLM` | `anthropic:claude-haiku-4-5` | Agent LLM |
| `FIREFLIES_WIKI_NAME` | `meetings` | Wiki name |
| `FIREFLIES_WIKI_STORAGE_DIR` | `~/.parrot/wikis/meetings` | Wiki storage root |
| `FIREFLIES_WIKI_SYNC_LIMIT` | `20` | Max transcripts fetched per run |
| `FIREFLIES_WIKI_ANALYSIS_LIMIT` | `20` | Max notes analyzed per run |
| `FIREFLIES_WIKI_DAILY_WINDOW_DAYS` | `1` | Daily digest lookback |
| `FIREFLIES_WIKI_EXTRACT_ENTITIES` | `false` | Phase-2 LLM entity extraction |

`ScheduleType.CRON` is used rather than `DAILY`/`WEEKLY` because
`AgentSchedulerManager._create_trigger` forwards `CronTrigger(**config)`
verbatim only for the `CRON` branch — it is the only branch that accepts a
`timezone` argument. The `DAILY` and `WEEKLY` branches construct
`CronTrigger(hour=..., minute=...)` with no timezone and would silently
inherit the scheduler's default.

## Error handling

- Every scheduled method returns a report dict and **never raises**. An
  APScheduler job that throws produces noise and no diagnosis.
- Wiki ingest failure degrades to a warning inside an otherwise-successful
  sync; the Obsidian vault is still updated.
- `_email` inspects the returned `status` rather than trusting a bare
  `await`. `send_notification` swallows provider errors and returns
  `{"status": "error", ...}` instead of raising — a bare await therefore
  always appears to succeed. This is the trap already documented in
  `agents/security_advisor.py::_email`.
- An empty window sends no email at all (logged), rather than mailing an
  empty bullet list.

## Testing

`tests/test_fireflies_wiki_agent.py`, mirroring `tests/test_security_advisor.py`.
pytest-asyncio, no network, no real LLM.

- `_notes_in_window` boundary correctness — inclusive start, malformed
  prefixes ignored, notes outside the window excluded
- `_collect_analyses` extracts only the Analysis block and tolerates notes
  that have none
- 07:00 job calls sync → summarize → ingest **in that order** (ordering
  assertion, not just call counts)
- wiki is `None` → sync still succeeds, ingest reported as skipped
- daily digest: empty window sends nothing; populated window calls
  `send_notification` with the daily recipients
- weekly insights: uses the 7-day window and the weekly recipients
- `_email` returns `False` when the provider reports `{"status": "error"}`
- decorator metadata: all three methods carry `_schedule_config` with the
  expected hour / minute / day_of_week / timezone

## Deliverables

- `agents/fireflies_wiki.py` — the agent (committed with `git add -f`)
- `tests/test_fireflies_wiki_agent.py` — unit tests
- `examples/agents/fireflies_wiki_agent.py` — manual one-shot runner for
  each of the three methods, alongside the existing
  `examples/agents/fireflies_obsidian_sync.py`

## Out of scope

- Changing `FirefliesObsidianAgent` itself
- Replacing the existing `examples/agents/fireflies_obsidian_sync.py`
- Slack/Teams delivery (email only, per the request)
- A dashboard or A2UI rendering of the digests
