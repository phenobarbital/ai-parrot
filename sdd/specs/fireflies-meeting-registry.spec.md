---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Fireflies Meeting Registry — id-keyed dedup for the Fireflies → Obsidian → Wiki sync

**Feature ID**: FEAT-472
**Date**: 2026-08-29
**Author**: Jesus Lara (spec: Claude session 2026-08-29)
**Status**: approved
**Target version**: next minor
**Input**: `sdd/proposals/fireflies-meeting-registry.brainstorm.md` (status `exploration`, Recommended Option A, all 12 open questions resolved)
**Related**: `sdd/references/obsidian-wiki-operating-contract.md` §14 "Deduplication and Source Identity" and §25 "Processed Source Registry" — the operating contract for the future knowledgebase agent; this feature implements the code-side registry that contract assumes (see §7 Known Risks for the one documented divergence).

---

## 1. Motivation & Business Requirements

### Problem Statement

`FirefliesObsidianAgent.sync_fireflies_transcripts()` decides whether a
Fireflies transcript is "already synced" by **note title**, not by the
transcript's id (`packages/ai-parrot/src/parrot/agents/obsidian.py:399-416`):
it lists the file stems in `meetings_folder` and skips a transcript when
`_make_note_title(date, title)` is already among them. The Fireflies id is
written into every note (`fireflies_id` frontmatter, `:462`; OKF
`node_id = obsidian::fireflies::<id>`, `:743`) but is **never read back**.

That breaks in four real situations:

| Situation | Today's behaviour |
|---|---|
| Meeting title edited in Fireflies after the first sync | New slug → **duplicate note** |
| Two meetings on the same day with the same title (recurring standups) | Second one **silently skipped** |
| Note renamed/moved inside Obsidian | Re-synced as a **new note** |
| Transcript re-finalised by Fireflies (late summary, corrected speakers) | **Never picked up** — "exists" is binary |

Analysis state has the same weakness: `summarize_pending_transcripts()`
(`:593-676`) re-reads every candidate note and greps for the `## Analysis`
heading (`_has_analysis`, `:697`). Nothing records *which version* of the
transcript an analysis was computed against, so a revised transcript keeps
its stale analysis forever.

The `FirefliesWikiAgent` (`agents/fireflies_wiki.py`) runs this sync
unattended every morning and feeds the result into the LLM Wiki. The
operating contract being drafted for the next-generation knowledgebase
agent names **registry ∪ Raw as the authoritative dedup gate**, keyed
`fireflies:<meeting-id>` with SHA-256 content hashes — and there is no
such registry in code today.

**Who is affected**: operators of the Fireflies agents (duplicate or
missed meetings in the vault and wiki) and every downstream consumer —
daily/weekly digests, `ingest_obsidian_vault`, the audio-notes flow
sharing the vault.

### Goals

- **G1** Identity of a synced meeting is the immutable Fireflies transcript
  id, stored as `external_id = "fireflies:<id>"`; the note title/path is a
  display key that may change.
- **G2** Reuse `SourceCollectionManager` as the persistence layer with a
  single additive, nullable, indexed `external_id` column — no new
  registry store, no behavioural change for existing callers, sqlite /
  json / arangodb parity.
- **G3** Every listing item is classified deterministically as
  `create | skip | revise`, driven by a **content-only** SHA-256
  fingerprint of the normalised transcript (Fireflies native summary
  hashed separately).
- **G4** `revise` updates the existing note **in place** (frontmatter
  preserved, `## Analysis` dropped, analysis reset to pending). Never a
  second file for a known id.
- **G5** The registry works with or without the wiki plane: the parent
  agent opens the manager on `<registry_dir>/wiki.db`; the subclass's
  `LLMWikiToolkit` opens the same file, so both see one table.
- **G6** Full lifecycle per meeting in one row: synced → analysed
  (with the fingerprint the analysis was computed against) → wiki-ingested.
- **G7** Renamed/moved notes are repaired: moved back to the canonical
  `{meetings_folder}/{YYYY-MM-DD-slug}.md` path (unless that path belongs
  to a different id) and re-registered; every move is reported.
- **G8** An existing vault migrates automatically and idempotently: on
  first open, the registry is seeded from note frontmatter; duplicate
  notes for one id are **merged** (one kept, others deleted) with an
  itemised report.
- **G9** The registry drives the sync window
  (`from_date = max(synced_at) − FIREFLIES_SYNC_OVERLAP_DAYS`, cold start
  = today's behaviour); a cheap no-fetch skip path avoids re-downloading
  unchanged transcripts, and `force_refetch` (parameter + Telegram
  `/sync force_refetch=true`) disables it.
- **G10** No regression: with the registry unavailable the sync falls
  back to today's title-based behaviour for that run; all new parameters
  default to current semantics.

### Non-Goals (explicitly out of scope)

- A standalone registry class or table separate from the wiki `sources`
  manifest (brainstorm Options B and C rejected — see
  `proposals/fireflies-meeting-registry.brainstorm.md`).
- Migrating other external-source ingests (Jira `jira_sync.py`, audio
  notes) to `external_id`. The `<source>:<id>` convention is documented
  here as the pattern they should adopt; doing so is follow-up work.
- The knowledgebase agent's Review Queue / `Raw/Processed/Revisions`
  bundle layout from the operating contract. This feature is the
  code-side registry the contract assumes; the contract's Markdown
  `processed-sources.md` mirror and revision review flow are that agent's
  concern.
- Testing against a live ArangoDB (unit-tested through sqlite; the Arango
  document mapping is covered by the existing round-trip tests).
- Slack/Teams surfaces; only the Telegram `/sync` command is added.
- Changing `FirefliesObsidianAgent`'s Fireflies MCP bootstrap, note
  authoring format, or `_build_okf_frontmatter`.

---

## 2. Architectural Design

### Overview

A `MeetingRegistry` facade (`parrot/agents/meeting_registry.py`) wraps a
`SourceCollectionManager` opened on `<registry_dir>/wiki.db` with
meeting-shaped async verbs. Persistence is the existing wiki `sources`
table extended with one additive nullable column, `external_id`
(`"fireflies:<transcript_id>"`), plus indexed lookups; all
meeting-specific state (transcript fingerprint, summary fingerprint,
analysis status + fingerprint, wiki-ingested timestamp, meeting date,
participants, last error) lives in the existing `doc_metadata` JSON
column under a `fireflies` key, written through
`record_document_metadata`.

Because the vault ingest (`LLMWikiToolkit.ingest_obsidian_vault`,
`incremental=True`) already registers every meeting note in the same
table by path, the two writers share one row: the sync sets
`external_id` + `doc_metadata.fireflies`, the ingest fills
`pages_generated` / `file_hash` / `mtime`. The manager's file-level
staleness (SHA-1 + mtime of the *note file*, `sources.py:479-527`) and
this feature's *transcript* fingerprint are two hashes with different
purposes on one row; §7 documents this clearly.

**Sync loop** (`sync_fireflies_transcripts`, rewired):

1. `from_date` (when neither the call nor `default_filters` supplies one)
   ← `registry.suggest_from_date()` = `max(synced_at) −
   FIREFLIES_SYNC_OVERLAP_DAYS` (default 2; the user observes no Fireflies
   changes later than ~2 days after a meeting). No rows → no `from_date`
   (today's behaviour).
2. For each listing item → `registry.classify(item, force_refetch)`:
   - id unknown → `create`.
   - id known, listing `title/date/duration` unchanged, `synced_at`
     younger than `FIREFLIES_RECHECK_DAYS` (default 7), and not
     `force_refetch` → `skip` **without fetching** the transcript.
   - otherwise fetch the transcript, normalise, SHA-256:
     equal to stored fingerprint → `skip`; different or stored `None`
     (backfilled row) → `revise`.
   - Additionally (operating contract §14.3 "hash match, different ID"):
     if the new fingerprint equals the fingerprint of a *different*
     `external_id`, the item is still processed but listed under
     `report["probable_duplicates"]` as `{id, matches}`.
3. Repair before `create`/`revise`: if the row's `source_uri` no longer
   exists, scan meetings-folder frontmatter for the id (`read_notes`,
   chunks of 50); found → `move_note` to the canonical path when free
   (else keep the user's path), update `source_uri`, append to
   `report["repaired"]`; not found → `create`.
4. Write:
   - `create`: slug de-duplicated against the registry *and* the
     filesystem (`-2`, `-3`, …), `create_note`, then
     `record_synced()` → `add_source(path)` + `external_id` +
     `doc_metadata.fireflies`.
   - `revise`: body rebuilt from the fresh transcript (+ optional
     Fireflies summary), `update_note(preserve_frontmatter=True)`,
     frontmatter `title/participants/synced_at` refreshed, then
     `record_synced()` with the new fingerprint, `analysis_status =
     "pending"`, `analysis_fingerprint = None`.
5. Report gains `revised`, `repaired`, `duplicates`, `probable_duplicates`,
   `from_date`, `registry` (`"ok" | "unavailable"`).

**Analysis loop** (`summarize_pending_transcripts`, rewired): when
`note_titles is None`, candidates come from `registry.pending_analysis()`
— rows with `analysis_status != "done"` **or** `analysis_fingerprint !=
fingerprint`. Success → `mark_analyzed(id, fingerprint)`; failure →
`analysis_status = "failed"`, `last_error`. `force=True` re-analyses
regardless. `_has_analysis()` survives only as the fallback when the
registry is unavailable.

**Wiki step** (`FirefliesWikiAgent.sync_meetings_to_wiki`): after
`_ingest_vault_into_wiki()` succeeds, `registry.mark_wiki_ingested()`
stamps `wiki_ingested_at` on every fireflies row whose manifest entry has
non-empty `pages_generated` and is not stale.

**Backfill** (`configure()`, once): if the table has no `fireflies:*`
rows and the meetings folder is non-empty → bulk-read frontmatter,
register each note by path with `external_id`, `fingerprint = None`,
`analysis_status` from the presence of `## Analysis`. Ids with more than
one note → `merge_duplicates()`: keep the note carrying an `## Analysis`
(newest by mtime otherwise), move it to the canonical path if needed,
`delete_note` the rest, itemise in `report["duplicates"]` as
`{id, kept, removed[]}`; unparsable notes are left alone under
`report["unmerged"]`. Logged at INFO per id — never silent.

**Toolkit permissions**: the parent's `ObsidianToolkit` gains `"move"`
and `"delete"` in `allowed_operations`; both verbs are used only by
repair and merge and only inside `meetings_folder`.

**Telegram**: `FirefliesWikiAgent` gains
`@telegram_command("sync", parse_mode="keyword")` →
`sync_now(force_refetch: str = "false", limit: str = "")`, which runs
`sync_meetings_to_wiki()` with the flags and replies with a compact
summary line.

### Component Diagram

```
Fireflies MCP ──listing──▶ FirefliesObsidianAgent.sync_fireflies_transcripts
                              │
                              ├─ registry.suggest_from_date() ─────────────┐
                              ├─ registry.classify(item) ─▶ create|skip|revise
                              ├─ registry.repair_path(id) ─▶ ObsidianToolkit.move_note
                              ├─ ObsidianToolkit.create_note / update_note
                              └─ registry.record_synced(...)               │
                                        │                                  │
                              MeetingRegistry (facade, asyncio.to_thread)  │
                                        │                                  │
                              SourceCollectionManager ── sources table ◀───┘
                              (<registry_dir>/wiki.db, + external_id column,
                               doc_metadata.fireflies JSON)
                                        ▲                 ▲
   summarize_pending_transcripts ───────┘                 │
     registry.pending_analysis() / mark_analyzed()        │
                                                          │
   FirefliesWikiAgent.sync_meetings_to_wiki               │
     └─ LLMWikiToolkit.ingest_obsidian_vault(incremental) ─┘  (same wiki.db, fills pages_generated)
     └─ registry.mark_wiki_ingested()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/models.py::SourceManifestEntry` | extends | `external_id: str \| None = None` |
| `parrot/knowledge/wiki/sources.py::SourceCollectionManager` | extends | `_SOURCES_EXTERNAL_COLUMNS` migration map, 15-column upsert, `external_id` kwarg on `add_source`/`record_decision`, `find_by_external_id`, `find_entries_by_external_ids`, `list_by_external_prefix`, `set_external_id`, `update_source_uri`; Arango `_entry_to_doc`/`_doc_to_entry` mapping |
| `parrot/knowledge/wiki/store.py::WIKI_SCHEMA_SQL` | extends | `external_id TEXT` + `CREATE INDEX IF NOT EXISTS idx_sources_external_id` on fresh DBs (migration covers old ones) |
| `parrot/agents/obsidian.py::FirefliesObsidianAgent` | modifies | ctor `registry_dir`, `configure()` opens registry + backfill, sync/summarize loops, `force_refetch`, `allowed_operations` += `move`, `delete`, report schema |
| `parrot/agents/conf.py` | extends | `FIREFLIES_REGISTRY_DIR` (default = `FIREFLIES_WIKI_STORAGE_DIR`), `FIREFLIES_SYNC_OVERLAP_DAYS=2`, `FIREFLIES_RECHECK_DAYS=7` |
| `agents/fireflies_wiki.py::FirefliesWikiAgent` | modifies | `mark_wiki_ingested()` after ingest; new `/sync` Telegram command; `git add -f` |
| `parrot/tools/obsidian.py::ObsidianToolkit` | uses | `create_note`, `update_note`, `move_note`, `delete_note`, `read_notes`, `list_notes` — unchanged |
| `LLMWikiToolkit.ingest_obsidian_vault` | shares data | unchanged; writes `pages_generated` on the same rows |
| `docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md` | docs | note id-keyed dedup and the `/sync` command |

### Data Models

```python
# parrot/agents/meeting_registry.py  (new)
from typing import Literal, Optional
from pydantic import BaseModel, Field

EXTERNAL_ID_PREFIX = "fireflies:"          # operating contract §14.1 preferred format

Classification = Literal["create", "skip", "revise"]
AnalysisStatus = Literal["pending", "done", "failed"]


class MeetingRecord(BaseModel):
    """Meeting-side view of one `sources` row (doc_metadata['fireflies'] + external_id)."""
    fireflies_id: str
    external_id: str                          # f"fireflies:{fireflies_id}"
    source_id: str                            # manager's row id (uuid5 of the ORIGINAL path)
    note_path: str                            # == SourceManifestEntry.source_uri
    title: str
    meeting_date: str                         # YYYY-MM-DD
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    fingerprint: Optional[str] = None         # sha256 of normalised transcript; None after backfill
    summary_fingerprint: Optional[str] = None # sha256 of Fireflies native summary
    synced_at: str                            # ISO-8601 UTC
    analysis_status: AnalysisStatus = "pending"
    analysis_fingerprint: Optional[str] = None
    wiki_ingested_at: Optional[str] = None
    last_error: Optional[str] = None


class Classified(BaseModel):
    action: Classification
    record: Optional[MeetingRecord] = None    # existing row for skip/revise
    fetched_text: Optional[str] = None        # transcript text when a fetch was needed
    fingerprint: Optional[str] = None
    summary_fingerprint: Optional[str] = None
    probable_duplicate_of: list[str] = Field(default_factory=list)  # other external_ids with same fingerprint


class RepairResult(BaseModel):
    fireflies_id: str
    from_path: Optional[str]
    to_path: Optional[str]                    # None → note not found, caller should create
    moved: bool


class MergeResult(BaseModel):
    fireflies_id: str
    kept: str
    removed: list[str]


class BackfillReport(BaseModel):
    seeded: int
    without_analysis: int
    duplicates: list[MergeResult]
    unmerged: list[str]
```

```sql
-- store.py WIKI_SCHEMA_SQL (fresh databases); sources.py migration adds the
-- column to existing ones via _migrate_sources_columns.
ALTER TABLE sources ADD COLUMN external_id TEXT;            -- nullable
CREATE INDEX IF NOT EXISTS idx_sources_external_id ON sources(external_id);
```

`doc_metadata` layout for a meeting row (JSON, under the existing column):

```json
{"fireflies": {"fireflies_id": "...", "title": "...", "meeting_date": "2026-08-28",
               "participants": ["a@x", "b@x"], "duration_minutes": 42.0,
               "fingerprint": "sha256…", "summary_fingerprint": "sha256…",
               "synced_at": "2026-08-29T07:00:03Z",
               "analysis_status": "done", "analysis_fingerprint": "sha256…",
               "wiki_ingested_at": "2026-08-29T07:05:41Z", "last_error": null}}
```

Other keys already present in `doc_metadata` (FEAT-451 `DocumentMetadata`
written by the ingest) are preserved — the facade merges, never replaces.

### New Public Interfaces

```python
# parrot/knowledge/wiki/sources.py — additions on SourceCollectionManager
def add_source(self, path: Path, *, external_id: str | None = None) -> SourceManifestEntry: ...
def record_decision(self, path: Path, *, destination: str, ..., external_id: str | None = None) -> SourceManifestEntry: ...
def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None: ...
def find_entries_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]: ...   # e.g. "fireflies:"
def set_external_id(self, source_id: str, external_id: str | None) -> SourceManifestEntry | None: ...
def update_source_uri(self, source_id: str, new_uri: Path | str) -> SourceManifestEntry | None: ...
#   ↑ keeps source_id; re-hashes the file at the new path; raises FileNotFoundError if absent

# parrot/agents/meeting_registry.py — new
def normalise_transcript(text: str) -> str: ...        # BOM, CRLF→LF, rstrip lines, collapse >2 blank lines, strip ends
def fingerprint(text: str) -> str: ...                 # sha256(normalise_transcript(text).encode("utf-8")).hexdigest()

class MeetingRegistry:
    def __init__(self, registry_dir: Path, *, manager: SourceCollectionManager | None = None) -> None: ...
    #   default: SourceCollectionManager(registry_dir/"sources", db_path=registry_dir/"wiki.db")
    #   every manager call is dispatched via asyncio.to_thread
    async def lookup(self, fireflies_id: str) -> MeetingRecord | None: ...
    async def classify(self, item: dict, *, fetch: Callable[[str], Awaitable[str]],
                       fetch_summary: Callable[[str], Awaitable[str | None]] | None,
                       force_refetch: bool = False) -> Classified: ...
    async def record_synced(self, *, fireflies_id: str, note_path: Path, title: str, meeting_date: str,
                            participants: list[str], duration_minutes: float,
                            fingerprint: str, summary_fingerprint: str | None,
                            reset_analysis: bool) -> MeetingRecord: ...
    async def pending_analysis(self) -> list[MeetingRecord]: ...
    async def mark_analyzed(self, fireflies_id: str, fingerprint: str) -> None: ...
    async def mark_analysis_failed(self, fireflies_id: str, error: str) -> None: ...
    async def mark_wiki_ingested(self, *, at: str | None = None) -> int: ...   # returns rows stamped
    async def repair_path(self, fireflies_id: str, *, toolkit: ObsidianToolkit,
                          meetings_folder: str, canonical_title: str) -> RepairResult: ...
    async def suggest_from_date(self, *, overlap_days: int) -> str | None: ...   # ISO date or None
    async def backfill_from_vault(self, *, toolkit: ObsidianToolkit, meetings_folder: str,
                                  analysis_heading: str) -> BackfillReport: ...
    async def merge_duplicates(self, fireflies_id: str, paths: list[str], *, toolkit: ObsidianToolkit,
                               meetings_folder: str, analysis_heading: str) -> MergeResult: ...
    async def forget(self, fireflies_id: str, *, reject: bool = False) -> bool: ...
    #   reject=True keeps the row with status="rejected" → classify() returns "skip" forever
    async def unique_slug(self, meetings_folder: str, base_title: str, *, vault_path: Path) -> str: ...
    @property
    def available(self) -> bool: ...

# parrot/agents/obsidian.py — changed signatures
class FirefliesObsidianAgent:
    def __init__(self, name: str = "FirefliesObsidianSync", vault_path=None, fireflies_token=None,
                 meetings_folder: str = "meetings", default_filters=None,
                 registry_dir: Optional[str | Path] = None, **kwargs) -> None: ...
    async def sync_fireflies_transcripts(self, limit: int = 10, skip_existing: bool = True,
                                         filters=None, include_summary: bool = ...,
                                         force_refetch: bool = False) -> Dict[str, Any]: ...
    #   report: {status, synced, revised, skipped, repaired: [...], duplicates: [...],
    #            probable_duplicates: [...], from_date, registry: "ok"|"unavailable", notes: [...], errors: [...]}

# agents/fireflies_wiki.py — new command
@telegram_command("sync", description="Sync Fireflies meetings now", parse_mode="keyword")
async def sync_now(self, force_refetch: str = "false", limit: str = "") -> str: ...
```

---

## 3. Module Breakdown

### Module 1: `external_id` on the wiki sources manifest
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`, `.../wiki/sources.py`, `.../wiki/store.py`
- **Responsibility**: additive nullable `external_id` column + index (fresh DDL and idempotent migration); 15-column upsert; `external_id` kwarg on `add_source` / `record_decision`; `find_by_external_id`, `find_entries_by_external_ids`, `list_by_external_prefix`, `set_external_id`, `update_source_uri`; json-backend and arangodb mapping parity; docstring documenting the `<source>:<id>` convention.
- **Depends on**: nothing new.

### Module 2: `MeetingRegistry` facade + fingerprint helpers
- **Path**: `packages/ai-parrot/src/parrot/agents/meeting_registry.py` (new), `packages/ai-parrot/src/parrot/agents/conf.py`
- **Responsibility**: Pydantic models (§2), `normalise_transcript` / `fingerprint`, all async verbs, `doc_metadata.fireflies` merge semantics, `suggest_from_date`, `unique_slug`, `available` degradation flag; conf constants `FIREFLIES_REGISTRY_DIR`, `FIREFLIES_SYNC_OVERLAP_DAYS`, `FIREFLIES_RECHECK_DAYS`.
- **Depends on**: Module 1.

### Module 3: Backfill and duplicate merge
- **Path**: `packages/ai-parrot/src/parrot/agents/meeting_registry.py`
- **Responsibility**: `backfill_from_vault` (chunked `read_notes`, frontmatter `fireflies_id`, analysis detection, progress logging every 500 notes) and `merge_duplicates` (keep-rule, canonical-path move, `delete_note`, itemised `MergeResult`, `unmerged` for unparsable notes); `repair_path`.
- **Depends on**: Module 2.

### Module 4: Rewire `FirefliesObsidianAgent`
- **Path**: `packages/ai-parrot/src/parrot/agents/obsidian.py`
- **Responsibility**: `registry_dir` ctor arg; `configure()` opens the registry and runs backfill once; `allowed_operations` += `move`, `delete`; sync loop → classify / repair / create-or-revise / record; `force_refetch`; registry-driven `from_date`; new report fields; `summarize_pending_transcripts` → `pending_analysis` / `mark_analyzed` / `mark_analysis_failed`; title-based fallback when `registry.available` is False.
- **Depends on**: Modules 2, 3.

### Module 5: Wiki agent — ingest stamp and `/sync` command
- **Path**: `agents/fireflies_wiki.py` (force-add), `tests/test_fireflies_wiki_agent.py`
- **Responsibility**: call `mark_wiki_ingested()` after a successful `_ingest_vault_into_wiki()`; `@telegram_command("sync", parse_mode="keyword") sync_now(force_refetch, limit)` returning a one-line summary; update the ordering test.
- **Depends on**: Module 4.

### Module 6: Documentation
- **Path**: `docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md`, `docs/` runbook or README section for the Fireflies agents
- **Responsibility**: describe id-keyed dedup, the report fields, the three new env vars, `/sync`, and the `external_id` convention for future sources.
- **Depends on**: Modules 4, 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_migration_adds_external_id_column` | 1 | Opening a pre-existing `wiki.db` without the column adds it + index; idempotent on second open |
| `test_add_source_with_external_id_roundtrip` | 1 | `add_source(path, external_id=…)` → `find_by_external_id` returns the row; json and sqlite backends |
| `test_external_id_survives_mark_ingested` | 1 | `mark_ingested` (which rebuilds the entry) preserves `external_id` and `doc_metadata` |
| `test_update_source_uri_keeps_source_id` | 1 | new path, same `source_id`, hash re-computed; missing file raises `FileNotFoundError` |
| `test_list_by_external_prefix` | 1 | only `fireflies:*` rows returned |
| `test_arango_doc_mapping_external_id` | 1 | `_entry_to_doc` / `_doc_to_entry` round-trip the field |
| `test_normalise_transcript_rules` | 2 | BOM, CRLF, trailing spaces, >2 blank lines, leading/trailing blanks — fingerprints equal |
| `test_fingerprint_ignores_summary` | 2 | same transcript, different summary → same `fingerprint`, different `summary_fingerprint` |
| `test_classify_unknown_id_creates` | 2 | no row → `create`, fetch called once |
| `test_classify_cheap_skip_no_fetch` | 2 | known id, unchanged listing metadata, fresh `synced_at` → `skip`, fetch **not** called |
| `test_classify_recheck_window_fetches` | 2 | `synced_at` older than `FIREFLIES_RECHECK_DAYS` → fetch, equal hash → `skip` |
| `test_classify_changed_content_revises` | 2 | different hash → `revise` |
| `test_classify_backfilled_none_fingerprint_fetches` | 2 | `fingerprint=None` → fetch always |
| `test_classify_force_refetch` | 2 | cheap path bypassed |
| `test_classify_rejected_row_skips` | 2 | `status="rejected"` → `skip` even with new content |
| `test_probable_duplicate_reported` | 2 | same fingerprint under another `external_id` → listed, action unchanged |
| `test_pending_analysis_selection` | 2 | pending, failed, and done-with-stale-fingerprint rows returned; done-current rows not |
| `test_record_synced_merges_doc_metadata` | 2 | pre-existing FEAT-451 keys in `doc_metadata` preserved |
| `test_suggest_from_date` | 2 | `max(synced_at) − overlap`; `None` when empty |
| `test_unique_slug_suffixes` | 2 | registry-known and filesystem-known collisions → `-2`, `-3` |
| `test_backfill_seeds_from_frontmatter` | 3 | fixture vault → rows with `external_id`, `fingerprint=None`, analysis status detected |
| `test_backfill_idempotent` | 3 | second call is a no-op (`seeded == 0`) |
| `test_merge_duplicates_keeps_analysed` | 3 | two notes, one id: analysed one kept, other deleted, `MergeResult` itemised |
| `test_merge_duplicates_unparsable_left` | 3 | bad frontmatter → `unmerged`, nothing deleted |
| `test_repair_path_moves_to_canonical` | 3 | moved note found by frontmatter → `move_note` called, `source_uri` updated |
| `test_repair_path_canonical_taken_by_other_id` | 3 | no move, registry updated only |
| `test_sync_same_id_changed_title_updates_in_place` | 4 | exactly one note; `update_note` called; `create_note` not; analysis reset |
| `test_sync_same_day_same_title_two_ids` | 4 | two notes, second slug `-2` |
| `test_sync_registry_unavailable_falls_back` | 4 | title-based dedup path used; `report["registry"] == "unavailable"` |
| `test_sync_report_fields` | 4 | `revised`, `repaired`, `duplicates`, `probable_duplicates`, `from_date` present |
| `test_sync_from_date_from_registry` | 4 | `fromDate` sent to the MCP equals `suggest_from_date`; explicit filter wins |
| `test_summarize_uses_registry_pending` | 4 | `_has_analysis` not called; `mark_analyzed` called with the fingerprint |
| `test_summarize_failure_marks_failed` | 4 | `analysis_status="failed"`, `last_error` set |
| `test_allowed_operations_include_move_delete` | 4 | parent toolkit permits both verbs |
| `test_sync_meetings_to_wiki_marks_ingested` | 5 | ordering: sync → summarize → ingest → `mark_wiki_ingested` |
| `test_sync_meetings_to_wiki_no_wiki_no_mark` | 5 | wiki `None` → mark not called, run still ok |
| `test_telegram_sync_command_parses_flags` | 5 | `force_refetch="true"` → `sync_meetings_to_wiki(force_refetch=True)`; reply is one line |

### Integration Tests

| Test | Description |
|---|---|
| `test_registry_shared_with_wiki_toolkit` | Parent opens `MeetingRegistry(tmp)`; `LLMWikiToolkit(WikiConfig(storage_dir=tmp))` ingests the same vault; the fireflies row now has both `external_id` and non-empty `pages_generated`; `mark_wiki_ingested` stamps it |
| `test_end_to_end_create_revise_analyse` | Fake Fireflies MCP returns v1 → note created; v2 same id → note updated in place, analysis pending; analyse → done; v2 again → cheap skip |
| `test_existing_vault_upgrade_no_duplicates` | Vault with 5 notes (one duplicated id) and no registry → backfill merges, sync of the same ids creates nothing |

### Test Data / Fixtures

```python
@pytest.fixture
def tmp_registry(tmp_path) -> MeetingRegistry:
    return MeetingRegistry(tmp_path / "wiki")          # sqlite in tmp_path/wiki/wiki.db

@pytest.fixture
def fake_fireflies():
    """Stub for _call_fireflies_tool: listing + get_transcript + get_summary keyed by id, mutable per test."""

@pytest.fixture
def vault(tmp_path) -> Path:
    """meetings/ folder with notes carrying fireflies_id frontmatter; one duplicated id; one without analysis."""

@pytest.fixture
def agent(vault, tmp_registry, fake_fireflies) -> FirefliesObsidianAgent:
    """Agent with a real local ObsidianToolkit on `vault`, registry_dir=tmp, MCP stubbed, no LLM."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit and integration tests in §4 pass (`pytest tests/knowledge/wiki/test_sources.py tests/test_meeting_registry.py tests/test_fireflies_obsidian_sync.py tests/test_fireflies_wiki_agent.py -v`); the pre-existing wiki suite `tests/knowledge/wiki/` still passes.
- [ ] `SourceManifestEntry.external_id` exists, is `None` by default, and existing `wiki.db` files open without error and gain the column + index (G2).
- [ ] `external_id` values use the `<source>:<id>` form; the Fireflies value is exactly `fireflies:<transcript_id>` (G1, contract §14.1).
- [ ] Syncing a transcript whose id is already registered never calls `create_note` — regardless of title change, same-title collision, or note rename (G1, G4, G7).
- [ ] A changed transcript for a known id results in `update_note(preserve_frontmatter=True)` on the existing path, `analysis_status == "pending"`, and `report["revised"] == 1` (G4).
- [ ] Two same-day, same-title transcripts with different ids produce two notes, the second with a `-2` slug suffix.
- [ ] Fingerprint is `sha256` of the normalised transcript only; a change in the Fireflies summary alone does not produce `revise` but does update `summary_fingerprint` (G3).
- [ ] With unchanged listing metadata and `synced_at` younger than `FIREFLIES_RECHECK_DAYS`, `fireflies_get_transcript` is **not** called; with `force_refetch=True` it always is (G9).
- [ ] When no `from_date` is supplied and the registry has rows, the MCP receives `fromDate = max(synced_at) − FIREFLIES_SYNC_OVERLAP_DAYS` (default 2); an explicit filter or `default_filters.from_date` wins; empty registry sends no `fromDate` (G9).
- [ ] `summarize_pending_transcripts()` selects candidates from the registry and never re-analyses a row whose `analysis_fingerprint == fingerprint` unless `force=True` (G6).
- [ ] After a successful vault ingest, `sync_meetings_to_wiki` stamps `wiki_ingested_at` on rows with non-empty `pages_generated`; with `self._wiki is None` it does not (G6).
- [ ] A renamed note is moved back to the canonical path and re-registered; if the canonical path belongs to another id, only the registry is updated; every move appears in `report["repaired"]` (G7).
- [ ] First `configure()` on a vault with no registry rows seeds one row per `fireflies_id` with `fingerprint=None`; the next sync of those ids creates nothing (G8).
- [ ] Duplicate notes for one id are merged — the analysed (else newest) note kept, others deleted — and every merge is present in the backfill report and INFO log; unparsable notes are never deleted (G8).
- [ ] The parent `ObsidianToolkit` `allowed_operations` contains `"move"` and `"delete"`; neither verb is invoked outside `meetings_folder`.
- [ ] `/sync` Telegram command exists on `FirefliesWikiAgent`, accepts `force_refetch=true|false` and `limit=<n>`, and replies with a single summary line.
- [ ] With the registry unavailable (simulated `sqlite3.OperationalError`), the sync completes using title-based dedup and `report["registry"] == "unavailable"`; no exception escapes (G10).
- [ ] Every new parameter defaults to current behaviour: existing callers of `sync_fireflies_transcripts` and `summarize_pending_transcripts` need no change (G10).
- [ ] The vault ingest and the registry share rows: after both run on one `wiki.db`, the fireflies row has `external_id`, `doc_metadata.fireflies`, and non-empty `pages_generated` (G5).
- [ ] `doc_metadata` keys written by FEAT-451 are preserved by every registry write.
- [ ] Docs updated (design doc + env vars + `/sync` + convention); Google-style docstrings and strict type hints on all new code; no `print`, no blocking I/O in async paths (manager calls via `asyncio.to_thread`).
- [ ] `agents/fireflies_wiki.py` committed with `git add -f`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-29 against `dev` (post-rebase on `origin/dev`, HEAD `905938d27`).

### Verified Imports
```python
from parrot.knowledge.wiki import SourceCollectionManager, SourceManifestEntry   # lazy map, wiki/__init__.py:52-53
from parrot.knowledge.wiki.sources import SourceCollectionManager               # sources.py:96
from parrot.knowledge.wiki.models import SourceManifestEntry, WikiConfig        # models.py:155
from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL                         # store.py (imported at sources.py:189)
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                        # toolkit.py:54
from parrot.agents.obsidian import FirefliesObsidianAgent, FirefliesFilters     # agents/obsidian.py:185 / :~50
from parrot.tools.obsidian import ObsidianToolkit                               # tools/obsidian.py
from parrot.agents.conf import FIREFLIES_WIKI_STORAGE_DIR, schedule_tzinfo      # conf.py:152 / :90
from parrot.integrations.telegram.decorators import telegram_command            # decorators.py:5 (used at agents/fireflies_wiki.py:66)
from parrot.registry import register_agent                                      # used at agents/fireflies_wiki.py:78
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/agents/obsidian.py
class FirefliesFilters(BaseModel):                                       # :~50-84
    from_date: Optional[str] = None       # :59 → tool arg "fromDate" (:102)
    to_date: Optional[str] = None         # :62
    keyword: Optional[str]                # :65
    scope: Literal["title","sentences","all"] = "all"   # :68
    organizers: List[EmailStr]            # :71
    participants: List[EmailStr]          # :74
    mine: Optional[bool]                  # :77
    channel_id: Optional[str]             # :80
def _filters_to_tool_args(filters: "FirefliesFilters") -> Dict[str, Any]   # :85
def _merge_filters(default, override)                                      # :120

class FirefliesObsidianAgent(...):
    def __init__(self, name="FirefliesObsidianSync", vault_path=None, fireflies_token=None,
                 meetings_folder="meetings", default_filters=None, **kwargs)     # :185
    self.vault_path: Path                                                    # :211-215
    self.meetings_folder: str; self.default_filters                          # :216-217
    self.obsidian_toolkit = ObsidianToolkit(vault_path=str(self.vault_path), backend="local",
        allowed_operations={"read","list","search","create","update"})       # :220-230
    self.logger                                                              # :233
    async def configure(self, app=None) -> None                              # :235
    async def _ensure_fireflies_mcp(self) -> None                            # :263
    async def sync_fireflies_transcripts(self, limit=..., skip_existing: bool = True, filters=..., include_summary=...) -> Dict[str, Any]  # :287-292
        # report = {"status", "synced": 0, "skipped": 0, "notes": [], "errors": []}          :340-346
        # effective_filters = _merge_filters(self.default_filters, filters)                  :352-354
        # existing_titles = await self._get_existing_meeting_titles()                        :399-401
        # transcript_id = transcript.get("id"); title; date                                  :406-408
        # note_title = self._make_note_title(date, title); skip if in existing_titles        :411-416
        # fireflies_get_transcript {"transcriptId": id} → transcript_text                    :419-428
        # fireflies_get_summary (optional) → _append_fireflies_summary_section               :436-458
        # metadata = {"fireflies_id","date","title","participants","duration_minutes","synced_at"}  :461-468
        # okf_metadata = self._build_okf_frontmatter(...)                                    :471-477
        # create_note(path=f"{meetings_folder}/{note_title}.md", content, frontmatter)       :485-489
        # report["synced"] += 1                                                              :492
    async def summarize_transcript(self, note_title: str, granularity: str = "standard") -> Dict[str, Any]   # :506
    async def summarize_pending_transcripts(self, note_titles=None, granularity="standard", limit=None, force=False) -> Dict[str, Any]  # :593
        # outcome = {"status","analyzed": [],"skipped": [],"errors": []}                    :621-626
        # candidates = sorted(await self._get_existing_meeting_titles())                    :630
        # if not force and await self._has_analysis(note_title): skip                       :649
    @classmethod def _strip_analysis_section(cls, content: str) -> str                     # :677
    async def _has_analysis(self, note_title: str) -> bool                                 # :697 — reads note, checks self.ANALYSIS_HEADING (:720)
    @staticmethod def _build_okf_frontmatter(fireflies_id, title, date, participants, duration) -> Dict  # :721
        # node_id = f"obsidian::fireflies::{fireflies_id}"  :743 ; resource = f"fireflies://transcript/{id}"  :745
    @staticmethod def _parse_fireflies_response(response_text: str) -> List[Dict[str, Any]]  # :783 — dicts with "id","title","date",participants…
    async def _call_fireflies_tool(self, name, args)                                       # :867
    async def _get_existing_meeting_titles(self) -> set[str]                               # :893 — list_notes(folder=meetings_folder, recursive=False) → file stems
    @staticmethod def _make_note_title(date: str, meeting_title: str) -> str               # :929 — "YYYY-MM-DD-<slug>"
    @staticmethod def _append_fireflies_summary_section(transcript: str, summary_text: str) -> str  # :1071

# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):
    async def read_note(self, path: str, include_content: bool = True) -> Dict[str, Any]              # :212
    async def read_notes(self, paths: list[str], include_content: bool = True) -> Dict[str, Any]      # :229 — max 50/call
    async def list_notes(self, folder=..., recursive=...) -> Dict[str, Any]                            # :257 — {"notes": [VaultFileInfo dicts: path/name/size/mtime]}
    async def create_note(self, path: str, content: str, frontmatter: Optional[Dict[str, Any]] = None) -> Dict[str, Any]   # :439 — fails if exists
    async def update_note(self, path: str, content: str, preserve_frontmatter: bool = True) -> Dict[str, Any]              # :471
    async def delete_note(self, path: str) -> Dict[str, Any]                                          # :522
    async def move_note(self, source: str, destination: str) -> Dict[str, Any]                        # :538

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):                                                  # :155
    source_id: str; source_uri: str; file_hash: str; mtime: float; ingested_at: str    # :195-199
    pages_generated: list[str]; status: str                                            # :200-…
    destination, decision_source, charter_version: str | None; composite_score: float | None   # FEAT-402
    doc_metadata: dict[str, Any] | None; content_type: str | None; loader: str | None  # FEAT-451

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
_SOURCES_UPSERT_SQL   # 14-column INSERT … ON CONFLICT(source_id) DO UPDATE           :50-67 → becomes 15 columns
_SQLITE_IN_CHUNK = 500                                                                 # :72
_SOURCES_DECISION_COLUMNS / _SOURCES_DOCUMENT_COLUMNS: dict[str, str]                  # :83-95 — add _SOURCES_EXTERNAL_COLUMNS = {"external_id": "TEXT"}
class SourceCollectionManager:                                                         # :96
    def __init__(self, sources_dir: Path, db_path: Path | None = None,
                 backend: Literal["sqlite","json","arangodb"] = "sqlite",
                 arango_db=None, arango_store=None) -> None                             # :121 — sqlite: executescript(WIKI_SCHEMA_SQL); _migrate_sources_columns(); _migrate_json_manifest()  :188-194
    def add_source(self, path: Path) -> SourceManifestEntry                            # :205 — FileNotFoundError if missing; id = existing-by-uri or uuid5(uri)
    def find_entries_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]  # :260
    def find_entries_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]   # :301
    def add_sources(...)                                                               # :339
    def mark_ingested_many(...)                                                        # :400
    def list_sources(self) -> list[SourceManifestEntry]                                # :442
    def get_source(self, source_id: str) -> SourceManifestEntry | None                 # :457
    def is_stale(self, source_id: str) -> bool                                         # :475
    def entry_is_stale(self, entry: SourceManifestEntry) -> bool                       # :496 — file gone / mtime + SHA-1
    def mark_ingested(self, source_id: str, pages_generated: list[str], status="ingested") -> SourceManifestEntry | None   # :533 — REBUILDS the entry from 7 fields (drops FEAT-402/451 fields and would drop external_id) — Module 1 must fix this to preserve them
    def record_decision(self, path: Path, *, destination: str, decision_source=None, charter_version=None, composite_score=None, pages_generated=None, status=None) -> SourceManifestEntry   # :570
    def record_document_metadata(self, source_id: str, *, doc_metadata: dict | None, content_type: str | None, loader: str | None) -> None   # :663 — never creates
    def remove_source(self, source_id: str) -> bool                                     # :708
    def find_by_uri(self, source_uri: str) -> str | None                                # :737
    def _connect(self) -> sqlite3.Connection                                            # :752
    def _upsert(self, entry) / _upsert_many(self, entries)                              # :764 / :776 — both use _SOURCES_UPSERT_SQL
    @staticmethod def _entry_params(entry) -> tuple                                     # :800 — bind order for the upsert
    @staticmethod def _optional_column(row, name)                                       # :820
    @staticmethod def _row_to_entry(row) -> SourceManifestEntry                         # :841
    def _compute_hash(self, path: Path) -> str                                          # :870 — SHA-1 of file bytes
    def _generate_source_id(self, source_uri: str) -> str                               # :887 — "src-" + uuid5(NAMESPACE_URL, uri).hex[:12]
    def _find_id_by_uri(self, source_uri: str) -> str | None                            # :902
    def _run_async(self, coro)                                                          # :922 (arango bridge)
    @staticmethod def _doc_to_entry(doc) -> SourceManifestEntry                         # :1026
    @staticmethod def _entry_to_doc(entry) -> dict                                       # :1042
    def _migrate_sources_columns(self) -> None                                          # :1116 — PRAGMA table_info + ALTER TABLE ADD COLUMN per map; idempotent
    def _migrate_json_manifest(self) -> None                                            # :1134
    def _load_manifest(self) -> None                                                    # :1170 (json backend)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
WIKI_SCHEMA_SQL   # CREATE TABLE IF NOT EXISTS sources (source_id PK, source_uri UNIQUE, file_hash, mtime, ingested_at, pages_generated, status, destination, decision_source, charter_version, composite_score)   :58-70

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                                                  # :54
    # sqlite: self._sources = SourceCollectionManager(config.storage_dir/"sources", db_path=config.storage_dir/"wiki.db")   :153-156
    # arangodb / other: :157-177
    async def ingest_obsidian_vault(self, wiki_name, vault_path, ..., incremental: bool = False, extract_entities=...)   # :295 — incremental → loader.incremental_update(self._pi, wiki_name, self._sources)  :333-338
    async def rebuild_index(self, wiki_name: str) -> dict[str, Any]                    # :1314

# agents/fireflies_wiki.py   (gitignored path — `git add -f`)
@register_agent(name="fireflies_wiki", at_startup=True)
class FirefliesWikiAgent(FirefliesObsidianAgent):                                      # :107
    self._wiki: Optional[LLMWikiToolkit]                                               # :180 — None when the plane failed to build
    async def configure(self, app=None) -> None                                        # :209 — super().configure(app); self._wiki = await self._build_wiki_toolkit()  :225
    @telegram_command("note", description="Capture the next message as a note")
    async def arm_note_mode(self, _args: str = "") -> str                              # :260-261 — the ONLY telegram command today
    async def _build_wiki_toolkit(self) -> Optional[Any]                               # :349 — WikiConfig(wiki_name=self.wiki_name, storage_dir=self.wiki_storage_dir, sync_graph=True)  :376-380
    async def sync_meetings_to_wiki(self, limit=None, analysis_limit=None) -> Dict     # :519 — sync (:556) → summarize (:562) → _ingest_vault_into_wiki (:571)
    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]                          # :583 — ingest_obsidian_vault(self.wiki_name, str(self.vault_path/self.meetings_folder), incremental=True, extract_entities=FIREFLIES_WIKI_EXTRACT_ENTITIES)  :607-612

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py
def telegram_command(command: str, description: str = "", parse_mode: str = "keyword") -> Callable   # :5-8
    # parse_mode "keyword": `/cmd key=val` → method(**kwargs) — all values arrive as str   :19

# packages/ai-parrot/src/parrot/agents/conf.py
FIREFLIES_WIKI_STORAGE_DIR: str   # :152 — default ~/.parrot/wikis/meetings
FIREFLIES_WIKI_SYNC_LIMIT / FIREFLIES_WIKI_ANALYSIS_LIMIT: int                         # :185-186
FIREFLIES_WIKI_DAILY_WINDOW_DAYS / WEEKLY_WINDOW_DAYS: int                             # :187-188
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MeetingRegistry.__init__` | `SourceCollectionManager(sources_dir, db_path=…)` | constructor | `sources.py:121` |
| `MeetingRegistry.record_synced` | `add_source(path, external_id=…)` + `record_document_metadata(...)` | thread-pool call | `sources.py:205`, `:663` |
| `MeetingRegistry.lookup` | `find_by_external_id` (new, Module 1) | thread-pool call | `sources.py` (new) |
| `MeetingRegistry.repair_path` | `ObsidianToolkit.move_note` + `update_source_uri` (new) | method calls | `tools/obsidian.py:538` |
| `MeetingRegistry.merge_duplicates` | `ObsidianToolkit.delete_note`, `read_notes` | method calls | `tools/obsidian.py:522`, `:229` |
| `FirefliesObsidianAgent.sync_fireflies_transcripts` | `registry.classify / repair_path / record_synced / suggest_from_date` | replaces `:399-416`, wraps `:485-492` | `agents/obsidian.py` |
| `FirefliesObsidianAgent.summarize_pending_transcripts` | `registry.pending_analysis / mark_analyzed / mark_analysis_failed` | replaces `:630`, `:649` | `agents/obsidian.py` |
| `FirefliesWikiAgent.sync_meetings_to_wiki` | `registry.mark_wiki_ingested` | after `:571` | `agents/fireflies_wiki.py` |
| `FirefliesWikiAgent.sync_now` | `sync_meetings_to_wiki(limit, force_refetch)` | `@telegram_command("sync")` | `decorators.py:5` |
| Vault ingest (unchanged) | same `sources` rows | `loader.incremental_update(..., self._sources)` | `toolkit.py:333-338` |

### Does NOT Exist (Anti-Hallucination)
- ~~`SourceManifestEntry.external_id`~~, ~~`find_by_external_id`~~, ~~`find_entries_by_external_ids`~~, ~~`list_by_external_prefix`~~, ~~`set_external_id`~~, ~~`update_source_uri`~~ — **created by Module 1**; not present today.
- ~~`parrot.agents.meeting_registry`~~ / ~~`MeetingRegistry`~~ — **created by Module 2**.
- ~~a Telegram `sync` command on either Fireflies agent~~ — only `/note` exists (`agents/fireflies_wiki.py:260`); **created by Module 5**.
- ~~`FirefliesObsidianAgent.registry_dir` / `.registry` / `.storage_dir`~~ — the parent has no storage-dir concept today; only the subclass has `wiki_storage_dir`.
- ~~`sync_fireflies_transcripts(force_refetch=…)`~~ — parameter does not exist yet.
- ~~a hard-coded 14-day window in the agent~~ — the window is whatever `FirefliesFilters.from_date` / `default_filters` say.
- ~~server-side "exclude processed" / `since_id` on `fireflies_get_transcripts`~~ — only `fromDate`/`toDate`/keyword/participant-style filters (`_filters_to_tool_args`, `agents/obsidian.py:85-118`).
- ~~a `SourceCollectionManager` method that registers a source without a real file~~ — `add_source` and `record_decision` both require the path to exist; the note must be written first.
- ~~`ObsidianToolkit.rename_note`~~ — the verb is `move_note`.
- ~~`parrot/knowledge/graphindex/toolkit.py`~~ — GraphIndex toolkit comes from `parrot.knowledge.graphindex.factory.build_graph_memory_toolkit`.
- ~~`"move"` / `"delete"` in the parent's `allowed_operations`~~ — not enabled today; Module 4 adds them.
- ~~`tests/test_meeting_registry.py`, `tests/test_fireflies_obsidian_sync.py`~~ — new test files; existing related tests are `tests/test_fireflies_wiki_agent.py` and `tests/knowledge/wiki/test_sources.py` (+ `test_sources_arango.py`).
- ~~`Wiki/Registry/processed-sources.md`~~ — the operating contract's Markdown registry mirror belongs to the future knowledgebase agent, not this feature.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Manager calls are synchronous by design (`sources.py` module docstring); the facade must wrap every call in `asyncio.to_thread` — never call the manager directly from a coroutine.
- Column additions follow the FEAT-402/FEAT-451 precedent exactly: a `dict[str, str]` map consumed by `_migrate_sources_columns`, the fresh DDL in `store.py`, one more `?` and bind value in `_SOURCES_UPSERT_SQL` / `_entry_params`, `_row_to_entry` via `_optional_column`, and the Arango `_entry_to_doc` / `_doc_to_entry` pair. Keep the 15-column statement defined once.
- **`mark_ingested` rebuilds the entry from seven fields (`sources.py:544-556`)** — it already drops FEAT-402/451 columns on a re-ingest. Module 1 must change it (and `mark_ingested_many`) to `model_copy(update=…)` so `external_id` and `doc_metadata` survive the nightly ingest; add a regression test (`test_external_id_survives_mark_ingested`).
- `doc_metadata` writes are a **merge**: read the row, `{**existing, "fireflies": {...}}`, write back. Never replace the dict.
- The `external_id` convention is `<source>:<id>` (contract §14.1). Document it in the `SourceCollectionManager` class docstring so Jira/audio-notes can follow.
- Reports never raise; scheduled callers depend on a dict (`agents/fireflies_wiki.py` design doc, "Error handling").
- Telegram keyword args arrive as strings; parse `"true"/"1"/"yes"` case-insensitively.
- Timestamps in ISO-8601 UTC (`datetime.now(UTC)`), matching `SourceManifestEntry.ingested_at`.
- Google-style docstrings, strict type hints, Pydantic models, `self.logger`.

### Known Risks / Gotchas
- **Two hashes on one row.** `file_hash` (SHA-1 of the note file, used by the vault ingest's staleness) and `doc_metadata.fireflies.fingerprint` (SHA-256 of the transcript text, used by classify) are different things. An analysis append changes `file_hash` (correct — the wiki must re-ingest) but not `fingerprint` (correct — the transcript did not change). Document in both docstrings.
- **Divergence from the operating contract §14.3.** The contract routes "same id, changed content" to a Review Queue and never auto-merges; this feature (brainstorm-resolved) updates the note in place because the vault *is* the raw layer for the existing sync agent and its analysis is regenerated. The knowledgebase agent can layer the review flow on top by consuming `report["revised"]`. Recorded in §8.
- **Deleting notes during merge.** Only inside `meetings_folder`, only for ids with >1 note, only when frontmatter parses, always reported. A dry-run flag (`merge=False`) on `backfill_from_vault` is cheap insurance — include it.
- **Registry row exists, note deleted by the user.** Repair finds nothing → `create` re-writes the note. `forget(id, reject=True)` marks the row `status="rejected"` so classify returns `skip` permanently.
- **Concurrent runs** (07:00 job + `/sync`). WAL sqlite keeps writes safe; `unique_slug` consults the registry so two concurrent creates of one id resolve to one note — the loser's `create_note` raises "exists" and is reported as `skipped`.
- **Cheap-skip correctness** depends on the listing carrying `title`, `date`, `duration`. If any is missing, fall through to fetch.
- **Backfill on a large vault** — `read_notes` is capped at 50 per call; chunk and log progress every 500 notes.
- **`source_id` is uuid5 of the *original* path.** After a repair move, `source_id` stays and `source_uri` changes (`update_source_uri`). The vault ingest's next `add_source(new_path)` must find the row by URI — it does (`_find_id_by_uri`) — so no second row is created. Test this in `test_registry_shared_with_wiki_toolkit`.
- **Registry unavailable** (locked db, permission error): log once, set `available=False`, fall back to title-based dedup for that run, `report["registry"]="unavailable"`. Never abort.
- **Arango backend**: `find_by_external_id` becomes an AQL filter; not exercised against a live server in CI.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `sqlite3` (stdlib) | — | manager persistence (WAL) |
| `hashlib` (stdlib) | — | SHA-256 fingerprint |
| `pydantic` | `>=2` (already required) | `MeetingRecord` & friends, `external_id` on `SourceManifestEntry` |

No new third-party dependencies.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `.claude/worktrees/feat-472-fireflies-meeting-registry` branched from
  `dev`, tasks run sequentially.
- **Order**: Module 1 → 2 → 3 → 4 → 5 → 6. Modules 1 and 2 *could* be
  built in parallel against a stubbed manager, but the gain (≈ one day)
  does not justify a three-way merge on `sources.py` and `obsidian.py`.
- **Cross-feature dependencies**: none must merge first. Shared files
  with completed features only: `sources.py` / `models.py` / `store.py`
  (FEAT-402, FEAT-451), `agents/fireflies_wiki.py` (FEAT-452). The
  in-flight `fireflies-wiki-knowledgebase-agent` brainstorm
  (`origin/dev` `0f814adac`) *depends on* this registry conceptually but
  touches no shared code yet; coordinate the `external_id` naming
  (`fireflies:<id>`) with it — already aligned with its contract §14.1.

---

## 8. Open Questions

> Resolved items are carried from the brainstorm verbatim; nothing below is re-asked.

- [x] Regular feature or hotfix, and base branch? — *Resolved in brainstorm*: feature on `dev`.
- [x] New registry class or reuse `SourceCollectionManager`? — *Resolved in brainstorm*: reuse the manager.
- [x] How is reuse realised given the manager is path-keyed? — *Resolved in brainstorm*: additive nullable `external_id` column + `find_by_external_id()`; meeting state in `doc_metadata`. → §2 Overview, Module 1.
- [x] Where does the registry come from when the parent agent has no wiki? — *Resolved in brainstorm*: the parent opens a standalone `SourceCollectionManager` on the storage dir's `wiki.db`; the wiki toolkit later shares the same file. → G5, `registry_dir`, `FIREFLIES_REGISTRY_DIR`.
- [x] Revise policy when a known transcript's content changes? — *Resolved in brainstorm*: update the note body in place, drop `## Analysis`, reset analysis to pending. → G4 (see §7 for the documented divergence from contract §14.3).
- [x] Fingerprint algorithm? — *Resolved in brainstorm*: sha256 of the normalised transcript text; Fireflies summary hashed separately; `file_hash` untouched. → G3, `normalise_transcript`.
- [x] Registry scope — sync + analysis only, or also the wiki mark? — *Resolved in brainstorm*: full lifecycle, including `wiki_ingested_at`. → G6, Module 5.
- [x] Enable `"move"` so repair can re-normalise renamed notes? — *Resolved in brainstorm*: yes — enable `"move"`; repair may move the note back to the canonical path. → G7, Module 4.
- [x] Defaults for overlap / recheck days? — *Resolved in brainstorm*: Fireflies changes are not observed beyond ~2 days after a meeting; keep overlap=2, recheck=7 as a generous ceiling. → G9, conf constants.
- [x] Telegram `--force-refetch`? — *Resolved in brainstorm*: yes. → since no Telegram `sync` command exists today, Module 5 adds `/sync force_refetch=true|false limit=<n>` (keyword parse mode).
- [x] Backfill duplicates: report-only or merge? — *Resolved in brainstorm*: merge duplicates, always with a report of what was kept/removed. → G8, Module 3 (plus a `merge=False` dry-run flag as insurance).
- [x] `external_id` as the general convention for other sources? — *Resolved in brainstorm*: yes — document `<source>:<id>`; migrating Jira/audio-notes callers is follow-up work. → Non-Goals, §7 Patterns.
- [x] Should the knowledgebase agent (`fireflies-wiki-knowledgebase-agent` brainstorm) consume `report["revised"]` to file `source-revision` review items, or should this registry gain a `revision_policy` switch (`in_place | review`) later? Decide when that agent is specced — not blocking. — *Owner: Jesus Lara*: resolve during build
- [x] Should the Markdown mirror `Wiki/Registry/processed-sources.md` (contract §25) be generated from this registry by a future exporter (`list_by_external_prefix("fireflies:")` → one line per row)? Not blocking. — *Owner: Jesus Lara*: Yes.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-29 | Jesus Lara / Claude | Initial draft from brainstorm (Option A, 12 resolved questions) |
