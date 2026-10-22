# TASK-4403: Clock-safe, origin-checked wiki sync LWW and a cheap pull page

**Feature**: FEAT-692 — fixgroup-d717e8a67520
**Spec**: `sdd/specs/fixgroup-d717e8a67520.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

Resolves ledger issue:5e85c06ed736.

---

## Context
Spec §1: sync LWW compares raw `updated_at` strings (format- and clock-unsafe), overwrites
non-memory destination pages, and `op_sync_pull` does one `get_page` per memory page on
every cursor page.

---

## Scope
- `sync.py`: `SYNC_CLOCK_SKEW`, `parse_sync_stamp`, `normalize_sync_stamp`, `_lww_outcome`,
  `_memory_page_window`; `SyncReport.skipped_foreign`; `_sync_records` and `_record_from`
  use the helpers.
- `operations.py`: `_apply_sync_push` uses `_lww_outcome` + origin check and an optional
  `caller_identity`; `op_sync_push` passes `caller_identity` from context; `op_sync_pull`
  uses `_memory_page_window`.
- New test module covering spec §4.

**NOT in scope**: transport authentication; backend SQL/AQL overrides; delete propagation.

---

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` | MODIFY | stamp helpers, origin check, pull window |
| `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` | MODIFY | push/pull ops use the helpers |
| `packages/ai-parrot/tests/knowledge/wiki/test_sync_lww_hardening.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord  # sync.py:33
```

### Existing Signatures to Use
```python
# sync.py
async def _sync_records(*, source, destination, direction, env, dry_run, skip_asserted_by): ...  # :221
def _record_from(page: dict[str, Any], body: str) -> WikiPageRecord: ...                       # :272
# operations.py
async def _apply_sync_push(store, params: SyncPagesInput, wiki_name: str) -> dict[str, Any]: ...  # :755
async def op_sync_push(store, params, **context) -> OperationResult: ...                         # :796
async def op_sync_pull(store, params, **context) -> OperationResult: ...                         # :836
# store.py
async def list_pages(self, category=None, limit=100, origin=None) -> list[dict]: ...             # :768
```

### Does NOT Exist
- ~~`parse_sync_stamp`~~ / ~~`normalize_sync_stamp`~~ / ~~`_memory_page_window`~~ / ~~`SyncReport.skipped_foreign`~~ before this task.
- ~~caller identity on `WikiOperationContext`~~.

---

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/sync.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/operations.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_sync_lww_hardening.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sync.py#_sync_records",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/operations.py#op_sync_pull"
  ]
}
```

---

## Acceptance Criteria
- [ ] Stamps parsed/normalised; far-future clamped to now+5min; unparseable never wins.
- [ ] Non-memory destination pages are never overwritten (`skipped_foreign`).
- [ ] `op_sync_pull` issues ≤ `limit` `get_page` calls per call; results and cursor paging unchanged.
- [ ] `caller_identity` overrides client `asserted_by` on push.
- [ ] Existing wiki sync tests green; `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_lww_hardening.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py packages/ai-parrot/tests/knowledge/wiki/test_bulk_tools.py packages/ai-parrot/tests/knowledge/wiki/test_sync_push_chunking.py packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py packages/ai-parrot/tests/knowledge/wiki/test_ledger_bulk_operations.py -q`

## Completion Note
Completed 2026-10-16 (sdd-fix lane, ledger issue:5e85c06ed736). Implementing commit b2a2d030c.

- `sync.py`: `SYNC_CLOCK_SKEW` (5 min), `parse_sync_stamp`, `normalize_sync_stamp`,
  `_lww_outcome`, `_memory_page_window`, `SyncReport.skipped_foreign`. `_sync_records`
  (local engine, also used by `remote_cli.sync_pull_remote`) and `_record_from` use them.
- `operations.py`: `_apply_sync_push` uses `_lww_outcome` (parsed UTC compare, clamp,
  origin check) and an optional `caller_identity`; `op_sync_push` reads it from context;
  `op_sync_pull` selects on stubs and fetches ≤ `limit` bodies per call. Cursor format unchanged.
- Tests: 20 new in `test_sync_lww_hardening.py`; 130 passed across all wiki sync-related
  modules. `test_tool_surface_golden.py::test_local_stdio_surface` fails identically on
  unmodified `dev` (ledger tools in the local surface) — pre-existing, unrelated.
- Limitations: no transport caller identity exists yet, so `asserted_by` stays
  client-asserted unless a host passes `caller_identity`. Records already stored with a
  far-future stamp before this change still win until repaired (the clamp applies on write).
  A *new* record with an unparseable stamp is created with the store's write time.
