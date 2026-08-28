# TASK-2554: `MeetingRegistry` facade, models, fingerprint helpers, and conf constants

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Spec**: `sdd/specs/fireflies-meeting-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2553
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, §2 Data Models and New Public Interfaces. This is the
meeting-shaped async layer over `SourceCollectionManager`: classify a Fireflies
listing item as `create | skip | revise`, record sync/analysis/wiki state in
`doc_metadata["fireflies"]`, and suggest the sync window. No agent code changes
here — TASK-2556 wires it in.

---

## Scope

- Create `packages/ai-parrot/src/parrot/agents/meeting_registry.py` with:
  - Constants `EXTERNAL_ID_PREFIX = "fireflies:"`, `DOC_METADATA_KEY = "fireflies"`.
  - Pydantic models exactly as spec §2: `MeetingRecord`, `Classified`,
    `RepairResult`, `MergeResult`, `BackfillReport`, plus the `Classification`
    / `AnalysisStatus` literals.
  - Pure functions `normalise_transcript(text) -> str` (strip BOM, `\r\n`→`\n`,
    rstrip each line, collapse >2 consecutive blank lines to 2, strip
    leading/trailing blank lines) and `fingerprint(text) -> str` (sha256 hex of
    the normalised UTF-8 bytes).
  - `class MeetingRegistry` with `__init__(registry_dir, *, manager=None)`,
    `available` property, and the verbs `lookup`, `classify`, `record_synced`,
    `pending_analysis`, `mark_analyzed`, `mark_analysis_failed`,
    `mark_wiki_ingested`, `suggest_from_date`, `unique_slug`, `forget`.
    (`repair_path`, `backfill_from_vault`, `merge_duplicates` are stubs raising
    `NotImplementedError` here — implemented by TASK-2555.)
  - Every manager call via `asyncio.to_thread`; every `doc_metadata` write is a
    read-merge-write that preserves other keys.
  - `classify` semantics (spec §2 "Sync loop" step 2): unknown → `create`; row
    `status == "rejected"` → `skip`; cheap skip when listing `title/date/duration`
    all present and unchanged, `synced_at` younger than `recheck_days`, and not
    `force_refetch`; otherwise call `fetch(id)` (and `fetch_summary(id)` if
    provided), fingerprint, compare; equal → `skip`, different or stored `None` →
    `revise`. Fill `probable_duplicate_of` with other `external_id`s sharing the
    fingerprint (scan `list_by_external_prefix`).
  - `record_synced`: if the URI is untracked → `add_source(path, external_id=…)`;
    if tracked by URI but without `external_id` → `set_external_id`; then merge
    the `fireflies` block via `record_document_metadata`. `reset_analysis=True`
    sets `analysis_status="pending"`, `analysis_fingerprint=None`.
  - `pending_analysis`: rows with `analysis_status != "done"` **or**
    `analysis_fingerprint != fingerprint`, excluding `status == "rejected"`.
  - `mark_wiki_ingested(at=None) -> int`: stamp rows whose manifest entry has
    non-empty `pages_generated` and is not stale (`entry_is_stale`); return count.
  - `suggest_from_date(overlap_days)`: `max(synced_at)` date minus overlap, ISO
    `YYYY-MM-DD`, or `None` when no rows.
  - `unique_slug(meetings_folder, base_title, vault_path)`: `-2`, `-3`… suffix
    while the path is in the registry (by URI) **or** exists on disk.
  - `forget(id, reject=False)`: `reject=False` → `remove_source`; `reject=True` →
    keep row with `status="rejected"`.
  - `available` becomes `False` (with one WARNING log) if the manager raises
    `sqlite3.Error`/`OSError` at construction or on first use; verbs then return
    neutral values (`lookup → None`, `classify → create`, etc.) rather than raise.
- `parrot/agents/conf.py`: `FIREFLIES_REGISTRY_DIR` (default =
  `FIREFLIES_WIKI_STORAGE_DIR`), `FIREFLIES_SYNC_OVERLAP_DAYS` (int, 2),
  `FIREFLIES_RECHECK_DAYS` (int, 7); add to `__all__`.
- Tests: `tests/test_meeting_registry.py`.

**NOT in scope**: backfill / merge / repair bodies (TASK-2555); any change to
`agents/obsidian.py` (TASK-2556).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/meeting_registry.py` | CREATE | models, helpers, facade |
| `packages/ai-parrot/src/parrot/agents/conf.py` | MODIFY | three constants |
| `tests/test_meeting_registry.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.sources import SourceCollectionManager        # sources.py:96
from parrot.knowledge.wiki.models import SourceManifestEntry             # models.py:155
from parrot.agents.conf import FIREFLIES_WIKI_STORAGE_DIR                # conf.py:152
from parrot.tools.obsidian import ObsidianToolkit                        # tools/obsidian.py (type hints only in this task)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py  (after TASK-2553)
class SourceCollectionManager:
    def __init__(self, sources_dir: Path, db_path: Path | None = None, backend="sqlite", ...)   # :121
    def add_source(self, path: Path, *, external_id: str | None = None) -> SourceManifestEntry  # TASK-2553
    def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None              # TASK-2553
    def find_entries_by_external_ids(self, ids: list[str]) -> dict[str, SourceManifestEntry]   # TASK-2553
    def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]                # TASK-2553
    def set_external_id(self, source_id: str, external_id: str | None) -> SourceManifestEntry | None   # TASK-2553
    def update_source_uri(self, source_id: str, new_uri) -> SourceManifestEntry | None         # TASK-2553
    def find_by_uri(self, source_uri: str) -> str | None                                       # :737
    def get_source(self, source_id: str) -> SourceManifestEntry | None                         # :457
    def entry_is_stale(self, entry: SourceManifestEntry) -> bool                               # :496
    def record_document_metadata(self, source_id, *, doc_metadata, content_type, loader) -> None   # :663 — never creates; pass content_type/loader from the existing entry to avoid clobbering
    def remove_source(self, source_id: str) -> bool                                            # :708

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):                # :155
    source_id, source_uri, file_hash, mtime, ingested_at, pages_generated: list[str], status: str
    doc_metadata: dict[str, Any] | None; content_type: str | None; loader: str | None
    external_id: str | None                          # TASK-2553

# packages/ai-parrot/src/parrot/agents/conf.py
FIREFLIES_WIKI_STORAGE_DIR: str = config.get("FIREFLIES_WIKI_STORAGE_DIR", fallback=...)   # :152-155
FIREFLIES_WIKI_SYNC_LIMIT: int = config.getint(...)                                       # :185 — pattern for the new int constants
__all__ list includes "FIREFLIES_WIKI_STORAGE_DIR"                                        # :49

# Fireflies listing item shape (from FirefliesObsidianAgent._parse_fireflies_response, agents/obsidian.py:783-866)
#   {"id": str, "title": str, "date": str (ISO, may contain "T"), "participants": list[str], "duration": float|int}
```

### Does NOT Exist
- ~~`parrot.agents.meeting_registry`~~ — this task creates it.
- ~~`SourceCollectionManager` async methods for sqlite/json~~ — all sync; wrap with `asyncio.to_thread`.
- ~~`record_document_metadata` creating a row~~ — it only updates; register first.
- ~~`FIREFLIES_REGISTRY_DIR`, `FIREFLIES_SYNC_OVERLAP_DAYS`, `FIREFLIES_RECHECK_DAYS`~~ — this task creates them.
- ~~a Fireflies content hash in the listing~~ — the listing has no hash; the cheap skip relies on `title/date/duration` only.

---

## Implementation Notes

### Pattern to Follow
```python
# every manager call
entry = await asyncio.to_thread(self._manager.find_by_external_id, external_id)

# doc_metadata merge
existing = dict(entry.doc_metadata or {})
existing[DOC_METADATA_KEY] = {**existing.get(DOC_METADATA_KEY, {}), **patch}
await asyncio.to_thread(self._manager.record_document_metadata, entry.source_id,
                        doc_metadata=existing, content_type=entry.content_type, loader=entry.loader)
```

### Key Constraints
- Timestamps ISO-8601 UTC (`datetime.now(UTC).isoformat()`); `meeting_date` is `date[:10]` like `_make_note_title` does (`agents/obsidian.py:936-943`).
- `fingerprint` must ignore the Fireflies summary: callers pass transcript text only; the summary is fingerprinted separately.
- Never raise from a verb when `available` is False.
- Google-style docstrings, strict typing, `self.logger`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` — manager
- `packages/ai-parrot/src/parrot/agents/obsidian.py:929-957` — `_make_note_title` slug rules (reuse via import in `unique_slug`)

---

## Acceptance Criteria

- [ ] `pytest tests/test_meeting_registry.py -v` passes; `ruff check packages/ai-parrot/src/parrot/agents/`
- [ ] `from parrot.agents.meeting_registry import MeetingRegistry, fingerprint, normalise_transcript` works.
- [ ] Normalisation rules produce equal fingerprints for CRLF/BOM/trailing-space variants.
- [ ] `classify`: unknown → create (fetch called once); cheap skip → fetch **not** called; recheck window expiry → fetch; changed hash → revise; `fingerprint=None` → fetch; `force_refetch` bypasses cheap skip; `status="rejected"` → skip.
- [ ] `probable_duplicate_of` populated when another id shares the fingerprint.
- [ ] `record_synced` preserves unrelated `doc_metadata` keys.
- [ ] `pending_analysis` returns pending / failed / stale-fingerprint rows only.
- [ ] `suggest_from_date` = max date − overlap; `None` on empty.
- [ ] `unique_slug` suffixes on registry **and** filesystem collisions.
- [ ] `mark_wiki_ingested` stamps only rows with non-empty `pages_generated` and not stale.
- [ ] `available=False` path: constructor with an unwritable dir logs once and verbs return neutral values.
- [ ] The three conf constants exist, are typed, and are exported in `__all__`.

---

## Test Specification

```python
# tests/test_meeting_registry.py
import pytest
from parrot.agents.meeting_registry import MeetingRegistry, fingerprint, normalise_transcript

@pytest.fixture
def registry(tmp_path): return MeetingRegistry(tmp_path / "wiki")
@pytest.fixture
def note(tmp_path):
    p = tmp_path / "vault" / "meetings" / "2026-08-28-standup.md"; p.parent.mkdir(parents=True); p.write_text("---\nfireflies_id: abc\n---\nbody"); return p

def test_normalise_transcript_rules(): ...
def test_fingerprint_ignores_summary(): ...
async def test_classify_unknown_id_creates(registry): ...
async def test_classify_cheap_skip_no_fetch(registry, note): ...
async def test_classify_recheck_window_fetches(registry, note): ...
async def test_classify_changed_content_revises(registry, note): ...
async def test_classify_backfilled_none_fingerprint_fetches(registry, note): ...
async def test_classify_force_refetch(registry, note): ...
async def test_classify_rejected_row_skips(registry, note): ...
async def test_probable_duplicate_reported(registry, tmp_path): ...
async def test_pending_analysis_selection(registry, tmp_path): ...
async def test_record_synced_merges_doc_metadata(registry, note): ...
async def test_suggest_from_date(registry, tmp_path): ...
async def test_unique_slug_suffixes(registry, tmp_path): ...
async def test_mark_wiki_ingested_only_ingested_rows(registry, tmp_path): ...
async def test_unavailable_registry_degrades(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. Read the spec §2 (Data Models, New Public Interfaces) and §7; 2. confirm TASK-2553 is in `sdd/tasks/completed/`; 3. verify the contract; 4. mark in-progress; 5. implement; 6. run tests; 7. move file to completed; 8. mark done; 9. Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
