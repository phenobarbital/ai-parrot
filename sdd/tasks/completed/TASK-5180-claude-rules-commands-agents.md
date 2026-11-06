# TASK-5180: Claude-side rule, commands and agents use the resolved root

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5175
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (Claude half) and AC9. The worktree-management rule, six slash commands and five agent prompts are the repo sources from which `scripts/sdd/check_asset_sync.py --write` regenerates `parrot/sdd/_assets/` (TASK-5183). Operational snippets must capture `parrot sdd worktree root --root "$MAIN_ROOT"` so `/sdd-done`, `/sdd-next`, `/remove-worktree` and the worker/planner/research/autopilot prompts agree with `ensure` under default, relative and absolute overrides.

---

## Scope

- Rewrite every `.claude/worktrees` occurrence in the files below (33 lines at `/sdd-task` time) by the rules R1-R6.
- In `.claude/commands/sdd-done.md` replace line 81 with `WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?` and keep every later `$WORKTREES_DIR`-derived path quoted (feature/brief paths, snapshot worktree, removal target).
- In `.claude/rules/worktree-management.md`: §1 names the default and the exported `WORKTREE_BASE_PATH` override (spec §7: navconfig `.env`-only values do not reach the scripts — say "export it in the shell"); add the R6 migration paragraph; §2/§6 snippets per R2; line 55 sandbox sentence names "the primary checkout's worktree root".

**NOT in scope**: the `.agent/`/`.agents/` twins (TASK-5181); docs/ and CLAUDE.md (TASK-5182); the `.sh` hook (TASK-5178); `_assets/` regeneration and the guard test (TASK-5183).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/rules/worktree-management.md` | MODIFY | 4 legacy-root line(s) |
| `.claude/commands/sdd-done.md` | MODIFY | 4 legacy-root line(s) |
| `.claude/commands/sdd-next.md` | MODIFY | 6 legacy-root line(s) |
| `.claude/commands/sdd-spec.md` | MODIFY | 1 legacy-root line(s) |
| `.claude/commands/remove-worktree.md` | MODIFY | 2 legacy-root line(s) |
| `.claude/commands/release.md` | MODIFY | 1 legacy-root line(s) |
| `.claude/commands/security-check.md` | MODIFY | 1 legacy-root line(s) |
| `.claude/agents/sdd-worker.md` | MODIFY | 2 legacy-root line(s) |
| `.claude/agents/sdd-coder.md` | MODIFY | 1 legacy-root line(s) |
| `.claude/agents/sdd-planner.md` | MODIFY | 1 legacy-root line(s) |
| `.claude/agents/sdd-research.md` | MODIFY | 4 legacy-root line(s) |
| `.claude/agents/sdd-autopilot.md` | MODIFY | 6 legacy-root line(s) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Interfaces
```bash
parrot sdd worktree root --root "$MAIN_ROOT"     # TASK-5175 — prints one absolute path; exit 0
parrot sdd worktree ensure --slug <slug> --feature-id FEAT-<NNN>   # prints the worktree path (ensure_worktree.py main)
parrot sdd worktree status                        # lists legacy entries as flow_type "legacy" after TASK-5177
parrot doctor                                     # prints the migration recipe in the "sdd: legacy worktrees" fix (TASK-5179)
MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)   # verified: .claude/commands/sdd-done.md:80
```

### Does NOT Exist
- ~~`parrot sdd worktree migrate`~~ / ~~`git worktree move` wrapper~~ — out of scope by decision; users run the printed recipe.
- ~~`parrot sdd worktree root` without `--root`~~ — the flag is required.
- ~~a dual-root lookup~~ — never tell an agent to "check both `.parrot/worktrees` and `.claude/worktrees`".

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/rules/worktree-management.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-next.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".claude/commands/remove-worktree.md", "action": "MODIFY"},
    {"path": ".claude/commands/release.md", "action": "MODIFY"},
    {"path": ".claude/commands/security-check.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-planner.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-research.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-autopilot.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Rewrite rules (identical across TASK-5180, TASK-5181, TASK-5182)

| Rule | Where it applies | Rewrite |
|---|---|---|
| R1 prose | a sentence that says where worktrees live | "under the worktree root (default `.parrot/worktrees/`, override with an exported `WORKTREE_BASE_PATH`)" — shorten to "the worktree root" after the first mention in a file |
| R2 operational snippet | a shell line that builds, `cd`s into, removes or tests a worktree path | resolve first: `MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)` then `WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") \|\| exit $?`; use `"$WORKTREES_DIR/<name>"` with the quotes kept |
| R3 creation snippet | `git worktree add -b X .claude/worktrees/X HEAD` | replace with the documented creator: `parrot sdd worktree ensure --slug <slug> --feature-id FEAT-<NNN>` (prints the path); hand-built `git worktree add` contradicts the worktree rule |
| R4 illustrative output / JSON | `Worktree: .claude/worktrees/x`, `"worktree_path": "/abs/.claude/worktrees/..."` | show the default: `.parrot/worktrees/x`, `/abs/.parrot/worktrees/...` |
| R5 "am I in a worktree" check | "refuse if inside `.claude/worktrees/`" | "refuse if `git rev-parse --git-dir` differs from `--git-common-dir` (a linked worktree)" — location-independent |
| R6 migration text | ONLY the worktree-management rule and its twin | one paragraph telling users with worktrees under the legacy `.claude/worktrees/` to run the recipe `parrot doctor` prints; every line that names `.claude/worktrees` must also contain `git worktree repair` (the TASK-5183 guard test allows exactly those lines) |

Never substitute another fixed path for `.claude/worktrees` in an operational snippet: a fixed `.parrot/worktrees` would ignore `WORKTREE_BASE_PATH` (spec §6 note under Edit Sites).


### Edit sites (verified at `/sdd-task` time; re-grep before editing)

| File | Line | Current text (verbatim, truncated at 110 chars) | Rule |
|---|---|---|---|
| `.claude/rules/worktree-management.md` | 15 | `- Always under `.claude/worktrees/` (git-ignored). Never `.worktrees/`, never a global directory.` | R1 |
| `.claude/rules/worktree-management.md` | 55 | `- SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git` | R5 |
| `.claude/rules/worktree-management.md` | 69 | `git worktree remove .claude/worktrees/<name>` | R2 |
| `.claude/rules/worktree-management.md` | 75 | ``.claude/worktrees/` that `git worktree list` no longer knows about —` | R1 |
| `.claude/commands/sdd-done.md` | 81 | `WORKTREES_DIR="$MAIN_ROOT/.claude/worktrees"` | R2 |
| `.claude/commands/sdd-done.md` | 390 | `Worktree: .claude/worktrees/feat-<ID>-<slug>` | R4 |
| `.claude/commands/sdd-done.md` | 932 | `Worktree removed: .claude/worktrees/feat-<ID>-<slug>` | R4 |
| `.claude/commands/sdd-done.md` | 950 | `Worktree removed: .claude/worktrees/feat-<ID>-<slug>` | R4 |
| `.claude/commands/sdd-next.md` | 101 | `git worktree add -b feat-008-mcp-security .claude/worktrees/feat-008-mcp-security HEAD` | R3 |
| `.claude/commands/sdd-next.md` | 102 | `cd .claude/worktrees/feat-008-mcp-security` | R2 |
| `.claude/commands/sdd-next.md` | 110 | `git worktree add -b task-042-prowler .claude/worktrees/task-042-prowler HEAD` | R3 |
| `.claude/commands/sdd-next.md` | 111 | `→ cd .claude/worktrees/task-042-prowler && /sdd-start TASK-042` | R2 |
| `.claude/commands/sdd-next.md` | 113 | `git worktree add -b task-043-trivy .claude/worktrees/task-043-trivy HEAD` | R3 |
| `.claude/commands/sdd-next.md` | 114 | `→ cd .claude/worktrees/task-043-trivy && /sdd-start TASK-043` | R2 |
| `.claude/commands/sdd-spec.md` | 685 | `.claude/worktrees/feat-<FEAT-ID>-<feature-name> HEAD` | R3 |
| `.claude/commands/remove-worktree.md` | 9 | `Remove leftover worktrees under `.claude/worktrees/` without destroying work` | R1 |
| `.claude/commands/remove-worktree.md` | 94 | `git -C .claude/worktrees/<name> push -u origin <branch>` | R2 |
| `.claude/commands/release.md` | 69 | ``.claude/worktrees/`, **abort** and say why.` | R1 |
| `.claude/commands/security-check.md` | 87 | `> `.claude/worktrees/` holds full checkouts of the repo, so every recursive` | R1 |
| `.claude/agents/sdd-worker.md` | 64 | `- The primary checkout's `.claude/worktrees/` and `.parrot/ledger/` are the only writable` | R1 |
| `.claude/agents/sdd-worker.md` | 768 | `Worktree: .claude/worktrees/<worktree-name>` | R4 |
| `.claude/agents/sdd-coder.md` | 9 | `Context: sdd-worker prepared .claude/worktrees/feat-FEAT-549-x--pool/TASK-3115-a1 for TASK-3115.` | R1 |
| `.claude/agents/sdd-planner.md` | 88 | `"worktree_path": "/abs/.claude/worktrees/feat-379-<slug>",` | R4 |
| `.claude/agents/sdd-research.md` | 9 | `.claude/worktrees/feat-FEAT-<NNN>-<slug>/ (feature) or` | R1 |
| `.claude/agents/sdd-research.md` | 10 | `.claude/worktrees/hotfix-<JIRA-KEY>-<slug>/ (hotfix, no id reserved).` | R1 |
| `.claude/agents/sdd-research.md` | 110 | `"worktree_path": "/abs/.claude/worktrees/feat-130-<slug>",` | R4 |
| `.claude/agents/sdd-research.md` | 124 | `"worktree_path": "/abs/.claude/worktrees/hotfix-OPS-1234-<slug>",` | R4 |
| `.claude/agents/sdd-autopilot.md` | 267 | `Worktree: .claude/worktrees/feat-071-jira-oauth` | R4 |
| `.claude/agents/sdd-autopilot.md` | 272 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.claude/agents/sdd-autopilot.md` | 276 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.claude/agents/sdd-autopilot.md` | 710 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.claude/agents/sdd-autopilot.md` | 723 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.claude/agents/sdd-autopilot.md` | 735 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |

The Rule column is a first guess from the line's shape; read each line's surrounding block and apply the
rule that fits (an R1 line inside a fenced shell block is R2).

---

## Implementation Blueprint

### Steps (in order)
1. For each file, open it, re-grep, and classify every hit by R1-R6 — *why*: line numbers drift and the rule depends on context.
2. Where a file has an operational shell block, add the two-line root resolution ONCE at the top of that block and reuse `$WORKTREES_DIR` — *why*: AC9, effective root honours `WORKTREE_BASE_PATH`.
3. Apply R1/R4/R5 text edits — *why*: prose must name the new default (G5).

4. Verify with `grep -rn 'claude/worktrees' <files>` — only R6 lines (containing `git worktree repair`) may remain.

### FILL IN checklist
- [ ] every row of the Edit-sites table resolved (record any re-classification in the Completion Note).
- [ ] no operational snippet names a fixed worktree directory.

---

## Acceptance Criteria

- [ ] `grep -n 'claude/worktrees' <listed files>` returns only R6 lines in `.claude/rules/worktree-management.md`, each containing `git worktree repair`.
- [ ] `/sdd-done`, `/sdd-next`, `/remove-worktree` and the four orchestration agents (worker, planner, research, autopilot) obtain the root via `parrot sdd worktree root --root`.
- [ ] The rule documents the default, the exported override and the hierarchy-preserving, collision-checked migration recipe with explicit repair destinations (spec §3 M5).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd/test_ledger_workflow_twins.py -q`

---

## Agent Instructions

1. Work in the feature worktree; TASK-5175 must be `done` (the `parrot sdd worktree root` verb exists).
2. Re-run `grep -n 'claude/worktrees' <file>` for every file before editing: the table was verified at
   `/sdd-task` time and line numbers may have moved; a vanished line is fine, a NEW one must be handled by the same rules.
3. Mark `in-progress`, edit, run the Validation Commands with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
4. Do NOT run `scripts/sdd/check_asset_sync.py --write` here — TASK-5183 regenerates `_assets/` once, after all prose tasks.
5. Commit only the listed files (`git add -f` for `.claude/`/`.agent/`/`.agents/` paths if a plain add refuses);
   `parrot sdd task close TASK-5180 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

Implemented by seat qwen (nova) — terminal 'salvaged' at 101 turns, engine-committed, 1 attempt, merged cleanly.

**Completed by**: sdd-worker (orchestrator)
**Date**: 2026-11-05
**Notes**: Merge-tier: 171 passed, 1 pre-existing failure (test_no_command_hand_rolls_a_worktree[sdd-worker.md], also red on origin/dev). Closed via `parrot sdd task close`; finalize unavailable (coder_record_review tool error). Final cross-check of residual `.claude/worktrees` references is TASK-5183's guard test. feedback NOT recorded.

**Deviations from spec**:
