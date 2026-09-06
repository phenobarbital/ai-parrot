# TASK-2903: Allow local references to foreign destinations

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2896, TASK-2897, TASK-2898, TASK-2899, TASK-2900, TASK-2901, TASK-2902, TASK-2906, TASK-2907 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements section 8 real federation decision. Code reread corrects the blast-radius note: the test near line 541 still forbids a foreign PAGE write and must remain. No neighbor/health/CLI changes yet.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Relax _strip_edge for locally owned references with a syntactically qualified foreign destination. Keep foreign source ids, foreign page/embedding/delete writes and invalid identifiers forbidden.
- Apply the same policy in add_edges and replace_source_slice; preserve three/four-element edge tuples and provenance and strip the local namespace prefix only where appropriate.
- Store the qualified target in the owning local plane; never write reverse edges or mutate the foreign plane. Do not require the foreign plane to be online to retain an already-known reference.
- Revise the foreign-destination assertion inside TestWrites.test_qualified_id_is_refused. Preserve its page/delete/embedding assertions and test_scoped_write_still_rejects_another_namespace, which verifies page writes, not foreign edge destinations.
- Use a narrow references exception rather than widening every write or every relation. Validate a whole batch before a mutation to avoid partial forbidden writes.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | Asymmetric edge validation only |
| `tests/knowledge/wiki/test_federation.py` | MODIFY | Update only foreign-destination edge expectation |
| `tests/knowledge/wiki/roblox/test_federation_writes.py` | CREATE | Cross-namespace edge ownership regressions |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord, SQLiteWikiStore, create_wiki_store, estimate_tokens
from parrot.knowledge.wiki.context import split_namespaced_id, qualify_id
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:947` — `def _assert_local(self, page_id: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:989` — `def _strip_edge(self, edge: tuple) -> tuple:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1002` — `async def add_edges(self, edges: list[tuple]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1006` — `async def replace_source_slice( self, source_id: str, pages: list[WikiPageRecord], edges: list[tuple[str, str, str]] | None = None, ) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:208` — `def estimate_tokens(text: str) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1795` — `def create_wiki_store( storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any, ) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1134` — `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1154` — `async def add_edges(self, edges: list[tuple]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1176` — `async def replace_source_slice( self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None, ) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1672` — `async def neighbors( self, concept_id: str, rel: Optional[str] = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1773` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:54` — `def split_namespaced_id(page_id: str) -> tuple[str | None, str]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:82` — `def qualify_id(namespace: str | None, page_id: str) -> str:`

### Existing Owned Files

- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `tests/knowledge/wiki/test_federation.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- No prerequisite task outputs.

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
- [ ] Reference is stored locally with unchanged foreign id and provenance.
- [ ] All existing foreign mutation prohibitions remain enforced.
- [ ] Source-owned replacement removes obsolete outgoing external edges.
- [ ] A forbidden source in a batch leaves no earlier edge inserted.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/test_federation.py tests/knowledge/wiki/roblox/test_federation_writes.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2903-federation-external-edge-writes.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_foreign_destination_reference_is_local` | Reference is stored locally with unchanged foreign id and provenance. |
| `test_foreign_sources_and_page_writes_refused` | All existing foreign mutation prohibitions remain enforced. |
| `test_replace_source_slice_foreign_destination` | Source-owned replacement removes obsolete outgoing external edges. |
| `test_invalid_batch_is_atomic` | A forbidden source in a batch leaves no earlier edge inserted. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2903-federation-external-edge-writes.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
