---
type: feature
base_branch: dev
feature_id: FEAT-692
projects: [ai-parrot]
tags: [wiki, sync, lww, remote]
---

# Feature Specification: Clock-safe, origin-checked wiki sync LWW and a cheap pull page

**Feature ID**: FEAT-692
**Date**: 2026-10-16
**Author**: Jesus Lara (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:5e85c06ed736 (discovered from spec:FEAT-569).

---

## 1. Motivation & Business Requirements

### Problem Statement
The wiki sync last-writer-wins (LWW) rule — server side in
`operations._apply_sync_push` / `op_sync_pull` (exposed as `WikiSyncPushTool` /
`WikiSyncPullTool`, re-exported by `parrot/knowledge/wiki/tools.py`) and the
local engine `sync._sync_records` — has three defects:

1. **Timestamps compared as raw strings.** `updated_at` values are compared
   lexicographically. `2026-10-05T10:00:00Z` vs `2026-10-05T10:00:00+00:00`, a
   fractional-seconds stamp, or a non-UTC offset compare wrongly, and a
   far-future client clock (`9999-…`) wins every later merge permanently.
2. **Origin not checked on the destination.** A pushed/pulled `memory` record
   overwrites an existing page with the same `concept_id` even when that page is
   a repo-scan / authored (non-`memory`) page.
3. **Pull is O(N) per page.** `op_sync_pull` calls `_synced_memory_pages`
   (one `get_page` per memory page, with body) on every cursor page, then filters
   and slices in Python.

### Goals
- Parse and normalise every sync stamp to UTC; compare parsed datetimes, never
  strings. Accept `Z`, offsets, fractional seconds; treat a naive stamp as UTC.
- Clamp a stamp written at the destination to `now + 5 min` (server/destination
  clock), so a future clock cannot win permanently. An unparseable or missing
  source stamp never beats an existing record.
- Refuse to overwrite a non-`memory` destination page (push and pull/local
  engine); count it in a new `SyncReport.skipped_foreign`.
- `op_sync_pull` filters (`since`, `skip_asserted_by`, cursor) and sorts on
  body-less `list_pages` stubs and fetches bodies only for the returned page
  (≤ `limit` `get_page` calls instead of N).
- `op_sync_push` accepts an optional server-side `caller_identity` context value;
  when present it overrides the client-supplied `asserted_by`.

### Non-Goals
- Authenticating the remote transport caller (no identity is plumbed through
  `transport.WikiOperationContext` today). `asserted_by` stays client-asserted
  when no `caller_identity` is supplied — documented limitation.
- Backend-specific SQL/AQL push-down of the window query (the stub-based window
  needs no store API change; a backend override is a later optimisation).
- Propagating deletes (FEAT-461 v1 limitation, unchanged).

---

## 2. Architectural Design

New helpers in `sync.py` (shared by the server ops and the local engine):

- `parse_sync_stamp(value) -> datetime | None` — `str`/`datetime` → aware UTC
  datetime; `None` for missing/unparseable.
- `normalize_sync_stamp(value, *, now=None) -> str | None` — parse, clamp to
  `now + SYNC_CLOCK_SKEW` (5 min), render `YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00`.
- `_lww_outcome(source_stamp, existing) -> "create"|"update"|"older"|"foreign"`.
- `_memory_page_window(store, *, since, cursor, skip_asserted_by, limit)
  -> (pages_with_body, has_more)` — stub-based selection for `op_sync_pull`.
- `_record_from` writes the normalised stamp (still the SOURCE's time, clamped).

Cursor format `"<stamp>|<concept_id>"` is unchanged; the stamp part is parsed,
so old cursors keep working.

---

## 3. Module Breakdown

### Module 1: Clock-safe LWW + origin check + cheap pull
- `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` — helpers, `SyncReport.skipped_foreign`,
  `_sync_records` uses them.
- `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` — `_apply_sync_push`,
  `op_sync_push` (`caller_identity`), `op_sync_pull`.
- Tests: `packages/ai-parrot/tests/knowledge/wiki/test_sync_lww_hardening.py` (new).

---

## 4. Test Specification
- `parse_sync_stamp`: `Z` == `+00:00`; `+02:00` converted; fractional seconds;
  naive → UTC; garbage/None → None.
- Push: `Z`-format newer stamp updates a `+00:00` record; a far-future stamp is
  clamped on write so a later real-time push still wins; an unparseable stamp is
  `skipped_older`; an existing non-memory page is `skipped_foreign` and unchanged;
  `caller_identity` overrides `asserted_by`.
- Local engine (`_sync_records`): non-memory destination → `skipped_foreign`.
- Pull: same results/cursor paging as before, `get_page` called ≤ `limit` times
  per call; `since` with a `Z` stamp filters correctly.
- Existing `test_sync_tools.py`, `test_bulk_tools.py`, `test_sync_push_chunking.py`,
  `test_cli_remote_push.py`, `test_ledger_bulk_operations.py` stay green.

---

## 5. Acceptance Criteria
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_lww_hardening.py` passes.
- [ ] Existing wiki sync test modules (§4) pass unchanged.
- [ ] `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
- `from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord` (sync.py:33)
- `from parrot.knowledge.wiki.sync import SyncReport, _merge_body, _record_from` (lazy, operations.py `_apply_sync_push`)
- `from parrot.knowledge.wiki.sync import _synced_memory_pages` (lazy, operations.py `op_sync_pull`)

### Existing Signatures
- `async def _sync_records(*, source, destination, direction, env, dry_run, skip_asserted_by) -> tuple[SyncReport, set[str]]` — sync.py:221
- `def _record_from(page: dict[str, Any], body: str) -> WikiPageRecord` — sync.py:272
- `async def _apply_sync_push(store, params: SyncPagesInput, wiki_name: str) -> dict[str, Any]` — operations.py:755
- `async def op_sync_push(store, params, **context) -> OperationResult` — operations.py:796
- `async def op_sync_pull(store, params, **context) -> OperationResult` — operations.py:836
- `BaseWikiStore.list_pages(category=None, limit=100, origin=None)` — store.py:768; stubs carry `updated_at`, `asserted_by`, `origin` on sqlite/postgres/arango/memory.
- `store._now_iso()` format `"%Y-%m-%dT%H:%M:%S+00:00"` — store.py:312

### Does NOT Exist
- No `parse_sync_stamp` / `normalize_sync_stamp` / `_memory_page_window` / `SyncReport.skipped_foreign` before this feature.
- No caller identity in `transport.WikiOperationContext`.

---

## 7. Implementation Notes & Constraints
- `remote_cli.sync_pull_remote` stages pulled pages in `_PullStaging` and calls
  `_sync_records` — it must keep working (it only needs `list_pages`/`get_page`).
- Keep the lazy `sync` import inside `operations.py` (module must not import the tool framework).

## 8. Open Questions
None.

## Revision History
- 2026-10-16: initial (sdd-fix lane for issue:5e85c06ed736).
