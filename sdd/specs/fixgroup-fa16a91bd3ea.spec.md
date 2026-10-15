---
type: feature
base_branch: dev
feature_id: FEAT-678
projects: [ai-parrot]
tags: [wiki, wikitoolkit, remote, sync]
---

# Feature Specification: Chunked, size-capped `wiki_sync_push`

**Feature ID**: FEAT-678
**Date**: 2026-10-15
**Author**: Jesus Lara (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:086be5c7371d (discovered from spec:FEAT-569).

---

## 1. Motivation & Business Requirements

### Problem Statement
`wikitoolkit sync push` in remote mode (`remote_cli.sync_push_remote`) sends
every local memory page and every asserted edge touching one in a **single**
`wiki_sync_push` tools/call. `WikiSyncPushTool` (`tools.py`) applies no count
or size cap. The server app's `client_max_size` is 4 MiB, so a large memory
plane gets HTTP 413, which the client surfaces as an opaque
`[remote:protocol] unparsable response`.

`WikiSyncPushTool` also writes to the plane **without** the wiki writer lock,
unlike `WikiIngestBatchTool` (`wiki_ingest_batch`), so a sync push can race a
concurrent build/ingest writer.

### Goals
- The client chunks the push: at most `SYNC_PUSH_MAX_PAGES` (200) pages and
  `SYNC_PUSH_MAX_BYTES` (1 MiB, minus envelope headroom) per call.
- Edges travel with a chunk that holds one of their endpoints, so the
  server's "edge must touch a pushed page" filter still accepts them.
- A single page larger than the byte budget is not sent; it is reported as
  rejected instead of failing the whole push.
- The server rejects an over-cap call with a clear error before writing.
- The server takes the wiki writer lock (asyncio lock + cross-process flock in
  a worker thread) exactly like `wiki_ingest_batch`, when it has the project
  root/config.
- Per-chunk results are aggregated into one report (`created`, `updated`,
  `skipped_older`, `rejected`); the CLI prints the rejected count when non-zero.

### Non-Goals
- LWW clock trust / pull O(N) (ledger issue:5e85c06ed736) — separate issue.
- Changing `wiki_sync_pull` or `wiki_ingest_batch`.

---

## 2. Architectural Design

### Overview
Mirror the `push_sources` / `WikiIngestBatchTool` pattern already used for the
build push: shared constants in `tools.py`, client-side chunking in
`remote_cli.py`, server-side validation then locked apply.

### Integration Points
- `tools.create_bulk_tools(store, root, config)` passes `root`/`config` to
  `WikiSyncPushTool` so it can lock; `root`/`config` stay optional for direct
  construction (tests construct `WikiSyncPushTool(store, "t")`).
- `cli.sync_push_cmd` remote branch prints `rejected=<n>` when non-zero.

---

## 3. Module Breakdown

### Module 1: chunked client push + capped, locked server tool
- `tools.py`: `SYNC_PUSH_MAX_PAGES = 200`, `SYNC_PUSH_MAX_BYTES = 1_048_576`;
  `WikiSyncPushTool.__init__(store, wiki_name, root=None, config=None)`;
  `_execute` validates count/bytes first, then applies under the lock.
- `remote_cli.py`: `sync_push_remote` builds chunks, sends one call per chunk,
  aggregates the reports.
- `cli.py`: echo rejected count.

---

## 4. Test Specification

- Server: >200 pages → error, nothing written; >1 MiB payload → error,
  nothing written; with root/config the tool acquires the writer lock and a
  held lock yields a `busy:` error.
- Client: N pages beyond the cap travel in multiple `wiki_sync_push` calls,
  every edge reaches a call that contains one of its endpoints, an oversized
  page is reported in `rejected`, and counts are aggregated.
- Existing `test_sync_tools.py` / `test_cli_remote_push.py` stay green.

---

## 5. Acceptance Criteria

- [ ] No single `wiki_sync_push` call from `sync_push_remote` exceeds 200 pages or the byte budget.
- [ ] `WikiSyncPushTool` returns an error (and writes nothing) for >200 pages or >1 MiB.
- [ ] `WikiSyncPushTool` built by `create_bulk_tools` writes under `wiki_write_lock`.
- [ ] Aggregated report printed by `wikitoolkit sync push` (remote) is the sum over chunks.
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py` passes.

---

## 6. Codebase Contract

### Verified Imports
- `from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock` (tools.py:26)
- `from parrot.knowledge.wiki.store import WikiPageRecord`
- `from parrot.knowledge.wiki.sync import SyncReport, _merge_body, _record_from, _synced_memory_pages`

### Existing Class Signatures
- `WikiSyncPushTool(store: BaseWikiStore, wiki_name: str)` — tools.py:1098
- `WikiIngestBatchTool._execute` lock pattern — tools.py:1041-1074 (`_INGEST_LOCK`, `wiki_write_lock(...).__enter__` via `asyncio.to_thread`, `WikiStoreBusy`)
- `sync_push_remote(client, local) -> dict[str, Any]` — remote_cli.py:358
- `push_sources` chunking loop — remote_cli.py:204
- `create_bulk_tools(store, root, config)` — tools.py:1211

### Does NOT Exist
- No `SYNC_PUSH_MAX_*` constants before this feature.
- `SyncReport` has no `rejected` field (the client adds `rejected` to the aggregated dict only).

---

## 7. Implementation Notes & Constraints
- Byte budget on the client: `SYNC_PUSH_MAX_BYTES - 8192` headroom, measured over
  the JSON of pages + edges, as `push_sources` does.
- Validate before locking; never take the lock for a rejected payload.

## 8. Open Questions
None.

## Revision History
- 2026-10-15: initial (sdd-fix lane for issue:086be5c7371d).
