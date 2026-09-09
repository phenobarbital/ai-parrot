# TASK-3041: O365 drive delta pages, validation and retry helper

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: sdd-worker (O365 lane, worktree feat-FEAT-539-contracts-o365-delta)
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

- [x] Fake Graph pages cover multipage, empty intermediate page, final cursor, duplicate item and deleted marker.
- [x] 410 triggers safe rescan state; retry is bounded and respects throttling; malicious foreign continuation host is rejected before request.
- [x] Helper imports no contracts package and performs no cursor commit or document ingestion.
- [x] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

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

**Executor**: sdd-worker (Claude Opus 5) — worktree `feat-FEAT-539-contracts-o365-delta`
**Completed**: 2026-09-09

### Implementation summary

Created `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`, the
transport half of Microsoft Graph drive change tracking, owned entirely by
the O365 lane:

- **Typed models** (Pydantic v2, `extra="forbid"`): `DeltaItem`
  (stable `(drive_id, item_id)` identity, `deleted` tombstone flag,
  normalized drive-relative `parent_path`/`path`, size/eTag/cTag/webUrl/
  last-modified and Graph content hashes), `DeltaPage` (items plus the
  opaque `next_link`/`delta_link`, `is_final`) and `DeltaEnumeration`
  (aggregated items, final cursor, `pages_fetched`, `complete`,
  `reset_performed`, `full_enumeration`, folder-filter metadata).
- **`DriveDeltaHelper`** — drive-level enumeration anchored at
  `drives/{drive-id}/items/root/delta`, following `@odata.nextLink` until
  `@odata.deltaLink`. Repeated items across pages collapse by id with the
  latest occurrence winning; empty intermediate pages do not end the walk;
  a page bound prevents unbounded following and, when hit, deliberately
  returns no committable cursor.
- **410 Gone** raises `DeltaResetRequiredError` out of `fetch_page`;
  `enumerate` catches it, discards the cursor and re-enumerates once from
  scratch, flagging `reset_performed=True` so the consumer treats the
  listing as a full rescan and never as mass deletion. A 410 burns no
  retry budget.
- **Bounded retry** on 429/500/502/503/504 honouring `Retry-After`
  (capped by `max_backoff`), otherwise exponential from `initial_backoff`;
  exhaustion raises `DeltaRetryExhaustedError`. Non-retryable statuses
  propagate immediately. The sleep function is injectable for
  deterministic tests.
- **Continuation-host validation** — every `nextLink`/`deltaLink`
  (including a caller-supplied stored cursor and the final cursor handed
  back) is checked against `DEFAULT_GRAPH_ORIGINS` *before* the request is
  built, so a poisoned feed can never receive the access token. Rejects
  non-HTTPS, hostless, suffix-spoofed and non-443-port URLs.
- **Local folder filtering** because Graph delta is drive-level; prefix
  traps (`ContractsArchive` vs `Contracts`) do not match, and tombstones
  whose parent path Graph did not report are retained so a retraction is
  never silently lost.

The helper holds no state between rounds: it commits no cursor, downloads
no content and ingests no document.

### Validation evidence

- `pytest packages/ai-parrot-tools/tests/test_o365_delta_protocol.py -q`
  → **55 passed** (fake Graph surface only; no network, credentials or
  tenant involved).
- `ruff check` on both owned files → clean.
- Log: `artifacts/logs/task-3041.log`.
- Codebase Contract re-verified against the installed SDK before coding:
  `DeltaRequestBuilder.get()/.with_url()`, `DeltaGetResponse.value/
  odata_next_link/odata_delta_link`, `DriveItem` fields and
  `APIError.response_status_code/response_headers` all confirmed in
  `.venv` msgraph; no assumed API.

### Deviations / notes for downstream tasks

- The task named no classes, so the interface TASK-3042 and the contracts
  delta job must consume is: `DriveDeltaHelper.enumerate(client, drive_id,
  *, delta_link=None, folder_path=None, max_pages=None) -> DeltaEnumeration`
  and `DriveDeltaHelper.fetch_page(client, drive_id, *, link=None) ->
  DeltaPage`. `client` is duck-typed on `.graph_client`.
- `DeltaEnumeration.delta_link` is `None` whenever the walk was truncated
  (page bound, or a page carrying neither link). Consumers MUST retain the
  previous cursor in that case — this is the idempotent-replay contract
  spec §2 requires, enforced here by simply not producing a cursor.
- Sovereign-cloud Graph origins (US Gov, DoD, China, Germany) are allowed
  by default alongside the commercial origin; deployments that want a
  tighter set pass `allowed_origins`.
- No packaging change was needed: `msgraph-sdk` already ships with the
  existing `office365` extra.
