# TASK-2906: Extract API references including known-root chains

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2899, TASK-2901
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2900, TASK-2902, TASK-2903, TASK-2904, TASK-2905, TASK-2908 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements final section 8 expanded link scope, overriding the earlier proposal that excluded chains. TASK-2899 owns parser internals; consume its verified bounded interface after dependency completion.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Recognize literal game:GetService("X"), explicit API type annotations and chained instance access on known unshadowed roots, including workspace.Terrain. Use the offline catalog from TASK-2901.
- Use source spans and lexical scope to exclude comments/string examples, shadowed game/workspace/class names and local type aliases. Preserve literal service arguments while masking irrelevant strings.
- Resolve known-root chains using explicit root/static catalog information; accept the owner-approved heuristic false-positive tradeoff without adding expression type inference or LSP calls.
- Deduplicate and qualify references to known catalog targets; report unresolvable chains without guessing unknown class identities. Preserve evidence kind for diagnostics.
- Use the same reviewed bounded source handling as the scanner; with no catalog produce no external edges and an explicit skipped-linking diagnostic.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/references.py` | CREATE | Bounded static code-to-API candidate resolution |
| `tests/knowledge/wiki/roblox/test_reference_candidates.py` | CREATE | Literal service/type/chain and shadowing cases |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages import get_scan_root
from parrot.knowledge.wiki.context import split_namespaced_id, qualify_id
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.store import WikiPageRecord
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:23` — `class LanguageOutline(BaseModel):` Fields: summary: str; outline: list[str]; imports: list[str]; symbols: list[SymbolRecord]; refs: list[SymbolRef].
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:66` — `def outline(self, source: str, rel_path: str) -> LanguageOutline:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:83` — `def build_reference_index(self, rel_paths: Iterable[str]) -> Any:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:100` — `def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:118` — `def mode(self) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py:101` — `def get_scan_root() -> Path | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py:48` — `def scanner_for(suffix: str) -> LanguageScanner | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:54` — `def split_namespaced_id(page_id: str) -> tuple[str | None, str]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/context.py:82` — `def qualify_id(namespace: str | None, page_id: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].

### Prerequisite Interfaces (new, not existing today)

- `TASK-2899` supplies implement bounded luau outlines and register both suffixes; read its completion contract before importing any new symbol.
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
- [ ] Literal services and genuine API annotations yield class references.
- [ ] Known-root chained access is included in v1.
- [ ] Local scope aliases/shadowed roots/string examples do not create references.
- [ ] No network and no invented API page ids.
- [ ] Pathological source follows the reviewed fallback/resource policy.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_reference_candidates.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2906-roblox-api-reference-candidates.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_services_and_explicit_types` | Literal services and genuine API annotations yield class references. |
| `test_workspace_terrain_and_known_chains` | Known-root chained access is included in v1. |
| `test_shadowing_aliases_and_comments` | Local scope aliases/shadowed roots/string examples do not create references. |
| `test_missing_catalog_and_unknown_target` | No network and no invented API page ids. |
| `test_bounded_candidate_extraction` | Pathological source follows the reviewed fallback/resource policy. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2906-roblox-api-reference-candidates.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
