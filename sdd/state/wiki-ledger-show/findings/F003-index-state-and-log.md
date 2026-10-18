# F003 — Issue state shape + event log (type: read)
Citations: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:159-190; ledger/log.py:83; .parrot/ledger/events.jsonl
- `_apply_issue_opened` state keys: title, body, kind, severity, status, acknowledged, discovered_from, about,
  claimed_by, closed_by, closed_reason, resolved_by. No timestamps in state (passed to _write_issue separately).
- Event lines: {event_id, kind, subject:"issue:<hex>", actor, ts, payload}. `LedgerLog.iter_events(from_offset)` (log.py:83)
  yields (event, offset) — usable for per-issue history by filtering `subject`.
- Live ledger: events.jsonl ~458K, 41 ready issues at research time.
