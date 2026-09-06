# TASK-2900: Acquire the versioned API dump and SHA-pinned docs tarball

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2897
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2896, TASK-2898, TASK-2899, TASK-2901, TASK-2903, TASK-2904, TASK-2905, TASK-2906, TASK-2907 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements section 8 final tarball decision, overriding earlier per-file concurrency/retry prose. The two-request figure concerns creator-docs only; Studio version/dump are additional requests. Do not claim benchmark timings as service guarantees.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Implement async explicit acquisition of Studio version and its API dump, plus creator-docs commit SHA and one codeload tarball pinned to that SHA. Validate each identity before using it in URL construction.
- Use aiohttp, io.BytesIO and tarfile. Read only regular class YAML members under */content/en-us/reference/engine/classes/*.yaml using extractfile; never extract to the filesystem, follow archive links or invoke git.
- Apply bounded HTTP timeouts and compressed/uncompressed/member-size limits. Filter to dump-named classes, safe-load YAML and distinguish missing class prose from malformed present data or transport failure.
- Honor section 8: no raw-file fan-out, per-file cache, automatic retries or backoff. Fail the acquisition with a clear error; publication belongs to TASK-2902 and cannot occur here.
- Return typed immutable-generation inputs and hashes for rendering. Accept previously acquired whole-generation payloads for explicit-refresh reuse when identities are unchanged; no ambient cache eviction or TTL.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/roblox/acquire.py` | CREATE | Explicit async HTTP acquisition and in-memory tar member reading |
| `tests/knowledge/wiki/roblox/test_acquire.py` | CREATE | Mocked endpoints, archive filtering and failure tests |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
import aiohttp
import yaml
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.store import WikiPageRecord
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:57` — `class DocumentRef(BaseModel):` Fields: uri: str; is_url: bool; suffix: str.
- `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` — `import aiohttp`
- `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:28` — `import yaml`
- `packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:23` — `class LanguageOutline(BaseModel):` Fields: summary: str; outline: list[str]; imports: list[str]; symbols: list[SymbolRecord]; refs: list[SymbolRef].
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299` — `class WikiPageRecord(BaseModel):` Fields: concept_id: str; node_id: Optional[str]; title: str; category: str; summary: str; body: str; source_id: Optional[str]; token_count: int; origin: str; asserted_by: Optional[str]; updated_at: Optional[str]; content_hash: Optional[str].

### Prerequisite Interfaces (new, not existing today)

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
- [ ] One commit-resolution and one tarball request for docs; no raw YAML requests.
- [ ] Only desired regular members are read; traversal/symlink/oversize archives fail or are ignored safely.
- [ ] Absent class docs are structural-only; invalid present YAML fails.
- [ ] Timeout, rate limit, invalid identities and truncated data fail once and do not publish.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_acquire.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2900-roblox-api-acquisition.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_sha_pinned_tarball_requests` | One commit-resolution and one tarball request for docs; no raw YAML requests. |
| `test_no_archive_extraction_to_disk` | Only desired regular members are read; traversal/symlink/oversize archives fail or are ignored safely. |
| `test_missing_vs_malformed_yaml` | Absent class docs are structural-only; invalid present YAML fails. |
| `test_http_failure_no_retry` | Timeout, rate limit, invalid identities and truncated data fail once and do not publish. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2900-roblox-api-acquisition.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
