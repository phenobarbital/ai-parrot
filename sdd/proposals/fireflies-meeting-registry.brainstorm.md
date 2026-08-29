---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Fireflies Meeting Registry — id-keyed dedup for the Fireflies → Obsidian → Wiki sync

**Date**: 2026-08-29
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`FirefliesObsidianAgent.sync_fireflies_transcripts()` decides whether a
Fireflies transcript is "already synced" by **note title**, not by the
transcript's id (`packages/ai-parrot/src/parrot/agents/obsidian.py:399-416`):
it lists the file stems in `meetings_folder` and skips a transcript when
`_make_note_title(date, title)` is already among them. The Fireflies id is
written into every note (`fireflies_id` frontmatter, `:462`; OKF
`node_id = obsidian::fireflies::<id>`, `:766`) but is **never read back**.

That breaks in four real situations:

| Situation | Today's behaviour |
|---|---|
| Meeting title edited in Fireflies after the first sync | New slug → **duplicate note** |
| Two meetings on the same day with the same title (recurring standups) | Second one **silently skipped** |
| Note renamed/moved inside Obsidian (allowed — `ObsidianToolkit.move_note` exists) | Re-synced as a **new note** |
| Transcript re-finalised by Fireflies (late summary, corrected speakers) | **Never picked up** — "exists" is binary |

Analysis state has the same weakness: `summarize_pending_transcripts()`
(`:593-676`) re-reads every candidate note and greps for the `## Analysis`
heading (`_has_analysis`, `:697`). There is no record of *which version* of
the transcript an analysis was computed against, so a revised transcript
keeps its stale analysis forever.

This matters now because the `FirefliesWikiAgent` (`agents/fireflies_wiki.py`)
runs the sync unattended every morning and feeds the result into the LLM
Wiki. In the wider "operating contract" being drafted for that agent,
**registry ∪ Raw is the authoritative dedup gate** and GraphIndex is a
derived accelerator only — but there is no registry today. This brainstorm
designs that registry.

Affected: operators of the Fireflies agents (duplicate/missed meetings in
the vault and wiki), and every downstream consumer — daily/weekly digests,
`ingest_obsidian_vault`, `audio-notes` flows sharing the vault.

## Constraints & Requirements

- **Identity is the Fireflies transcript id.** Immutable and external. The
  note title/path is a *display key* that may change; never the reverse.
- **Reuse `SourceCollectionManager`** (`parrot/knowledge/wiki/sources.py`)
  rather than a new registry class — decided in discovery. The manager is
  path-keyed (`source_uri` UNIQUE, `source_id = uuid5(path)`), so the reuse
  must be additive and must not disturb the vault ingest that already
  registers meeting notes by path.
- **Works without the wiki.** The sync lives in the parent
  `FirefliesObsidianAgent`, which has no `LLMWikiToolkit`. The registry must
  be usable with `self._wiki is None`; when the wiki *is* present both must
  see one table (same `wiki.db`).
- **Content-only fingerprint.** `sha256` of the whitespace/line-ending
  normalised transcript body. Excludes `synced_at`, fetch timestamps, and
  the Fireflies native summary (tracked as its own hash) so a re-fetch with
  an updated summary does not force re-analysis of an unchanged transcript.
- **Revise = update in place.** When a known id's fingerprint changes, the
  existing note body is replaced via `update_note` (frontmatter preserved),
  the `## Analysis` section is dropped, and analysis state resets to
  pending. Never a second file.
- **Backfill is automatic and idempotent.** Existing vaults must migrate
  without duplicating anything: on first open, seed the registry from note
  frontmatter (`fireflies_id`), fingerprint unknown → compare on next fetch.
- **Registry drives the sync window.** `from_date` defaults to
  `max(synced_at) − overlap` (cold start: existing behaviour). No
  server-side "exclude processed" exists on the Fireflies MCP; the
  fingerprint gate absorbs the overlap. Fireflies is not observed to
  change a transcript later than ~2 days after the meeting, so
  `FIREFLIES_SYNC_OVERLAP_DAYS=2` and `FIREFLIES_RECHECK_DAYS=7` are
  fixed defaults; `force_refetch` exists for the exceptions.
- **`external_id` is a general convention.** Values are `<source>:<id>`
  (`fireflies:<transcript_id>` here). The column is documented as the
  pattern future external-source ingests (Jira `jira_sync.py`, audio
  notes) should adopt; migrating them is out of scope.
- **Repair may move files; merge may delete them.** Both verbs are
  explicit, reported, and limited to the meetings folder; the parent
  toolkit's `allowed_operations` grows by `"move"` and `"delete"`.
- **Full lifecycle in one place.** Registry records sync, analysis and
  wiki-ingest state per meeting (decided in discovery). The wiki ingest
  itself stays incremental through the existing manifest staleness check.
- Async-first, Pydantic models, Google docstrings, `self.logger`. No new
  external dependencies. Tests without network or a real LLM, mirroring
  `tests/test_fireflies_wiki_agent.py`.
- Never modify `abstract_client.py`; `agents/` files need `git add -f`.

---

## Options Explored

### Option A: Extend `SourceCollectionManager` with an `external_id` column and a `MeetingRegistry` facade

Add one additive, nullable, indexed column `external_id` (value
`fireflies:<transcript_id>`) to the `sources` table through the existing
`_migrate_sources_columns()` mechanism, plus `find_by_external_id()` /
`find_entries_by_external_ids()` readers and an `external_id` parameter on
the writers. Meeting-specific state (transcript fingerprint, summary
fingerprint, analysis status + fingerprint, wiki-ingested timestamp,
participants, meeting date) lives in the existing `doc_metadata` JSON
column under a `fireflies` key, written through `record_document_metadata`.

A thin async facade — `MeetingRegistry` in `parrot/agents/` (or
`parrot/knowledge/wiki/meetings.py`) — wraps the manager with
meeting-shaped verbs: `lookup(fireflies_id)`, `classify(listing_item,
fingerprint) -> create|skip|revise`, `record_synced(...)`,
`pending_analysis()`, `mark_analyzed(...)`, `mark_wiki_ingested(ids)`,
`repair_path(...)`, `backfill_from_vault(...)`, `suggest_from_date()`. All
manager calls go through `asyncio.to_thread` (the manager's public API is
synchronous by design).

The parent agent constructs the manager itself
(`SourceCollectionManager(storage_dir / "sources", db_path=storage_dir /
"wiki.db")`); the subclass's `LLMWikiToolkit` later opens the same
`wiki.db` (`toolkit.py:154`), so the vault ingest and the registry share
rows: the row the ingest created by path gains an `external_id`, and the
row the sync created gets `pages_generated` filled by the ingest.

✅ **Pros:**
- One table, one file, one backup story — the meeting's whole lifecycle
  (synced → analysed → ingested) is visible in a single row.
- Rename-safe: lookup by `external_id`, `source_uri` updated on repair;
  `source_id` stability is no longer load-bearing for meetings.
- Zero schema risk for existing wikis — the migration pattern
  (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`) is already proven twice
  (FEAT-402, FEAT-451). Arango backend gets the same field in
  `_entry_to_doc` for free.
- No new persistence code; the Arango/json/sqlite tri-backend keeps working.

❌ **Cons:**
- `doc_metadata` is opaque JSON: `pending_analysis()` must load all
  fireflies rows and filter in Python (fine at meeting scale — hundreds to
  low thousands — but not indexable).
- `add_source(path)` requires the file to exist; the facade must create the
  note *before* registering, and the fingerprint is computed on the
  transcript text, not on the file (two hashes with different purposes on
  one row — must be documented clearly).
- Touches a core wiki module (`sources.py`, `models.py`, `store.py` schema
  comment) for an agent-level need.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlite3` (stdlib) | registry persistence | already used by the manager, WAL mode |
| `hashlib` (stdlib) | sha256 fingerprint | — |
| `pydantic` ≥2 | `MeetingRecord` model, `SourceManifestEntry.external_id` | already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/sources.py` — `SourceCollectionManager`, `_migrate_sources_columns`, `record_document_metadata`, `find_entries_by_ids`
- `parrot/knowledge/wiki/models.py:155` — `SourceManifestEntry` (add `external_id: str | None`)
- `parrot/agents/obsidian.py:399-500` — the sync loop to rewire
- `parrot/agents/obsidian.py:593-676` — `summarize_pending_transcripts` to rewire
- `parrot/tools/obsidian.py:471,538,229` — `update_note`, `move_note`, `read_notes`

---

### Option B: Sibling `meeting_registry` table in the same `wiki.db`

A dedicated table (`fireflies_id TEXT PRIMARY KEY, note_path, fingerprint,
summary_fingerprint, title, meeting_date, participants JSON, synced_at,
analysis_status, analysis_fingerprint, wiki_ingested_at, last_error`) with
its own small manager class, reusing only the manager's `_connect()` /
WAL / migration conventions. Linked to the `sources` row by `note_path =
source_uri`.

✅ **Pros:**
- Clean, typed schema; `pending_analysis()` is one indexed `WHERE`.
- No change to core wiki models or the tri-backend manager.

❌ **Cons:**
- Two tables describe the same file; the join by path breaks on rename
  unless both are updated together — the exact class of bug we are fixing.
- No Arango parity unless a second collection is added; the wiki agent
  already supports `storage_backend="arangodb"`.
- More code than A for the same behaviour; contradicts the discovery
  decision to reuse the manager.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlite3` (stdlib) | registry persistence | — |
| `pydantic` ≥2 | record model | — |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/sources.py:752` — `_connect()` pattern
- `parrot/knowledge/wiki/store.py:58` — `WIKI_SCHEMA_SQL` (append table)

---

### Option C (unconventional): The vault *is* the registry — frontmatter as source of truth, in-memory id index per run

No database. Every sync starts by bulk-reading the meetings folder
(`read_notes`, 50 per call) and building `{fireflies_id → (path,
fingerprint, analysis_fingerprint)}` from frontmatter; the agent writes
`fireflies_fingerprint` / `analysis_fingerprint` / `wiki_ingested_at` back
into frontmatter as state changes. Obsidian users see all state inline.

✅ **Pros:**
- Nothing to migrate or back up; the vault stays self-describing and
  portable (a vault copied to another machine carries its registry).
- Rename-proof by construction (index is rebuilt from content each run).

❌ **Cons:**
- O(n) full-vault read every run; unacceptable once the folder holds
  thousands of notes or lives on a remote backend.
- Users editing frontmatter can corrupt state; no atomicity across notes.
- Each state change is a note write → mtime/hash change → the wiki source
  manifest sees the note as stale and re-ingests it on every analysis
  update.
- Cannot answer "what did we last sync" without reading the vault, so the
  sync-window optimisation is weak.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` / existing `ObsidianNoteParser` | frontmatter read/write | already used by `ObsidianToolkit` |

🔗 **Existing Code to Reuse:**
- `parrot/tools/obsidian.py:229` — `read_notes` bulk reader
- `parrot/agents/obsidian.py:721` — `_build_okf_frontmatter`

---

## Recommendation

**Option A** is recommended because:

- It honours the discovery decision (reuse `SourceCollectionManager`) while
  fixing the one property that made reuse look impossible — path-keyed
  identity — with a single additive column and no behavioural change for
  every other caller of the manager.
- Sharing the row with the vault ingest is a feature, not a coincidence:
  the registry can truthfully record `wiki_ingested_at` because the ingest
  writes `pages_generated` on the *same* row, and `lint()` / `status`
  tooling that already reads `sources` sees meetings without new code.
- The cost we accept is the JSON-typed meeting state in `doc_metadata`
  (Python-side filtering for `pending_analysis()`). At meeting-corpus
  scale that is milliseconds; if it ever matters, promoting
  `analysis_status` to a real column is the same additive migration again.
- Option B duplicates identity across two tables and reintroduces the
  rename hazard; Option C trades correctness for zero infrastructure and
  fights the wiki manifest's staleness detection.

---

## Feature Description

### User-Facing Behavior

- Running `sync_fireflies_transcripts()` (manually, via the 07:00 job, or
  via the Telegram commands) never creates a duplicate note for a
  transcript id that is already in the vault — regardless of title edits,
  same-title collisions, or notes moved/renamed in Obsidian.
- Same-day, same-title meetings with different ids both land; the second
  gets a `-2` (…`-n`) suffix on its slug.
- When Fireflies re-finalises a transcript, the next sync **updates the
  note in place**, drops the stale `## Analysis`, and the next
  `summarize_pending_transcripts()` re-analyses it. The sync report gains a
  `revised` counter alongside `synced` / `skipped`.
- The sync report also lists `repaired` notes (renamed notes moved back to
  the canonical `YYYY-MM-DD-slug` path and re-registered) and the
  effective `from_date` used.
- `sync_fireflies_transcripts(force_refetch=True)` / Telegram
  `sync --force-refetch` re-fingerprints every transcript in the window
  instead of trusting the cheap listing-metadata skip.
- First run on an existing vault logs a backfill summary ("registry
  seeded from N notes, M without analysis, K duplicate ids merged") and
  behaves exactly like today for those notes — no forced re-analysis.
  Duplicate notes for one id are merged (one kept, the rest deleted) and
  every merge is itemised in the report.
- `summarize_pending_transcripts()` reports `skipped` from the registry
  instead of re-reading every note; `force=True` still re-analyses.
- With `FIREFLIES_WIKI_*` unset or the wiki plane failing to build, all of
  the above still works — the registry lives in `wiki.db` under the
  storage dir but does not need the wiki toolkit.

### Internal Behavior

1. **Boot.** `FirefliesObsidianAgent.configure()` builds
   `MeetingRegistry(storage_dir)`; the facade opens
   `SourceCollectionManager(storage_dir/"sources", db_path=storage_dir/"wiki.db")`
   (sqlite, migration adds `external_id` if missing). If the `sources`
   table has no `fireflies:*` rows and the meetings folder is non-empty,
   run **backfill**: bulk-read frontmatter, register each note by path with
   `external_id = fireflies:<id>`, `fingerprint = None`,
   `analysis_status = done|pending` by presence of `## Analysis`.
   The storage dir defaults to `FIREFLIES_WIKI_STORAGE_DIR`
   (`~/.parrot/wikis/meetings`); the parent gains a `registry_dir`
   constructor argument so it is not coupled to the wiki config names.
2. **Window.** Unless the caller/`default_filters` provide `from_date`,
   `suggest_from_date()` returns `max(synced_at) − FIREFLIES_SYNC_OVERLAP_DAYS`
   (default 2). Cold start → no `from_date` (today's behaviour).
3. **Listing pass.** For each transcript in the Fireflies listing:
   `classify(item)`:
   - id unknown → `create`.
   - id known, `title/date/duration` unchanged and `synced_at` newer than
     `FIREFLIES_RECHECK_DAYS` (default 7) → `skip` **without** fetching the
     transcript (cheap path). `force_refetch=True` (exposed on
     `sync_fireflies_transcripts` and as `--force-refetch` on the Telegram
     `sync` command) disables this path: every id in the window is fetched
     and fingerprinted.
   - otherwise → fetch transcript, normalise, `sha256`; equal to stored
     fingerprint → `skip`; different (or stored `None` from backfill) →
     `revise`.
4. **Repair.** Before `create`/`revise`, verify `source_uri` still exists.
   If not, scan the meetings folder frontmatter for the id
   (`read_notes`, chunked); found → `repair_path()`: `move_note` the file
   back to the canonical `{meetings_folder}/{YYYY-MM-DD-slug}.md` path
   (the parent's `ObsidianToolkit` gains `"move"` in
   `allowed_operations`), then update `source_uri`; if the canonical path
   is already taken by a *different* id, keep the user's path and only
   update the registry. `pages_generated` is left to the ingest. Not
   found → treat as `create`. Every move is listed under
   `report["repaired"]` as `{id, from, to}`.
5. **Write.**
   - `create`: `create_note` (slug de-duplicated with `-n` suffix against
     the registry, not just the filesystem), then `record_synced()` →
     `add_source(path)` + `external_id` + `doc_metadata.fireflies = {…}`.
   - `revise`: `_strip_analysis_section` is not needed — the body is
     rebuilt from the fresh transcript (+ optional Fireflies summary) and
     written via `update_note(preserve_frontmatter=True)`; frontmatter
     `synced_at`/`title`/`participants` refreshed through the toolkit; then
     `record_synced()` with the new fingerprint and
     `analysis_status = pending`, `analysis_fingerprint = None`.
6. **Analysis.** `summarize_pending_transcripts()` takes candidates from
   `registry.pending_analysis()` (status ≠ done **or**
   `analysis_fingerprint ≠ fingerprint`) when `note_titles is None`; on
   success `mark_analyzed(id, fingerprint)`; on failure
   `analysis_status = failed`, `last_error` recorded. The old
   `_has_analysis` grep remains only as the fallback when the registry is
   unavailable.
7. **Wiki.** `FirefliesWikiAgent._ingest_vault_into_wiki()` unchanged;
   afterwards `mark_wiki_ingested()` stamps `wiki_ingested_at` on every
   fireflies row whose `pages_generated` is non-empty and whose manifest
   entry is not stale (the ingest already wrote those columns on the same
   row).
8. **Fingerprint normalisation** (pure function, unit-tested): strip BOM,
   `\r\n`→`\n`, strip trailing whitespace per line, collapse >2 blank
   lines, strip leading/trailing blank lines; hash UTF-8 bytes. The
   Fireflies native summary is hashed separately into
   `summary_fingerprint`; a summary-only change does not trigger `revise`
   of the transcript but does refresh the summary section.

### Edge Cases & Error Handling

- **Registry unavailable** (db locked, permission error): log a warning
  once, fall back to today's title-based dedup for that run; report carries
  `registry: "unavailable"`. Never abort the sync.
- **Backfill finds two notes with the same `fireflies_id`** (a duplicate
  created by the old behaviour): `merge_duplicates()` keeps the note that
  carries an `## Analysis` (newest by mtime if several or none), moves it
  to the canonical path if needed, deletes the others via `delete_note`
  (the parent toolkit gains `"delete"` for this single verb), and records
  every decision in `report["duplicates"]` as `{id, kept, removed[]}`.
  The merge never runs silently: it is part of the backfill report and
  logged at INFO per id. Any note whose frontmatter is unparsable is left
  untouched and listed under `report["unmerged"]`.
- **Note deleted by the user**: `classify` sees the id but no file →
  repair scan finds nothing → `create` re-writes the note. If the user
  wants a meeting gone for good they must also remove the row (a
  `forget(fireflies_id)` verb is provided for an explicit opt-out;
  `status="rejected"` on the row is honoured as "never re-create").
- **Fireflies listing lacks `duration`/`date`**: cheap-skip is not
  attempted; the transcript is fetched and fingerprinted.
- **Transcript fetch fails mid-run**: row untouched, error appended, loop
  continues (as today).
- **Concurrent runs** (07:00 job + manual Telegram sync): WAL sqlite makes
  writes safe; the second run's `classify` sees the first run's rows.
  Slug de-dup consults the registry so two concurrent `create`s of the same
  id resolve to one — the loser gets a `create_note` "already exists" error
  and reports `skipped`.
- **Arango backend wiki**: `external_id` travels through `_entry_to_doc` /
  `_doc_to_entry`; `find_by_external_id` becomes an AQL filter. Out of scope
  to *test* against a live Arango; unit-tested through the sqlite path
  with the Arango mapping covered by the existing model round-trip tests.
- **Backfill on a huge vault**: bulk `read_notes` in chunks of 50;
  progress logged every 500 notes.

---

## Capabilities

### New Capabilities
- `fireflies-meeting-registry`: id-keyed registry (facade over
  `SourceCollectionManager`) recording sync / analysis / wiki state per
  Fireflies transcript, with create-skip-revise classification,
  `force_refetch`, path repair (move back to canonical path), backfill
  with reported duplicate merge, and sync-window suggestion.
- `wiki-sources-external-id`: additive `external_id` column + lookups on
  the wiki `sources` manifest (sqlite/json/arangodb parity).

### Modified Capabilities
- `fireflies-obsidian-sync` (`FirefliesObsidianAgent.sync_fireflies_transcripts`,
  `summarize_pending_transcripts`): dedup and pending-analysis selection
  driven by the registry; new report fields `revised`, `repaired`,
  `duplicates`, `from_date`, `registry`.
- `fireflies-wiki-agent` (`agents/fireflies_wiki.py`): `sync_meetings_to_wiki`
  stamps `wiki_ingested_at` after ingest.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/models.py` `SourceManifestEntry` | extends | `external_id: str \| None = None` |
| `parrot/knowledge/wiki/sources.py` | extends | column migration, upsert SQL (+1 column), `find_by_external_id`, `find_entries_by_external_ids`, `external_id` kwarg on `add_source`/`record_decision`, Arango doc mapping |
| `parrot/knowledge/wiki/store.py` `WIKI_SCHEMA_SQL` | extends | `external_id TEXT` + index on fresh databases (migration covers old ones) |
| `parrot/agents/obsidian.py` | modifies | sync loop, summarize loop, `configure()`, constructor arg `registry_dir`, `force_refetch` param, `allowed_operations` += `"move"`, `"delete"`, report schema |
| Telegram `sync` command on the Fireflies agents | extends | `--force-refetch` flag |
| `parrot/agents/conf.py` | extends | `FIREFLIES_SYNC_OVERLAP_DAYS`, `FIREFLIES_RECHECK_DAYS`, `FIREFLIES_REGISTRY_DIR` (default = `FIREFLIES_WIKI_STORAGE_DIR`) |
| new `parrot/agents/meeting_registry.py` | new | `MeetingRegistry` facade + `MeetingRecord` Pydantic model + `normalise_transcript()` / `fingerprint()` |
| `agents/fireflies_wiki.py` | modifies | one call after ingest (`mark_wiki_ingested`); `git add -f` |
| `tests/test_fireflies_wiki_agent.py` | extends | ordering test now also asserts `mark_wiki_ingested` |
| new `tests/test_meeting_registry.py`, `tests/test_wiki_sources_external_id.py` | new | see Test notes in Feature Description |
| `docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md` | docs | note that dedup is id-keyed |
| Existing `wiki.db` files | data | additive migration, no rewrite; backfill runs once |

No breaking API changes: all new parameters default to today's behaviour;
`skip_existing=True` keeps its meaning (now id-based).

---

## Code Context

### User-Provided Code

_None — the design was discussed in prose; no snippets were supplied._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/agents/obsidian.py
class FirefliesObsidianAgent(...):                                   # parent of FirefliesWikiAgent
    def __init__(self, name: str = "FirefliesObsidianSync",           # :185
                 vault_path: Optional[str | Path] = None,
                 fireflies_token: Optional[str] = None,
                 meetings_folder: str = "meetings",
                 default_filters: Optional["FirefliesFilters"] = None,
                 **kwargs)
    self.vault_path: Path; self.meetings_folder: str                  # :211-216
    self.obsidian_toolkit = ObsidianToolkit(vault_path=..., backend="local",
        allowed_operations={"read","list","search","create","update"})  # :220-230  (NOTE: no "move"/"delete")
    async def configure(self, app=None) -> None                       # :235
    async def sync_fireflies_transcripts(self, ..., skip_existing: bool = True, ...) -> Dict[str, Any]  # :287-290
        # dedup: existing_titles = await self._get_existing_meeting_titles()  :400-401
        # transcript_id = transcript.get("id"); title; date                  :406-408
        # note_title = self._make_note_title(date, title); skip if in set    :411-416
        # fireflies_get_transcript(transcriptId) → transcript_text          :419-428
        # fireflies_get_summary(transcriptId) (optional, additive)          :436-458
        # metadata = {"fireflies_id", "date", "title", "participants",
        #             "duration_minutes", "synced_at"}                       :461-468
        # okf_metadata = self._build_okf_frontmatter(fireflies_id=..., ...)  :471-477
        # await self.obsidian_toolkit.create_note(path=f"{meetings_folder}/{note_title}.md",
        #        content=transcript_text, frontmatter=merged_metadata)      :485-489
    async def summarize_transcript(self, note_title: str, granularity: str = "standard") -> Dict[str, Any]  # :506
    async def summarize_pending_transcripts(self, note_titles=None, granularity="standard",
                                            limit=None, force=False) -> Dict[str, Any]   # :593
        # candidates = sorted(await self._get_existing_meeting_titles())   :630
        # if not force and await self._has_analysis(note_title): skip      :649
    def _strip_analysis_section(cls, content: str) -> str                # :677 (classmethod)
    async def _has_analysis(self, note_title: str) -> bool               # :697 — greps ANALYSIS_HEADING
    def _build_okf_frontmatter(fireflies_id, title, date, participants, duration) -> Dict  # :721 (static)
        # node_id = f"obsidian::fireflies::{fireflies_id}"                  :743
        # resource = f"fireflies://transcript/{fireflies_id}"              :745
    def _parse_fireflies_response(response_text: str) -> List[Dict[str, Any]]  # :783 (static) — yields dicts with "id", "title", dateString→"date", participants
    async def _call_fireflies_tool(self, name, args)                     # :867
    async def _get_existing_meeting_titles(self) -> set[str]             # :893 — file stems via list_notes(folder=meetings_folder, recursive=False)
    def _make_note_title(date: str, meeting_title: str) -> str           # :929 (static) — "YYYY-MM-DD-kebab-title"
    ANALYSIS_HEADING  # "## Analysis" class attribute (used at :720)

class FirefliesFilters(BaseModel):   # :~50-84
    from_date: ...   # ISO date string → tool arg "fromDate"             # :60, :102
def _filters_to_tool_args(filters) -> Dict[str, Any]                     # :85
def _merge_filters(default, override)                                    # :120

# From packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):
    async def read_note(self, path: str, include_content: bool = True) -> Dict[str, Any]           # :212
    async def read_notes(self, paths: list[str], include_content: bool = True) -> Dict[str, Any]   # :229 (max 50)
    async def list_notes(...)                                                                      # :257
    async def create_note(self, path: str, content: str, frontmatter: Optional[Dict] = None) -> Dict  # :439 — fails if exists
    async def update_note(self, path: str, content: str, preserve_frontmatter: bool = True) -> Dict   # :471
    async def delete_note(self, path: str) -> Dict[str, Any]                                       # :522
    async def move_note(self, source: str, destination: str) -> Dict[str, Any]                     # :538

# From packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):                                    # :155
    source_id: str; source_uri: str; file_hash: str; mtime: float; ingested_at: str   # :195-199
    pages_generated: list[str]; status: str                              # :200-…
    destination / decision_source / charter_version / composite_score    # FEAT-402, nullable
    doc_metadata: dict | None; content_type: str | None; loader: str | None  # FEAT-451, nullable

# From packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
_SOURCES_UPSERT_SQL  # 14-column INSERT … ON CONFLICT(source_id) DO UPDATE   :46-63 — must grow by one column
_SOURCES_DECISION_COLUMNS / _SOURCES_DOCUMENT_COLUMNS: dict[str, str]        :83-95 — migration maps
class SourceCollectionManager:                                               # :96
    def __init__(self, sources_dir: Path, db_path: Path | None = None,
                 backend: Literal["sqlite","json","arangodb"] = "sqlite",
                 arango_db=None, arango_store=None) -> None               # :121 — sqlite: executescript(WIKI_SCHEMA_SQL) + _migrate_sources_columns + _migrate_json_manifest  :188-194
    def add_source(self, path: Path) -> SourceManifestEntry               # :205 — raises FileNotFoundError; source_id = existing-by-uri or uuid5(uri)
    def find_entries_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]   # :260
    def find_entries_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]  # :301
    def add_sources(...) / mark_ingested_many(...)                        # :339 / :400
    def list_sources(self) -> list[SourceManifestEntry]                  # :442
    def get_source(self, source_id: str) -> SourceManifestEntry | None   # :457
    def is_stale(self, source_id: str) -> bool                           # :475 — file gone / mtime+SHA-1 changed
    def entry_is_stale(self, entry) -> bool                              # :496
    def mark_ingested(self, source_id, pages_generated, status="ingested")  # :533 — re-hashes the FILE
    def record_decision(self, path: Path, *, destination, decision_source=None, ...)  # :570 — creates entry if untracked
    def record_document_metadata(self, source_id, *, doc_metadata, content_type, loader) -> None  # :663 — never creates
    def remove_source(self, source_id: str) -> bool                       # :708
    def find_by_uri(self, source_uri: str) -> str | None                  # :737
    def _connect(self) -> sqlite3.Connection                              # :752
    def _compute_hash(self, path: Path) -> str                            # :870 — SHA-1 of file bytes
    def _generate_source_id(self, source_uri: str) -> str                 # :887 — "src-" + uuid5(URL ns, uri)[:12]
    def _migrate_sources_columns(self) -> None                            # :1116 — PRAGMA table_info + ALTER TABLE ADD COLUMN, idempotent
    def _doc_to_entry / _entry_to_doc (arango mapping)                    # :1026 / :1042

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
WIKI_SCHEMA_SQL  # CREATE TABLE IF NOT EXISTS sources (source_id PK, source_uri UNIQUE, file_hash, mtime, ingested_at, pages_generated, status, destination, decision_source, charter_version, composite_score)   :58-70

# From packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                                    # :54
    # self._sources = SourceCollectionManager(config.storage_dir/"sources", db_path=config.storage_dir/"wiki.db")  :153-156 (sqlite)
    async def ingest_obsidian_vault(self, wiki_name, vault_path, ..., incremental: bool = False, extract_entities=...)  # :295 — incremental → loader.incremental_update(...) uses the manifest  :333-338
    async def rebuild_index(self, wiki_name: str) -> dict[str, Any]       # :1314

# From agents/fireflies_wiki.py  (gitignored path — commit with `git add -f`)
@register_agent(name="fireflies_wiki", at_startup=True)
class FirefliesWikiAgent(FirefliesObsidianAgent):                        # :107
    self._wiki: Optional[LLMWikiToolkit]  (None when the plane failed to build)   # :180
    async def configure(self, app=None) -> None                           # :209 — super().configure(app) then _build_wiki_toolkit()
    async def _build_wiki_toolkit(self) -> Optional[Any]                  # :349 — WikiConfig(wiki_name, storage_dir=self.wiki_storage_dir, sync_graph=True)
    async def sync_meetings_to_wiki(self, limit=None, analysis_limit=None) -> Dict   # :519 — sync → summarize → _ingest_vault_into_wiki
    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]              # :583 — ingest_obsidian_vault(wiki_name, str(vault_path/meetings_folder), incremental=True, ...)

# From packages/ai-parrot/src/parrot/agents/conf.py
FIREFLIES_WIKI_STORAGE_DIR: str   # :152 — default ~/.parrot/wikis/meetings
FIREFLIES_WIKI_SYNC_LIMIT / ANALYSIS_LIMIT: int                         # :185-186
FIREFLIES_WIKI_DAILY_WINDOW_DAYS / WEEKLY_WINDOW_DAYS: int              # :187-188
def schedule_tzinfo() -> timezone | ZoneInfo                              # :90
```

#### Verified Imports
```python
from parrot.knowledge.wiki import SourceCollectionManager, SourceManifestEntry   # wiki/__init__.py:52-53 (lazy map)
from parrot.knowledge.wiki.sources import SourceCollectionManager              # sources.py:96
from parrot.knowledge.wiki.models import SourceManifestEntry, WikiConfig        # models.py:155
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                        # toolkit.py:54
from parrot.agents.obsidian import FirefliesObsidianAgent                       # used by agents/fireflies_wiki.py:64
from parrot.tools.obsidian import ObsidianToolkit                               # tools/obsidian.py
from parrot.agents.conf import FIREFLIES_WIKI_STORAGE_DIR                      # conf.py:152
```

#### Key Attributes & Constants
- `SourceManifestEntry.source_uri` is UNIQUE and is the *vault-note path* for notes registered by the vault ingest (`sources.py:205-224`).
- `SourceCollectionManager.backend` ∈ `{"sqlite","json","arangodb"}` (`sources.py:161`); the meeting agents use sqlite, keyed on `wiki.db` under the storage dir.
- `ObsidianToolkit.allowed_operations` in the parent agent is `{"read","list","search","create","update"}` (`agents/obsidian.py:224-230`) — `"move"` and `"delete"` are **not** enabled today; this feature adds both (repair → `move_note`, duplicate merge → `delete_note`).
- `FirefliesObsidianAgent.ANALYSIS_HEADING == "## Analysis"` (referenced `agents/obsidian.py:720`).
- The wiki manifest's staleness rule is *file* mtime + SHA-1 (`sources.py:479-527`) — distinct from the transcript fingerprint introduced here.

### Does NOT Exist (Anti-Hallucination)
- ~~`SourceManifestEntry.external_id`~~ / ~~`SourceCollectionManager.find_by_external_id()`~~ — **to be added** by this feature; do not assume present.
- ~~a "14-day window" constant in the agent~~ — the sync window is whatever `FirefliesFilters.from_date` / `default_filters` say; there is no hard-coded 14-day default in `agents/obsidian.py`.
- ~~`FirefliesObsidianAgent.storage_dir` / `registry`~~ — the parent has no storage-dir concept today; only the subclass has `wiki_storage_dir`.
- ~~server-side "exclude processed" / `since_id` on the Fireflies MCP `fireflies_get_transcripts`~~ — only `fromDate`/`toDate`/participants-style filters exist (`_filters_to_tool_args`, `agents/obsidian.py:85-118`).
- ~~a `SourceCollectionManager` method that registers a source without a real file~~ — `add_source` and `record_decision` both take a `Path` that must exist; the note must be written first.
- ~~`ObsidianToolkit.rename_note`~~ — the verb is `move_note` (`tools/obsidian.py:538`).
- ~~a `parrot/knowledge/graphindex/toolkit.py` module~~ — the GraphIndex toolkit is built via `parrot.knowledge.graphindex.factory.build_graph_memory_toolkit`.

---

## Parallelism Assessment

- **Internal parallelism**: two independent lanes — (1) the core
  `external_id` column/lookups in `parrot/knowledge/wiki/` with its own
  tests, and (2) the `MeetingRegistry` facade + fingerprint helpers, which
  can be developed against a stubbed manager. Lane (3), rewiring the agent
  sync/summarize loops and the wiki agent, depends on both.
- **Cross-feature independence**: touches `sources.py` / `models.py` /
  `store.py`, which the supervised-ingestion (FEAT-402) and document
  metadata (FEAT-451) features also own — both are completed. No known
  in-flight spec edits `agents/obsidian.py`; the `audio-notes-obsidian`
  feature (TASK-2378/2380, completed) shares `agents/fireflies_wiki.py`.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the core column change is small and the facade is useless
  until the agent loop is rewired; a single worktree with sequential tasks
  (core → facade → agent → wiki agent → docs) avoids a three-way merge on
  `sources.py` and `obsidian.py` for a gain of maybe one day.

---

## Open Questions

- [x] Regular feature or hotfix, and base branch? — *Owner: Jesus Lara*: feature on `dev`.
- [x] New registry class or reuse `SourceCollectionManager`? — *Owner: Jesus Lara*: reuse the manager.
- [x] How is reuse realised given the manager is path-keyed? — *Owner: Jesus Lara*: additive nullable `external_id` column + `find_by_external_id()`; meeting state in `doc_metadata`.
- [x] Where does the registry come from when the parent agent has no wiki? — *Owner: Jesus Lara*: the parent opens a standalone `SourceCollectionManager` on the storage dir's `wiki.db`; the wiki toolkit later shares the same file.
- [x] Revise policy when a known transcript's content changes? — *Owner: Jesus Lara*: update the note body in place, drop `## Analysis`, reset analysis to pending.
- [x] Fingerprint algorithm? — *Owner: Jesus Lara*: sha256 of the normalised transcript text; Fireflies summary hashed separately; `file_hash` untouched.
- [x] Registry scope — sync + analysis only, or also the wiki mark? — *Owner: Jesus Lara*: full lifecycle, including `wiki_ingested_at`.
- [x] Should `"move"` be added to the parent's `ObsidianToolkit.allowed_operations` so path repair can *also* re-normalise a renamed note back to the `YYYY-MM-DD-slug` convention? — *Owner: Jesus Lara*: yes — enable `"move"`; repair may move the note back to the canonical path.
- [x] Defaults for `FIREFLIES_SYNC_OVERLAP_DAYS` (proposed 2) and `FIREFLIES_RECHECK_DAYS` (proposed 7)? — *Owner: Jesus Lara*: Fireflies changes are not observed beyond ~2 days after a meeting; keep overlap=2, recheck=7 as a generous ceiling.
- [x] Should the Telegram `sync` command expose `--force-refetch`? — *Owner: Jesus Lara*: yes.
- [x] Backfill duplicates (two notes, one id): report-only, or a `merge_duplicates` verb? — *Owner: Jesus Lara*: merge duplicates, **always with a report** of what was kept/removed.
- [x] Should the `external_id` convention be the general pattern for other external sources (Jira, audio notes)? — *Owner: Jesus Lara*: yes — document `<source>:<id>` as the convention; migrating Jira/audio-notes callers is follow-up work, not this feature.
