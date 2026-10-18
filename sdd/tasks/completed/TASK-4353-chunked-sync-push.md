# TASK-4353: Chunk the remote `wiki_sync_push` and cap/lock the server tool

**Feature**: FEAT-678 — fixgroup-fa16a91bd3ea
**Spec**: `sdd/specs/fixgroup-fa16a91bd3ea.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

Resolves ledger issue:086be5c7371d.

---

## Context
Spec §1: `sync_push_remote` sends every memory page + edge in one call (HTTP 413
past 4 MiB, surfaced as an opaque protocol error); `WikiSyncPushTool` has no cap
and writes without the wiki writer lock.

---

## Scope
- `tools.py`: add `SYNC_PUSH_MAX_PAGES = 200`, `SYNC_PUSH_MAX_BYTES = 1_048_576`;
  `WikiSyncPushTool.__init__(store, wiki_name, root=None, config=None)`; `_execute`
  validates count/bytes before writing and applies under `_INGEST_LOCK` +
  `wiki_write_lock` (when root/config are set), mapping a held lock / `WikiStoreBusy`
  to a `busy:` error; `create_bulk_tools` passes root/config.
- `remote_cli.py`: `sync_push_remote` chunks pages (≤200, ≤ byte budget incl. edges),
  attaches each edge to the first chunk holding one endpoint, reports oversized
  pages in `rejected`, aggregates `created/updated/skipped_older/rejected`.
- `cli.py`: remote `sync push` echoes `rejected=<n>` when non-zero.
- Tests for the server caps/lock and the client chunking.

**NOT in scope**: LWW clock trust / pull O(N) (issue:5e85c06ed736); `wiki_sync_pull`.

---

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | caps + writer lock in `WikiSyncPushTool` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py` | MODIFY | chunked `sync_push_remote` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | echo rejected count |
| `packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py` | MODIFY | server cap/lock tests |
| `packages/ai-parrot/tests/knowledge/wiki/test_sync_push_chunking.py` | CREATE | client chunking tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock  # tools.py:26
from parrot.knowledge.wiki.sync import SyncReport, _merge_body, _record_from, _synced_memory_pages
from parrot.knowledge.wiki.store import WikiPageRecord
```

### Existing Signatures to Use
```python
# tools.py:1098
class WikiSyncPushTool(AbstractTool):
    def __init__(self, store: BaseWikiStore, wiki_name: str): ...
# tools.py:1041 — lock pattern to mirror (WikiIngestBatchTool._execute)
# remote_cli.py:358
async def sync_push_remote(client: RemoteWikiClient, local: BaseWikiStore) -> dict[str, Any]: ...
# tools.py:1211
def create_bulk_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]: ...
```

### Does NOT Exist
- ~~`SYNC_PUSH_MAX_PAGES` / `SYNC_PUSH_MAX_BYTES`~~ before this task.
- ~~`SyncReport.rejected`~~ — `rejected` lives only in the client's aggregated dict.

---

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_sync_push_chunking.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiSyncPushTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py#sync_push_remote"
  ]
}
```

---

## Acceptance Criteria
- [ ] No single `wiki_sync_push` call from `sync_push_remote` exceeds 200 pages or the byte budget.
- [ ] `WikiSyncPushTool` returns an error and writes nothing for >200 pages or >1 MiB.
- [ ] `WikiSyncPushTool` from `create_bulk_tools` writes under `wiki_write_lock`; a held lock → `busy:` error.
- [ ] Aggregated counts equal the sum over chunks; tests pass; `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py packages/ai-parrot/tests/knowledge/wiki/test_sync_push_chunking.py packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py -q`

## Completion Note
Completed 2026-10-15 (sdd-fix lane, ledger issue:086be5c7371d). Implementing commit b61cbee2c.

- Server: `WikiSyncPushTool` validates `SYNC_PUSH_MAX_PAGES` (200) and
  `SYNC_PUSH_MAX_BYTES` (1 MiB) before any write and returns a clear
  "chunk the push" error; when built by `create_bulk_tools` (root/config set)
  it applies under `_INGEST_LOCK` + `wiki_write_lock`, held lock → `busy:` error.
  Direct construction `WikiSyncPushTool(store, name)` keeps working, unlocked.
- Client: `sync_push_remote` chunks by count and byte budget (1 MiB − 8 KiB
  headroom); each edge rides with the chunk of its first memory endpoint;
  a page that alone exceeds the budget is reported in `rejected` (CLI prints
  `rejected=<n>`); created/updated/skipped_older are summed over chunks.
- Known limit: an edge owned by a rejected page is dropped with it.
- Tests: 3 new server tests (count cap, size cap, writer lock) + 3 client
  chunking tests; wiki remote/bulk/surface suites 28 passed, 1 skipped; ruff clean.
- Worktree note: tests needed the main checkout's Cython `.so` files symlinked
  (untracked, git-ignored) into the worktree.
