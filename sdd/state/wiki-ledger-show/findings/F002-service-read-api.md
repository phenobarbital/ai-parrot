# F002 — LedgerService read API (type: read)
Citations: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:109-125,205-219,254-308,336-341
- `_issue_dict()` (109-125) projects state to the public shape — it OMITS `body` (state does carry it, see F003).
- `list_issues(statuses=("open","claimed"), *, kind, about_prefix)` (278-308) already exists, severity-sorted;
  only caller is standup collector (standup/collectors/ledger.py:44). No CLI/MCP surface uses it.
- `_issue_state(issue_id)` (336-341) private single-issue reader; returns decoded state incl. body, or None.
- `_sync_best_effort()` (198-203) — reads tolerate busy writer lock.
