# TASK-2911: Document setup and enforce grammar/fallback CI coverage

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-2910
**Parallel**: false
**Parallelism notes**: Final dependent deliverable; no independent sibling work remains. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements spec section 3.7 and final documentation/CI criteria. Follow existing CI setup/actions and package-scoped uv sync. Check workflow syntax and targeted commands, not a speculative new dependency.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Document explicit first download with ingest roblox-api --refresh, later offline reuse, namespace registration, stored download metadata, refresh revisions and retention of old generations.
- Document mapping fallback, .lua/.luau coverage, no Luau sym/type inference, known-root chain heuristics and false positives, and the measured guard policy report.
- Extend the existing wiki-extras CI job to require the Luau grammar and run its tests without silently skipping; add a separate forced-absence path that proves fallback behavior even when other extras are installed.
- Include the TASK-2910 end-to-end suite, deterministic fixture generation and externally bounded pathological parser checks; use existing Python/uv/pytest dependencies, not a new timeout plugin.
- Publish logs as lightweight CI artifacts where practical and ensure the workflow cannot mark a grammar job successful when all Luau tests skip. Preserve existing CI jobs and report tested validation.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/guides/llm-wiki-guide.md` | MODIFY | Luau, setup, refresh, status and limitation guidance |
| `.github/workflows/ci.yml` | MODIFY | Focused Luau optional-grammar and forced-fallback checks |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.languages.treesitter import get_parser
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.cli import wiki
```

Declarations and source anchors for these imports are below. Pydantic, aiohttp
and yaml are already imported by `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:26` and
`packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:18`; dependency declarations were checked in
`packages/ai-parrot/pyproject.toml`. Only TASK-2896 may add/install the approved optional Luau grammar; no other new dependency is authorized.

### Existing Signatures to Use

- `.github/workflows/ci.yml:140` — `test-wiki-extras:`
- `docs/guides/llm-wiki-guide.md:1` — `# LLM Wiki — Complete Guide`
- `tests/knowledge/wiki/test_federation.py:1` — `"""Tests for multi-wiki federation (FEAT-450, wiki/federation.py).`
- `tests/knowledge/wiki/test_repo_scan.py:1` — `"""Tests for the deterministic repository scanner (repo_scan).`
- `tests/knowledge/wiki/test_namespaces_e2e.py:1` — `"""End-to-end namespace scenarios (FEAT-450).`
- `tests/knowledge/wiki/test_project_namespaces.py:1` — `"""Unit tests for FEAT-450 namespace declaration (project.py, Module 1)."""`
- `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py:1` — `"""Tests: federated namespaces reach the wikitoolkit MCP server (FEAT-450).`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:648` — `async def _ingest_files( store: BaseWikiStore, sources: SourceCollectionManager, root: Path, scan: Any, force: bool = False, ) -> dict[str, int]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3626` — `def ingest( source: str, path_: str | None, charter_opt: str | None, dry_run: bool, review_opt: Path | None, interactive_flag: bool, auto_flag: bool, extract_flag: bool, lightweight_model_opt: str | None, model_opt: str | None, audit_rate: float, manifest_opt: Path | None, recursive: bool, fetch_timeout: float, ) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1773` — `def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:173` — `def _federate( root: Path, config: WikiProjectConfig, local: BaseWikiStore, ns_opt: str | None, ) -> BaseWikiStore:`
- `packages/ai-parrot/pyproject.toml:271` — `wiki-languages = [`
- `pyproject.toml:60` — `[dependency-groups]`
- `uv.lock:1` — `version = 1`

### Existing Owned Files

- `docs/guides/llm-wiki-guide.md:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.
- `.github/workflows/ci.yml:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- `TASK-2910` supplies verify roblox lifecycle and federation compatibility; read its completion contract before importing any new symbol.

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
- [ ] The extra job verifies tree_sitter_luau import/parse capability before tests.
- [ ] A separate forced-absence test invocation covers the bounded heuristic path.
- [ ] Pathological case cannot hang the job indefinitely.
- [ ] Documented registration/build/query/refresh commands match successful CLI fixtures.
- [ ] Focused checks pass: `Validate .github/workflows/ci.yml and run its focused Luau test invocations.`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2911-roblox-docs-ci.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `ci_luau_grammar_presence` | The extra job verifies tree_sitter_luau import/parse capability before tests. |
| `ci_luau_fallback` | A separate forced-absence test invocation covers the bounded heuristic path. |
| `ci_resource_deadline` | Pathological case cannot hang the job indefinitely. |
| `docs_command_smoke` | Documented registration/build/query/refresh commands match successful CLI fixtures. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2911-roblox-docs-ci.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
