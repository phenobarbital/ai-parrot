# TASK-2555: Registry backfill, duplicate merge, and path repair

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Spec**: `sdd/specs/fireflies-meeting-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2554
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, §2 "Backfill" and "Sync loop" step 3, §7 Known Risks
("Deleting notes during merge", "source_id is uuid5 of the original path").
Existing vaults must migrate without duplicating anything (G8), and renamed
notes must be repaired (G7). These are the only verbs that move or delete
files; they are limited to `meetings_folder` and always reported.

---

## Scope

Implement in `parrot/agents/meeting_registry.py` (replacing the TASK-2554 stubs):

- `backfill_from_vault(*, toolkit, meetings_folder, analysis_heading, merge=True) -> BackfillReport`
  - No-op (`seeded=0`) when any `fireflies:*` row already exists.
  - `list_notes(folder=meetings_folder, recursive=False)` → `read_notes` in chunks
    of 50 → parse frontmatter `fireflies_id`; notes without it are ignored.
  - Group by id. Single note → `add_source(path, external_id=…)` +
    `doc_metadata.fireflies` with `fingerprint=None`, `summary_fingerprint=None`,
    `analysis_status = "done" if analysis_heading in body else "pending"`,
    `title/meeting_date/participants/duration_minutes/synced_at` from frontmatter
    (`title`, `date`, `participants`, `duration_minutes`, `synced_at`; fall back to
    the filename's `YYYY-MM-DD` prefix and `""`).
  - Multiple notes → `merge_duplicates(...)` when `merge=True`; when `merge=False`
    register nothing for that id and list it in `unmerged`.
  - Unparsable frontmatter → `unmerged`, never deleted.
  - Progress log every 500 notes; INFO summary at the end.
- `merge_duplicates(fireflies_id, paths, *, toolkit, meetings_folder, analysis_heading) -> MergeResult`
  - Keep rule: the note whose body contains `analysis_heading`; if several or
    none, the newest by mtime.
  - If the kept note is not at the canonical path
    (`{meetings_folder}/{_make_note_title(date, title)}.md`) and that path is free
    (not on disk, not in the registry under another id) → `move_note`.
  - `delete_note` the others; register the kept one as in backfill; return
    `MergeResult(kept, removed)`; INFO log per id.
- `repair_path(fireflies_id, *, toolkit, meetings_folder, canonical_title) -> RepairResult`
  - Row's `source_uri` exists → `RepairResult(moved=False, from=to=uri)`.
  - Otherwise scan the folder's frontmatter for the id (same chunked reader);
    found → if canonical path free → `move_note`, then `update_source_uri`;
    else `update_source_uri` to the found path only. Not found →
    `RepairResult(to_path=None)` (caller creates).
- Tests in `tests/test_meeting_registry.py`.

**NOT in scope**: calling these from the agent (TASK-2556); enabling `"move"`/`"delete"`
on the agent's toolkit (TASK-2556) — tests construct their own `ObsidianToolkit`
with all operations allowed.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/meeting_registry.py` | MODIFY | three verbs + `_scan_frontmatter` helper |
| `tests/test_meeting_registry.py` | MODIFY | backfill / merge / repair tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.agents.meeting_registry import MeetingRegistry, BackfillReport, MergeResult, RepairResult   # TASK-2554
from parrot.tools.obsidian import ObsidianToolkit                          # tools/obsidian.py
from parrot.agents.obsidian import FirefliesObsidianAgent                 # agents/obsidian.py:185 — for _make_note_title (staticmethod)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):
    def __init__(self, vault_path: str, backend: str = "local", allowed_operations: set[str] = ..., ...)   # ctor used at agents/obsidian.py:220-230
    async def read_note(self, path: str, include_content: bool = True) -> Dict[str, Any]            # :212 — returns dict with "content" and parsed frontmatter ("metadata"/"frontmatter" — VERIFY the key name by reading :212-228 before use)
    async def read_notes(self, paths: list[str], include_content: bool = True) -> Dict[str, Any]    # :229 — max 50 paths
    async def list_notes(self, folder=..., recursive=...) -> Dict[str, Any]                          # :257 — {"notes": [{"path","name","size","mtime"}...]}
    async def create_note(self, path, content, frontmatter=None) -> Dict[str, Any]                  # :439
    async def update_note(self, path, content, preserve_frontmatter=True) -> Dict[str, Any]         # :471
    async def delete_note(self, path: str) -> Dict[str, Any]                                        # :522
    async def move_note(self, source: str, destination: str) -> Dict[str, Any]                      # :538

# packages/ai-parrot/src/parrot/agents/obsidian.py
class FirefliesObsidianAgent:
    @staticmethod def _make_note_title(date: str, meeting_title: str) -> str      # :929 — "YYYY-MM-DD-<slug>"
    ANALYSIS_HEADING   # "## Analysis" (used :720)
    async def _get_existing_meeting_titles(self) -> set[str]                      # :893 — shows how list_notes output is consumed (file stem from "title"/"name"/"path")

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py (after TASK-2553)
def add_source(self, path, *, external_id=None); def update_source_uri(self, source_id, new_uri)
def find_by_external_id(self, external_id); def list_by_external_prefix(self, prefix); def find_by_uri(self, uri)
```

### Does NOT Exist
- ~~`ObsidianToolkit.rename_note`~~ — use `move_note`.
- ~~a frontmatter-indexed search on the toolkit (e.g. `find_by_frontmatter`)~~ — scan with `read_notes`.
- ~~`read_notes` accepting more than 50 paths~~ — chunk.
- ~~`SourceCollectionManager.add_source` for a missing file~~ — the kept note must exist on disk before registering.

---

## Implementation Notes

### Pattern to Follow
Chunked reader:
```python
paths = [n["path"] for n in listing["notes"]]
for i in range(0, len(paths), 50):
    batch = await toolkit.read_notes(paths[i:i+50], include_content=True)
    ...
    if (i // 50) % 10 == 0: self.logger.info("backfill: %d/%d notes scanned", i, len(paths))
```

### Key Constraints
- Never delete a note whose frontmatter failed to parse.
- Never move/delete outside `meetings_folder` (assert the path prefix).
- All decisions logged at INFO with the id.
- `merge=False` is a dry run: report only.

### References in Codebase
- `agents/obsidian.py:893-927` — list_notes consumption
- spec §7 Known Risks — merge and repair safety rules

---

## Acceptance Criteria

- [ ] `pytest tests/test_meeting_registry.py -v` passes; `ruff check` clean.
- [ ] Backfill on a fixture vault (5 notes, one duplicated id, one without analysis) → 4 rows, `fingerprint=None`, analysis status correct, one `MergeResult`; second call `seeded == 0`.
- [ ] Merge keeps the analysed note (else newest), moves it to the canonical path when free, deletes the rest, returns an itemised `MergeResult`.
- [ ] Unparsable frontmatter → listed in `unmerged`, file untouched.
- [ ] `merge=False` → duplicates reported, nothing deleted or registered for that id.
- [ ] Repair: moved note found by frontmatter → `move_note` called, `source_uri` updated, `source_id` unchanged; canonical path owned by another id → no move, registry updated; not found → `to_path=None`.

---

## Test Specification

```python
# tests/test_meeting_registry.py (additions)
@pytest.fixture
def vault(tmp_path): ...   # meetings/ with 5 notes: ids a,b,c,c(dup),d ; d without ## Analysis ; one note with broken frontmatter
@pytest.fixture
def toolkit(vault): return ObsidianToolkit(vault_path=str(vault), backend="local", allowed_operations={"read","list","search","create","update","move","delete"})

async def test_backfill_seeds_from_frontmatter(registry, toolkit): ...
async def test_backfill_idempotent(registry, toolkit): ...
async def test_backfill_dry_run_reports_only(registry, toolkit): ...
async def test_merge_duplicates_keeps_analysed(registry, toolkit): ...
async def test_merge_duplicates_unparsable_left(registry, toolkit): ...
async def test_repair_path_moves_to_canonical(registry, toolkit): ...
async def test_repair_path_canonical_taken_by_other_id(registry, toolkit): ...
async def test_repair_path_not_found(registry, toolkit): ...
```

---

## Agent Instructions

1. Read spec §2 Backfill + §7; 2. confirm TASK-2554 completed; 3. verify contract (especially the `read_note` frontmatter key name); 4. mark in-progress; 5. implement; 6. tests; 7. move to completed; 8. mark done; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-29
**Notes**: Implemented `backfill_from_vault`, `merge_duplicates`, and
`repair_path` in `parrot/agents/meeting_registry.py`, replacing the
TASK-2554 `NotImplementedError` stubs, plus internal helpers `_vault_root`
(resolves the toolkit's local-backend absolute vault path — the only way
to convert vault-relative `ObsidianToolkit` paths to the absolute paths
`SourceCollectionManager` requires, since none of the three signatures
carry a `vault_path` parameter), `_date_from_filename` (`YYYY-MM-DD`
fallback), and `_register_from_frontmatter` (shared registration logic
for both backfill's single-note case and merge's kept note).
`backfill_from_vault` is a no-op when any `fireflies:*` row already
exists, chunks `read_notes` in batches of 50, groups by `fireflies_id`,
routes single notes straight to registration and duplicate groups to
`merge_duplicates` (or `unmerged` when `merge=False`), and logs progress
every 500 notes plus an INFO summary. `merge_duplicates` picks the
analysed note (else newest by mtime) among only the notes `read_notes`
could actually parse — a note it could not even decode is never a keep
or delete candidate, matching "never deletes unparsable frontmatter";
duplicates are deleted before the canonical-path move is attempted so a
duplicate that already occupies the canonical slot doesn't block it;
registry ownership of the canonical path is checked (and skipped only
when owned by a genuinely different id — a stale row for the SAME
meeting must not block its own repair) before `move_note`, with a
`FileExistsError` fallback. `repair_path` scans the folder's frontmatter
via the same chunked reader when `source_uri` no longer exists, applying
the identical "free = not on disk AND not owned by another id" rule
before `update_source_uri` (which keeps `source_id`). 28 tests in
`tests/test_meeting_registry.py` cover: backfill seeding (4 rows from 5
notes + 1 unreadable file, one `MergeResult`, correct `without_analysis`
count), idempotency, dry-run (`merge=False`), merge keeping the analysed
note and moving it to its canonical path (including a variant where the
kept note starts at a non-canonical filename), merge leaving an
unreadable duplicate untouched, and repair's three outcomes (moved,
blocked by another id's ownership, not found). All pass; `ruff check`
clean.

**Deviations from spec**: None from the task's own scope. One judgment
call, flagged for spec-author awareness: the task's Codebase Contract
gives `backfill_from_vault`/`merge_duplicates`/`repair_path` signatures
with no `vault_path` parameter, yet converting the vault-relative paths
`ObsidianToolkit` returns into the absolute paths `SourceCollectionManager`
requires needs the vault root. Resolved via `toolkit.vault.vault_path` —
a public (non-underscore) attribute of the local vault backend
(`interfaces/obsidian/local.py:43`), not explicitly listed in this task's
"Existing Signatures to Use" but the only way to honor the mandated
signatures without adding a new parameter. `_vault_root` raises a clear
`RuntimeError` if ever called against the REST backend (which has no
`vault_path`), so this narrowing is explicit rather than silent.
