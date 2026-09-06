# TASK-2905: Classify external reference health without weakening local lint

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2904
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2896, TASK-2897, TASK-2898, TASK-2899, TASK-2900, TASK-2901, TASK-2902, TASK-2906, TASK-2907 once each task's own prerequisites are complete; owned files are disjoint. Shared-file edits are serialized after TASK-2903, TASK-2904. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements sections 2 cross-plane health and 8 blast radius. No API CDN/GitHub probes and no SQL change to hide qualified targets. This task serializes after TASK-2904 because both own federation.py.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Classify local broken_edges candidates at the federated boundary: resolved foreign pages are healthy, known-available namespaces with missing pages remain broken, unavailable/unbuilt namespaces are deferred/unverifiable diagnostics.
- Never blanket-ignore a string containing ::. Preserve malformed/local ids as local lint failures and maintain task-local skip reporting for concurrent reads.
- Inspect LLMWikiToolkit.lint and route a configured federation read context to cross-reference checks while keeping source staleness and ownership local. Do not acquire API data or silently create namespace state.
- Keep standalone BaseWikiStore.broken_edges behavior unchanged. Use existing report dictionaries for additive classification; if the toolkit has no namespace declaration context, report raw unresolved edges honestly rather than treating them as valid.
- Preserve scope semantics and fail-soft namespace reads without swallowing genuine local-store failures. CLI status presentation follows in TASK-2908.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | Foreign target health and per-read degradation notes |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | Preserve federation-aware lint read context when supplied |
| `tests/knowledge/wiki/roblox/test_edge_health.py` | CREATE | Resolved/missing/unavailable/malformed health matrix |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, NamespaceSkip
from parrot.knowledge.wiki.store import WikiPageRecord, SQLiteWikiStore, create_wiki_store, estimate_tokens
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.knowledge.wiki.models import WikiLintReport
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:597` — `def __init__( self, local: BaseWikiStore, local_name: str = "local", handles: list[NamespaceHandle] | None = None, skipped: list[NamespaceSkip] | None = None, *, qualify_local: bool = False, ) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:646` — `def scoped(self, selector: str | None) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:877` — `async def neighbors( self, concept_id: str, rel: str | None = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1088` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:552` — `def _qualify_row(row: dict[str, Any], namespace: str | None) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:208` — `def estimate_tokens(text: str) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1795` — `def create_wiki_store( storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any, ) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1134` — `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1154` — `async def add_edges(self, edges: list[tuple]) -> int:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1176` — `async def replace_source_slice( self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None, ) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1672` — `async def neighbors( self, concept_id: str, rel: Optional[str] = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1773` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:458` — `async def lint( self, wiki_name: str, fix: bool = False, ) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/models.py:302` — `class WikiLintReport(BaseModel):` Fields: okf_report: dict[str, Any]; orphan_sources: list[str]; stale_sources: list[str]; uncovered_sources: list[str]; cross_ref_issues: list[dict[str, Any]]; total_issues: int.

### Existing Owned Files

- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- `TASK-2904` supplies route external neighbors and local incoming references; read its completion contract before importing any new symbol.

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
- [ ] Available API page clears the candidate while ordinary local missing targets remain broken.
- [ ] Typo in an available declared namespace is still reported.
- [ ] Unavailable plane is diagnosed separately and local results survive.
- [ ] Malformed ids are not suppressed and per-call skip notes do not leak.
- [ ] Configured federated lint classifies edges while checking local source staleness.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_edge_health.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2905-federation-edge-health.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_resolved_external_edge_is_healthy` | Available API page clears the candidate while ordinary local missing targets remain broken. |
| `test_missing_page_is_broken` | Typo in an available declared namespace is still reported. |
| `test_unbuilt_namespace_is_unverifiable` | Unavailable plane is diagnosed separately and local results survive. |
| `test_malformed_namespace_and_concurrent_reads` | Malformed ids are not suppressed and per-call skip notes do not leak. |
| `test_toolkit_lint_uses_read_context` | Configured federated lint classifies edges while checking local source staleness. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2905-federation-edge-health.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
