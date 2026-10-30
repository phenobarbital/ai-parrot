# TASK-4870: Wire closeout hooks into both `/sdd-done` twins; remove `--resolve-jira`

**Feature**: FEAT-764 — `/sdd-done` closeout hooks
**Spec**: `sdd/specs/sdd-done-closeout-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4869
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4 (not delegation-eligible: prose in two twins must stay consistent).
Spec G2, G4, G6; AC3–AC8, AC10. `.claude/` paths may need `git add -f`.

---

## Scope

In **`.claude/commands/sdd-done.md`**:
- Add `### 4.8. Closeout Hooks — pre_pr (FEAT-764)` immediately before `### 5. Build Verification Report`:
  write the context JSON (`feat_id, spec_path, branch, base_branch, worktree, test_report_md, e2e_gate=GATE_JSON, dry_run`)
  to `${SDD_HOOKS_ARTIFACT_ROOT:-/tmp/claude-$(id -u)/sdd-hooks}/<FEAT-ID>/context.json`, run
  `python -m scripts.sdd.run_closeout_hooks --event pre_pr --context <ctx> --root "$WORKTREE_PATH" [--dry-run]`.
  Exit 0 → continue; 3 → for each `pending_agents[]` launch `Agent(subagent_type=<agent>, prompt=<prompt>)`,
  then `--record <name> --status pass|fail --summary ...`, then `--finalize`; 1 or 2 → run on_failure, abort
  before Step 7 (state: not bypassed by `--force`). Runs under `--dry-run` (AC4).
- After `### 9.2` add `### 9.3. Closeout Hooks — post_pr (FEAT-764)`: add `pr_url`/`merge_sha` to the
  context, run `--event post_pr` (skip under `--dry-run`); never aborts; agent hooks same loop.
- Every abort path (4.6 E2E gate, 4.8, Step 9 merge blockers) gets one line: run
  `--event on_failure` with `abort_reason` (never changes the abort).
- PR body (in 9.2's `gh pr create` heredoc): append the pre_pr outcome's `evidence_md` as `## Evidence`
  when non-empty; Step 12 output gets `Hooks: pre_pr <n pass/fail>, post_pr <...>` and the evidence paths.
- Delete Step 10 (`### 10. Transition Jira Ticket (if --resolve-jira)`) entirely, the Usage line
  `/sdd-done FEAT-014 --resolve-jira`, the `--resolve-jira` mention in the Guardrails flag list (line ~50),
  and the `{if --resolve-jira}` lines in Step 12. Add one sentence under 9.3: Jira transition is now the
  opt-in `jira.transition` builtin in `.parrot/sdd_hooks.toml`.
- Do NOT renumber Step 11/12 (other docs reference them).

In **`.agents/skills/sdd-done/SKILL.md`**: mirror the same — new item `4.8.` after the 4.6 block,
post_pr after `12. Integrate:`, remove `14. Resolve Jira if requested:` and `[--resolve-jira]` in the
invocation line. Codex has no native subagent dispatch: for pending agent hooks, record
`--status fail --summary "agent hooks unsupported on this host"` (spec §7), unless the host can run them.

Write `tests/sdd_scripts/test_sdd_done_hooks_contract.py`.

**NOT in scope**: `docs/sdd/*.md` mentions of `--resolve-jira` (TASK-4871); the scripts themselves.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Step 4.8 pre_pr, post_pr after 9.2, on_failure on aborts, Evidence, drop Step 10 + flag |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Same in the Codex numbered list |
| `tests/sdd_scripts/test_sdd_done_hooks_contract.py` | CREATE | Text-contract test over both twins |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path   # contract test reads both twins, same as tests/sdd_scripts/test_sdd_done_brief_contract.py:9-10
```

### Existing Signatures to Use
Anchors (re-run `grep -c` before editing; all counts were 1 on 2026-10-28):
```
.claude/commands/sdd-done.md:27   /sdd-done FEAT-014 --resolve-jira      # also transition the Jira ticket to Done
.claude/commands/sdd-done.md:50   > flag combination — including `--force` and `--resolve-jira`. ...
.claude/commands/sdd-done.md:193  ### 4.6. Verify E2E Evidence (FEAT-581)
.claude/commands/sdd-done.md:284  ### 5. Build Verification Report
.claude/commands/sdd-done.md:543  ### 9.2. Integrate Feature Branch (FEAT-145, flow-aware)
.claude/commands/sdd-done.md:765  ### 10. Transition Jira Ticket (if --resolve-jira)
.claude/commands/sdd-done.md:868  ### 11. Cleanup the Worktree
.claude/commands/sdd-done.md:892  ### 12. Output
.agents/skills/sdd-done/SKILL.md:19   Codex invocation: `$sdd-done FEAT-NNN [--dry-run] [--merge] [--force] [--resolve-jira] ...
.agents/skills/sdd-done/SKILL.md:98   4.6. Verify E2E evidence (FEAT-581/FEAT-703), before any stamp/push/
.agents/skills/sdd-done/SKILL.md:119  5. Classify:
.agents/skills/sdd-done/SKILL.md:206  12. Integrate:
.agents/skills/sdd-done/SKILL.md:221  14. Resolve Jira if requested:
.agents/skills/sdd-done/SKILL.md:227  15. Cleanup:
```
Line numbers drift (FEAT-758 also edits sdd-done): locate by the verbatim text, not the number.

### Does NOT Exist
- ~~`--force` bypass for hooks~~ — must not be documented.
- ~~a CLAUDE.md hooks section~~ — config is TOML only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_sdd_done_hooks_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.claude/commands/sdd-done.md` per Scope, top to bottom — *why*: line anchors shift as you go.
2. Mirror into the Codex twin — *why*: both twins must call the same CLI (AC10).
3. Run the existing contract tests (brief + e2e) — *why*: they assert text in the same files.
4. Write and run the new contract test.

### `.claude/commands/sdd-done.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^### 5. Build Verification Report' .claude/commands/sdd-done.md)
# BEFORE — insert above `### 5. Build Verification Report` (verified: .claude/commands/sdd-done.md:284)
### 4.8. Closeout Hooks — pre_pr (FEAT-764)

Repository-defined hooks from `.parrot/sdd_hooks.toml` (absent file ⇒ no-op). The dispatcher is
code; **its exit code is the contract** — do not re-derive it here.

```bash
HOOKS_DIR="${SDD_HOOKS_ARTIFACT_ROOT:-/tmp/claude-$(id -u)/sdd-hooks}/$FEAT_ID"; mkdir -p "$HOOKS_DIR"
# FILL IN: write $HOOKS_DIR/context.json (fields per spec §2 HookContext)
python -m scripts.sdd.run_closeout_hooks --event pre_pr --context "$HOOKS_DIR/context.json"   --root "$WORKTREE_PATH" ${DRY_RUN:+--dry-run}
HOOKS_EXIT=$?
```
# FILL IN: exit-code handling table (0 / 3 agent loop / 1,2 abort + on_failure, not --force-able)
```
**Why**: placed after 4.7 so hooks can read the test report and before §5 so results land in the report.

### `.agents/skills/sdd-done/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^5. Classify:' .agents/skills/sdd-done/SKILL.md)
# BEFORE — insert above `5. Classify:` (verified: .agents/skills/sdd-done/SKILL.md:119)
4.8. Closeout hooks — pre_pr (FEAT-764): `python -m scripts.sdd.run_closeout_hooks --event pre_pr ...`
# FILL IN: same contract, condensed; Codex agent-hook rule
```

### FILL IN checklist
- [ ] 4.8 context + exit handling; 9.3 post_pr; on_failure lines on each abort
- [ ] Evidence in PR body + Step 12 `Hooks:` line
- [ ] Remove Step 10 / twin step 14 / all `--resolve-jira`
- [ ] Contract test

---

## Acceptance Criteria

- [ ] `git grep -n -- --resolve-jira .claude/commands/sdd-done.md .agents/skills/sdd-done/SKILL.md` is empty (AC8).
- [ ] Both twins call `run_closeout_hooks` for `pre_pr`, `post_pr`, `on_failure` (AC10).
- [ ] 4.8 appears after 4.7 and before §5; neither twin says hooks can be bypassed with `--force` (AC3).
- [ ] Existing brief/e2e contract tests still pass.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_done_hooks_contract.py -q`
- `pytest tests/sdd_scripts/test_sdd_done_brief_contract.py -q`
- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_sdd_done_hooks_contract.py
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / ".claude/commands/sdd-done.md"
_TWIN = _ROOT / ".agents/skills/sdd-done/SKILL.md"

def test_no_resolve_jira_anywhere(): ...
def test_all_three_events_invoked_in_both_twins(): ...
def test_pre_pr_between_test_report_and_report(): ...   # index("### 4.7") < index("### 4.8") < index("### 5. Build")
def test_post_pr_after_integrate(): ...
def test_hooks_not_force_bypassable(): ...
def test_jira_points_to_builtin(): ...                  # "jira.transition" mentioned in both
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-done-closeout-hooks --feature-id FEAT-764`), never on `dev`.
2. Read the spec `sdd/specs/sdd-done-closeout-hooks.spec.md` (§2 Overview, Data Models, exit-code table).
3. Every `Depends-on` task must be `done` in `sdd/tasks/index/sdd-done-closeout-hooks.json`.
4. Verify the Codebase Contract before writing code; fix stale entries first.
5. Mark `in-progress` in the index, implement from the Blueprint, complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH=.` from the worktree root; `ruff check` the new files.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh <TASK-ID> sdd-done-closeout-hooks verified`.

---

## Completion Note


- Task: TASK-4870
- Feature: sdd-done-closeout-hooks
- Implementation SHA: 1d92d5f5619b73ceb79909433a1c9f5ac8d8421a
- Closed at (UTC): 2026-10-28T00:30:09+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: haiku · Backend: native · Model: haiku · Attempts: 1 · Duration: 350s · Tokens: n/a. Follow-ups: .agent/workflows/sdd-done.md (Antigravity twin) still has --resolve-jira/Step 10; on_failure agent hooks (exit 3) are not dispatched by the twins. |
