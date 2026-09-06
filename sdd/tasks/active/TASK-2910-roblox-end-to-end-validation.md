# TASK-2910: Verify Roblox lifecycle and federation compatibility

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2909
**Parallel**: false
**Parallelism notes**: Final dependent deliverable; no independent sibling work remains. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements spec section 4 integration tests and section 5 acceptance verification. Unit tests belong to the owning implementation tasks; this is lifecycle coverage, not a duplicate unit suite. No production refactors.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Build a tiny mixed-language Roblox project and API generation using mocked acquisition and real temporary SQLite planes; exercise the public CLI query/page/related/status/build path.
- Verify reference ownership, incoming queries, namespace weighting/selection, explicit refresh, offline default operation, source-map changes and disappearing API entities.
- Assert failed/interrupted refresh leaves existing queries usable and no writes hit the read-only API generation. Verify absent namespace recovery and no double qualification.
- Run focused feature tests and existing scanner/federation/namespace regressions with and without the optional grammar; document failures with task ownership rather than making unrelated production edits.
- Use small authored fixtures and network traps, never downloaded dumps in Git. Store logs in artifacts/logs and report actual tested commands and limits.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/roblox/test_end_to_end.py` | CREATE | Public CLI/two-plane lifecycle acceptance tests |
| `tests/knowledge/wiki/roblox/conftest.py` | CREATE | Small authored multi-plane fixtures and network traps |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, build_file_slice, scan_repository
from parrot.knowledge.wiki.store import WikiPageRecord, SQLiteWikiStore, create_wiki_store, estimate_tokens
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, NamespaceSkip
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
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
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:208` — `def estimate_tokens(text: str) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1795` — `def create_wiki_store( storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any, ) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1134` — `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1154` — `async def add_edges(self, edges: list[tuple]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1176` — `async def replace_source_slice( self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None, ) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1672` — `async def neighbors( self, concept_id: str, rel: Optional[str] = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1773` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:597` — `def __init__( self, local: BaseWikiStore, local_name: str = "local", handles: list[NamespaceHandle] | None = None, skipped: list[NamespaceSkip] | None = None, *, qualify_local: bool = False, ) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:646` — `def scoped(self, selector: str | None) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:877` — `async def neighbors( self, concept_id: str, rel: str | None = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1088` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:552` — `def _qualify_row(row: dict[str, Any], namespace: str | None) -> dict[str, Any]:`
- `tests/knowledge/wiki/test_federation.py:1` — `"""Tests for multi-wiki federation (FEAT-450, wiki/federation.py).`
- `tests/knowledge/wiki/test_repo_scan.py:1` — `"""Tests for the deterministic repository scanner (repo_scan).`
- `tests/knowledge/wiki/test_namespaces_e2e.py:1` — `"""End-to-end namespace scenarios (FEAT-450).`
- `tests/knowledge/wiki/test_project_namespaces.py:1` — `"""Unit tests for FEAT-450 namespace declaration (project.py, Module 1)."""`
- `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py:1` — `"""Tests: federated namespaces reach the wikitoolkit MCP server (FEAT-450).`

### Prerequisite Interfaces (new, not existing today)

- `TASK-2909` supplies persist enrichment and refresh unchanged source slices; read its completion contract before importing any new symbol.

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
- [ ] End-to-end reference paths and metadata behave through public surfaces.
- [ ] Previous plane or local-only retrieval stays usable.
- [ ] Unchanged source is correctly re-enriched on the next build.
- [ ] Scope/weights/access restrictions hold for project plus API planes.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_end_to_end.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2910-roblox-end-to-end-validation.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_build_query_page_related_status_lifecycle` | End-to-end reference paths and metadata behave through public surfaces. |
| `test_failed_refresh_and_unbuilt_namespace` | Previous plane or local-only retrieval stays usable. |
| `test_api_and_map_generation_transition` | Unchanged source is correctly re-enriched on the next build. |
| `test_existing_federation_scoping` | Scope/weights/access restrictions hold for project plus API planes. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2910-roblox-end-to-end-validation.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
