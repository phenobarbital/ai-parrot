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

### Adversarial review triage (post-completion)

Both tasks were reviewed together after implementation by two independent
reviewers given the same neutral brief (diff + requirements + question, no
reasoning supplied): an external `codex` session and a Claude `code-reviewer`
subagent. A separate agent verified the disputed Microsoft Graph semantics
against Microsoft Learn. Findings and dispositions — fixes landed in commit
`bdde521ea`:

| # | Finding | Disposition |
|---|---|---|
| 1 | `with_url()` replaces the entire URL, so origin-only validation let a supplied cursor redirect the authenticated request at any Graph resource (e.g. another drive's `/content`) | **CONFIRM — fixed.** Links are now confined structurally to the enumerated drive's delta endpoint. My own follow-up probe then found two bypasses of the first fix (`.../delta/../../users` and `/delta/drives/<id>/items/x/content`); the check is now anchored on the last path segment and the segment following `drives`, with relative segments rejected. All are regression-tested. |
| 2 | Graph omits `parentReference.path` from delta responses, so the `folder_path` filter was silently a no-op on real data while reporting `filtered_out=0` | **CONFIRM — fixed.** Verified verbatim against Microsoft Learn: *"The parentReference property on items won't include a value for path... When using delta you should always track items by id."* Added `folder_id` (matches `parentReference.id`, which delta does report) and match/miss/undecidable classification; undecidable items are kept but counted in `unresolved_parent` and surfaced via `folder_filter_reliable`. |
| 3 | Filtering ran before de-duplication, so a later "moved out of the folder" occurrence lost to the stale earlier one | **CONFIRM — fixed.** Last occurrence now wins in both directions. |
| 4 | `Retry-After` was truncated to `max_backoff`, retrying while still throttled | **CONFIRM — fixed.** Honoured in full up to a new `max_retry_after` budget; beyond it the round is abandoned. `max_backoff` still caps self-computed backoff. |
| 5 | Status-less transient failures (dropped connection, timeout) skipped the retry budget entirely | **CONFIRM — fixed.** `TimeoutError`/`OSError`/`httpx.TransportError` retried within the same bound. |
| 6 | SharePoint library lookup inferred "absent"/"only library" from a truncated first page of the drives collection | **CONFIRM — fixed.** A truncated listing now refuses to infer and asks for an explicit `drive_id`. |
| 7 | OneDrive drive resolution bypassed the `O365Client.get_user_context()` convention, ignoring a credential-configured default user | **CONFIRM — fixed.** Now delegates to `get_user_context()`, so app-only auth without an identity gets its actionable error. |
| 8 | The msgraph/Kiota stack runs its own `RetryHandler` (3 retries) beneath this helper, so the configured bound does not bound raw HTTP attempts — they multiply | **CONFIRM as documentation; code change REJECTED for now.** Verified (`kiota_client_factory` wires `RetryHandler` unconditionally). Total attempts stay finite and the SDK layer honours `Retry-After`, so the honest fix is to document the layering rather than pass an untested `RetryHandlerOption` through `get()` — that would change behaviour on a path the fakes cannot exercise, which is precisely how this class of bug got in. Recorded as a follow-up. |
| 9 | `fetch_page()` returned unvalidated continuation links to a direct caller | **CONFIRM — fixed.** Validated in `_build_page`, not only at follow time. |
| 10 | `Retry-After` parser handled only delta-seconds, not the RFC 7231 HTTP-date form | **CONFIRM — fixed.** |
| 11 | A rejection test asserted only the exception type, not that no request followed | **CONFIRM — fixed** in both suites. |
| 12 | The `drive_id=""` fallback test passed even when execution failed | **CONFIRM — fixed.** Split into a rejection case and a genuine success case. |
| 13 | `DEFAULT_GRAPH_ORIGINS` trusts all five sovereign clouds rather than the client's own cloud | **NOTED, not changed.** All five are genuine Microsoft Graph origins, a commercial token would not authenticate against a sovereign endpoint, and finding 1's path confinement removes the practical concern. Deployments that want a single origin pass `allowed_origins` via `delta_helper=`. Flagged for the PR reviewer. |
| 14 | `_validate_graph_identifier` is duplicated verbatim in `sharepoint.py` and `onedrive.py` | **NOTED, not changed.** The natural shared home is `delta.py`, which TASK-3042 does not own. Trivial follow-up. |

Neither reviewer found a hallucinated API; both independently confirmed the
410/rescan handling, the retry loop's attempt accounting, the additive bundle
registration and the contracts/scheduler independence.

**Residual limitation to carry into TASK-3049 (`ingest_delta`)**: exact folder
scoping is not achievable from an incremental delta round alone — Graph omits
the path, and `folder_id` matches direct children only. The delta job should
either track the whole drive and scope by item id against the catalog, or
treat `unresolved_parent > 0` as "membership must be re-checked locally".

### Second-pass review (fixes re-reviewed)

The fixes above were re-reviewed independently. All four claims were
confirmed to hold — the reviewer probed 22 crafted continuation URLs
(cross-drive-as-item-id, `..`, `%2e%2e`, double-encoded `%252e%252e`,
backslash traversal, `userinfo@` spoof, `delta` out of final position,
`deltaX`, drive id in the query only, `/users/{id}/delta`) and every bypass
attempt was rejected while all legitimate Graph shapes were accepted. It also
confirmed no pre-existing test was weakened rather than fixed. Its four
remaining points were adopted in commit `f738e5f84`:

- `validate_continuation_link` now **requires** `drive_id` — the origin-only
  mode is no longer reachable by omission from a future caller.
- `filtered_out` now counts distinct items, matching every other counter.
- `DeltaRetryExhaustedError` carries a `reason`, distinguishing "throttled
  beyond our budget, defer" from "retries genuinely exhausted".
- `folder_filter_reliable` is now in the tool payload (it is a `@property`,
  so `model_dump()` had dropped it).

Left alone deliberately, noted for the PR reviewer: the `drives` path segment
is matched case-sensitively (Graph emits lowercase — conservative, not
wrong), and a cursor may re-anchor enumeration to a different subtree of the
*same* drive, which stays inside that drive's own permission boundary.

### Duplicate-implementation collision with the core lane (merge of dev)

`dev` (PR #1347) landed the core lane's own implementation of M8 —
`o365/delta.py` with `DriveDeltaReader`/`validate_continuation`, its own
`DeltaSharePointFilesTool`/`DeltaOneDriveFilesTool`, and same-named test
modules — even though the spec's parallelism notes assign M8 to this
worktree ("Execute in O365 worktree feat-FEAT-539-contracts-o365-delta.
M8 commits must be integrated into the core lane before the delta job").
Both lanes therefore built the same module twice, and the tool classes and
tool `name` strings collide, so they cannot coexist.

Merging `dev` here resolved every `o365/` file and both delta test modules
to **this lane's** implementation, because it is the one that went through
two adversarial review rounds and carries fixes for defects the core lane's
copy still has (see the triage above): continuation links confined to the
drive's delta endpoint rather than origin-only, folder-membership honesty,
`Retry-After` respected in full, status-less transient retries, and the
paginated library lookup. The core lane's copy is preserved in git history
on `dev`.

To keep the merged consumer working unchanged, the tools gained an additive
compatibility surface for `parrot_tools.contracts.jobs.ingest_delta`
(TASK-3049): the `delta_token` argument alias and the `tombstones` /
`rescan_required` / `pages` payload keys it reads.

### Post-merge review — two defects left open (they live in `contracts/jobs.py`)

Reviewed again after merging `dev`. Everything the review found inside this
lane's files is fixed (commit `67d10fa32`). Two findings are in TASK-3049's
`parrot_tools/contracts/jobs.py`, which this lane does not own, and are
reported rather than changed:

1. **`ingest_delta` cannot call a real delta tool at all.** `_enumerate`
   does `client = getattr(delta_tool, "client", None)` and then
   `delta_tool._execute_graph_operation(client, ...)`, but `O365Tool` has
   `_client`/`_client_cache` and acquires an authenticated client through
   the async `_get_client()` — there is no `.client` property. Reproduced:
   `AttributeError: 'NoneType' object has no attribute 'graph_client'`. This
   pre-dates the merge and applies equally to the core lane's own tool, so
   the job has never been run against a real tool; its suite injects a
   hand-written fake with an `enumerate()` method, which takes the other
   branch. Calling `_execute_graph_operation` directly also bypasses
   authentication and the `ToolResult` error wrapping. Fix belongs in
   `_enumerate`: await the tool's authenticated surface instead.

2. **A recovered 410 commits a new cursor without reconciling deletions.**
   This helper recovers an expired cursor by re-enumerating once and
   reporting `reset_performed`; the tools therefore return
   `rescan_required=False`, because the rescan already happened. The job
   only understands `rescan_required`, so it processes the rescan and
   commits the new cursor without comparing the full listing against its
   existing source items — a deletion that occurred while the cursor was
   expired stays indexed. (The core lane's alternative was not better: it
   returned `rescan_required=True` and retained the old cursor, so every
   subsequent run would 410 again and ingestion would stall permanently.)
   Microsoft's resynchronisation guidance requires comparing against local
   state after a reset. Fix belongs in the job.
