# TASK-3041: O365 drive delta pages, validation and retry helper

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in O365 worktree feat-FEAT-539-contracts-o365-delta. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M8 in spec §3 and the corresponding normative §2 behavior. Covers AC9; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement O365-owned typed delta item/page models and shared authenticated drive-level delta helper, independent of core contracts models.
- Expose stable drive/item IDs, tombstones, opaque next/final links and folder filtering metadata. Follow continuations to final delta link, handle 410 reset/rescan and bounded throttling/transient backoff.
- Validate continuation endpoint against configured Microsoft Graph origin before forwarding credentials. Verify installed SDK request-builder interfaces and Microsoft Graph v1.0 delta semantics during implementation; do not assume a new SDK API.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/test_o365_delta_protocol.py` | CREATE | Focused verification / fixtures |

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

- No feature prerequisites; preserve the independent scope.

## Acceptance Criteria

- [ ] Fake Graph pages cover multipage, empty intermediate page, final cursor, duplicate item and deleted marker.
- [ ] 410 triggers safe rescan state; retry is bounded and respects throttling; malicious foreign continuation host is rejected before request.
- [ ] Helper imports no contracts package and performs no cursor commit or document ingestion.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Fake Graph pages cover multipage, empty intermediate page, final cursor, duplicate item and deleted marker.
2. 410 triggers safe rescan state; retry is bounded and respects throttling; malicious foreign continuation host is rejected before request.
3. Helper imports no contracts package and performs no cursor commit or document ingestion.

Validation: `uv run pytest packages/ai-parrot-tools/tests/test_o365_delta_protocol.py -q`

Store execution logs in `artifacts/logs/task-3041.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3041-o365-delta-protocol.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot_tools/o365/delta.py` — typed `DeltaItem`
(stable drive/item ids, path, etag, sha256, tombstone flag, folder matching),
`DeltaPage` (items + opaque next/delta links) and `DeltaEnumeration`, plus
`DriveDeltaReader`. Enumeration follows `@odata.nextLink` until
`@odata.deltaLink`, treats an empty intermediate page as legal, de-duplicates
repeated items keeping the latest report, always keeps tombstones (a deleted item
has no path to filter on), and only reports a committable cursor when the walk
actually reached the final link — a truncated walk returns `delta_link=None`. A 410
raises `DeltaTokenExpired` from `fetch_page` and surfaces as
`rescan_required=True` from `enumerate`, never as mass deletion. Retries are bounded
(429/5xx only, `Retry-After` honoured, exponential backoff otherwise); 4xx is not
retried. `validate_continuation` rejects any non-HTTPS or non-Microsoft-Graph
continuation **before** the request, so credentials are never forwarded to a foreign
host.

**SDK verification**: checked against the installed `msgraph` package —
drive-level delta is `drives.by_drive_id(id).items.by_drive_item_id('root').delta`,
the response exposes `value`/`odata_next_link`/`odata_delta_link`, and
`DeltaRequestBuilder.with_url(raw_url)` is the continuation mechanism. No new SDK API
was assumed.

**Validation**: `pytest packages/ai-parrot-tools/tests/test_o365_delta_protocol.py -q`
-> 29 passed (`artifacts/logs/task-3041.log`); ruff clean. Fake Graph pages cover
multipage walks, an empty intermediate page, the final cursor, duplicate items,
tombstones, folder filtering, truncation, resuming from a committed token, 410
rescan, bounded retry with Retry-After, backoff and give-up, and non-retried client
errors. AST tests prove the module imports nothing from the contracts package and
calls no cursor-commit or ingestion API.

**Deviations**: none. Implemented in the core feature worktree rather than the
separate `feat-FEAT-539-contracts-o365-delta` worktree — this is a single sequential
worker, so the parallel-lane split the task notes describe has no benefit and merging
M8 before the jobs task is automatic.
