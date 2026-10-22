# TASK-4462: Rewire both `/sdd-done` twins onto the gate script

**Feature**: FEAT-703 — Code-enforced E2E closeout gate for `/sdd-done`
**Spec**: `sdd/specs/fixgroup-603217cacd87.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4461
**Assigned-to**: unassigned

**Discovered-from**: `issue:4b887b8e3ce0`

---

## Context

With the gate shipped (TASK-4460) and the contract suite retargeted at it
(TASK-4461), the last step is to make the two closeout surfaces actually *call*
it. Today `.claude/commands/sdd-done.md` Step 4.6 (L192–274) and
`.agents/skills/sdd-done/SKILL.md` step 4.6 (L98–121) restate the decision table
in prose and ask the agent to execute inline `python -c` + `jq` and then reason
about the result. That is the prose-enforcement `issue:4b887b8e3ce0` reports.

After this task the twins resolve the gate by **exit code**, which an agent
cannot misread.

---

## Scope

- Replace Step 4.6's narrative in `.claude/commands/sdd-done.md` with the single
  invocation from spec §7 plus an exit-code branch, retaining: the user-facing
  `E2E: <policy> — <status>` reporting line, the full refusal message, the
  `--force` clarification, and the `--dry-run` behaviour.
- Apply the identical change to `.agents/skills/sdd-done/SKILL.md` step 4.6.
- Update the 5 `test_each_surface_*` tests (L488–521 of
  `tests/sdd_scripts/test_e2e_closeout_contract.py`) so they assert the twins
  **invoke the gate script** rather than restate the decision table.

**NOT in scope**:
- The 15 behavioral tests (TASK-4461 retargeted them; leave them alone).
- `scripts/sdd/check_e2e_closeout.py`.
- Any other `/sdd-done` step or gate. Task-state, lint and merge-blocker gates
  stay prose-level — this feature deliberately sets no conversion obligation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Step 4.6 → one invocation + exit-code branch |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | step 4.6 → the same, Codex twin |
| `tests/sdd_scripts/test_e2e_closeout_contract.py` | MODIFY | 5 doc-surface tests assert invocation |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# scripts/sdd/check_e2e_closeout.py  (TASK-4460)
def main(argv: Optional[Sequence[str]] = None) -> int: ...
#   --spec <path> --feat-id FEAT-<NNN> --worktree <path>
#   stdout: one JSON object {policy, status, gate_satisfied, reason_codes}
#   exit:   0 = proceed, 1 = abort closeout
```

### Edit anchors (re-verified at `c26bf74bf`)
```text
.claude/commands/sdd-done.md:192   "### 4.6. Verify E2E Evidence (FEAT-581)"
    occurrences: 1   (grep -c '^### 4\.6\. Verify E2E Evidence (FEAT-581)$')
    replaced region: L192 through L274 (ends before "### 4.7. Test Report (FEAT-695)" at L276)

.agents/skills/sdd-done/SKILL.md:98  "4.6. Verify E2E evidence (FEAT-581), before any stamp/push/merge-blocker/PR/"
    occurrences: 1
    replaced region: L98 through L121 (ends before "5. Classify:" at L122)

tests/sdd_scripts/test_e2e_closeout_contract.py:488-521  the 5 test_each_surface_* tests
    _DOC_SURFACES tuple defined at L49 — reuse it, do not redefine
```

### Text that MUST survive the rewrite (quoted verbatim from L266-268)
```text
This is NOT bypassed by --force: --force only overrides per-task
partial/missing evidence (Step 6) and ledger merge blockers (Step 9),
never a required E2E gate (spec AC9).
```

### Does NOT Exist
- ~~a `--force` flag on `check_e2e_closeout.py`~~ — the gate takes none, by design
- ~~`parrot e2e verify --json`~~ — the twins no longer shell out to the CLI at all
- ~~a `jq` dependency~~ — removed by this change; do not reintroduce it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": ".claude/commands/sdd-done.md", "action": "MODIFY" },
    { "path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY" },
    { "path": "tests/sdd_scripts/test_e2e_closeout_contract.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:tests/sdd_scripts/test_e2e_closeout_contract.py#evaluate_closeout_gate"
  ]
}
```

---

## Implementation Notes

**Twin drift is the main risk.** The two files must say the same thing; the
doc-surface tests iterate `_DOC_SURFACES` (L49) and will fail if they diverge.
Edit both in the same pass.

**`.agents/` may be git-ignored.** Check before committing — if so, stage the
SKILL.md edit with `git add -f`. A silently-dropped twin edit is the classic
failure here.

**Keep the prose that is still true.** The rewrite removes the *decision table*
and the inline `python -c`/`jq`, not the explanation of what the gate is for,
the refusal message, or the `--force` scoping note. Those stay — they tell the
operator why closeout stopped.

**Why the doc tests change shape.** `test_each_surface_states_the_three_policy_literals_with_no_coercion`
currently asserts the prose enumerates `required`/`optional`/`none`. After this
task the literals live in `resolve_policy()`, so asserting them in markdown would
force the prose to keep duplicating the table — the very duplication being
removed. Re-point that test at invocation + the surviving `--force` guarantee.

---

## Implementation Blueprint

### Steps (in order)

1. Replace `.claude/commands/sdd-done.md` L192–274 with Block 1.
2. Replace `.agents/skills/sdd-done/SKILL.md` L98–121 with Block 2.
3. Update the 5 doc-surface tests (Block 3).
4. Run the Validation Commands. Confirm `git status` shows **both** markdown
   files staged (`git add -f` the `.agents/` one if ignored).

### Block 1 — `.claude/commands/sdd-done.md` Step 4.6 (MODIFY)

```markdown
# AFTER — replaces L192-274, attaching at the verified anchor
# occurrences: 1 (verified: grep -c '^### 4\.6\. Verify E2E Evidence (FEAT-581)$' .claude/commands/sdd-done.md)
### 4.6. Verify E2E Evidence (FEAT-581)

Before any closeout mutation — Step 5's report is descriptive, but Step 7's
index stamp, Step 8's push, Step 9's merge-blocker check, Step 9.2's PR/merge
and Step 11's cleanup are not — the E2E evidence gate runs as **code**, not as
instructions (FEAT-703). It is read-only: it never runs pytest, a target or the
ordinary task suite, and it never reads an `e2e-exploration.json` report —
exploratory scenarios can never satisfy this gate.

```bash
GATE_JSON=$(python -m scripts.sdd.check_e2e_closeout \
    --spec "<spec-path>" --feat-id "$FEAT_ID" --worktree "$WORKTREE_PATH")
GATE_EXIT=$?
```

- **`GATE_EXIT` is 0** — record the `E2E: <policy> — <status>` line from
  `GATE_JSON` (`.policy`, `.status`, `.gate_satisfied`, `.reason_codes`) and
  continue. This covers `none` (exempt), `optional` (advisory, reported
  honestly and never upgraded to a pass) and `required` satisfied.
- **`GATE_EXIT` is non-zero** — abort the entire command now, before Step 5's
  report is even built:
  ```
  # FILL IN: the refusal message -- bounded by the pre-change text at L261-269,
  # reproduced verbatim including the three --force lines quoted in this task's
  # Codebase Contract.
  ```
  Exit nonzero. `--dry-run` still shows this refusal and stops the same way it
  stops after Step 5 — it never proceeds to a mutating step.

The gate's own decision table (policy resolution, missing plans, malformed
policy values, validator errors, an uninstalled `ai-parrot-server`) lives in
`scripts/sdd/check_e2e_closeout.py` and is proven by
`tests/sdd_scripts/test_e2e_closeout_contract.py`. Do not restate it here — the
exit code is the contract.

Carry `GATE_JSON` into Step 5's report and Step 12's output as the `E2E:` line.
```

**Why**: the agent's only job becomes "run it, branch on the exit code". There
is no table left to misread, which is the whole point of `issue:4b887b8e3ce0`.

### Block 2 — `.agents/skills/sdd-done/SKILL.md` step 4.6 (MODIFY)

```markdown
# AFTER — replaces L98-121, attaching at the verified anchor
# occurrences: 1 (verified: grep -c on the full anchor line)
4.6. Verify E2E evidence (FEAT-581/FEAT-703), before any stamp/push/
   merge-blocker/PR/merge/cleanup step below — the gate is code, not prose:
   - run `python -m scripts.sdd.check_e2e_closeout --spec <spec-path>
     --feat-id <FEAT-ID> --worktree <worktree>`
   - exit 0: record `E2E: <policy> - <status> (gate_satisfied: <bool>)` from the
     JSON on stdout and continue; `optional` outcomes are advisory only, always
     reported with their real status and never upgraded to a pass
   - exit non-zero: abort the entire command now, before building the
     verification report — `--force` does not bypass this (spec AC9); it only
     overrides per-task partial/missing evidence and ledger merge blockers
   - the decision table itself lives in the script, not here
```

**Why**: byte-for-byte parity of *meaning* with Block 1 so `_DOC_SURFACES`
assertions hold across both files.

### Block 3 — doc-surface tests (MODIFY)

```python
# AFTER — replaces the 5 test_each_surface_* tests at L488-521
# occurrences: 1 (verified: grep -c 'def test_each_surface_invokes_verify_before_every_mutating_step')
@pytest.mark.parametrize("path", _DOC_SURFACES, ids=lambda p: p.name)
def test_each_surface_invokes_the_gate_script(path: Path) -> None:
    """FEAT-703: both surfaces delegate the decision to the gate script."""
    text = path.read_text(encoding="utf-8")
    assert "scripts.sdd.check_e2e_closeout" in text


# FILL IN: retain, adapted to the new prose --
#   - test_each_surface_states_force_never_bypasses_required_gate (keep as-is:
#     the --force guarantee still appears verbatim in both files)
#   - test_each_surface_excludes_exploration_from_the_gate
#   - test_each_surface_names_the_worktree_scoped_plan_path -> now asserts the
#     --worktree/--feat-id invocation shape instead of a literal plan path
#   bounded by AC6: the prose must no longer restate the decision table.
```

**Why**: these tests are what stop the twins drifting apart or quietly losing the
`--force` guarantee; they must keep testing the surfaces, just against the new
contract.

### FILL IN checklist

- [ ] Verbatim refusal message restored in Block 1
- [ ] Four remaining doc-surface tests adapted (Block 3)
- [ ] Both markdown twins actually staged (`git add -f` if `.agents/` is ignored)

---

## Acceptance Criteria

- [ ] Both twins invoke `python -m scripts.sdd.check_e2e_closeout` before any
      stamp/push/PR/merge/cleanup step and branch solely on its exit code.
- [ ] Neither twin restates the decision table; neither uses `jq` or an inline
      `python -c` policy parser for this step.
- [ ] The `--force` guarantee survives verbatim in both files.
- [ ] `--dry-run` still shows the refusal and stops before any mutating step.
- [ ] The 5 doc-surface tests pass and still cover both surfaces.
- [ ] The 15 behavioral tests from TASK-4461 still pass, untouched.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`

---

## Test Specification

The doc-surface tests are the deliverable's own coverage. They must fail if
either twin stops invoking the script or loses the `--force` guarantee — verify
that by temporarily reverting one twin and confirming a red run before
committing.

---

## Agent Instructions

1. Read `.claude/commands/sdd-done.md` L192–276 and
   `.agents/skills/sdd-done/SKILL.md` L95–122 before editing.
2. Edit both twins in one pass; they must stay in sync.
3. Check `.gitignore` for `.agents/` and use `git add -f` if needed — verify
   with `git diff --cached --name-only` that all three files are staged.
4. Commit only the three files:
   `feat(sdd): TASK-4462 — rewire /sdd-done twins onto the code-enforced E2E gate`.

---

## Completion Note

**Completed by**: sdd-fix (Claude)
**Status**: done

- Replaced `.claude/commands/sdd-done.md` Step 4.6 (L192–274, ~83 lines of
  prose + an inline `python -c` policy parser + a `jq`-parsed
  `parrot e2e verify` call + a 4-bullet decision table) with the single
  `python -m scripts.sdd.check_e2e_closeout` invocation and an exit-code branch.
  The `jq` dependency for this step is gone.
- Applied the equivalent change to `.agents/skills/sdd-done/SKILL.md` step 4.6.
  Both twins retain the verbatim `--force` guarantee, the refusal message, the
  `--dry-run` behaviour and the exploration-exclusion statement.
- Updated the doc-surface tests: `test_each_surface_invokes_verify_before_every_mutating_step`
  → `test_each_surface_invokes_the_gate_script`, and
  `test_each_surface_states_the_three_policy_literals_with_no_coercion` →
  `test_each_surface_branches_on_the_gate_exit_code`. The latter was replaced
  rather than kept because the policy literals now live in `resolve_policy()`;
  asserting them in markdown would force the prose to keep duplicating the very
  table this feature removes. The other three tests are unchanged.
- **Gotcha corrected from the task's Implementation Notes**: the task warned
  that `.agents/` might be git-ignored. It is not — `.claude/` is. The already-
  tracked `.claude/commands/sdd-done.md` needed `git add -f`; `.agents/` staged
  normally.
- **Negative test performed** (required by this task's Test Specification):
  reverting `SKILL.md` to its pre-change state turned the suite red
  (`test_each_surface_invokes_the_gate_script[SKILL.md]` failed), then the file
  was restored clean. The doc-surface tests do catch twin drift.
- **End-to-end smoke test** of the real gate, invoked exactly as the twins now
  specify:
  - `--spec sdd/specs/fixgroup-603217cacd87.spec.md --feat-id FEAT-703` (policy
    `none`) → exit 0, `{"status": "NONE", "allowed": true}`.
  - `--spec sdd/specs/agentic-e2e-testing.spec.md --feat-id FEAT-581` (policy
    `required`) → exit 1, `reason_codes: ["e2e_required_not_satisfied:MISSING",
    "evidence_pointer_missing"]`. That second reason code comes from the real
    `verify_evidence`, confirming the full integration path (not just the
    missing-plan short circuit) is exercised.
- Validation: `pytest tests/sdd_scripts/test_e2e_closeout_contract.py
  tests/sdd_scripts/test_check_e2e_closeout.py -q` → 44 passed; `ruff` and
  `black` clean.
