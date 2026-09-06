# TASK-2898: Resolve Roblox sourcemaps and static project paths

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2896, TASK-2897
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2900, TASK-2901, TASK-2902, TASK-2903, TASK-2904, TASK-2905, TASK-2908 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

**Execution gate**: TASK-2896 must record reviewed resource limits before mapping implementation starts.

---

## Context

Implements spec sections 2 Local scanning, 3.2 and 8 measured JSON limits. Use TASK-2896 reviewed policy; retain the exact LanguageScanner ABC and make this helper independent of production Luau parsing.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Implement mapping lookup using the explicit scan root, full discovered paths and TASK-2897 models. Read sourcemap.json first; use default.project.json when missing or invalid; always retain relative-string resolution.
- Resolve static script.Parent chains, game.Service.Path chains and relative strings, including .lua/.luau and init-module conventions. Retain className and all DataModel associations in stable order.
- Enforce reviewed byte/depth bounds from TASK-2896 before expensive decoding/traversal. Handle invalid, unsupported, cyclic-looking and stale mapping content as diagnostics, not build failures.
- Only emit a unique existing in-root discovered target. Reject numeric/computed requires, symlink escape, absolute external paths and duplicate candidates. Do not guess through a valid but stale sourcemap using project fallback.
- Expose a deterministic mapping digest and source-owned DataModel presentation inputs. No network or external executables.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/project.py` | CREATE | Bounded mapping reader and unique require resolver |
| `tests/knowledge/wiki/roblox/test_project_resolution.py` | CREATE | Mapping/require fixtures and edge cases |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages import get_scan_root
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
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/php.py:319` — `def build_reference_index(self, rel_paths: Iterable[str]) -> Any:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:219` — `class FileSlice(BaseModel):` Fields: rel_path: str; record: WikiPageRecord; imports: list[str]; language: str | None; symbols: list[SymbolRecord]; refs: list[SymbolRef].
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:248` — `class RepoScan(BaseModel):` Fields: root: Path; files: list[FileSlice]; dir_records: list[WikiPageRecord]; dir_edges: list[tuple[str, str, str]]; import_edges: list[tuple[str, str, str]]; skipped: list[str]; symbol_records: list[WikiPageRecord]; symbol_edges: list[tuple[str, str, str, str]].
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:630` — `def build_file_slice( root: Path, rel_path: str, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, symbol_depth: int = 2, ) -> FileSlice | None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:321` — `def file_concept_id(rel_path: str) -> str:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:803` — `def build_import_edges( files: list[FileSlice], index_paths: Iterable[str] | None = None, ) -> list[tuple[str, str, str]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:1116` — `def scan_repository( root: Path, suffixes: Iterable[str] | None = None, exclude_dirs: Iterable[str] | None = None, body_max_chars: int = DEFAULT_BODY_MAX_CHARS, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, use_git: bool = True, rel_paths: Iterable[str] | None = None, symbol_depth: int = 2, ) -> RepoScan:`

### Prerequisite Interfaces (new, not existing today)

- `TASK-2896` supplies measure luau parser limits and declare the optional grammar; read its completion contract before importing any new symbol.
- `TASK-2897` supplies define shared roblox scan and api generation models; read its completion contract before importing any new symbol.

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
- [ ] Sourcemap wins; absent/invalid map falls back; relative strings work in every mode.
- [ ] Stale, duplicate, non-discovered and escaping targets resolve to None.
- [ ] Static $path trees and Script/LocalScript/ModuleScript identities map predictably.
- [ ] Oversized or deep JSON fails quickly with a diagnostic.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_project_resolution.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2898-roblox-project-resolution.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_resolution_cascade` | Sourcemap wins; absent/invalid map falls back; relative strings work in every mode. |
| `test_unique_existing_target_only` | Stale, duplicate, non-discovered and escaping targets resolve to None. |
| `test_project_init_and_script_classes` | Static $path trees and Script/LocalScript/ModuleScript identities map predictably. |
| `test_mapping_resource_limits` | Oversized or deep JSON fails quickly with a diagnostic. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2898-roblox-project-resolution.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
