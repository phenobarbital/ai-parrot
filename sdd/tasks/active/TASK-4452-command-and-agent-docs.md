# TASK-4452: `/sdd-done`, `sdd-worker`, `qa-runner`, `sdd-coder` docs — contract-driven validation

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4449, TASK-4450, TASK-4451
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. The behaviour is frozen by TASK-4445…4451; the prompts that drive the agents must now
describe it, or agents will keep expecting suite escalation, the `> 10 tasks` skip and raw red counts.

---

## Scope

- `/sdd-done` (`.claude/commands/sdd-done.md` + byte-identical body in `.agent/workflows/sdd-done.md`, plus the
  matching paragraph in `.agents/skills/sdd-done/SKILL.md`):
  - replace the "re-run only for features of <= 10 tasks" comment (sdd-done.md:286) with: the feature tier
    always re-runs fresh at the final HEAD (`--fresh` is the feature-tier default), driven by the index's
    `test_contract`;
  - pass `--index "$IDX"` to both `select_tests --tier feature` calls (sdd-done.md:185 and :294-296);
  - document the table: New red / Baseline red / Unknown columns, the cached line, and the gate line —
    "the PR is blocked only by new reds or unknowns; baseline reds are reported, not blocking".
- `sdd-worker` (`.claude/agents/sdd-worker.md`, its twins `.agent/agents/sdd-worker/agent.md` and
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`): in the merge-gate
  paragraph (`coder_run_validation(... tier="merge" ...)`, sdd-worker.md:383) and the fallback lane
  (`select_tests --tier merge`, sdd-worker.md:557) say: the plan is the chunk tasks' Validation Commands ∪ the
  spec contract (fallback: own tests + direct importers, never a suite); unchanged green targets are skipped
  as `cached`; a red verdict means a NEW red vs `origin/<base_branch>`; add `--index <idx>` to the fallback command.
- `qa-runner` (`.claude/agents/qa-runner.md`): add `--index <idx>` to its `select_tests --tier feature` call
  (qa-runner.md:68) and one sentence on the new-red gate next to "Never run the whole suite here" (line 64).
- `sdd-coder` (`.claude/agents/sdd-coder.md` + `_subagent_data/sdd-coder.md`): one sentence — the task tier
  runs the task's own Validation Commands plus file-level mirror tests; a directory mirror no longer happens.
- New doc-contract test `tests/sdd_scripts/test_feat699_doc_contract.py` asserting the key phrases/flags are
  present in every edited file and that no edited file still contains `<= 10 tasks`.

**NOT in scope**: behaviour changes of any kind.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Fresh closeout, `--index`, table semantics |
| `.agent/workflows/sdd-done.md` | MODIFY | Twin (byte-identical body) |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Codex skill paragraph |
| `.claude/agents/sdd-worker.md` | MODIFY | Merge gate wording, fallback `--index` |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | Twin |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Packaged twin (`git add -f` if ignored) |
| `.claude/agents/qa-runner.md` | MODIFY | `--index`, new-red gate |
| `.claude/agents/sdd-coder.md` | MODIFY | Task-tier sentence |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | Packaged twin |
| `tests/sdd_scripts/test_feat699_doc_contract.py` | CREATE | Phrase/flag contract test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use (verified anchors, occurrences 1 each unless noted)
- `.claude/commands/sdd-done.md:185` — `  python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree "$WT"`
- `.claude/commands/sdd-done.md:286` — `# Deterministic rule: re-run the feature tier at the final HEAD only for features of <= 10 tasks.`
- `.claude/commands/sdd-done.md:287` — `DECISION=$(python -m scripts.sdd.test_report decide-rerun --index "$IDX")`
- `.claude/commands/sdd-done.md:294-296` — `timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> \` … `--feature FEAT-<ID> --report-task _rerun --no-ledger --timeout 300 --run`
- `.claude/agents/sdd-worker.md:383` — `` `coder_run_validation(feature, worktree, execution_id, task_ids=<this chunk's merged task ids>, tier="merge", ``
- `.claude/agents/sdd-worker.md:557` — `  python -m scripts.sdd.select_tests --tier merge --base origin/<base_branch>`
- `.claude/agents/qa-runner.md:64` — `   # Never run the whole suite here — CI owns full-suite and e2e runs.`
- `.claude/agents/qa-runner.md:68` — `   python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> \`
- Twin parity: `tests/sdd_scripts/test_command_twin_parity.py` (commands ↔ `.agent/workflows`); memory note:
  the two sdd-worker prompt suites (FEAT-543 vs FEAT-549) both exist — edit BOTH `.claude/agents/sdd-worker.md`
  and `_subagent_data/sdd-worker.md`.
- `$IDX` is already defined in sdd-done.md before line 287 (it is passed to `decide-rerun`); re-grep its
  definition before using it at line 185 — if it is defined later than 185, move/duplicate the definition.

### Does NOT Exist
- ~~a `> 10 tasks` skip after TASK-4449~~ — `decide-rerun` always prints `rerun` for a non-empty index
- ~~suite escalation in any FEAT-699 plan~~ — never document it as possible

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
    {"path": ".agent/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md", "action": "MODIFY"},
    {"path": ".claude/agents/qa-runner.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_feat699_doc_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `/sdd-done` + twin + skill — *why*: twin parity test runs in CI.
2. `sdd-worker` three copies — *why*: two prompt suites consume different copies.
3. `qa-runner`, `sdd-coder` two copies.
4. Doc-contract test.

### `.claude/commands/sdd-done.md` (MODIFY — same body edit in `.agent/workflows/sdd-done.md`)
```bash
# occurrences: 1 (verified: grep -c '# Deterministic rule: re-run the feature tier at the final HEAD only for features of <= 10 tasks.')
# REPLACE that comment line with:
# FEAT-699: the feature tier always re-runs FRESH at the final HEAD (contract-driven, cheap); decide-rerun
# prints `rerun` for any non-empty index. Gate = new reds (+ unknowns) vs origin/<base_branch>.
```
```bash
# Both `select_tests --tier feature` calls: FILL IN — append `--index "$IDX"` (keep line continuations intact)
```
```markdown
<!-- FILL IN: under the Tests table description, add the New red / Baseline red / Unknown / cached / Gate explanation (Scope bullet 1) -->
```

### FILL IN checklist
- [ ] sdd-done edits ×3 (parity holds)
- [ ] sdd-worker edits ×3
- [ ] qa-runner, sdd-coder ×2
- [ ] doc-contract test: `--index` present in every select_tests call of the edited files; "new red" phrase present; no `<= 10 tasks`

---

## Acceptance Criteria

- [ ] Twin parity passes for `sdd-done`.
- [ ] `test_feat699_doc_contract.py` passes.
- [ ] `test_sdd_done_brief_contract.py`, `test_sdd_worker_brief_contract.py`, `test_e2e_closeout_contract.py` still pass.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_feat699_doc_contract.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_sdd_done_brief_contract.py -q`
- `pytest tests/sdd_scripts/test_sdd_worker_brief_contract.py -q`
- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_feat699_doc_contract.py
"""FEAT-699: agent/command prompts describe contract-driven, new-red-gated validation."""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md", ".claude/agents/sdd-worker.md",
         ".agent/agents/sdd-worker/agent.md", "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
         ".claude/agents/qa-runner.md"]

@pytest.mark.parametrize("rel", FILES)
def test_no_ten_task_skip(rel):
    assert "<= 10 tasks" not in (ROOT / rel).read_text(encoding="utf-8")
# FILL IN: --index on every `select_tests --tier` line; "new red" phrase
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4452 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
