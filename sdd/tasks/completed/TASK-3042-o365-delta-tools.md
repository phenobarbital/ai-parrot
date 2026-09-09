# TASK-3042: SharePoint and OneDrive delta tools and registration

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3041
**Assigned-to**: sdd-worker (O365 lane, worktree feat-FEAT-539-contracts-o365-delta)
**Parallel**: true
**Parallelism notes**: Execute in O365 worktree feat-FEAT-539-contracts-o365-delta. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M8 in spec §3 and the corresponding normative §2 behavior. Covers AC9, AC13; full feature acceptance remains governed by spec §§4–5.

## Scope

- Add DeltaSharePointFilesTool and DeltaOneDriveFilesTool backed by shared delta helper through O365Tool._execute_graph_operation and authenticated O365Client.graph_client.
- Resolve configured drive/folder identity without model-supplied endpoint expansion; expose typed pages and tombstones via normal tool result/auth lifecycle.
- Register/export in existing bundles without removing existing list/search/download/upload tools. Keep this O365 lane independent and integrate its commits before contracts delta-job work.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/o365/__init__.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/test_o365_delta_tools.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot_tools.o365.base import O365Tool, O365ToolArgsSchema  # packages/ai-parrot-tools/src/parrot_tools/o365/base.py:31
from parrot.interfaces.o365 import O365Client  # packages/ai-parrot/src/parrot/interfaces/o365.py:339
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| O365Tool._execute_graph_operation | async (self, client: O365Client, **kwargs) -> Any; _execute handles authentication and ToolResult | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:200 |
| O365Client.graph_client | Authenticated GraphServiceClient property | packages/ai-parrot/src/parrot/interfaces/o365.py:339 |

Existing O365 registration files re-read: `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py:15`, `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py:14`, `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py:9`, `packages/ai-parrot-tools/src/parrot_tools/o365/__init__.py:17`. Delta classes/helper do not yet exist.

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3041`: O365 drive delta pages, validation and retry helper; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [x] Both tools preserve O365 authentication/error wrapping and produce equivalent typed continuation/deletion outcomes.
- [x] Bundle regression retains prior tools and adds both delta tools; no contracts or scheduler import appears.
- [x] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Both tools preserve O365 authentication/error wrapping and produce equivalent typed continuation/deletion outcomes.
2. Bundle regression retains prior tools and adds both delta tools; no contracts or scheduler import appears.

Validation: `uv run pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`

Store execution logs in `artifacts/logs/task-3042.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3042-o365-delta-tools.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

**Executor**: sdd-worker (Claude Opus 5) — worktree `feat-FEAT-539-contracts-o365-delta`
**Completed**: 2026-09-09
**Depends-on**: TASK-3041 (completed and committed in this worktree first — `668ccbf9a`)

### Implementation summary

- **`DeltaSharePointFilesTool`** (`sharepoint.py`) — `name="delta_sharepoint_files"`.
  Resolves a document library to its stable drive id through
  `graph_client.sites.by_site_id(site_id).drives`, matching `library`
  case-insensitively and erroring with the available names when it does not
  exist (or when the site is ambiguous and no library was named). An explicit
  `drive_id` skips the lookup.
- **`DeltaOneDriveFilesTool`** (`onedrive.py`) — `name="delta_onedrive_files"`.
  Resolves `graph_client.me.drive` or, for app-only access,
  `graph_client.users.by_user_id(user_id).drive`. An explicit `drive_id`
  skips the lookup.
- Both delegate the actual walk to `DriveDeltaHelper.enumerate()` from
  TASK-3041 and return the same payload shape:
  `enumeration.model_dump(mode="json")` (items with tombstones, `delta_link`,
  `pages_fetched`, `complete`, `reset_performed`, `full_enumeration`,
  `folder_path`, `filtered_out`) plus `source`, `total_items`,
  `changed_count`, `deleted_count` and the source-specific identity keys.
  A `delta_helper=` constructor argument allows tuning retry bounds or the
  trusted Graph origins per deployment.
- Both stay inside the standard `O365Tool` lifecycle: `_execute` performs
  authentication (including the OBO bridge) and wraps success *and* failure
  in a `ToolResult`; the tools only implement `_execute_graph_operation` and
  only ever touch `O365Client.graph_client`.
- **No model-supplied endpoint expansion**: `site_id` / `drive_id` /
  `user_id` pass through `_validate_graph_identifier`, which rejects
  URL-shaped values (`://`, leading `//`), whitespace/control characters and
  implausibly long strings *before* any request is built. Delta cursors are
  separately validated against the configured Graph origins by the helper.
- **Registration is additive** (`bundle.py`): `SharePointToolkit`,
  `OneDriveToolkit` and `Office365FileManagementToolkit` keep all four
  pre-existing list/search/download/upload tools and gain the delta tool;
  `get_sharepoint_tools()` / `get_onedrive_tools()` include it too.
  `o365/__init__.py` exports both tool classes plus `DriveDeltaHelper`,
  `DeltaItem`, `DeltaPage`, `DeltaEnumeration` and the delta error types.

### Validation evidence

- `pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`
  → **42 passed**; both delta suites together → **97 passed**.
- `ruff check` on the whole `o365/` package + the new test: 8 findings, all
  pre-existing on `dev` (`base.py` unused `contextlib`, `bundle.py` unused
  `Dict` and its `__main__` example locals, `events.py` unused `Importance`,
  `oauth_toolkit.py` TYPE_CHECKING import, `sharepoint.py:582` unused
  `overwrite` in the *upload* tool). Verified against the pre-change blobs;
  **no new finding** comes from this task.
- `pytest packages/ai-parrot-tools/tests/test_imports_integrity.py`
  → 8 passed, 2 failed; both failures are pre-existing and unrelated to
  O365 (`ydata_profiling` / `parrot_tools.nextstop` / `parrot.finance`
  missing from the registry, and a stale `parrot.tools.*` import in
  `parrot_tools/databasequery.py`).
- Log: `artifacts/logs/task-3042.log`.

### Deviations / notes for downstream tasks

- **Stale Codebase Contract corrected.** The contract implied the tools
  could follow the sibling SharePoint/OneDrive tools and call
  `client.verify_sharepoint_access()` / `client._resolve_drive(...)`. Those
  methods exist only on `SharepointClient` / `OneDriveClient`, while
  `O365Tool._get_client()` always constructs a plain `O365Client`
  (`base.py:148`) — so the existing list/search/download/upload tools would
  raise `AttributeError` on that path. This is a **pre-existing defect in
  `base.py`, which this task does not own**; it is reported here rather than
  fixed. The delta tools therefore resolve drive identity through
  `graph_client` only, which is exactly the surface the contract verified.
- **`TOOL_REGISTRY` not updated.** The two delta tools are not registered in
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py`, because that file
  is owned by neither this task nor spec §3 M8 (which scopes M8 to
  `o365/{delta,sharepoint,onedrive,bundle,__init__}.py`). Follow-up if
  name-based discovery is wanted: add
  `"delta_share_point_files"` / `"delta_one_drive_files"` entries there.
- Also noted while editing `o365/__init__.py`: it never exported the
  SharePoint list/search/download/upload tools. Left as-is (out of scope);
  only `DeltaSharePointFilesTool` was added from that module.
- Downstream (TASK-3049 `ingest_delta`): commit the returned `delta_link`
  **only** when `complete is True` and every item has been durably processed
  or explicitly recorded as skipped; `reset_performed=True` means the
  listing is a full rescan and must never be read as mass deletion.
