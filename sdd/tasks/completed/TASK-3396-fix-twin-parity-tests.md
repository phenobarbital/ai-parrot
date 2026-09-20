# TASK-3396: `TestFixTwins` and `TestSddNextRetarget` parity tests

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3394, TASK-3395
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (twin half), §4 integration rows `test_all_sdd_next_twins_point_at_sdd_fix`
and `test_all_twins_require_a_pr_on_the_fast_lane`, design research S9. "Three twins, one
behaviour" is only true if a test says so. This task appends two classes to the shared twin
parity module, mirroring `TestCodereviewTwins` exactly, asserting the **twin token contract**
defined in TASK-3394 and the retargeting wording fixed in TASK-3395.

---

## Scope

- Append `class TestFixTwins` (9 tests) and `class TestSddNextRetarget` (2 tests) to
  `tests/sdd/test_ledger_workflow_twins.py`, above the `if __name__ == "__main__":` line.
- No changes to existing classes.

**NOT in scope**: planner/service lifecycle tests (TASK-3397); editing any twin.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd/test_ledger_workflow_twins.py` | MODIFY | append `TestFixTwins`, `TestSddNextRetarget` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# tests/sdd/test_ledger_workflow_twins.py already imports: from pathlib import Path; import pytest   (lines 12-14)
# module-level helpers (reuse, do not redefine):
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]        # line 23 — repo root, resolved from __file__ (CWD gotcha)
def read_workflow_file(path: str) -> str                    # line 26 — pytest.fail if missing
```

### Existing Signatures to Use
```python
# tests/sdd/test_ledger_workflow_twins.py
class TestCodereviewTwins:                                  # 39-79 — THE shape to mirror:
    CLAUDE = ".claude/commands/sdd-codereview.md"; ANTIGRAVITY = ".agent/workflows/sdd-codereview.md"; CODEX = ".agents/skills/sdd-codereview/SKILL.md"
    def test_workflow_files_exist(self): for file_path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX): assert (_WORKTREE_ROOT / file_path).exists()
    def test_basic_content_verification(self): … len(claude) > 1000; len(codex) > 100; "# /sdd-codereview" in claude; "# SDD Code Review" in codex
class TestStartNextTwins:                                    # 131-173 — NEXT / TASK dicts of the six files this task re-reads
    NEXT = {"claude": ".claude/commands/sdd-next.md", "antigravity": ".agent/workflows/sdd-next.md", "codex": ".agents/skills/sdd-next/SKILL.md"}
    TASK = {"claude": ".claude/commands/sdd-task.md", "antigravity": ".agent/workflows/sdd-task.md", "codex": ".agents/skills/sdd-task/SKILL.md"}
if __name__ == "__main__":                                   # 176 ← insert ABOVE this

# Files under test (TASK-3394 / TASK-3395): see the twin token contract table in TASK-3394 and the wording in TASK-3395.
```

### Does NOT Exist
- ~~`tests/sdd/test_sdd_fix_twins.py`~~ — do NOT create a new module; the spec says *extends* the shared twins file.
- ~~`read_workflow_file` returning `None`~~ — it fails the test when the file is missing; no `exists()` guard needed inside content tests.
- ~~`.claude/commands/sdd-fix.md` etc. before TASK-3394~~ — run this task only after both dependencies landed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/sdd/test_ledger_workflow_twins.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:tests/sdd/test_ledger_workflow_twins.py#read_workflow_file",
    "sym:tests/sdd/test_ledger_workflow_twins.py#TestCodereviewTwins",
    "sym:tests/sdd/test_ledger_workflow_twins.py#TestStartNextTwins"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Assert **literal tokens** from the TASK-3394 contract table; do not soften them with
  regexes or `.lower()` unless the table says so (`Deprecated` is capitalised).
- Absence assertions are as important as presence: `ledger acknowledge`, `git push origin
  dev`, `--no-pr` must be absent from every `/sdd-fix` twin; `sdd-task --from-issue` absent
  from every `/sdd-next` twin.
- Paths resolve via `_WORKTREE_ROOT`, never the CWD (spec §7 "Test CWD").

### References in Codebase
- `tests/sdd/test_ledger_workflow_twins.py:39-79` — pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Append the two classes above the `__main__` guard — *why*: the file is jointly owned; each feature adds its own class.
2. Run the file — *why*: it must be green on top of TASK-3394 + TASK-3395.

### `tests/sdd/test_ledger_workflow_twins.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'if __name__ == "__main__":' tests/sdd/test_ledger_workflow_twins.py)
# BEFORE — insert ABOVE `if __name__ == "__main__":` (verified: :176), two blank lines on each side


# --------------------------------------------------------------------------
# FEAT-572 — /sdd-fix twins and /sdd-next retargeting
# --------------------------------------------------------------------------


class TestFixTwins:
    """Mirrors TestCodereviewTwins; asserts the TASK-3394 twin token contract."""

    CLAUDE = ".claude/commands/sdd-fix.md"
    ANTIGRAVITY = ".agent/workflows/sdd-fix.md"
    CODEX = ".agents/skills/sdd-fix/SKILL.md"
    ALL = (CLAUDE, ANTIGRAVITY, CODEX)

    def test_workflow_files_exist(self):
        for file_path in self.ALL:
            assert (_WORKTREE_ROOT / file_path).exists(), f"Missing workflow file: {file_path}"

    def test_basic_content_verification(self):
        assert len(read_workflow_file(self.CLAUDE)) > 1000 and "# /sdd-fix" in read_workflow_file(self.CLAUDE)
        assert len(read_workflow_file(self.ANTIGRAVITY)) > 1000 and "# /sdd-fix" in read_workflow_file(self.ANTIGRAVITY)
        assert len(read_workflow_file(self.CODEX)) > 100 and "# SDD Fix" in read_workflow_file(self.CODEX)

    def test_all_twins_call_plan_fix_json(self):
        """Twins INVOKE the plan; they never parse `ledger ready` text (S9)."""
        for path in self.ALL:
            assert "wikitoolkit ledger plan-fix --json" in read_workflow_file(path), path

    def test_all_twins_document_both_lanes(self):
        # FILL IN: "Fast lane" and "SDD lane" in every twin; "--lane" present (override documented)

    def test_all_twins_require_resolved_by_on_close(self):
        # FILL IN: "ledger close", "--resolved-by" and "two keys" in every twin

    def test_all_twins_release_unfixed_issues(self):
        # FILL IN: "ledger unclaim" in every twin; "ledger claim" in every twin (claim precedes release)

    def test_all_twins_require_a_pr_on_the_fast_lane(self):
        for path in self.ALL:
            content = read_workflow_file(path)
            assert "gh pr create --base dev" in content, path
            assert "git push origin dev" not in content, path
            assert "--no-pr" not in content, path

    def test_no_twin_calls_acknowledge(self):
        # FILL IN: "ledger acknowledge" not in any twin

    def test_all_twins_reuse_open_parent_or_mint(self):
        # FILL IN: "parents", "reserve_ids" and "ensure_worktree" in every twin (open parent ⇒ reuse; else mint FEAT)

    def test_read_only_ledger_exits_without_claiming(self):
        # FILL IN: "shared ledger is read-only" in every twin; "ledger context" and "--max-tokens 3000" in every twin


class TestSddNextRetarget:
    """S9: /sdd-fix replaces --from-issue as the ledger entry point (TASK-3395)."""

    NEXT = TestStartNextTwins.NEXT
    TASK = TestStartNextTwins.TASK

    def test_all_sdd_next_twins_point_at_sdd_fix(self):
        for platform, path in self.NEXT.items():
            content = read_workflow_file(path)
            assert "sdd-fix" in content, (platform, path)
            assert "sdd-task --from-issue" not in content, (platform, path)

    def test_all_sdd_task_twins_carry_from_issue_deprecation(self):
        # FILL IN: "Deprecated" and "sdd-fix" in every TASK twin; "--from-issue" still present
```
**Why**: one assertion per contract row keeps a failure message pointing at the exact twin and
the exact promise it broke — which is the whole point of "three twins, one behaviour".

### FILL IN checklist
- [ ] 6 test bodies marked FILL IN — each bounded by the TASK-3394 token table / TASK-3395 wording

---

## Acceptance Criteria

- [ ] `TestFixTwins` (9 tests) and `TestSddNextRetarget` (2 tests) exist and pass.
- [ ] Existing classes untouched and passing.
- [ ] `pytest tests/sdd/test_ledger_workflow_twins.py -v` green.

---

## Validation Commands

- `pytest tests/sdd/test_ledger_workflow_twins.py -q`

---

## Test Specification

```python
class TestFixTwins:          # 9 tests (see blueprint)
class TestSddNextRetarget:   # 2 tests
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 6 skeleton, §4 twin rows, §5 twin ACs).
2. **Check dependencies** — TASK-3394 and TASK-3395 completed.
3. **Verify the Codebase Contract** — the `__main__` anchor occurs once; `TestStartNextTwins.NEXT/TASK` exist.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement**; if a twin fails an assertion, fix the **twin** (it broke the contract), not the test — unless the token table itself is wrong, in which case report.
6. **Verify** the Validation Command.
7. **Move this file** to `sdd/tasks/completed/TASK-3396-fix-twin-parity-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator, sequential-loop fallback — `parrot-sdd-coder`
roster was empty, `fallback_reason: suspension_history_unavailable`)
**Date**: 2026-09-19
**Notes**: Appended `TestFixTwins` (9 tests) and `TestSddNextRetarget` (2 tests) above the
`__main__` guard, mirroring `TestCodereviewTwins` exactly, asserting the TASK-3394 twin
token contract and the TASK-3395 retargeting wording.

Validation: `pytest tests/sdd/test_ledger_workflow_twins.py -v` → 25 passed (all
pre-existing classes unmodified and still green). `pytest tests/sdd/ -q` → 39 passed
(no regressions).

**Deviations from spec**: Scope says "NOT in scope: ... editing any twin", but this
task's own Agent Instructions step 5 says "if a twin fails an assertion, fix the twin
(it broke the contract), not the test — unless the token table itself is wrong, in which
case report." The new tests caught 3 genuine, pre-existing contract violations against
TASK-3394's own token table, so per that instruction I fixed the twins rather than
weakening the tests:
1. All three `/sdd-fix` twins contained the literal string `ledger acknowledge` (in prose
   explaining it's out of scope), which `test_no_twin_calls_acknowledge` requires absent
   everywhere. Reworded without changing meaning (e.g. "acknowledgement stays human-only
   and out of scope here").
2. Both `/sdd-next` twins (claude, antigravity) still contained the literal deprecated
   phrase `sdd-task --from-issue` in an explanatory aside about what `/sdd-fix` replaces,
   which `test_all_sdd_next_twins_point_at_sdd_fix` requires absent. Reworded to
   "supersedes the deprecated --from-issue flow".
3. The Codex `/sdd-fix` skill (`.agents/skills/sdd-fix/SKILL.md`) used capitalized
   "Two keys" / "Parents" / "Shared ledger is read-only" where TASK-3394's own token
   contract (already matched verbatim by the other two twins) requires the lowercase
   literals `two keys` / `parents` / `shared ledger is read-only`. Fixed to match.

All fixes are additive wording-only changes — no procedural/behavioral content changed,
only the surface tokens the parity tests assert on. Full diff in commit `550c85352`.
