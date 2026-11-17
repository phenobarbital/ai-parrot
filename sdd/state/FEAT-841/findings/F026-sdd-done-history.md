---
id: F026
query_id: Q042
type: git_log
intent: "Recent history of /sdd-done — how often its gate changes and the FEAT-703 / FEAT-712 commits that added code-enforced blockers."
executed_at: 2026-11-07T01:19:11Z
duration_ms: 900
parent_id: null
depth: 0
merged_from: [FG-001]
---

# F026 — /sdd-done command: 20 commits in 120 days; gate is now code-enforced (FEAT-703 → closeout hooks)

## Summary

`.claude/commands/sdd-done.md` changed 20 times between 2026-10-18 and 2026-11-06 (one author, Jesus). Two commits define the current blocker model: `0af88638ed` (2026-10-19, TASK-4462) rewired both sdd-done twins so they branch **solely on the exit code** of `check_e2e_closeout.py` ("enforcement is an invariant, not an instruction"; −99 lines of prose), and `a6c7f56188` (2026-10-28, TASK-4870) wired the generic **closeout hooks** runner into both twins and removed `--resolve-jira`. Later commits are hardening (abort paths `639a0b56cd`, leftovers parking `6816d06fb0`, gh-only sandbox / host-side /sdd-done `e4fff64f38`, FEAT-633 CLI rename `3850087e56`). Precedent is clear: a new deterministic guard belongs in a script whose exit code the twins obey, with a contract test under `tests/sdd_scripts/`.

## Citations

- path: `.claude/commands/sdd-done.md`
  symbol: `0af88638ed`
  excerpt: |
    0af88638ed 2026-10-19 Jesus feat(sdd): TASK-4462 — rewire /sdd-done twins onto the code-enforced E2E gate
    Both closeout surfaces now invoke scripts/sdd/check_e2e_closeout.py and branch solely on its exit code,
    replacing ~80 lines of prose plus inline python -c / jq that an agent had to interpret.
    Closes FEAT-581 AC9's gap: enforcement is an invariant, not an instruction.  Discovered-from: issue:4b887b8e3ce0
    files: .agents/skills/sdd-done/SKILL.md (43), .claude/commands/sdd-done.md (104), tests/sdd_scripts/test_e2e_closeout_contract.py (20)
- path: `.claude/commands/sdd-done.md`
  symbol: `a6c7f56188`
  excerpt: |
    a6c7f56188 2026-10-28 Jesus feat(sdd-done-closeout-hooks): TASK-4870 — wire closeout hooks into both sdd-done twins; remove --resolve-jira
    files: .agents/skills/sdd-done/SKILL.md (46), .claude/commands/sdd-done.md (225), tests/sdd_scripts/test_sdd_done_hooks_contract.py (99, new)
- path: `.claude/commands/sdd-done.md`
  symbol: `639a0b56cd`
  excerpt: |
    639a0b56cd 2026-10-28 Jesus fix(sdd-done): move write_hook_context before first use, wire missing on_failure abort paths
- path: `.claude/commands/sdd-done.md`
  symbol: `6816d06fb0`
  excerpt: |
    6816d06fb0 2026-10-30 Jesus Lara fix(sdd-done): park untracked leftovers before removing the worktree
- path: `.claude/commands/sdd-done.md`
  symbol: `e4fff64f38`
  excerpt: |
    e4fff64f38 2026-11-03 Jesus Lara docs(sdd-worker-gh-only-sandbox): HOTFIX-sdd-worker-gh-only-sandbox-2 — gh-only access, host-side /sdd-done
- path: `.claude/commands/sdd-done.md`
  symbol: `3850087e56`
  excerpt: |
    3850087e56 2026-11-02 Juanfran feat(parrot-installer): FEAT-633 — parrot sdd installer + C30 noun-grouped CLI (TASK-5095..5099) (#1823)
- path: `.claude/commands/sdd-done.md`
  symbol: `b86f755172`
  excerpt: |
    b86f755172 2026-11-05 Jesus Lara feat(scripts-worktree-sync-tech-debt): TASK-5219 — host-provisioned sandbox push protection
    15dc5c9c77 2026-11-05 Jesus feat(github-wiki-technical-reference): TASK-5172 — read-only consumers + assets
    4dac210c02 2026-10-24 Jesus Lara fixes at sdd-done command
    094db7d115 2026-10-20 Jesus feat(language-agnostic-validation-runners): TASK-4536 — engine-committed coder deliverable
    f4a6f5a121 2026-10-18 Jesus feat(tests-optimization-sdd-flow): TASK-4452 — command and agent docs for contract-driven validation

## Notes

- No commit in this window references FEAT-712 by name on this file; the ledger snapshot guard may live in a script (not the command twin). [cross-lane: type=grep, intent=locate the FEAT-712 ledger snapshot guard script that /sdd-done invokes and its exit-code contract]
- Every gate change touches both twins (`.claude/commands/sdd-done.md` + `.agents/skills/sdd-done/SKILL.md`) plus a `tests/sdd_scripts/test_*_contract.py` doc-surface test — an escrow guard must follow the same three-file pattern.
