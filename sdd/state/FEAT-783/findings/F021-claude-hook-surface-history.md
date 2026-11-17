---
id: F021
query_id: Q038
type: git_log
intent: "Recent history of .claude/hooks and settings - the hook surface's stability."
executed_at: 2026-10-30T22:41:00Z
duration_ms: 700
parent_id: null
depth: 0
lane: git
merged_from: ['FG-004']
---

# F021 — The Claude Code hook surface is stable and additive: settings.json untouched since 2026-09-10

## Summary

`.claude/` as a whole is busy (25 commits/60d) but almost all of that is
commands, agents and rules, not hooks. The **hook surface itself is stable**:
`.claude/settings.json` has not been modified since **2026-09-10**
(a6c1880606), and only three hook scripts have ever been added, each in its own
commit — `dangerous-actions-blocker.sh` and `sdd-worker-format.sh` (df49b30733,
2026-08-22), `e2e-teardown.sh` (edbe7e746d, 2026-09-24, TASK-3544), and
`e2e-exploration-write-guard.sh` (af6d21c23c, 2026-10-30, a HOTFIX brief).
Adding a `SessionStart` / `SubagentStop` hook is therefore a low-collision,
well-precedented change — and the e2e write guard shows the house pattern for a
new `PreToolUse` hook shipped through a brief. The one live hazard is sandbox
interaction: three commits in the last four days changed how hooks behave under
Bubblewrap (RTK rewrite inside the sandbox, RTK data dir read-only, and
HOTFIX-6756c929a450-2 "sandboxed sessions never load the user setting source").

## Citations

- path: `.claude/settings.json`
  symbol: `hook registration`
  excerpt: |
    a6c1880606|2026-09-10|chore: ignore local Claude Code settings and bookstore skill  (last touch)
    09edddb316|2026-09-01|feat(portable-wikitoolkit-config-paths): TASK-2720 — remove duplicate hardcoded wiki hook
    df49b30733|2026-08-22|chore(claude): add release, worktree-cleanup, security commands and safety hooks
                           -> .claude/hooks/dangerous-actions-blocker.sh, .claude/hooks/sdd-worker-format.sh,
                              .claude/settings.json

- path: `.claude/hooks/e2e-exploration-write-guard.sh`
  symbol: `PreToolUse guard added via a brief`
  excerpt: |
    af6d21c23c|2026-10-30|feat(e2e-explorer-write-scope): HOTFIX-e009ded74983-1 — PreToolUse write
                           guard for E2E exploration agents

- path: `.claude/hooks/e2e-teardown.sh`
  symbol: `owner-scoped teardown hook`
  excerpt: |
    edbe7e746d|2026-09-24|feat(agentic-e2e-testing): TASK-3544 — Add optional API/UI exploration and
                           owner-scoped teardown hooks

- path: `.claude/`
  symbol: `sandbox/hook interaction, last 4 days`
  excerpt: |
    c55972f0c4|2026-10-29|docs(sdd): HOTFIX-6756c929a450-2 — sandboxed sessions never load the user setting source
    a75e251f3a|2026-10-29|fix(sdd): HOTFIX-6756c929a450-2 — launch sdd-worker without the user setting source
    1ed09cef77|2026-10-28|fix(dev-loop): keep RTK's data dir read-only in the SDD sandbox
    2c2d5faea2|2026-10-27|fix(dev-loop): apply the RTK rewrite inside the SDD sandbox hook

## Notes

HOTFIX-6756c929a450 is directly load-bearing for the brainstorm's §"Correlation
protocol per seat": a hook that only exists in the *user* setting source will
not fire for a sandboxed `sdd-worker`, which is precisely the seat whose usage
the feature wants to bind. Any `usage.session.bound` hook must live in the
*project* setting source.

[cross-lane: type=read, intent=read .claude/settings.json to see which hook events are registered today and in which setting source]
