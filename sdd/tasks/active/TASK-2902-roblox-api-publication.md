# TASK-2902: Publish immutable API generations with explicit refresh

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2900, TASK-2901
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2896, TASK-2898, TASK-2899, TASK-2903, TASK-2904, TASK-2905, TASK-2906, TASK-2907 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements sections 2 generation lifecycle, 3.4 and final section 8 refresh policy. In-memory tar expansion does not forbid persisted generation payloads/SQLite output outside the repository. Offload substantial synchronous IO/rendering from the event loop.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Implement async ingest_roblox_api(refresh=False) using acquisition and rendering contracts. Without --refresh, return validated existing state offline; if missing/invalid, return an actionable instruction to run --refresh. First acquisition also requires --refresh under the final section 8 decision.
- On explicit refresh compare Studio version, docs SHA and renderer schema. Reuse whole-generation payloads where unchanged; rebuild when either revision/schema changes. Persist reusable inputs outside the repository without a per-file docs cache.
- Build and validate a closed SQLite generation under parrot_home()/roblox, preserving counts, manifest and catalog; then atomically promote its active pointer. Keep previous generations usable by active readers and leave automatic GC out of scope.
- Serialize writers around publication, or implement a real checked compare-and-swap; atomic replace alone does not prevent lost updates. Make interrupted/render-failed/registry-failed publication leave the previous generation selected.
- Preserve user namespace settings. Update a registry pointer only when it demonstrably names the previously managed generation; never overwrite an unrelated roblox declaration. For first use publish managed local generation metadata and return a registration hint; register using existing namespace tooling.
- Return download timestamp and recorded versions for offline status; no automatic expiry, background work or foreign project-plane writes.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/ingest.py` | CREATE | Generation validation, selection, explicit refresh and publication |
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/generations.py` | CREATE | Atomic active-generation metadata and writer coordination |
| `tests/knowledge/wiki/roblox/test_publication.py` | CREATE | Generation failure/reuse/concurrency tests |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.store import WikiPageRecord, SQLiteWikiStore, create_wiki_store, estimate_tokens
from parrot.knowledge.wiki.project import WikiNamespaceConfig, parrot_home, load_global_registry, save_global_registry
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

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

### Prerequisite Interfaces (new, not existing today)

- `TASK-2900` supplies acquire the versioned api dump and sha-pinned docs tarball; read its completion contract before importing any new symbol.
- `TASK-2901` supplies render deterministic roblox class and enum pages; read its completion contract before importing any new symbol.

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
- [ ] No-refresh missing plane performs zero requests and explains the command.
- [ ] Existing plane is returned without revision probes or regeneration.
- [ ] Studio/docs/schema changes trigger the appropriate reuse/rebuild.
- [ ] Every acquisition/render/promotion failure preserves old readability.
- [ ] No torn/lost registry update and no unrelated declaration replacement.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_publication.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2902-roblox-api-publication.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_first_use_requires_refresh` | No-refresh missing plane performs zero requests and explains the command. |
| `test_no_refresh_reuses_generation_offline` | Existing plane is returned without revision probes or regeneration. |
| `test_refresh_revision_matrix` | Studio/docs/schema changes trigger the appropriate reuse/rebuild. |
| `test_failed_refresh_keeps_old_generation` | Every acquisition/render/promotion failure preserves old readability. |
| `test_concurrent_publication_and_registry_conflict` | No torn/lost registry update and no unrelated declaration replacement. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2902-roblox-api-publication.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
