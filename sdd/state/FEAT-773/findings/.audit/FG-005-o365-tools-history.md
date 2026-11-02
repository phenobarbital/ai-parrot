---
id: FG-005
query_id: Q064
type: git_log
intent: "History: O365 tools (delegated mode) — recent auth homologation work."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 600
parent_id: null
depth: 0
---

# FG-005 — parrot_tools/o365: 21 commits in 120 days, all SharePoint/contracts delta work; delegated-auth surface last touched 2026-07-03

## Summary

21 commits (2026-07-03 → 2026-09-26) on `packages/ai-parrot-tools/src/parrot_tools/o365/`, all Jesus / Jesus Lara. Dominant theme: **contracts-card-ontology** (2026-09-09, TASK-3041/3042 — O365 drive/SharePoint delta feeds) and **sharepoint-filemanager** (FEAT-603, 2026-09-25/26, TASK-3761–3764). None of these touch authentication. The only auth-adjacent commit is `5a5d81c21` 2026-07-03 "changes on o365 integration" — +11 lines in `o365/oauth_toolkit.py` (the per-user delegated OAuth toolkit). No "o365-auth-homologation" or "devicecode" commits appear under this path in the window, so whatever those specs changed landed elsewhere (likely `parrot/auth/oauth2/o365_provider.py`, `parrot/interfaces/o365.py`) or before July 2026.

## Citations

- sha: `5a5d81c21` · 2026-07-03 · Jesus Lara · changes on o365 integration
  files: `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py` (+11).
- sha: `850d51847` · 2026-09-09 · Jesus · fix(contracts): resolve the three P1s from the O365 delta pre-merge review
  files: `parrot_tools/o365/delta.py` (+31/-2) — Graph delta root handling; unrelated to auth.
- sha: `13f67881a` / `668ccbf9a` · 2026-09-09 · Jesus · TASK-3041 — O365 drive delta (contracts-card-ontology).
- sha: `c4bce1160` / `df1dba311` · 2026-09-09 · Jesus · TASK-3042 — SharePoint delta.
- sha: `b7306d448` `124d6896d` `68244a113` `1f93ef9df` · 2026-09-25 · Jesus · FEAT-603 sharepoint-filemanager TASK-3761–3764.

## Notes

- The O365 *tool* side is quiet on auth; the delegated-token source question (brainstorm S-3a "token source = vault resolver") must be answered from `parrot/auth/oauth2/o365_provider.py` and the O365 interface, not from this package's history.
- [cross-lane: type=read, intent=read `parrot_tools/o365/oauth_toolkit.py` and `parrot_tools/o365/base.py` (`O365AuthMode`) to see where DELEGATED tokens are read from today (permission-context bridge per wiki test name `test_o365_permission_context_bridge.py`)]
