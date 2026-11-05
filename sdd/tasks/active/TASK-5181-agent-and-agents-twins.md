# TASK-5181: Codex/Gemini twins (`.agent/`, `.agents/`) use the resolved root

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5175
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (twin half), G5 and AC9. The `.agent/` (Antigravity/Gemini) and `.agents/` (Codex) twins carry the same workflows as the Claude side and must say the same thing. `.agent/skills/worktree-management/SKILL.md` is NOT a manifest target (spec §6: only `.claude/rules/worktree-management.md` is) — it is updated by hand here and must mirror TASK-5180's rule text, including the R6 migration paragraph.

---

## Scope

- Rewrite every `.claude/worktrees` occurrence in the files below (49 lines at `/sdd-task` time) by the rules R1-R6.
- Mirror TASK-5180's wording: if TASK-5180 is already merged in the worktree, copy its rule/command phrasing; otherwise apply R1-R6 directly (both tasks use the same rules, so the results converge).
- `.agent/workflows/sdd-done.md:90`, `.agents/skills/sdd-{spec,task}/SKILL.md` refusal checks use R5.
- `.agents/skills/sdd-done/SKILL.md:74` describes `WORKTREES_DIR` as the output of `parrot sdd worktree root --root <MAIN_ROOT>`.

**NOT in scope**: Claude-side files (TASK-5180); docs/ (TASK-5182); `_assets/` regeneration (TASK-5183).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | 3 legacy-root line(s) |
| `.agent/workflows/sdd-done.md` | MODIFY | 6 legacy-root line(s) |
| `.agent/workflows/sdd-next.md` | MODIFY | 6 legacy-root line(s) |
| `.agent/workflows/sdd-spec.md` | MODIFY | 1 legacy-root line(s) |
| `.agent/workflows/remove-worktree.md` | MODIFY | 2 legacy-root line(s) |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | 1 legacy-root line(s) |
| `.agent/agents/sdd-planner/agent.md` | MODIFY | 3 legacy-root line(s) |
| `.agent/agents/sdd-research/agent.md` | MODIFY | 2 legacy-root line(s) |
| `.agent/agents/sdd-autopilot/agent.md` | MODIFY | 7 legacy-root line(s) |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | 1 legacy-root line(s) |
| `.agents/agents/sdd-planner/agent.md` | MODIFY | 3 legacy-root line(s) |
| `.agents/agents/sdd-research/agent.md` | MODIFY | 2 legacy-root line(s) |
| `.agents/agents/sdd-autopilot/agent.md` | MODIFY | 7 legacy-root line(s) |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | 2 legacy-root line(s) |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | 1 legacy-root line(s) |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | 2 legacy-root line(s) |

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
    {"path": ".agent/skills/worktree-management/SKILL.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-done.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-next.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/remove-worktree.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-planner/agent.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-research/agent.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-autopilot/agent.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-planner/agent.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-research/agent.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-autopilot/agent.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"}
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
| `.agent/skills/worktree-management/SKILL.md` | 16 | `- Always under `.claude/worktrees/` (git-ignored). Never `.worktrees/`, never a global directory.` | R1 |
| `.agent/skills/worktree-management/SKILL.md` | 66 | `git worktree remove .claude/worktrees/<name>` | R2 |
| `.agent/skills/worktree-management/SKILL.md` | 72 | ``.claude/worktrees/` that `git worktree list` no longer knows about —` | R1 |
| `.agent/workflows/sdd-done.md` | 90 | `If currently inside a worktree (path contains `.claude/worktrees/`), abort:` | R5 |
| `.agent/workflows/sdd-done.md` | 279 | `Worktree: .claude/worktrees/feat-<ID>-<slug>` | R4 |
| `.agent/workflows/sdd-done.md` | 337 | `WORKTREE_PATH=".claude/worktrees/feat-<FEAT-ID>-<slug>"` | R2 |
| `.agent/workflows/sdd-done.md` | 836 | `WT=".claude/worktrees/feat-<FEAT-ID>-<slug>"` | R2 |
| `.agent/workflows/sdd-done.md` | 883 | `Worktree removed: .claude/worktrees/feat-<ID>-<slug>` | R4 |
| `.agent/workflows/sdd-done.md` | 899 | `Worktree removed: .claude/worktrees/feat-<ID>-<slug>` | R4 |
| `.agent/workflows/sdd-next.md` | 101 | `git worktree add -b feat-008-mcp-security .claude/worktrees/feat-008-mcp-security HEAD` | R3 |
| `.agent/workflows/sdd-next.md` | 102 | `cd .claude/worktrees/feat-008-mcp-security` | R2 |
| `.agent/workflows/sdd-next.md` | 110 | `git worktree add -b task-042-prowler .claude/worktrees/task-042-prowler HEAD` | R3 |
| `.agent/workflows/sdd-next.md` | 111 | `→ cd .claude/worktrees/task-042-prowler && /sdd-start TASK-042` | R2 |
| `.agent/workflows/sdd-next.md` | 113 | `git worktree add -b task-043-trivy .claude/worktrees/task-043-trivy HEAD` | R3 |
| `.agent/workflows/sdd-next.md` | 114 | `→ cd .claude/worktrees/task-043-trivy && /sdd-start TASK-043` | R2 |
| `.agent/workflows/sdd-spec.md` | 689 | `.claude/worktrees/feat-<FEAT-ID>-<feature-name> HEAD` | R3 |
| `.agent/workflows/remove-worktree.md` | 7 | `Remove leftover worktrees under `.claude/worktrees/` without destroying work` | R1 |
| `.agent/workflows/remove-worktree.md` | 92 | `git -C .claude/worktrees/<name> push -u origin <branch>` | R2 |
| `.agent/agents/sdd-worker/agent.md` | 427 | `Worktree: .claude/worktrees/<worktree-name>` | R4 |
| `.agent/agents/sdd-planner/agent.md` | 35 | `4. **Create the worktree** at ``.claude/worktrees/feat-<id>-<slug>/``` | R1 |
| `.agent/agents/sdd-planner/agent.md` | 37 | ```git worktree add -b feat-<id>-<slug> .claude/worktrees/feat-<id>-<slug> HEAD``` | R3 |
| `.agent/agents/sdd-planner/agent.md` | 63 | `"worktree_path": "/abs/.claude/worktrees/feat-379-<slug>",` | R4 |
| `.agent/agents/sdd-research/agent.md` | 93 | `"worktree_path": "/abs/.claude/worktrees/feat-130-<slug>",` | R4 |
| `.agent/agents/sdd-research/agent.md` | 107 | `"worktree_path": "/abs/.claude/worktrees/hotfix-OPS-1234-<slug>",` | R4 |
| `.agent/agents/sdd-autopilot/agent.md` | 263 | `.claude/worktrees/feat-<FEAT-ID>-<slug> HEAD` | R3 |
| `.agent/agents/sdd-autopilot/agent.md` | 274 | `Worktree: .claude/worktrees/feat-071-jira-oauth` | R4 |
| `.agent/agents/sdd-autopilot/agent.md` | 279 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agent/agents/sdd-autopilot/agent.md` | 283 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agent/agents/sdd-autopilot/agent.md` | 717 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agent/agents/sdd-autopilot/agent.md` | 730 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agent/agents/sdd-autopilot/agent.md` | 742 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agents/agents/sdd-worker/agent.md` | 365 | `Worktree: .claude/worktrees/<worktree-name>` | R4 |
| `.agents/agents/sdd-planner/agent.md` | 35 | `4. **Create the worktree** at ``.claude/worktrees/feat-<id>-<slug>/``` | R1 |
| `.agents/agents/sdd-planner/agent.md` | 37 | ```git worktree add -b feat-<id>-<slug> .claude/worktrees/feat-<id>-<slug> HEAD``` | R3 |
| `.agents/agents/sdd-planner/agent.md` | 63 | `"worktree_path": "/abs/.claude/worktrees/feat-379-<slug>",` | R4 |
| `.agents/agents/sdd-research/agent.md` | 93 | `"worktree_path": "/abs/.claude/worktrees/feat-130-<slug>",` | R4 |
| `.agents/agents/sdd-research/agent.md` | 107 | `"worktree_path": "/abs/.claude/worktrees/hotfix-OPS-1234-<slug>",` | R4 |
| `.agents/agents/sdd-autopilot/agent.md` | 263 | `.claude/worktrees/feat-<FEAT-ID>-<slug> HEAD` | R3 |
| `.agents/agents/sdd-autopilot/agent.md` | 274 | `Worktree: .claude/worktrees/feat-071-jira-oauth` | R4 |
| `.agents/agents/sdd-autopilot/agent.md` | 279 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agents/agents/sdd-autopilot/agent.md` | 283 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agents/agents/sdd-autopilot/agent.md` | 715 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agents/agents/sdd-autopilot/agent.md` | 728 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agents/agents/sdd-autopilot/agent.md` | 740 | `cd .claude/worktrees/feat-071-jira-oauth` | R2 |
| `.agents/skills/sdd-done/SKILL.md` | 74 | ``WORKTREES_DIR` as `<MAIN_ROOT>/.claude/worktrees`` | R1 |
| `.agents/skills/sdd-done/SKILL.md` | 280 | `Worktree removed: .claude/worktrees/<name>` | R4 |
| `.agents/skills/sdd-spec/SKILL.md` | 79 | `- refuse if inside `.claude/worktrees/`` | R5 |
| `.agents/skills/sdd-task/SKILL.md` | 36 | `- Must run from the main repo, not inside `.claude/worktrees/`.` | R5 |
| `.agents/skills/sdd-task/SKILL.md` | 53 | `- refuse if inside `.claude/worktrees/`` | R5 |

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

- [ ] `grep -rn 'claude/worktrees' .agent .agents` returns only R6 lines in `.agent/skills/worktree-management/SKILL.md`, each containing `git worktree repair`.
- [ ] Every operational twin (`sdd-done`, `sdd-next`, `remove-worktree`, worker/planner/research/autopilot) obtains the root via `parrot sdd worktree root --root`.
- [ ] No twin builds a worktree with a hand-written `git worktree add ... HEAD` (R3).

---

## Validation Commands

- `pytest tests/sdd/test_ledger_workflow_twins.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Agent Instructions

1. Work in the feature worktree; TASK-5175 must be `done` (the `parrot sdd worktree root` verb exists).
2. Re-run `grep -n 'claude/worktrees' <file>` for every file before editing: the table was verified at
   `/sdd-task` time and line numbers may have moved; a vanished line is fine, a NEW one must be handled by the same rules.
3. Mark `in-progress`, edit, run the Validation Commands with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
4. Do NOT run `scripts/sdd/check_asset_sync.py --write` here — TASK-5183 regenerates `_assets/` once, after all prose tasks.
5. Commit only the listed files (`git add -f` for `.claude/`/`.agent/`/`.agents/` paths if a plain add refuses);
   `parrot sdd task close TASK-5181 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
