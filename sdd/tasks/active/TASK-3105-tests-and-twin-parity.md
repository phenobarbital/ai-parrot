# TASK-3105: Tests, twin parity, and acceptance dry run

**Feature**: FEAT-546 — Design Research Hardening
**Spec**: `sdd/specs/design-research-hardening.spec.md` (§3 Module 6, §4 Test Specification, AC-9)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3100, TASK-3101, TASK-3102, TASK-3103, TASK-3104
**Assigned-to**: unassigned

---

## Context

The five hardening tasks (TASK-3100…3104) each edit `.claude/commands/sdd-spec.md`,
`.claude/commands/sdd-task.md`, and/or `sdd/templates/task.md`. This task is the
feature's closing task: it adds the one new automated assertion the spec calls for
(the MODIFY-block occurrence-count line), relies on the EXISTING
`test_command_twin_parity.py` to catch any twin drift across all five, and — per spec
AC-9 — runs a lightweight functional rehearsal proving the five edits actually compose
into a working `/sdd-spec` §3b, since this feature's own spec §9 is `skipped` (its
requirements were pre-sourced from FEAT-545's own dry run, not a fresh `codex` pass —
see spec §8).

---

## Scope

- Add `test_task_template_modify_block_states_occurrence_count()` to
  `tests/sdd_scripts/test_design_research_templates.py`.
- Run the full existing `tests/sdd_scripts/` suite and confirm everything is green
  after all five hardening tasks have landed.
- **AC-9 acceptance dry run** (functional rehearsal, no code changes):
  1. Manually exercise §3b.1 (staging + probe, real or with `SDD_DESIGN_RESEARCH_MODEL=does-not-exist`
     to hit the skip path if `codex` is unavailable) and confirm the run-scoped `$DR`
     path is produced (TASK-3100) and `run.json`'s first half is written (TASK-3102).
  2. Craft one intentionally out-of-repo `affected_paths` string (e.g.
     `"../../../etc/passwd"`) and confirm §3b.4's containment check (TASK-3101)
     rejects it with `REJECT — path outside repository`, distinct from
     `REJECT — path not found`.
  3. If `codex` is available, run §3b.3 for real (or simulate the merge step) and
     confirm `run.json`'s second half (`started_at`/`ended_at`/`exit_code`) is merged
     in (TASK-3102) and the probe-content check (TASK-3104) behaves correctly for
     both a genuine `OK` and a forced bad value.
  4. Record the run-id, full `run.json` contents, and the out-of-repo test outcome (or
     the skip-path outcome, if `codex` was unavailable) in this task's Completion Note.

**NOT in scope**: a new test file (the existing `test_design_research_templates.py` is
extended, not replaced); any change to `test_command_twin_parity.py` itself; a real
`codex` design-research pass over an exploration document (spec §9 is `skipped` by
design — this dry run is a functional rehearsal of the five edits, not a fresh
adversarial cross-check).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_design_research_templates.py` | MODIFY | Add one new test function |

*(The AC-9 dry run produces no committed artifact — spec §9 is `skipped`, so there is
no `sdd/state/FEAT-546/design_research/` to populate, unlike FEAT-545's TASK-3099.
Evidence lives in this task's Completion Note only.)*

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `416c7bc64` (2026-09-10), BEFORE TASK-3100…3104 land — re-grep
> everything below after they do; the anchors will already carry each task's edits
> (run-scoped `$DR`, containment check, `run.json` writes, probe-content check,
> occurrence-count line).

### Anchors in `tests/sdd_scripts/test_design_research_templates.py` (75 lines)
```text
:1-23  imports + module constants (_REPO_ROOT, _TPL, _SCHEMA, _PROMPT, _PLACEHOLDERS) — reuse `_TPL`
:75    def test_task_template_has_blueprint_section() -> None:                         ← the new test is appended AFTER this function
       (final function in the file today — verify with `tail -20` before inserting)
```
### Existing test this task must NOT modify (regression guard for TASK-3100…3104)
```text
tests/sdd_scripts/test_command_twin_parity.py  — unchanged; asserts
  .agent/workflows/{sdd-spec,sdd-task}.md mirror their .claude/commands/ originals
  via an exact single-substitution assertion (FEAT-545 TASK-3098's tightened version).
  Every hardening task (TASK-3100…3104) regenerates its twin using the established
  head -n 4 + cat + (sed for sdd-spec only) recipe — none of them are expected to
  introduce a NEW tolerated-delta line, so this test needs no changes here.
```
### `/sdd-spec` §3b, as landed by TASK-3100…3104 (re-grep for exact anchors after they merge)
```text
.claude/commands/sdd-spec.md §3b.1 — run-scoped $DR (TASK-3100), probe-content check (TASK-3104)
.claude/commands/sdd-spec.md §3b.3 — run.json merge (TASK-3102)
.claude/commands/sdd-spec.md §3b.4 — containment check before test -e (TASK-3101)
.claude/commands/sdd-spec.md §6    — atomic promotion (TASK-3100)
```

### Does NOT Exist
- ~~`test_task_template_modify_block_states_occurrence_count`~~ — created by this task
- ~~a new test file for FEAT-546~~ — this task extends the existing FEAT-545 test file
- ~~`sdd/state/FEAT-546/design_research/`~~ — spec §9 is `skipped`; no committed
  transcript directory for THIS feature (unlike FEAT-545's own TASK-3099 output)

---

## Implementation Notes

### Pattern to Follow
For the test: mirror `test_task_template_has_blueprint_section` immediately above
(same file, same `_TPL` fixture, same `assert needle in text` idiom).
For the dry run: mirror FEAT-545's own TASK-3099 methodology (render → run/skip →
verify) but scoped to a functional rehearsal, not a full adversarial `codex` pass —
this feature's §9 is `skipped` by design (spec §8).

### Key Constraints
- Keep the new test dependency-light — stdlib + the existing `_TPL` constant only, no
  new imports.
- Run the FULL `tests/sdd_scripts/` twin-parity + template suite, not just the new
  test, since this task is also the feature's final green-light check (spec §4
  Integration Tests / AC-1).
- The dry run must exercise the out-of-repo path case even if `codex` itself is
  unavailable in the worktree — the containment check (TASK-3101) is a pure bash/python
  check, independent of whether the actual `codex exec` call can run.

---

## Implementation Blueprint

### Steps (in order)
1. Append the new test function after `test_task_template_has_blueprint_section` —
   *why*: keeps template-content tests grouped together in file order.
2. Run `pytest tests/sdd_scripts/test_command_twin_parity.py
   tests/sdd_scripts/test_design_research_templates.py -v` and confirm 9 passed —
   *why*: spec AC-1 is the feature's overall completion gate.
3. Perform the AC-9 functional rehearsal (Scope, item 3) and record results in the
   Completion Note — *why*: AC-9 requires evidence, not just green tests.

### `tests/sdd_scripts/test_design_research_templates.py` (MODIFY — append after `test_task_template_has_blueprint_section`)
```python
def test_task_template_modify_block_states_occurrence_count() -> None:
    text = (_TPL / "task.md").read_text(encoding="utf-8")
    assert "# occurrences:" in text
```
**Why this shape**: mirrors the exact style of every other template-content test in
this file (a single `assert needle in text` over `_TPL / "task.md"`); this is the one
new automated check spec §4/§6 calls for (TASK-3103's occurrence-count line). The
other four hardening tasks are covered by the existing (unmodified) twin-parity test
plus this task's own AC-9 functional rehearsal — spec §4 explicitly notes "no
dedicated Python test for bash execution semantics" for those.

### FILL IN checklist
- [ ] Record the AC-9 dry-run evidence (run-id, `run.json` contents, out-of-repo test
  outcome, or skip-path outcome) in the Completion Note — bounded by AC-9's exact
  wording in spec §5.

---

## Acceptance Criteria

- [ ] `pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v` → 9 passed (spec AC-1)
- [ ] `ruff check tests/sdd_scripts/test_design_research_templates.py` clean
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` still passes (spec AC-10, dev_loop untouched)
- [ ] No file under `packages/ai-parrot/src/parrot/flows/dev_loop/` is modified (`git status` confirms — spec AC-10)
- [ ] AC-9 dry run performed and recorded in the Completion Note: run-id + `run.json`
  contents (or skip-path outcome) + out-of-repo `affected_paths` rejection reason
- [ ] No other file changed besides the one test file

---

## Test Specification

Run with the venv active:
```bash
source .venv/bin/activate
pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v
ruff check tests/sdd_scripts/test_design_research_templates.py
pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v
```
AC-9 dry-run smoke test (adapt paths/run-id to whatever TASK-3100 actually produced):
```bash
# containment check, independent of codex availability
python -c "
import os, sys
p = os.path.realpath('../../../etc/passwd')
root = os.path.realpath('.')
sys.exit(0 if p == root or p.startswith(root + os.sep) else 1)" && echo "BUG: accepted" || echo "correctly rejected — outside repository"
```

---

## Agent Instructions

1. Read spec §3 Module 6, §4 Test Specification, and AC-9.
2. Dependencies: TASK-3100, TASK-3101, TASK-3102, TASK-3103, TASK-3104 must all be in
   `sdd/tasks/completed/` — this task is the feature's final verification gate.
3. Implement from the blueprint; run every command in Test Specification; perform the
   AC-9 dry run; verify all acceptance criteria; commit the one file.
4. Move to completed; index → `"done"`; Completion Note (include the AC-9 evidence —
   this is also the feature's overall completion summary).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
