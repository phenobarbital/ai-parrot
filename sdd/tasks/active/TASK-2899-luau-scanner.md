# TASK-2899: Implement bounded Luau outlines and register both suffixes

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2896, TASK-2898
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2900, TASK-2901, TASK-2902, TASK-2903, TASK-2904, TASK-2905, TASK-2908 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

**Execution gate**: Do not start until TASK-2896 has measured and recorded review of its resource policy; fixed thresholds are not guessed from the spec.

---

## Context

Implements spec sections 3.1 and 5 scanner criteria. TASK-2896 owns dependency files; this task must not edit them. Registry and repo_scan ownership are serialized with TASK-2907.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Implement all LanguageScanner methods for Luau, delegating mapping resolution to TASK-2898. Extract leading comments, named/local functions, colon methods, written types/exported types, module-table exports and raw require arguments.
- Apply all three reviewed guards from TASK-2896: pre-parse size admission, ERROR density handling and enforceable parse timeout. Bound fallback input and ensure timeout cleanup/reset before reuse; never depend on a post-parse check to interrupt a stuck parse.
- Use tree-sitter when available and bounded heuristics otherwise. Mask comments and string bodies while retaining literal call arguments needed for requires; do not treat examples embedded in prose as code.
- Return empty LanguageOutline on unexpected failure; preserve unrelated valid declarations after local grammar errors. Return empty symbols and refs in all modes, including when wiki-structural is installed.
- Register luau and both suffixes; report grammar/heuristic capability accurately with per-file guard diagnostics. Do not modify ABC signatures or ast-grep registration.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/luau.py` | CREATE | Complete LanguageScanner implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/luau_guard.py` | CREATE | Measured parse admission/cancellation/fallback implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py` | MODIFY | Explicit Luau scanner registration |
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py` | MODIFY | Luau grammar module entry only |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | CODE_SUFFIXES .lua and .luau entries only |
| `tests/knowledge/wiki/languages/test_luau.py` | CREATE | Outline, guard, import and fallback tests |
| `tests/knowledge/wiki/languages/test_registry.py` | MODIFY | Assert both suffixes are claimed |
| `tests/knowledge/wiki/languages/test_treesitter.py` | MODIFY | Luau loader/fallback coverage |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages import get_scan_root
from parrot.knowledge.wiki.languages.treesitter import get_parser
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, build_file_slice, scan_repository
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
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py:64` — `def get_parser(language: str) -> Parser | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py:86` — `def _build_parser(language: str) -> Parser | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/perl.py:222` — `def outline(self, source: str, rel_path: str) -> LanguageOutline:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:219` — `class FileSlice(BaseModel):` Fields: rel_path: str; record: WikiPageRecord; imports: list[str]; language: str | None; symbols: list[SymbolRecord]; refs: list[SymbolRef].
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:248` — `class RepoScan(BaseModel):` Fields: root: Path; files: list[FileSlice]; dir_records: list[WikiPageRecord]; dir_edges: list[tuple[str, str, str]]; import_edges: list[tuple[str, str, str]]; skipped: list[str]; symbol_records: list[WikiPageRecord]; symbol_edges: list[tuple[str, str, str, str]].
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:630` — `def build_file_slice( root: Path, rel_path: str, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, symbol_depth: int = 2, ) -> FileSlice | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:321` — `def file_concept_id(rel_path: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:803` — `def build_import_edges( files: list[FileSlice], index_paths: Iterable[str] | None = None, ) -> list[tuple[str, str, str]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:1116` — `def scan_repository( root: Path, suffixes: Iterable[str] | None = None, exclude_dirs: Iterable[str] | None = None, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, use_git: bool = True, rel_paths: Iterable[str] | None = None, symbol_depth: int = 2, ) -> RepoScan:`
- `packages/ai-parrot/pyproject.toml:271` — `wiki-languages = [`
- `pyproject.toml:60` — `[dependency-groups]`
- `uv.lock:1` — `version = 1`

### Existing Owned Files

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/__init__.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/treesitter.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `tests/knowledge/wiki/languages/test_registry.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `tests/knowledge/wiki/languages/test_treesitter.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- `TASK-2896` supplies measure luau parser limits and declare the optional grammar; read its completion contract before importing any new symbol.
- `TASK-2898` supplies resolve roblox sourcemaps and static project paths; read its completion contract before importing any new symbol.

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
- [ ] Functions, colon methods, type exports and module tables preserve written signatures.
- [ ] Attributes/type packs leave later valid declarations intact.
- [ ] Missing/broken grammar yields bounded output without sym pages.
- [ ] Measured size, density and timeout paths terminate and clean up.
- [ ] Only code-level calls produce import specifiers.
- [ ] Default discovery and explicit scanner lookup agree.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/languages/test_luau.py tests/knowledge/wiki/languages/test_registry.py tests/knowledge/wiki/languages/test_treesitter.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2899-luau-scanner.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_outline_syntax_matrix` | Functions, colon methods, type exports and module tables preserve written signatures. |
| `test_unsupported_syntax_local_recovery` | Attributes/type packs leave later valid declarations intact. |
| `test_forced_heuristic` | Missing/broken grammar yields bounded output without sym pages. |
| `test_guard_combination` | Measured size, density and timeout paths terminate and clean up. |
| `test_requires_ignore_comments` | Only code-level calls produce import specifiers. |
| `test_registry_claims_lua_and_luau` | Default discovery and explicit scanner lookup agree. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2899-luau-scanner.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
