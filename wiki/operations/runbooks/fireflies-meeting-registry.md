# Runbook — the Fireflies Meeting Registry

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Audience**: operators of the Fireflies agents (`FirefliesObsidianAgent`,
`FirefliesWikiAgent`); Claude Code sessions debugging a sync run.
**Status**: current.

---

## What this is

`FirefliesObsidianAgent.sync_fireflies_transcripts()` used to decide
whether a Fireflies meeting was "already synced" by comparing the note
**title** it would generate against the vault's existing file stems. That
breaks the moment a meeting title is edited in Fireflies, two meetings on
the same day share a title (recurring standups), or a note is renamed
inside Obsidian.

The meeting registry replaces title-based dedup with **id-keyed** dedup:
every synced meeting is identified by its immutable Fireflies transcript
id, stored as `external_id = "fireflies:<id>"` on the wiki's existing
`sources` manifest row (`parrot.knowledge.wiki.sources.SourceCollectionManager`
— no new store, no new table). Meeting-specific state (content
fingerprint, analysis status, `wiki_ingested_at`, last error) lives in
that row's `doc_metadata["fireflies"]` JSON block.

Full design: `sdd/specs/fireflies-meeting-registry.spec.md`. Agent-level
architecture: `docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md`
§"Meeting registry (FEAT-472)".

## Where it lives

`<registry_dir>/wiki.db` — a plain sqlite file, the SAME file the meetings
wiki (`LLMWikiToolkit`) uses for its own `sources` manifest. `registry_dir`
defaults to `FIREFLIES_WIKI_STORAGE_DIR` (i.e. the meetings wiki's own
storage dir) via the `FIREFLIES_REGISTRY_DIR` env var, so a stock
deployment has exactly one `wiki.db` shared by the sync agent and the
wiki ingest — this is deliberate (spec §2 G5): the sync loop writes
`external_id` + `doc_metadata.fireflies`; the nightly wiki ingest fills
`pages_generated`/`file_hash`/`mtime` on the SAME row.

`parrot.agents.meeting_registry.MeetingRegistry` is the facade agents call
through — never touch `SourceCollectionManager` directly in agent code.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `FIREFLIES_REGISTRY_DIR` | `FIREFLIES_WIKI_STORAGE_DIR` | Directory whose `wiki.db` backs the registry |
| `FIREFLIES_SYNC_OVERLAP_DAYS` | `2` | Days subtracted from `max(synced_at)` for the sync window's `fromDate` |
| `FIREFLIES_RECHECK_DAYS` | `7` | A row younger than this is eligible for the cheap-skip path (no transcript fetch) |

## Daily operation

Nothing to schedule beyond what already exists:
`FirefliesWikiAgent.sync_meetings_to_wiki()` (07:00 cron,
`agents/fireflies_wiki.py`) already calls
`sync_fireflies_transcripts()` / `summarize_pending_transcripts()`,
both now registry-driven when the registry is available. The registry
itself is opened once, in `FirefliesObsidianAgent.configure()`, which also
runs the one-time backfill (see below) and logs its summary.

### On-demand sync via Telegram

```
/sync force_refetch=true|false limit=<n>
```

- `force_refetch=true` (or `1`/`yes`, case-insensitive) bypasses the
  cheap-skip path — every known meeting is re-fetched and
  re-fingerprinted. Use this after fixing something in a transcript's
  source data upstream, or when debugging a sync that seems stuck.
- `limit` bounds how many transcripts are fetched, total across pages.
  Empty or unparsable falls back to `FIREFLIES_WIKI_SYNC_LIMIT`.
- The reply is one line:
  `✅ synced N · revised R · skipped S · analysed A · wiki: ok/skipped [· errors N]`

### Inspecting the registry directly

```bash
sqlite3 "$FIREFLIES_REGISTRY_DIR/wiki.db" \
  "select external_id, source_uri, status from sources where external_id like 'fireflies:%'"
```

To see the full per-meeting state (fingerprint, analysis status,
`wiki_ingested_at`, last error):

```bash
sqlite3 "$FIREFLIES_REGISTRY_DIR/wiki.db" \
  "select external_id, doc_metadata from sources where external_id like 'fireflies:%'"
```

`doc_metadata` is a JSON blob; pipe through `python -m json.tool` or `jq
'.fireflies'` (after extracting the `doc_metadata` column value) for a
readable view.

### Forcing a re-fetch for one meeting

There is no per-meeting "reset freshness" verb today. The two available
levers are both whole-run:

- `/sync force_refetch=true` — re-fetches and re-fingerprints **every**
  known meeting this run (bypasses `classify()`'s cheap-skip path
  entirely), or
- `registry.forget(fireflies_id)` (below) followed by a normal sync —
  removes the row entirely, so the next sync treats that id as brand new
  and fetches it unconditionally.

### `forget` — removing or permanently rejecting a meeting

```python
await registry.forget(fireflies_id)                 # removes the row entirely
await registry.forget(fireflies_id, reject=True)     # keeps the row, flags it "do not re-sync"
```

- `reject=False` (default) deletes the `sources` row outright. The next
  sync of that id will `create` a fresh note and a fresh row — use this
  when a meeting was synced by mistake and should be fully forgotten.
- `reject=True` keeps the row but marks it rejected in
  `doc_metadata["fireflies"]["rejected"]`; `classify()` then returns
  `"skip"` for that id **forever**, even if the note file is later
  deleted by a human. Use this for a meeting that should never come back
  (e.g. a test transcript, or one explicitly excluded from the vault).

  > Implementation note: the spec's own Known Risks section describes
  > this as the row's `status` becoming `"rejected"` — the shipped
  > implementation instead sets a `doc_metadata["fireflies"]["rejected"]`
  > flag, because the `SourceCollectionManager` methods available to
  > `MeetingRegistry` (`record_document_metadata`, `set_external_id`, …)
  > don't include a way to touch the generic `status` column without
  > either requiring the note file to still exist
  > (`mark_ingested`) or silently dropping `doc_metadata`
  > (`record_decision`, a separate pre-existing gap). Effect on `classify`
  > is identical either way: permanent `"skip"`.

### Backfill and duplicate merge (existing-vault upgrade)

The first time `configure()` runs against a vault with **zero**
`fireflies:*` rows, it seeds one row per meeting straight from note
frontmatter (`fireflies_id`, `title`, `date`, `participants`,
`duration_minutes`, `synced_at`; `fingerprint=None` — nothing was ever
fetched from Fireflies for these rows, so the very next sync of each id
always re-checks once). Any id with more than one note is merged: the
analysed note is kept (else the newest by mtime), moved to its canonical
`{meetings_folder}/{YYYY-MM-DD-slug}.md` path when that path is free, and
every other note for that id is deleted. **A note whose frontmatter
cannot be parsed is never touched** — it is reported as `unmerged` and
left exactly where it is.

This only ever runs once automatically (guarded on "the registry has no
rows yet"). To dry-run the merge decision without deleting or moving
anything, call the facade directly with `merge=False`:

```python
report = await registry.backfill_from_vault(
    toolkit=agent.obsidian_toolkit,
    meetings_folder=agent.meetings_folder,
    analysis_heading=agent.ANALYSIS_HEADING,
    merge=False,
)
print(report.seeded, report.without_analysis, report.duplicates, report.unmerged)
```

With `merge=False`, every id with more than one note is left completely
alone (listed in `report.unmerged`, nothing deleted or registered for
that id) — safe to run repeatedly to preview what a real backfill would
do.

## The `external_id` convention

`external_id` is an immutable identity in **`"<source>:<id>"`** form —
e.g. `"fireflies:abc123"` for a Fireflies transcript. It is deliberately
separate from `source_id`/`source_uri`, which are derived from the file's
current path and change when a file is renamed or moved. Any future
external-source ingest that needs identity-not-path dedup (Jira tickets,
audio notes, …) should adopt the same `"<source>:<id>"` convention against
the same `sources` table rather than inventing a parallel registry — see
the `SourceCollectionManager` class docstring
(`packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`) for the
authoritative statement of this convention, and
`find_by_external_id`/`find_entries_by_external_ids`/
`list_by_external_prefix`/`set_external_id` for the generic lookups any
such integration would use. Migrating the existing Jira (`jira_sync.py`)
or audio-notes ingests to this convention is explicitly out of scope for
this feature — follow-up work.

## Relation to the operating contract (§14 / §25)

`sdd/proposals/brainstorm-obsidian-wiki-knowledgebase.md` §14
"Deduplication and Source Identity" and §25 "Processed Source Registry"
describe the operating contract a future knowledgebase agent is expected
to honor: **registry ∪ Raw as the authoritative dedup gate**, keyed
`<source>:<id>` with content hashes. This feature IS that code-side
registry — `MeetingRegistry` implements the contract's identity model for
the Fireflies case specifically.

One documented divergence: the contract routes "same id, changed content"
to a Review Queue and never auto-merges. This feature instead updates the
note **in place** when content changes (`revise`), because the vault *is*
the raw layer for this sync agent and its analysis is regenerated
automatically on the next analysis pass. A future knowledgebase agent
layering the contract's Review Queue on top can consume
`report["revised"]` (from `sync_fireflies_transcripts`'s report) as its
trigger for filing a `source-revision` review item — no code change to
this feature is needed for that.

The contract's Markdown mirror, `Wiki/Registry/processed-sources.md`, is
**not** produced by this feature. It is intended to be generated by a
future exporter reading `list_by_external_prefix("fireflies:")` — one
line per row — that exporter's concern, not this registry's.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| A meeting keeps getting re-created as a new note | `classify()` never saw the existing row — usually the note was moved/renamed AND the content also changed in the same run before `repair_path` could run, or the registry was unavailable for a prior run | `report["registry"]` on the last few sync reports; `sqlite3 wiki.db "select * from sources where external_id='fireflies:<id>'"` |
| A meeting is stuck "pending" analysis forever | `summarize_pending_transcripts` errored on that note (LLM failure) | `doc_metadata['fireflies']['last_error']` on that row |
| Renamed note not repaired | Repair only runs ahead of an actual `create`/`revise` — a same-content rename alone is invisible to `classify()` (nothing changed, so it cheap-skips before repair ever runs) and needs a real content change or `force_refetch=true` to surface | confirm the row's `source_uri` (via the inspect query above) still points at the old path |
| `wiki_ingested_at` never gets stamped | No wiki plane (`self._wiki is None`), the ingest itself failed, or the registry is unavailable | `sync_meetings_to_wiki()`'s own report `["wiki"]` dict — `"stamped"` is present only when the stamp actually ran |
| Registry "unavailable" in every report | The `wiki.db` file/directory is not writable, or a permission error is happening at construction | Agent logs a single WARNING with the exception at `configure()` time — check that log line first |
