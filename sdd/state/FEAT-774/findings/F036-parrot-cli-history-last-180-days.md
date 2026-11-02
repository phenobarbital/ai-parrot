---
id: F036
query_id: Q048
type: git_log
intent: "Recent history of the CLI package (who touched identity / REPL and why)."
executed_at: 2026-10-30T15:19:33Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FG-001]
---

# F036 — parrot/cli history, last 180 days

## Summary

12 commits (2026-09-18 → 2026-10-26), all by Jesus / Jesus Lara. Dominant theme: FEAT-573
`new-ui-cli-agents` (2026-09-18 burst: REPL, session, events, devloop console/renderer) followed by
sub-command registrations in `cli/__init__.py` (jira CLI TASK-4422, training-agent TASK-3728, e2e
TASK-3534, formbuilder TASK-4204). The most recent change is `4a79623d6` "cli session" (2026-10-26),
which touched `session.py` (+15/−4), one line of `agent_repl.py` and added
`packages/ai-parrot/tests/cli/test_session.py` (+42). **`cli/identity.py` has NOT been touched in
180 days** — the O365 device-code bootstrap (FEAT-266) predates this window and is static.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/session.py`
  lines: 1-1
  symbol: `(commit 4a79623d6)`
  excerpt: |
    4a79623d6 2026-10-26 Jesus Lara "cli session"
    files: cli/agent_repl.py (2 lines), cli/session.py (+15/-4),
           tests/cli/test_session.py (+42, new), sdd/ledger/events.jsonl
- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 1-1
  symbol: `(sub-command registrations)`
  excerpt: |
    e3924f44d 2026-10-24 TASK-4204 (a2ui-dialect-formbuilder) — cli/__init__.py
    094ec8616 2026-10-16 TASK-4422 (jiratoolkit-upgrades) — Jira CLI — cli/__init__.py
    6ccb486ab 2026-09-25 TASK-3728 (training-agent) — cli/__init__.py
    3f09eb219 2026-09-24 TASK-3534 (agentic-e2e-testing) — cli/__init__.py
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 1-1
  symbol: `(FEAT-573 burst)`
  excerpt: |
    8fa34ba3a 2026-09-18 fix(new-ui-cli-agents): resolve remaining FEAT-573 review items
      — agent_repl.py, commands.py, devloop/bootstrap.py, events.py, repl.py, session.py
    06556eb3e 2026-09-18 fix(new-ui-cli-agents): code review fixes
      — agent_repl.py, commands.py, devloop/console.py, devloop/renderer.py, session.py
    52dd9286c / acbf8b003 / 8b088bde2 / 85263443c 2026-09-18 — devloop console/renderer, TASK-3414/3416
- path: `packages/ai-parrot/src/parrot/cli/loaders.py`
  lines: 1-1
  symbol: `(commit f39b69c02)`
  excerpt: |
    f39b69c02 2026-09-18 Jesus Lara "changes on planogram check" — cli/loaders.py, cli/toolkits.py

## Notes

- Absence evidence: no commit in the window touches `cli/identity.py`; the CLI identity story is frozen at FEAT-266.
- [cross-lane: type=read, intent=Read packages/ai-parrot/tests/cli/test_session.py to see what the CLI session now persists (4a79623d6 added it) — candidate home for a login token.]
- [cross-lane: type=grep, intent=Check whether cli/__init__.py registers any auth/login/connect sub-command among the TASK-4422/3728/3534/4204 additions.]
