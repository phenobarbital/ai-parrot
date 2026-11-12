---
id: FG-004
query_id: Q019
type: git_log
intent: "Recent activity on the parrot self_ CLI package."
executed_at: 2026-11-12T20:39:39Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-004 — parrot self_ is a hot, installer-focused package (20+ commits in 10 days); it manages ~/.parrot, not databases

## Summary

`packages/ai-parrot/src/parrot/self_` shipped with FEAT-633 (`parrot sdd installer + C30 noun-grouped CLI`, PR #1823, 2026-11-02) and has had ~22 commits since: doctor checks (bwrap probes, missing SDD files), self update lockstep, worktree-root move (FEAT-802), installer portability, uv shadowing / legacy uv migration (FEAT-872, 2026-11-10). Every commit concerns the parrot-managed runtime/installer; none touch databases. Note the word "migration" is already used inside self_ for `migrate_legacy_uv` (legacy uv binary migration) — a `parrot self migration` subcommand name risks confusion with that.

## Citations

- path: `packages/ai-parrot/src/parrot/self_`
  lines: n/a (git)
  symbol: `migrate_legacy_uv`
  excerpt: |
    58afb57543 2026-11-10 fix: preserve external uv symlink during migration
    455f81a09a 2026-11-10 feat(self--uv-fixes): TASK-5465 - Guard migrate_legacy_uv against symlinked legacy bin/uv

- path: `packages/ai-parrot/src/parrot/self_`
  lines: n/a (git)
  symbol: null
  excerpt: |
    3850087e56 2026-11-02 feat(parrot-installer): FEAT-633 — parrot sdd installer + C30 noun-grouped CLI (#1823)
    be24d3f469 2026-11-03 TASK-5117 — self update keeps ai-parrot / ai-parrot-tools in lockstep
    179b5bd36b 2026-11-04 feat(doctor): detect bwrap nested userns support in parrot self doctor
    6b8bead2ef 2026-11-05 TASK-5179 — installer and doctor hard cut, resolved-root ignore rule
    4405636a5f 2026-11-06 fix(self doctor): give each bwrap probe level a writable /proc

## Notes

- Fit question for synthesis: `parrot self` = "manage the parrot-managed runtime (~/.parrot)" (wiki page summary). DB schema migration of a deployment's Postgres is a different scope; navauth also chose `self upgrade`, so the user's naming is deliberate, but the noun-grouped CLI convention (memory: FEAT-633 C26 `parrot <noun> <verb>`) and the existing `migrate_legacy_uv` vocabulary should be weighed.
- High churn → coordinate with any in-flight self_ work.
