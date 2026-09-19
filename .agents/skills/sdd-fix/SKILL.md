---
name: sdd-fix
description: Drain the SDD work ledger — plan-fix, claim, route to the Fast or SDD lane, close by evidence, release the rest.
---

# SDD Fix

Use this skill when the user asks to fix ledger issues, drain the ledger, or runs `$sdd-fix`.

## Procedure

1. **Plan** — Run `wikitoolkit ledger plan-fix --json` with any filters passed through. Parse the FixPlan JSON containing severity-ordered groups.

2. **Select** — Use interactive picker or resolve from arguments (specific issue-id or top N groups).

3. **Claim** — For each issue in selected groups, run `wikitoolkit ledger claim <issue-id> --actor agent:sdd-fix`. Drop issues that fail to claim.

4. **Prime** — Load context with `wikitoolkit ledger context <group.files…> --max-tokens 3000`.

5. **Route** by lane:
   - **Fast lane**: Create branch in main checkout, make changes, run tests, commit, `git push`, then `gh pr create --base dev`.
   - **SDD lane**: Reuse open parent spec or mint new feature with `reserve_ids`, create spec, run `/sdd-task`, then `ensure_worktree`.

6. **Close** — Two keys required: agent asserts resolution + file appears in diff. Close with `ledger close <id> --reason --actor --resolved-by commit:<sha>|task:TASK-<NNN>`.

7. **Release** — Unfinished claimed issues: `wikitoolkit ledger unclaim <issue-id> --reason --actor agent:sdd-fix`.

Shared ledger is read-only — exit without claiming if so. Never call `ledger acknowledge`. Both lanes documented. Parents/reserve_ids/ensure_worktree for SDD. Fast lane always uses `gh pr create --base dev`. Support `--lane` override (refused for critical groups).