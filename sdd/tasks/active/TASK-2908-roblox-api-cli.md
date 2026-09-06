# TASK-2908: Add API ingest dispatch and offline plane status

**Feature**: FEAT-532 - Luau/Roblox support for wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-luau-roblox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2902, TASK-2905
**Parallel**: true
**Parallelism notes**: Can run in a separate implementation worktree alongside TASK-2896, TASK-2898, TASK-2899, TASK-2906, TASK-2907 once each task's own prerequisites are complete; owned files are disjoint. Do not share an implementation checkout between parallel writers. Per-spec index updates require coordination.
**Assigned-to**: unassigned

---

## Context

Implements sections 2 CLI and final 8 refresh/status decisions. Serialize all later CLI writes behind this task. Account for FEAT-531 active CLI LLM-fallback work by re-reading cli.py at execution time; preserve those changes.

The approved spec's final section 8 owner decisions override stale earlier
proposal text: real cross-namespace federation, SHA-pinned in-memory tarball
acquisition, known-root chained accesses in v1, and network/regeneration only
on explicit `--refresh`. First acquisition therefore requires `--refresh`.
There is no TTL, raw-file downloader, retry/backoff machinery, LSP, ast-grep
Luau registration or Luau `sym:` output.

## Scope

- Add --refresh dispatch for bare SOURCE roblox-api before document mode validation or LLM imports. Keep ingest a command, preserve existing SOURCE modes/options and let ./roblox-api address a literal document path.
- Follow final section 8: ingest roblox-api without --refresh is offline and never regenerates; absent state produces instructions to use --refresh. Reject incompatible explicit document-ingest flags only, not their Click default values.
- On successful explicit refresh print plane location, provenance and namespace-registration guidance. Do not replace an unrelated namespace or auto-expire a plane.
- Add stored downloaded_at and recorded Studio/docs versions to text and JSON status for the selected Roblox plane; status makes no API CDN/GitHub probes and must not introduce new network access.
- Preserve existing backend probing behavior for unrelated server-backed namespaces; the new Roblox status path reads only local manifest state. Show appropriate not-downloaded/unavailable diagnostics.

**NOT in scope**: work owned by other tasks, unrelated refactors, deployment,
and changes to the approved feature decisions. Only edit the owned files below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Ingest early dispatch, namespace hint and download-status payload |
| `tests/knowledge/wiki/roblox/test_api_cli.py` | CREATE | Click compatibility and zero-network defaults |

## Codebase Contract (Anti-Hallucination)

Verified by fresh source reads on 2026-09-06. These are source-level verified
contracts, not a claim that every optional runtime import was executed.
Line numbers are anchors; reverify before implementation if the base changes.

### Verified Imports

```python
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiNamespaceConfig, parrot_home, load_global_registry, save_global_registry
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, NamespaceSkip
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
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:175` — `class WikiNamespaceConfig(BaseModel):` Fields: path: str | None; store: str | None; backend: str; database: str | None; credentials_env: str; vault: str | None; description: str; weight: float.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:940` — `def parrot_home() -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:960` — `def load_global_registry(path: Path | None = None) -> GlobalWikiRegistry:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:986` — `def save_global_registry(registry: GlobalWikiRegistry, path: Path | None = None) -> Path:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1017` — `def merge_namespaces( repo: dict[str, WikiNamespaceConfig], global_: dict[str, WikiNamespaceConfig], ) -> dict[str, tuple[WikiNamespaceConfig, str]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:597` — `def __init__( self, local: BaseWikiStore, local_name: str = "local", handles: list[NamespaceHandle] | None = None, skipped: list[NamespaceSkip] | None = None, *, qualify_local: bool = False, ) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:646` — `def scoped(self, selector: str | None) -> BaseWikiStore:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:877` — `async def neighbors( self, concept_id: str, rel: str | None = None, direction: str = "both", ) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1088` — `async def broken_edges(self) -> list[dict[str, Any]]:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:552` — `def _qualify_row(row: dict[str, Any], namespace: str | None) -> dict[str, Any]:`

### Existing Owned Files

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1` — existing owned file re-read; modifications restricted to the scope/file-table region above.

### Prerequisite Interfaces (new, not existing today)

- `TASK-2902` supplies publish immutable api generations with explicit refresh; read its completion contract before importing any new symbol.
- `TASK-2905` supplies classify external reference health without weakening local lint; read its completion contract before importing any new symbol.

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
- [ ] API path reaches generation orchestration before document/LLM setup.
- [ ] Missing plane without --refresh makes no HTTP calls and provides explicit next command.
- [ ] Refresh works; explicit incompatible flags fail without rejecting defaults.
- [ ] Existing ingest SOURCE and ./roblox-api keep their behavior.
- [ ] Stored timestamp/versions render without API acquisition or freshness probes.
- [ ] Focused checks pass: `uv run pytest tests/knowledge/wiki/roblox/test_api_cli.py -q`.
- [ ] Applicable Python formatting/import checks pass for owned code.
- [ ] Verification output is stored at `artifacts/logs/task-2908-roblox-api-cli.log`.
- [ ] Changes outside owned paths are absent; prerequisite review gates are recorded.

## Test Specification

Use pytest/pytest-asyncio and isolated temporary state. The following observable
behaviors are required; write meaningful tests rather than mirroring helpers.
Do not invent a test fixture/API from its name without verifying or defining it.

| Test / check | Required behavior |
|---|---|
| `test_api_dispatch_has_no_llm_import` | API path reaches generation orchestration before document/LLM setup. |
| `test_default_first_use_offline` | Missing plane without --refresh makes no HTTP calls and provides explicit next command. |
| `test_refresh_and_document_flag_validation` | Refresh works; explicit incompatible flags fail without rejecting defaults. |
| `test_literal_document_source_compatibility` | Existing ingest SOURCE and ./roblox-api keep their behavior. |
| `test_status_text_json_are_offline` | Stored timestamp/versions render without API acquisition or freshness probes. |

## Agent Instructions

1. Read `sdd/specs/wikitoolkit-luau-roblox.spec.md`, particularly the final section 8 decisions.
2. Check that dependencies are completed and any execution gate is satisfied.
3. Re-read the contract files and dependency outputs before writing code.
4. Update only this task entry in `sdd/tasks/index/wikitoolkit-luau-roblox.json` to `in-progress`, recording assignment/time.
5. Implement only owned paths; coordinate shared changes and preserve other work.
6. Run the focused checks, record logs and verify each acceptance criterion.
7. Move this task to `sdd/tasks/completed/TASK-2908-roblox-api-cli.md`.
8. Update this per-spec index entry to `done` with completion time and moved path.
9. Fill the completion note and commit implementation plus scoped task/index state.

Do not use the historical `sdd/tasks/.index.json`.

## Completion Note

To be completed by the implementing agent after verification; this task is pending.
Record completed-by identity, date, exact checks/results, measured limits where
applicable, and any deviations from the approved scope.
