# TASK-2749: `StructuralService` — lookup, outline, blast radius, read-repair

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2748
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. One service, two surfaces later (TASK-2750). It is the only
component that reads the working tree: `_ensure_fresh()` hashes candidate
files, compares with `page_hashes()`, and re-scans stale ones through the
same code path as `wikitoolkit upsert --changed`. Resolved: when the write
lock is busy, serve stale hits flagged `stale=True` without waiting.

---

## Scope

- Create `parrot/knowledge/wiki/structural/__init__.py` and
  `structural/service.py` with the Pydantic outputs (`SymbolHit`,
  `SymbolLookupOutput`, `CodeOutlineOutput`, `ImpactedSymbol`,
  `BlastRadiusOutput` — spec §2 New Public Interfaces) and
  `StructuralService(store, root, config)`:
  - `lookup(query, *, kind=None, language=None, path_prefix=None, limit=20)`:
    exact `qualname` → exact `name` → `search_symbols_fts`; dedupe; score
    (1.0 / 0.9 / FTS rank normalised); `_ensure_fresh` on the hit files; re-query
    when anything was repaired; `SymbolHit.stale=True` only when the lock was busy.
  - `outline(target, *, depth=2, include_source=False)`: accepts `file:<rel>`,
    `sym:<rel>#<q>`, or a relative path; root-confined (`Path.resolve()` +
    `is_relative_to(root)`; reject `.parrot/`, `.git/`, `DEFAULT_EXCLUDE_DIRS`);
    `symbols_for(rel_path)` filtered by depth/subtree; `include_source` reads
    `start_byte:end_byte` (≤ 4 000 chars) for a `sym:` target only.
  - `blast_radius(symbol, *, relations=[...], depth=2, include_inferred=True, include_tests=True)`:
    resolve `symbol` (sym id or exact qualname via `find_symbols`), BFS over
    `store.neighbors(cid, rel=r, direction="in")` for each requested `rel`,
    depth-bounded, dedup by concept id, skip dangling targets, `provenance`
    from the edge dict, `files` = sorted unique `rel_path`s, `include_tests`
    filters `rel_path.startswith("tests/")` or `/tests/` segment; `truncated`
    when a cap (500 nodes) hits.
  - `_ensure_fresh(rel_paths) -> list[str]`: `sha1(bytes)` vs `page_hashes([file:…])`;
    stale/missing → under `wiki_write_lock(config.storage_path(root), timeout=0)`:
    existing files → `scan_repository(root, rel_paths=stale, suffixes=…, exclude_dirs=…)`
    + `_ingest_files(store, sources, root, scan, force=True)`; deleted files → the
    same removal the `upsert` command does for `deleted` paths; lock busy → `[]`
    and set a `self._lock_busy` flag consumed by `lookup` to mark `stale=True`.
    Never runs for a foreign namespace (caller decides; service is local-only).
- Tests with a tmp repo + sqlite plane: ranking, outline confinement,
  blast radius provenance/files/tests filter, repair on edit, lock-busy,
  deleted file.

**NOT in scope**: `AbstractTool` wrappers, MCP, toolkit, CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py` | CREATE | Package; re-export service + models |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` | CREATE | `StructuralService` + output models |
| `tests/knowledge/wiki/structural/__init__.py` | CREATE | — |
| `tests/knowledge/wiki/structural/conftest.py` | CREATE | `built_repo` fixture: tmp repo (py + ts + php files) → sqlite plane via `scan_repository` + `_ingest_files` |
| `tests/knowledge/wiki/structural/test_service.py` | CREATE | Service tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store    # store.py:332/224 ; factory used in tests (test_store.py:385)
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind, sym_concept_id, parse_sym_id, sha1_of_text, symbol_from_page   # TASK-2738/2747
from parrot.knowledge.wiki.repo_scan import scan_repository, file_concept_id, DEFAULT_EXCLUDE_DIRS, is_wiki_relevant, is_inside_wiki_bundle   # repo_scan.py:776/249/85/202/327
from parrot.knowledge.wiki.cli import _ingest_files                                          # cli.py:622 (module-level coroutine; importing cli is acceptable — mcp_server/tools already import wiki modules lazily; if import cost is an issue, move _ingest_files to ingest.py and re-export from cli)
from parrot.knowledge.wiki.sources import SourceCollectionManager                            # sources.py:107
from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock, load_effective_config   # project.py:~400/65/813
from parrot.knowledge.wiki.context import truncate_to_tokens                                 # context.py:272
```

### Existing Signatures to Use
```python
async def BaseWikiStore.neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]   # store.py:389
    # SQLite :1237 — dicts with keys concept_id, rel, direction (+ title/summary when the neighbour page exists); provenance: read the edge row — extend the SQLite neighbors SELECT to include `provenance` if absent (verify at :1255-1298)
async def BaseWikiStore.find_symbols(...) / symbols_for(rel_path) / search_symbols_fts(query, limit) / page_hashes(concept_ids)   # TASK-2747
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]        # project.py:65 — context manager yielding acquired flag
WikiProjectConfig.storage_path(root) -> Path                                         # used in mcp_server.py:~103 and cli upsert (:1405)
def scan_repository(root, suffixes=None, exclude_dirs=None, ..., use_git=True, rel_paths=None) -> RepoScan   # repo_scan.py:776
async def _ingest_files(store, sources, root, scan, force=False) -> dict[str, int]   # cli.py:622
# upsert command (cli.py:1389-1470): normalisation + `deleted = [rel for rel in normalized if not (root / rel).is_file()]` → removal path — mirror it for read-repair of deleted files
def truncate_to_tokens(text: str, max_tokens: int | None) -> tuple[str, bool]       # context.py:272
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.structural`~~ — created here.
- ~~`StructuralService`, `SymbolHit`, `BlastRadiusOutput`, …~~ — new.
- ~~`neighbors()` returning `provenance`~~ — verify; if the SQLite/Arango/InMemory implementations omit it, add it (additive dict key) in this task and cover it in `test_store.py`.
- ~~an async `wiki_write_lock`~~ — it is a sync context manager; wrap the repair in `asyncio.to_thread` only for the sync manifest parts (as `_ingest_files` already does), keep the lock acquisition in the calling thread.
- ~~read-repair across federated namespaces~~ — local root only.
- ~~any write to source files~~ — the service writes only to the wiki plane under `.parrot/`.

---

## Implementation Notes

### Pattern to Follow
```python
async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]:
    ids = [file_concept_id(p) for p in rel_paths]
    known = await self._store.page_hashes(ids)
    stale = [p for p, cid in zip(rel_paths, ids) if self._disk_hash(p) != known.get(cid)]
    if not stale: return []
    with wiki_write_lock(self._config.storage_path(self._root), timeout=0) as acquired:
        if not acquired:
            self._lock_busy = True; return []
        existing = [p for p in stale if (self._root / p).is_file()]
        if existing:
            scan = scan_repository(self._root, rel_paths=existing, suffixes=self._config.include_suffixes or None, exclude_dirs=self._config.exclude_dirs)
            await _ingest_files(self._store, self._sources, self._root, scan, force=True)
        ... # deleted → drop slices as `upsert` does
    return stale
```

### Key Constraints
- `_disk_hash` hashes bytes (matches `content_hash` from TASK-2748); missing file → `None`.
- Only hit files are hashed (≤ `limit`), never the repo.
- Outputs are Pydantic; the service never formats text — tools do.
- Root confinement before any disk read; reject with a structured error, not an exception.

### References in Codebase
- `cli.py:1389-1470` — `upsert` command: lock, normalisation, deleted handling.
- `mcp_server.py:90-140` — how a store + config are opened from `root` (test fixture reuse).

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/structural/test_service.py -v` passes (sqlite plane; Python fixtures so no extra is needed; TS/PHP fixtures additionally when ast-grep is installed).
- [ ] Ranking: exact qualname > exact name > FTS; `limit` honoured; `kind`/`language`/`path_prefix` filters applied.
- [ ] Editing a fixture file on disk then calling `lookup()` returns fresh symbols, `repaired_files == [rel]`, and `page_hashes` reflects the new hash.
- [ ] With the lock held by another process/thread: hits returned, `stale=True`, `repaired_files == []`, no write performed.
- [ ] Deleting a fixture file then `lookup()` removes its `file:`/`sym:` pages and symbol rows.
- [ ] `outline("../x")`, absolute paths outside root, and `.parrot/…` are rejected without reading.
- [ ] `blast_radius`: `files` sorted unique; `include_inferred=False` removes inferred; `include_tests=False` removes `tests/`; dangling targets skipped; `provenance` populated.
- [ ] `ruff` / `mypy` clean.

---

## Test Specification

```python
async def test_read_repair_on_edit(built_repo):
    svc, root = built_repo
    out = await svc.lookup("helper"); assert out.hits and not out.repaired_files
    (root / "a.py").write_text((root / "a.py").read_text() + "\ndef helper_two(): ...\n")
    out2 = await svc.lookup("helper_two")
    assert out2.repaired_files == ["a.py"] and out2.hits[0].qualname == "helper_two"

async def test_lock_busy_serves_stale(built_repo):
    svc, root = built_repo
    (root / "a.py").write_text("def changed(): ...\n")
    with wiki_write_lock(svc._config.storage_path(root), timeout=0) as ok:
        assert ok
        out = await svc.lookup("helper")
    assert out.repaired_files == [] and all(h.stale for h in out.hits)
```

---

## Agent Instructions

1. Read spec §2 ("Service & tools"), §3 Module 7, §7 Patterns + Risks
("Read-repair vs. concurrent build"). 2. Confirm TASK-2748 completed. 3. Verify
contract lines (especially `neighbors` provenance). 4. Index → `in-progress`.
5. Implement. 6. Tests. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-02
**Notes**: Implemented `StructuralService` (`lookup`/`outline`/`blast_radius`/
`_ensure_fresh`) and its five Pydantic output models exactly as scoped.
`neighbors()` was widened to return `provenance` on all three backends
(sqlite `store.py`, `arango_store.py`, `file_store.py`) as pre-authorized
by the task's own "Does NOT Exist" section, covered by a new
`test_neighbors_includes_provenance` in `test_store.py`.
`outline(..., include_source=True)` reads the byte-accurate excerpt from
the already-fetched `symbols_for()` records (full-fidelity on SQLite's
native `symbols` table) rather than round-tripping through
`get_page`/`symbol_from_page`, whose `start_byte`/`end_byte` are
intentionally zeroed for the page-based decode (documented lossy path in
`symbols.py`) — using the lossy path here would always yield an empty
excerpt. 21 tests added, all pass; `ruff`/`mypy` clean; full
`tests/knowledge/wiki/` suite run — 1369 passed (1 pre-existing,
unrelated failure in `test_claude_code.py::test_fresh_install_writes_all_artifacts`,
confirmed via `git stash` to predate this task).

**Deviations from spec**:
1. `_read_source_excerpt` resolves byte offsets from the `outline()`-local
   `symbols_for()` result list instead of a fresh `get_page()` round trip
   (see Notes) — required for `include_source` to return non-empty text
   on the SQLite backend the tests exercise; no file outside the task's
   scope was touched.
2. The task's own literal Test Specification block queries a brand-new
   symbol name (`"helper_two"`) directly after editing the file and
   expects `repaired_files == ["a.py"]` on that same call. This is
   internally inconsistent with the Scope's own "Key Constraints"
   ("Only hit files are hashed... never the repo"): `_ensure_fresh` only
   hashes files that were already *hits* of the query, and a name
   introduced by the very edit that made the file stale can never be a
   pre-repair hit (exact-match and FTS both search the still-stale
   index — verified empirically against SQLite FTS5's `unicode61`
   tokenizer). Implemented `test_read_repair_on_edit` against a
   corrected, self-consistent sequence instead: query an *existing*
   symbol (`"helper"`, still present after the edit) to trigger and
   observe the repair, then show the new symbol is queryable on the
   very next call. The literal `test_lock_busy_serves_stale` from the
   spec was reproduced verbatim and passes as written.
