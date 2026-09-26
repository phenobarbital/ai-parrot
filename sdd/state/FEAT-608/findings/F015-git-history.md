---
id: F015
query_id: Q020
type: git_log
intent: Recent activity on Google interface/tools and whether FEAT-603 is merged into dev (Q020 + Q021)
executed_at: 2026-09-25T22:54:40Z
duration_ms: 800
parent_id: null
depth: 0
---

# F015 — FEAT-603 is NOT on `dev` yet (worktree ahead of `origin/dev`, dirty); Google interface last touched by FEAT-534 / TASK-2393

## Summary

`git log --since="60 days" -- packages/ai-parrot/src/parrot/interfaces/file/`
on `dev` returns **no commits**: `graph.py`, `batch.py`, `sharepoint.py`,
`onedrive.py` exist only in the FEAT-603 worktree (branch
`feat-FEAT-603-sharepoint-filemanager`, HEAD `e11822c64`, merge-base
`8b5c42b3a` vs `origin/dev` `bdaf25b78`), whose per-spec index on `dev` still
shows all 21 tasks `pending` and whose tree has 4 uncommitted files (review
fixes in progress). Google side on `dev`: 10 commits in 90 days, all
Lyria (FEAT-534) or Calendar (TASK-2393) — nothing touched `GoogleClient`
auth or Drive.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/file/`
  symbol: dev history (60 days)
  excerpt: |
    (empty) — no commits on dev

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager`
  symbol: branch state
  excerpt: |
    e11822c64 fix(sharepoint-filemanager): FEAT-603 — narrow size-guard exception handling in graph.py
    8511be814 sdd: complete TASK-3768 for sharepoint-filemanager
    status: M packages/ai-parrot/src/parrot/interfaces/file/graph.py, sharepoint.py, tools/filemanager.py, parrot_tools/o365/onedrive.py

- path: `sdd/tasks/index/sharepoint-filemanager.json`
  symbol: per-spec index (dev)
  excerpt: |
    TASK-3748..TASK-3768 all "pending" on dev (statuses live on the feature branch)

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  symbol: dev history (90 days)
  excerpt: |
    e74891c78 style: apply black formatting (post sdd-worker)
    a6aa9e4fd fix(lyria-toolkit): address code-review findings (FEAT-534)
    0cd06246a feat(web-automation-infra): TASK-2393 — Google Calendar event tools + live calendar client
