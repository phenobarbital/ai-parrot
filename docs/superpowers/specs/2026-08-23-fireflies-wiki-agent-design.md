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

### Meeting registry (FEAT-472)

`sync_fireflies_transcripts` (inherited from `FirefliesObsidianAgent`) no
longer dedupes meetings by note title. Identity is the immutable Fireflies
transcript id, stored as `external_id = "fireflies:<id>"` on the shared
wiki `sources` row (`parrot.knowledge.wiki.sources.SourceCollectionManager`
— see its class docstring for the general `"<source>:<id>"` convention any
future external-source ingest, e.g. Jira or audio notes, should follow).
All meeting-specific state (transcript/summary fingerprints, analysis
status + fingerprint, `wiki_ingested_at`, last error) lives in that row's
`doc_metadata["fireflies"]` JSON block.

`parrot.agents.meeting_registry.MeetingRegistry` is the facade over the
manager:

- `classify(item, fetch=..., fetch_summary=..., force_refetch=...)` →
  `create` | `skip` | `revise`. `skip` is cheap (no transcript fetch) when
  the listing's title/date/duration are unchanged and the row was synced
  within `FIREFLIES_RECHECK_DAYS`; otherwise the transcript is fetched and
  fingerprinted (SHA-256 of the normalised text — the Fireflies summary is
  fingerprinted separately and never affects this decision).
- `revise` never creates a second file for a known id: the body is
  rebuilt from the fresh transcript and the note is updated in place
  (`update_note(preserve_frontmatter=True)` for the body, then a
  read-merge-rewrite for the `title`/`participants`/`synced_at`
  frontmatter fields), analysis is reset to `pending`.
- `repair_path(...)` runs ahead of every create/revise: if the row's note
  file no longer exists, the meetings folder is scanned by frontmatter
  for the id; found → moved back to the canonical
  `{meetings_folder}/{YYYY-MM-DD-slug}.md` path when that path is free,
  else the registry is updated to the found path only; not found → the
  item falls through to `create`.
- `backfill_from_vault(...)` runs once, inside `configure()`, only when
  the registry has no `fireflies:*` rows yet (a pre-FEAT-472 vault):
  every note's frontmatter is scanned, one row seeded per id
  (`fingerprint=None` — nothing was fetched from Fireflies, so the next
  sync always re-checks once), and `merge_duplicates(...)` collapses any
  id with more than one note (keeps the analysed note, else the newest by
  mtime; moves it to the canonical path when free; deletes the rest;
  never deletes a note whose frontmatter failed to parse).
- With the registry unavailable (construction or a later manager call
  raised), every verb degrades to a neutral value and the sync/analysis
  loops fall back to the pre-FEAT-472 title-based path for that run —
  never raises.

`summarize_pending_transcripts` sources its candidates from
`registry.pending_analysis()` instead of scanning the folder for notes
missing `## Analysis`, and calls `mark_analyzed(fireflies_id, fingerprint)`
/ `mark_analysis_failed(fireflies_id, error)` afterward.

`sync_meetings_to_wiki` gained a fourth step, after a successful wiki
ingest: `stamped = await self.registry.mark_wiki_ingested()`, stamping
`wiki_ingested_at` on every up-to-date fireflies row and closing the
lifecycle (synced → analysed → wiki-ingested). Skipped when there is no
wiki plane, the ingest itself did not run, or the registry is
unavailable.

An on-demand Telegram command complements the 07:00 schedule:

```
/sync force_refetch=true|false limit=<n>
```

`force_refetch` bypasses the cheap-skip path (case-insensitive
`true`/`1`/`yes`; anything else is `False`). `limit` is parsed as an int;
empty or unparsable falls back to `FIREFLIES_WIKI_SYNC_LIMIT`. The reply
is one line:

```
✅ synced N · revised R · skipped S · analysed A · wiki: ok/skipped [· errors N]
```

`sync_meetings_to_wiki`'s report gains `wiki["stamped"]` (present only
when `mark_wiki_ingested` ran); `sync_fireflies_transcripts`'s report
(consumed as `report["sync"]`) gains `revised`, `repaired`,
`probable_duplicates`, `from_date`, and `registry` (`"ok"` |
`"unavailable"`) — see that method's own docstring for the full shape.
`duplicates` is reserved on that report but always empty: duplicate
merges are reported by `backfill_from_vault`'s own `BackfillReport`
(logged in `configure()`), never surfaced through the sync report itself.

Out of scope for this feature (see the operating contract,
`sdd/proposals/brainstorm-obsidian-wiki-knowledgebase.md` §14/§25): the
Review Queue / `Raw/Processed/Revisions` bundle layout, and the Markdown
mirror `Wiki/Registry/processed-sources.md` — both belong to the future
knowledgebase agent, which can consume this feature's `report["revised"]`
as its trigger. This feature deliberately revises a changed transcript in
place rather than routing it to a review queue — a documented divergence
from the contract's default (spec §7 Known Risks), accepted because the
vault *is* the raw layer for this agent and analysis is regenerated
automatically.

Full spec: `sdd/specs/fireflies-meeting-registry.spec.md`. Operator
runbook: `docs/runbooks/fireflies-meeting-registry.md`.

### The three scheduled jobs

| Method | Trigger | Responsibility |
|---|---|---|
| `sync_meetings_to_wiki()` | daily 07:00 | sync → summarize → wiki ingest |
| `email_daily_meeting_digest()` | daily 08:00 | last-24h analyses → bullets → email |
| `email_weekly_insights()` | Mon 09:00 | last-7d analyses → insights → email |

#### 07:00 — `sync_meetings_to_wiki()`

Runs four steps, in this order (FEAT-472 added the fourth):

1. `sync_fireflies_transcripts(limit=SYNC_LIMIT, skip_existing=True, force_refetch=force_refetch)`
   — id-keyed dedup via the meeting registry; see "Meeting registry
   (FEAT-472)" above.
2. `summarize_pending_transcripts(granularity="standard", limit=ANALYSIS_LIMIT)`
   — candidates from the registry's `pending_analysis()` when available.
3. `self._wiki.ingest_obsidian_vault(wiki_name, vault_path, incremental=True,
   extract_entities=EXTRACT_ENTITIES)`
4. `await self.registry.mark_wiki_ingested()` when step 3 ingested
   successfully and the registry is available — stamps `wiki_ingested_at`.

The order is load-bearing. Summarizing **before** the wiki ingest means the
page published to the wiki carries the transcript *and* its summary in a
single ingest pass, which is the stated requirement. It also guarantees the
08:00 digest finds its input already written into the vault. Stamping
`wiki_ingested_at` **after** the ingest (never before) means the stamp
only ever reflects a wiki that genuinely contains the meeting.

`incremental=True` uses the source manifest's staleness check, so the job is
idempotent and self-healing: a run that failed yesterday is picked up today
without special-casing.

`force_refetch` (default `False`) is forwarded from `sync_meetings_to_wiki`'s
own parameter — set by the `/sync force_refetch=true` Telegram command,
never by the 07:00 schedule itself.

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
| `FIREFLIES_REGISTRY_DIR` | `FIREFLIES_WIKI_STORAGE_DIR` | FEAT-472: directory whose `wiki.db` backs the `MeetingRegistry` — same file the wiki toolkit opens, so both share one row per meeting |
| `FIREFLIES_SYNC_OVERLAP_DAYS` | `2` | FEAT-472: days subtracted from `max(synced_at)` to derive the sync window's `fromDate` when no explicit filter is given |
| `FIREFLIES_RECHECK_DAYS` | `7` | FEAT-472: a row younger than this is eligible for `classify()`'s cheap-skip path (no transcript fetch) when the listing metadata is unchanged |

The digest windows are computed in **the same timezone the triggers fire
in**, resolved by `parrot.agents.conf.schedule_tzinfo()`
(`ZoneInfo(FIREFLIES_WIKI_TZ)`, falling back to UTC on an unknown name). Computing "today" in UTC while the job fires at 08:00
`Asia/Tokyo` would select the *previous* day's meetings — the window would be
silently shifted by a day. The email subject line uses the same local date.

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
- FEAT-472: a `MeetingRegistry` that fails to construct (or raises on a
  later call) degrades to `available=False` after one WARNING log; the
  sync and analysis loops then fall back to the pre-FEAT-472 title-based
  path for that run — never raises, and `report["registry"]` reflects the
  degradation (`"ok"` | `"unavailable"`).

## Testing

`tests/test_fireflies_wiki_agent.py`, mirroring `tests/test_security_advisor.py`.
pytest-asyncio, no network, no real LLM.

- `_notes_in_window` boundary correctness — inclusive start, malformed
  prefixes ignored, notes outside the window excluded
- `_collect_analyses` extracts only the Analysis block and tolerates notes
  that have none
- 07:00 job calls sync → summarize → ingest → `mark_wiki_ingested`
  **in that order** (ordering assertion, not just call counts; FEAT-472
  added the fourth step)
- wiki is `None` → sync still succeeds, ingest reported as skipped,
  `mark_wiki_ingested` never called; same when the registry is unavailable
- `/sync` (`sync_now`) parses `force_refetch`/`limit`, forwards them to
  `sync_meetings_to_wiki`, and replies with one line, including an error
  count when non-zero
- daily digest: empty window sends nothing; populated window calls
  `send_notification` with the daily recipients
- weekly insights: uses the 7-day window and the weekly recipients
- `_email` returns `False` when the provider reports `{"status": "error"}`
- decorator metadata: all three scheduled methods carry `_schedule_config`
  with the expected hour / minute / day_of_week / timezone; `sync_now`
  carries `_telegram_command` with `command="sync"`

FEAT-472 also added, in `packages/ai-parrot`'s own test tree (not this
gitignored `agents/` file's sibling):

- `tests/test_meeting_registry.py` — `MeetingRegistry` unit tests
  (classify, backfill, merge, repair)
- `tests/test_fireflies_obsidian_sync.py` — `FirefliesObsidianAgent`'s
  registry-driven sync/analysis loops
- `tests/integration/test_fireflies_meeting_registry.py` — the registry
  and the wiki toolkit sharing one `wiki.db`; the full
  create → revise → analyse → cheap-skip cycle; an existing vault
  upgrading without duplicates

## Deliverables

- `agents/fireflies_wiki.py` — the agent (committed with `git add -f`;
  `examples/**/*.py` is *also* gitignored, so the example needs `-f` too)
- `tests/test_fireflies_wiki_agent.py` — unit tests
- `examples/agents/fireflies_wiki_agent.py` — manual one-shot runner for
  each of the three methods, alongside the existing
  `examples/agents/fireflies_obsidian_sync.py`
- `packages/ai-parrot/src/parrot/agents/meeting_registry.py` — the
  FEAT-472 `MeetingRegistry` facade (see "Meeting registry (FEAT-472)"
  above and `sdd/specs/fireflies-meeting-registry.spec.md`)

## Out of scope

- Changing `FirefliesObsidianAgent` itself
- Replacing the existing `examples/agents/fireflies_obsidian_sync.py`
- Slack/Teams delivery (email only, per the request)
- A dashboard or A2UI rendering of the digests
