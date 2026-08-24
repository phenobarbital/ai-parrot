# TASK-2466: Sync engine — `wiki/sync.py` (push/pull, LWW, author filter, note merge)

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2462, TASK-2465
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (Sync v1) + §3 Module 5 (engine half). Moves authored
knowledge — memory pages (`origin="memory"`), attributed notes, and
`asserted` edges — between the local sqlite plane and a shared ArangoDB
plane. Explicit directions (push/pull), last-write-wins by `updated_at`,
author-filtered pull, append-if-absent note merge, full bookkeeper audit.
The CLI wiring is TASK-2467; this task delivers the engine + unit tests.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` with:
  - `SyncReport(BaseModel)`: `direction: Literal["push","pull"]`, `env: str`,
    `created: int`, `updated: int`, `skipped_older: int`, `skipped_own: int`,
    `dry_run: bool` (plus an optional `details: list[str]` for per-record
    lines).
  - `async def sync_push(root: Path, *, target_env: str = "dev",
    dry_run: bool = False, local_identity: str | None = None) -> SyncReport`
  - `async def sync_pull(root: Path, *, target_env: str = "dev",
    include_own: bool = False, dry_run: bool = False,
    local_identity: str | None = None) -> SyncReport`
- Plane opening: LOCAL = effective config for env `"local"`
  (`load_effective_config(root, env="local")`); REMOTE = effective config
  for `target_env` + `resolve_arango_params(config)` — the remote plane must
  be `backend="arangodb"` (or, in tests, any `BaseWikiStore` — the engine
  talks ONLY `BaseWikiStore` APIs, never raw drivers).
- Record selection: `list_pages(origin=["memory"])` on the source, plus
  `asserted`-provenance edges touching those pages. Repo-scan (`ingest`)
  pages are NEVER synced. (Authored notes ride along inside page bodies —
  see note merge.)
- LWW: compare per `concept_id` by `updated_at` (ISO-8601 lexicographic);
  source strictly newer → upsert at destination PRESERVING the source
  `updated_at` (TASK-2465 semantics); equal/older → count `skipped_older`.
  Missing at destination → `created`.
- Pull author filter: when `include_own` is False, skip source records whose
  `asserted_by` == the local identity → count `skipped_own`. Default
  `local_identity`: `f"human:{getpass.getuser()}"` AND any `agent:` identity
  configured for this repo — v1 rule: skip records whose `asserted_by`
  matches the provided/derived identity string exactly; the CLI (TASK-2467)
  passes it explicitly.
- Note merge (append-if-absent): notes are blockquote lines appended to page
  bodies in the format `> **Note (YYYY-MM-DD, <author>):** <text>` (see
  contract — tools.py:373-375). When BOTH sides have the page, parse each
  side's note lines, key them by hash(author + date + text), and write the
  union (date-ordered, stable) into the winning body — never drop a note
  present on either side; non-note body content follows LWW.
- Edges: sync `asserted` edges whose src is a synced memory page — insert
  missing at destination via `add_edges` (4-tuples
  `(src, dst, rel, provenance)` as used by toolkit.py:993).
- `dry_run=True`: compute the full report, apply NOTHING, log NOTHING.
- Audit: every APPLIED change logged via `WikiBookkeeper().log_operation(
  wiki_dir, "SYNC_PUSH"|"SYNC_PULL", details)` (signature in contract).
- Unreachable remote → raise a clean, typed error naming host/env; nothing
  partially applied without its audit entry.
- Unit tests in `tests/knowledge/wiki/test_sync.py` using two sqlite/memory
  planes (NO Arango required).

**NOT in scope**: CLI `sync` command group and summary printing
(TASK-2467); delete propagation/tombstones (spec Non-Goal); syncing
`ingest` pages.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` | CREATE | engine: SyncReport, sync_push, sync_pull, note-merge helpers |
| `tests/knowledge/wiki/test_sync.py` | CREATE | two-plane unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import (
    BaseWikiStore,      # store.py:289
    WikiPageRecord,     # store.py:215 (updated_at added by TASK-2465)
    create_wiki_store,  # factory used by cli.py _open_store (cli.py:383-392)
)
from parrot.knowledge.wiki.project import (
    load_effective_config,   # TASK-2462
    resolve_arango_params,   # project.py:467 — host/port/protocol/username/
                             # password/database dict for AsyncDB("arangodb")
)
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper  # bookkeeper.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                        # line 289
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int   # line 308
    async def add_edges(self, edges: list[tuple]) -> int               # line 311
    async def get_page(..., include_body: bool = ...)                  # line 331
    async def list_pages(..., origin: Optional[list[str]] = None)      # lines 336-340
        # origin filter e.g. ["memory", "authored"] — line 1120 docstring
    async def dump_edges(self) -> list[dict[str, Any]]                 # line 365
        # sqlite impl returns ONLY {src, dst, rel} — NO provenance
        # (SELECT at line 1300). To select `asserted` edges you must either
        # extend dump_edges to include provenance or add a filtered reader —
        # verify the Arango twin before choosing; keep it on BaseWikiStore.

# packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py
class WikiBookkeeper:
    def log_operation(self, wiki_dir: Path, operation: str,
                      details: str, timestamp: Optional[str] = None) -> None  # line 175
        # SYNC direction goes in `operation`; per-record info in `details`.

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:944 (remember)
#   memory pages: concept_id = "mem-" + sha1(f"{title}::{category}")[:12],
#   origin="memory", asserted_by=f"agent:{self.agent_id}"
#   related links: add_edges([(page_id, rp, "references", "asserted")])  # 4-tuple

# Note format (tools.py:373-375, WikiNoteTool._execute):
#   stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
#   body += f"\n\n> **Note ({stamp}, agent:mcp):** {text}"
#   → regex the lines:  ^> \*\*Note \((?P<date>\d{4}-\d{2}-\d{2}), (?P<author>[^)]+)\):\*\* (?P<text>.*)$

# edges DDL (store.py:96-101): edges(src, dst, rel, provenance) with
#   provenance TEXT NOT NULL DEFAULT 'extracted'; asserted edges carry
#   provenance='asserted'.
```

### Does NOT Exist
- ~~`wiki/sync.py` / `SyncReport` / `sync_push` / `sync_pull`~~ — created by
  THIS task.
- ~~`BaseWikiStore.delete_page` tombstone semantics for sync~~ — deletes are
  NOT propagated (spec Non-Goal); do not implement.
- ~~a provenance-filtered edge reader~~ — `dump_edges()` returns src/dst/rel
  only in the sqlite impl; extending it (or adding one) is part of THIS
  task's scope — verify both backends before assuming a signature.
- ~~`store.add_note()`~~ — no store-level note API; notes live inside page
  bodies (read-modify-write, tools.py:357-358 comment).
- ~~network retry/queue machinery~~ — fail cleanly on unreachable remote;
  no background retries in v1.

---

## Implementation Notes

### Pattern to Follow
```python
# Engine talks BaseWikiStore ONLY — tests fake the remote with a second
# sqlite plane. Opening the remote arango plane mirrors cli.py:380-390:
#   create_wiki_store(storage, wiki_name=..., backend="arangodb",
#                     arango_params=resolve_arango_params(cfg),
#                     database=cfg.arango_database or "",
#                     text_analyzer=cfg.arango_text_analyzer)
```

### Key Constraints
- async/await throughout; module-level `logging.getLogger(__name__)`.
- Pydantic for `SyncReport`; Google-style docstrings; strict type hints.
- ISO-8601 lexicographic comparison for LWW (guaranteed by `_now_iso()`
  format — do not parse to datetime unless normalizing legacy values).
- Note merge must be deterministic (stable date-then-hash ordering) so
  push→pull round-trips are idempotent.
- Deterministic `mem-*` id collisions across authors are EXPECTED — LWW
  handles them; audit trail preserves the loser (spec §7 risk).

### References in Codebase
- `cli.py:380-392` — arango store opening (copy the parameter shape).
- `toolkit.py:944-1009` — the record class sync moves.
- `federation.py:292-337` — bounded-timeout probe pattern for the remote
  reachability pre-check.

---

## Acceptance Criteria

- [ ] `sync_push` moves memory pages + asserted edges + notes to the target
  plane; `ingest` pages never move (test proves exclusion).
- [ ] LWW: strictly-newer wins, source `updated_at` preserved at destination;
  equal/older → `skipped_older`.
- [ ] `sync_pull` skips local-identity `asserted_by` records by default
  (`skipped_own`); `include_own=True` → pure LWW.
- [ ] Note merge: two-sided note additions union date-ordered; no note
  dropped; idempotent on repeat sync.
- [ ] `dry_run` applies nothing and logs nothing, but reports accurately.
- [ ] Applied changes are bookkeeper-logged (`SYNC_PUSH`/`SYNC_PULL`).
- [ ] Unreachable remote → clean typed error naming host/env.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_sync.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/sync.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_sync.py
"""Two-plane sync tests — both planes are local stores; no Arango needed."""

@pytest.fixture
async def two_planes(tmp_path):
    """(local_store, remote_store) — two independent sqlite planes."""

class TestSelection:
    async def test_push_moves_memory_pages_only(self, two_planes): ...
    async def test_push_moves_asserted_edges_of_synced_pages(self, two_planes): ...

class TestLWW:
    async def test_newer_source_wins_and_preserves_stamp(self, two_planes): ...
    async def test_equal_or_older_skipped(self, two_planes): ...

class TestPullAuthorFilter:
    async def test_own_records_skipped_by_default(self, two_planes): ...
    async def test_include_own_pulls_everything(self, two_planes): ...

class TestNoteMerge:
    async def test_two_sided_notes_union_date_ordered(self, two_planes): ...
    async def test_note_merge_idempotent(self, two_planes): ...

class TestSafety:
    async def test_dry_run_applies_nothing(self, two_planes): ...
    async def test_report_counts_accurate(self, two_planes): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§2 Sync v1, §3 Module 5, §6, §7).
2. **Check dependencies** — TASK-2462 and TASK-2465 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code — especially the
   `dump_edges` provenance gap and both backends' edge readers.
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
