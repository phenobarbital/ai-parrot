# TASK-2897: Define shared Roblox scan and API generation models

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2896, TASK-2903, TASK-2904, TASK-2905 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements spec section 2 Data Models. New model names are proposed contracts, not existing imports. This task owns models.py; downstream tasks should consume these interfaces and request a scoped follow-up if a contract must change.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Define RobloxInstanceIndex, RobloxApiManifest, RobloxApiCatalog, RobloxFileEnrichment and RobloxApiIngestResult as the proposed spec models. Include explicit one-to-many instance/file associations, mapping diagnostics, generation identities and dependency digests.
- Keep API ids as class/<name> and enum/<name> inside the generation; qualified ids belong to external references. Define typed candidate records retaining source span, recognized root and extraction kind for diagnostics.
- Include Studio version, creator-docs SHA, renderer schema version, payload hashes, downloaded_at, generation location, counts and structural-only diagnostics in manifest/result contracts. Separate stable content identity from acquisition time.
- Define read-only normalized dump input types or typed mappings needed by acquisition and rendering so those tasks agree without shared-file edits. Reject invalid identity/hash/schema data; do not require a hardcoded class count.
- Document serialization and mutability boundaries; import the package without aiohttp clients, LLM clients, grammar loading or filesystem writes.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/__init__.py` | CREATE | Minimal package with no eager network imports |
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/models.py` | CREATE | Typed data contracts shared by independent tracks |
| `tests/knowledge/wiki/roblox/test_models.py` | CREATE | Validation and stable serialization |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.store import WikiPageRecord
from parrot.knowledge.wiki.project import WikiNamespaceConfig, parrot_home, load_global_registry, save_global_registry
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:23` — `class LanguageOutline(BaseModel):` Fields: summary: str; outline: list[str]; imports: list[str]; symbols: list[SymbolRecord]; refs: list[SymbolRef].
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:175` — `class WikiNamespaceConfig(BaseModel):` Fields: path: str | None; store: str | None; backend: str; database: str | None; credentials_env: str; vault: str | None; description: str; weight: float.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:940` — `def parrot_home() -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:960` — `def load_global_registry(path: Path | None = None) -> GlobalWikiRegistry:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:986` — `def save_global_registry(registry: GlobalWikiRegistry, path: Path | None = None) -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1017` — `def merge_namespaces( repo: dict[str, WikiNamespaceConfig], global_: dict[str, WikiNamespaceConfig], ) -> dict[str, tuple[WikiNamespaceConfig, str]]:`

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
- [ ] All provenance survives deterministic serialization and parsing.
- [ ] Multiple instance/file associations survive without arbitrary collapse.
- [ ] Invalid required identifiers/negative counts fail validation.
- [ ] No acquisition, parser construction or filesystem mutation on import.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_models.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2897-roblox-shared-models.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_manifest_roundtrip` | All provenance survives deterministic serialization and parsing. |
| `test_instance_mapping_preserves_ambiguity` | Multiple instance/file associations survive without arbitrary collapse. |
| `test_invalid_identity_is_rejected` | Invalid required identifiers/negative counts fail validation. |
| `test_package_import_is_inert` | No acquisition, parser construction or filesystem mutation on import. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2897-roblox-shared-models.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
