# TASK-2909: Persist enrichment and refresh unchanged source slices

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2907, TASK-2908
**Parallel**: false
**Parallelism notes**: Final dependent deliverable; no independent sibling work remains. Shared-file edits are serialized after TASK-2908. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements source-owned lifecycle and invalidation criteria. Depends on TASK-2908 to serialize cli.py ownership and on the scan-enrichment carrier. Keep state inside the active local plane directory; use atomic writes and stable schema-versioned content.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Load selected API catalog and mapping context offline before build scan and persist external references together with their owning source slices on fresh and incremental paths.
- Use a separate per-plane enrichment fingerprint state; do not overwrite raw file hashes used by structural freshness. Compare source state and mapping/catalog/namespace/schema digests when deciding unchanged-file skips.
- When mappings or the active API generation change, rescan/re-enrich affected Luau files even if source bytes/mtime are unchanged, including partial-build triggers. An explicit API refresh does not itself mutate every project; its new generation is observed on that project next build.
- Atomically record fingerprints only after the corresponding source-slice writes succeed. Failed writes leave retryable stale enrichment; deletion/removal and disappearing API use clear obsolete source-owned outgoing edges.
- Preserve existing source manifest batching, file hashes, source pruning, incoming edges and symbol persistence. No direct SQL into other backend implementations and no network acquisition in build.
- Exercise real read-only foreign SQLite generation with a local plane; ensure no locally imported filesystem-target edge is rewritten as an API id.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Bulk/incremental build integration and enrichment freshness |
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/enrichment_state.py` | CREATE | Atomic per-plane local enrichment digest state |
| `tests/knowledge/wiki/roblox/test_incremental_enrichment.py` | CREATE | Build/refresh/remove/failure lifecycle tests |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, build_file_slice, scan_repository
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import WikiPageRecord, SQLiteWikiStore, create_wiki_store, estimate_tokens
from parrot.knowledge.wiki.project import WikiNamespaceConfig, parrot_home, load_global_registry, save_global_registry
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:648` — `async def _ingest_files( store: BaseWikiStore, sources: SourceCollectionManager, root: Path, scan: Any, force: bool = False, ) -> dict[str, int]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3626` — `def ingest( source: str, path_: str | None, charter_opt: str | None, dry_run: bool, review_opt: Path | None, interactive_flag: bool, auto_flag: bool, extract_flag: bool, lightweight_model_opt: str | None, model_opt: str | None, audit_rate: float, manifest_opt: Path | None, recursive: bool, fetch_timeout: float, ) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1773` — `def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:173` — `def _federate( root: Path, config: WikiProjectConfig, local: BaseWikiStore, ns_opt: str | None, ) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:219` — `class FileSlice(BaseModel):` Fields: rel_path: str; record: WikiPageRecord; imports: list[str]; language: str | None; symbols: list[SymbolRecord]; refs: list[SymbolRef].
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:248` — `class RepoScan(BaseModel):` Fields: root: Path; files: list[FileSlice]; dir_records: list[WikiPageRecord]; dir_edges: list[tuple[str, str, str]]; import_edges: list[tuple[str, str, str]]; skipped: list[str]; symbol_records: list[WikiPageRecord]; symbol_edges: list[tuple[str, str, str, str]].
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:630` — `def build_file_slice( root: Path, rel_path: str, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, symbol_depth: int = 2, ) -> FileSlice | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:321` — `def file_concept_id(rel_path: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:803` — `def build_import_edges( files: list[FileSlice], index_paths: Iterable[str] | None = None, ) -> list[tuple[str, str, str]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:1116` — `def scan_repository( root: Path, suffixes: Iterable[str] | None = None, exclude_dirs: Iterable[str] | None = None, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, use_git: bool = True, rel_paths: Iterable[str] | None = None, symbol_depth: int = 2, ) -> RepoScan:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:549` — `def entry_is_stale(self, entry: SourceManifestEntry) -> bool:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:302` — `def find_entries_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:452` — `def mark_ingested_many( self, pages_by_source: dict[str, list[str]], status: str = "ingested", ) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:208` — `def estimate_tokens(text: str) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1795` — `def create_wiki_store( storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any, ) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1134` — `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1154` — `async def add_edges(self, edges: list[tuple]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1176` — `async def replace_source_slice( self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None, ) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1672` — `async def neighbors( self, concept_id: str, rel: Optional[str] = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1773` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:175` — `class WikiNamespaceConfig(BaseModel):` Fields: path: str | None; store: str | None; backend: str; database: str | None; credentials_env: str; vault: str | None; description: str; weight: float.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:940` — `def parrot_home() -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:960` — `def load_global_registry(path: Path | None = None) -> GlobalWikiRegistry:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:986` — `def save_global_registry(registry: GlobalWikiRegistry, path: Path | None = None) -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1017` — `def merge_namespaces( repo: dict[str, WikiNamespaceConfig], global_: dict[str, WikiNamespaceConfig], ) -> dict[str, tuple[WikiNamespaceConfig, str]]:`

### Existing Owned Files

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- `TASK-2907` supplies attach datamodel and external references to offline scans; read its completion contract before importing any new symbol.
- `TASK-2908` supplies add api ingest dispatch and offline plane status; read its completion contract before importing any new symbol.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/` and `packages/ai-parrot/src/parrot/knowledge/wiki/languages/luau.py` do not exist on the decomposition base; proposed symbols become usable only after their owning tasks complete.
- `LanguageOutline.metadata` and `LanguageOutline.external_edges` do not exist. Its `refs` field is for structural symbol references.
- `resolve_import()` does not accept arbitrary wiki destinations; existing import-edge construction wraps a repository-relative target in `file:`.
- Foreign edge writes and destination-aware neighbor hydration are not existing federation guarantees; TASK-2903 through TASK-2905 establish them.
- `WikiPageRecord` is defined in `store.py`, not wiki `models.py`, and has no arbitrary metadata field.

## Implementation Notes

### Pattern to Follow

Use the verified APIs above and the typed contracts delivered by dependencies.
Follow existing scanner fallback, source-owned slice replacement, namespace
configuration and temporary SQLite test patterns where applicable. Keep
synchronous scanning separate from async acquisition; offload substantial
blocking work in async orchestration. Use ordinary Python logging, Pydantic
models and explicit type annotations; Python 3.11+ and Black/isort conventions.

### Key Constraints

- Preserve the scanner ABC and existing file-page identities.
- Never execute Roblox code or invoke Rojo/luau-lsp/git for runtime acquisition.
- Never mutate foreign API pages while writing local references.
- Use generated tiny fixtures, not vendored API dumps or upstream code archives.
- You are not alone in the codebase: preserve others' changes and coordinate
  shared-file/index updates. FEAT-531 concurrently touches wiki CLI behavior.
- Respect any recorded measurement-review execution gate before implementation.

### References in Codebase

Use the paths and exact signatures in this task's Codebase Contract. The full
spec supplies rationale; final owner decisions in section 8 are binding.

## Acceptance Criteria

- [ ] The complete scoped deliverable is implemented with no production stubs.
- [ ] Bulk and per-source paths produce the same local/external graph.
- [ ] A mapping-only/catalog-only change refreshes body and references.
- [ ] Partial scan cannot leave other affected Luau slices stale.
- [ ] Old outgoing links disappear; preserved incoming links remain correct.
- [ ] Retry occurs after an injected persistence failure.
- [ ] Existing batching/hash/structural behavior stays intact.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_incremental_enrichment.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2909-roblox-incremental-persistence.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_fresh_and_incremental_have_identical_edges` | Bulk and per-source paths produce the same local/external graph. |
| `test_catalog_mapping_change_rescans_unchanged_luau` | A mapping-only/catalog-only change refreshes body and references. |
| `test_partial_build_detects_context_change` | Partial scan cannot leave other affected Luau slices stale. |
| `test_removed_use_and_file_prune_edges` | Old outgoing links disappear; preserved incoming links remain correct. |
| `test_failed_write_does_not_advance_digest` | Retry occurs after an injected persistence failure. |
| `test_non_luau_manifest_and_symbols_unchanged` | Existing batching/hash/structural behavior stays intact. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2909-roblox-incremental-persistence.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
