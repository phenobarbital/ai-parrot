# TASK-2366: Vault hazards — `.parrot` in `VAULT_EXCLUDE_DIRS` and scoped `_prune_removed` (D4.2 / D4.4)

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, G8. Two verified hazards (F017) make the shared-store vault path unsafe today:
(1) `scan_vault` (vault_scan.py:111-140) filters only `VAULT_EXCLUDE_DIRS = {.obsidian, .trash,
.git, .hg, .svn}` (50-52) and takes no exclude argument, while `WikiBookkeeper` writes `index.md` /
`log.md` into the storage dir (bookkeeper.py:44-45, 142, 201) — a plane at `<vault>/.parrot/wiki`
is re-ingested into itself on every build; (2) `_prune_removed` (cli.py:390-423) is global over the
store and `VaultIngestTool` calls it on the project's own plane (tools.py:367), so ingesting a vault
into a repo plane deletes every codebase page and the next `build` deletes the notes back.

---

## Scope

- `vault_scan.py`: add `".parrot"` to `VAULT_EXCLUDE_DIRS` (mirrors
  `repo_scan.DEFAULT_EXCLUDE_DIRS`, repo_scan.py:85-89, which already prunes `.parrot` by bare name).
- `cli.py::_prune_removed(store, sources, root, scan, *, scope: Literal["plane", "root"] = "plane") -> int`:
  - `"plane"` — current behaviour, unchanged (used by `build`, cli.py:842).
  - `"root"` — only sources whose `source_uri` starts with `str(root.resolve()) + os.sep` are
    eligible for removal; `file:` pages are removed only through those sources'
    `replace_source_slice(source_id, [], [])` (no global `list_pages` sweep of `file:` ids); a
    `dir:` page is deleted only when no surviving page id (`list_pages`) lies under that directory
    path **and** the dir id is one this scan would have produced or previously produced for this
    root (i.e. `dir:` ids whose path is a prefix of some removed file's relative path).
- `tools.py::VaultIngestTool._execute`: call `_prune_removed(self._store, sources, vault, scan, scope="root")`.
- Tests: `tests/knowledge/wiki/test_vault_scan.py` (or extend the existing vault test module —
  `grep -rl scan_vault tests/` first): `.parrot/wiki/log.md` inside a vault is not scanned;
  `tests/knowledge/wiki/test_cli.py` or a new `test_prune_scope.py`: a plane holding repo pages +
  a vault ingest with `scope="root"` keeps every repo page; `scope="plane"` behaviour unchanged.

**NOT in scope**: `ns add --vault` (TASK-2364); making `scan_vault` honour `config.exclude_dirs`
(spec chose the constant; note it as a possible follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py` | MODIFY | exclude `.parrot` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `_prune_removed(scope=...)` (lines 390-423 only) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `VaultIngestTool` passes `scope="root"` (line 367) |
| `tests/knowledge/wiki/test_prune_scope.py` | CREATE | prune scoping tests |
| `tests/knowledge/wiki/test_vault_scan.py` | MODIFY/CREATE | `.parrot` exclusion test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.vault_scan import VAULT_EXCLUDE_DIRS, is_obsidian_vault, scan_vault, VaultScanStats   # vault_scan.py:50,55,111
from parrot.knowledge.wiki.cli import _prune_removed, _ingest_files, _open_sources              # cli.py:390,327,138
from parrot.knowledge.wiki.tools import VaultIngestTool                                          # tools.py:288
from parrot.knowledge.wiki.sources import SourceCollectionManager                                # sources.py:57
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord                          # store.py:441,215
from parrot.knowledge.wiki.repo_scan import RepoScan, file_concept_id, dir_concept_id            # repo_scan.py (RepoScan dataclass), 249, 254
```

### Existing Signatures to Use
```python
# vault_scan.py
VAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({".obsidian", ".trash", ".git", ".hg", ".svn"})   # 50-52
def scan_vault(root: Path, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> tuple[RepoScan, VaultScanStats]   # 111-115
    for path in sorted(root.rglob("*.md")): rel = ...; parts = PurePosixPath(rel).parts
    if any(part in VAULT_EXCLUDE_DIRS for part in parts): continue                 # 134-138
# cli.py
async def _prune_removed(store: BaseWikiStore, sources: SourceCollectionManager, root: Path, scan: Any) -> int   # 390-423
    expected_files = {fs.record.concept_id for fs in scan.files}                   # 401
    expected_dirs = {r.concept_id for r in scan.dir_records}                       # 402
    expected_uris = {str((root / fs.rel_path).resolve()) for fs in scan.files}     # 403-405
    for entry in await asyncio.to_thread(sources.list_sources):                    # 408
        if entry.source_uri not in expected_uris: await store.replace_source_slice(entry.source_id, [], []); await asyncio.to_thread(sources.remove_source, entry.source_id)   # 409-412
    stubs = await store.list_pages(limit=1_000_000)                                # 414
    for stub in stubs: cid = ...; if cid.startswith("file:") and cid not in expected_files: delete_page; elif cid.startswith("dir:") and cid not in expected_dirs: delete_page   # 415-422
build(...): counts["removed"] = await _prune_removed(store, sources, root, scan)   # 842
# tools.py VaultIngestTool._execute (311-368)
scan, stats = await asyncio.to_thread(scan_vault, vault, self._config.body_max_chars, self._config.max_file_kb * 1024)   # 355-360
sources = _open_sources(self._root, self._config, store=self._store)             # 361
counts = await _ingest_files(self._store, sources, vault, scan, force=force)      # 362-364
await self._store.upsert_pages(scan.dir_records); await self._store.add_edges(scan.dir_edges)   # 365-366
removed = await _prune_removed(self._store, sources, vault, scan)                 # 367
# sources.py
SourceCollectionManager.list_sources() -> list[SourceManifestEntry] (213); .remove_source(id) -> bool (428); entry.source_id / entry.source_uri (absolute path str)
# bookkeeper.py: INDEX_FILENAME="index.md" (44), LOG_FILENAME="log.md" (45) written under wiki_dir (142, 201)
# repo_scan.py: DEFAULT_EXCLUDE_DIRS includes ".parrot" (85-89); pruned by bare name at any depth (239)
```

### Does NOT Exist
- ~~`scan_vault(exclude_dirs=...)`~~ — no such parameter; the fix is the constant.
- ~~`_prune_removed(..., scope=...)`~~ — you add it; current call sites: `cli.py:842` (build) and `tools.py:367` (vault tool) — verified by grep, no others.
- ~~`SourceManifestEntry.root`~~ — entries carry `source_uri` only; derive "under root" from the path string.
- ~~`store.list_pages(prefix=...)`~~ — `list_pages(category=None, limit=100, origin=None)` only.

---

## Implementation Notes

### Pattern to Follow
```python
root_prefix = str(root.resolve()) + os.sep
eligible = [e for e in entries if scope == "plane" or str(e.source_uri).startswith(root_prefix)]
```
For `"root"` scope, collect `removed_rel_paths` from the removed sources' uris, derive candidate
`dir:` ids from their parent chains (`dir_concept_id(parent)` up to `"."`), and delete a candidate
only if no surviving stub id (`file:`/`dir:`) has that path as a prefix.

### Key Constraints
- Zero behaviour change for `scope="plane"` (existing build tests must stay green).
- Edit only `cli.py:390-423` — FEAT-451 is editing 2093-2544 concurrently; TASK-2363/2364 edit
  87-272 and 1075-1288 / 1470-1495. Rebase carefully if this task runs in parallel.

### References in Codebase
- `repo_scan.py:225-240` — bare-name exclusion logic `scan_vault` now mirrors for `.parrot`.

---

## Acceptance Criteria

- [ ] `".parrot" in VAULT_EXCLUDE_DIRS`; a vault containing `.parrot/wiki/log.md` scans without it
- [ ] `_prune_removed(scope="root")` on a plane with repo pages + vault pages removes nothing outside `root`; `dir:` survives while children exist
- [ ] `VaultIngestTool` uses `scope="root"`; `build` unchanged (`scope="plane"`)
- [ ] `pytest tests/knowledge/wiki -v` (incl. existing build/vault tests) and `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py`
- [ ] `ruff check` on the three modules

---

## Test Specification

```python
# tests/knowledge/wiki/test_prune_scope.py
import pytest
from parrot.knowledge.wiki.cli import _prune_removed
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.vault_scan import scan_vault

async def test_root_scope_keeps_foreign_pages(tmp_path):
    store = SQLiteWikiStore(tmp_path / "plane" / "wiki.db")
    await store.upsert_pages([WikiPageRecord(concept_id="file:src/app.py", title="app", source_id="repo-src"),
                              WikiPageRecord(concept_id="dir:src", title="src/")])
    sources = SourceCollectionManager(tmp_path / "plane" / "sources", db_path=tmp_path / "plane" / "wiki.db")
    # register a repo source whose uri is outside the vault
    ...sources.register/upsert API: grep sources.py:82-212 for the method that records (source_id, source_uri)...
    vault = tmp_path / "vault"; (vault / ".obsidian").mkdir(parents=True); (vault / "A.md").write_text("# A")
    scan, _ = scan_vault(vault)
    removed = await _prune_removed(store, sources, vault, scan, scope="root")
    assert await store.get_page("file:src/app.py") and await store.get_page("dir:src")

def test_vault_scan_excludes_parrot(tmp_path):
    vault = tmp_path / "v"; (vault / ".obsidian").mkdir(parents=True)
    (vault / "note.md").write_text("# n"); (vault / ".parrot" / "wiki").mkdir(parents=True); (vault / ".parrot" / "wiki" / "log.md").write_text("x")
    scan, _ = scan_vault(vault)
    assert {fs.record.concept_id for fs in scan.files} == {"file:note.md"}
```

---

## Agent Instructions

1. Read spec §3 Module 6, §6 (`vault_scan.py`, `cli.py:_prune_removed`, `tools.py:VaultIngestTool` blocks), §7.
2. Verify the contract (line numbers may have shifted if TASK-2363/2364 or FEAT-451 landed first).
3. Implement; run the tests above plus the existing vault/build tests.
4. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
