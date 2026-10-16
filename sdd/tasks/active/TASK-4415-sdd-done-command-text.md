# TASK-4415: `/sdd-done` mirrors + sdd-worker twins — test report step and PR table

**Feature**: FEAT-695 — sdd-done test-results table
**Spec**: `sdd/specs/sdd-done-tests.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4412, TASK-4414
**Assigned-to**: unassigned
**Discovered-from**: `issue:326c8c0da36c`

---

## Context

This task implements spec §3 Module 5. The command text is what actually runs at closeout. All
three `/sdd-done` mirrors must gain the §4.7 Test Report step and the `## Tests` PR section. Both
sdd-worker twins must pass `--feature/--report-task` in the fallback-lane `select_tests` call
(AC10). It needs the flag names from TASK-4412 and the CLI names from TASK-4414.

---

## Scope

- **`.claude/commands/sdd-done.md`**:
  - Replace the §4 "Test validation is intentionally skipped" note. Per-task results are now recorded and aggregated in §4.7.
  - Add `### 4.7. Test Report (FEAT-695)` before `### 5. Build Verification Report`:
    - `decide-rerun`;
    - if `rerun`: a background `timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree "$WT" $(printf -- '--task-file %s ' <every task file of the index>) --feature FEAT-<ID> --report-task _rerun --no-ledger --timeout 300 --run`;
    - then `python -m scripts.sdd.test_report render --index <idx> --worktree "$WT" --out "$TEST_REPORT_MD"` (a path under the report root). It never blocks.
    - every later use of `$TEST_REPORT_MD` is guarded by `[ -s "$TEST_REPORT_MD" ]` (`issue:326c8c0da36c`): the render may legitimately
      produce no file (unwritable path — the CLI then falls back to stdout), and an unguarded `cat`/`--body-file` on a missing file
      would fail the PR step that §4.7 promises never to block.
  - Add `Tests: <total passed>/<total tests> (<failed> failed) — re-run: <done|skipped (N tasks > 10)>` to the §5 report.
  - Insert the rendered section into the §9.2 PR body, after `<N>/<total> tasks verified.`, as
    `$([ -s "$TEST_REPORT_MD" ] && cat "$TEST_REPORT_MD")` — a missing file omits the section instead of breaking the heredoc.
  - The manual/hotfix fallback commands use `--body-file "$TEST_REPORT_MD"` **only when that file is non-empty**, and otherwise keep
    the placeholder body — `gh pr create --body-file` on a missing path exits non-zero (`issue:326c8c0da36c`).
- **`.agent/workflows/sdd-done.md`**: the same edits (note at `:124`, PR body at `:451`).
- **`.agents/skills/sdd-done/SKILL.md`**: the same steps in its condensed numbered style; the PR line (`:197`) includes the rendered section.
- **`.claude/agents/sdd-worker.md`** and **`packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`**: on line 538 add `--feature FEAT-<NNN> --report-task TASK-<NNN>` before `--run`.
- **`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py`**: assert all `_DONE_TWINS` mention `test_report render`, `decide-rerun` and `--no-ledger`, and both sdd-worker twins mention `--report-task`.

**NOT in scope**: any Python under `scripts/` or `packages/*/src`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | §4 note, §4.7, §5 line, §9.2 body |
| `.agent/workflows/sdd-done.md` | MODIFY | mirror |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | mirror (condensed) |
| `.claude/agents/sdd-worker.md` | MODIFY | fallback-lane flags |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | twin |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py` | MODIFY | mirror assertions |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py
_DONE_TWINS = (".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md", ".agents/skills/sdd-done/SKILL.md")  # line ~17
def _repo_root() -> Path   # line ~35
```
CLI names fixed by TASK-4412/4414: `select_tests --feature --report-task --no-ledger`; `python -m scripts.sdd.test_report decide-rerun --index <idx>`; `... render --index <idx> --worktree <wt> --out <file>`.

### Does NOT Exist
- ~~a §4.7 in any `/sdd-done` mirror~~ — added here.
- ~~`test_command_twin_parity.py` covering sdd-done~~ — use `test_done_optimization_contract.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-done.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.claude/commands/sdd-done.md` first, then port it to `.agent/workflows/sdd-done.md` verbatim (same section numbers). *Why*: those two mirrors are near-identical; the SKILL is condensed.
2. Edit both sdd-worker twins identically. Use `git add -f` if a twin is ignored. *Why*: project memory notes that the twins drift when only one is edited.
3. Add the contract assertions. *Why*: AC10 is enforced by test, not by review.

### `.claude/commands/sdd-done.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '**Note:** Test validation is intentionally skipped here' .claude/commands/sdd-done.md) -->
<!-- REPLACE the note paragraph starting at line 145 with: -->
**Note:** Per-task test runs are recorded (FEAT-695) and aggregated in §4.7 — this step does not run tests.

<!-- occurrences: 1 (verified: grep -c '### 5. Build Verification Report' .claude/commands/sdd-done.md) -->
<!-- BEFORE — insert above `### 5. Build Verification Report` (verified: line 264) -->
### 4.7. Test Report (FEAT-695)
<!-- FILL IN: decide-rerun → optional background re-run (exact command in Scope) → render; never blocks (AC6) -->

<!-- occurrences: 1 — AFTER `E2E: <policy> — <status> (gate_satisfied: <bool>)` (line 280): -->
Tests: <passed>/<tests> (<failed> failed) — re-run: <done | skipped (N tasks > 10)>

<!-- occurrences: 1 — AFTER `<N>/<total> tasks verified.` (line 560), inside the heredoc: -->
$([ -s "$TEST_REPORT_MD" ] && cat "$TEST_REPORT_MD")
```

### `.claude/agents/sdd-worker.md` + `_subagent_data/sdd-worker.md` (MODIFY)
```text
# occurrences: 1 each (verified: grep -c -- '--run > artifacts/logs/merge-tests-TASK-<NNN>.log 2>&1`' <file>, line 538)
# change `--task-file sdd/tasks/active/TASK-<NNN>-<slug>.md --run >` to
#        `--task-file sdd/tasks/active/TASK-<NNN>-<slug>.md --feature FEAT-<NNN> --report-task TASK-<NNN> --run >`
```

### FILL IN checklist
- [ ] §4.7 text for all three mirrors (re-run in background, `timeout -k 10 1800`, every `--task-file`, `--no-ledger`)
- [ ] hotfix manual command + `gh` fallback print `--body-file "$TEST_REPORT_MD"` (spec §9 S11), guarded by `[ -s "$TEST_REPORT_MD" ]` with the
      placeholder body as the fallback (`issue:326c8c0da36c`)
- [ ] contract test assertions (AC10)

---

## Acceptance Criteria
- [ ] Spec AC3, AC4, AC6, AC10, AC12 are reflected in all three mirrors.
- [ ] No mirror references `$TEST_REPORT_MD` unguarded: every `cat`/`--body-file` use is preceded by a non-empty check, so a missing
      render degrades to "no `## Tests` section" instead of a failed PR step — `issue:326c8c0da36c`.
- [ ] The contract test passes.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q`

---

## Agent Instructions
Follow `sdd/templates/task.md` § Agent Instructions. Close with `scripts/sdd/close_task.sh TASK-4415 sdd-done-tests verified`.

---

## Completion Note
*(Agent fills this in when done)*
