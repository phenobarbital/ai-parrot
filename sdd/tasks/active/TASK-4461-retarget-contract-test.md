# TASK-4461: Retarget the closeout contract test at the real gate

**Feature**: FEAT-703 — Code-enforced E2E closeout gate for `/sdd-done`
**Spec**: `sdd/specs/fixgroup-603217cacd87.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-4460
**Assigned-to**: unassigned

**Discovered-from**: `issue:4b887b8e3ce0`

---

## Context

`tests/sdd_scripts/test_e2e_closeout_contract.py` currently defines its own
`evaluate_closeout_gate()` (L68–113) and proves *that* against the real
`verify_evidence`. The function is correct, but it is a test-local
reimplementation — so the suite certifies a copy, not the shipped gate. That is
precisely the gap `issue:4b887b8e3ce0` reports.

TASK-4460 moved the function into `scripts/sdd/check_e2e_closeout.py`. This task
deletes the copy and points the 15 behavioral tests at the real one.

**Keeping both copies silently re-creates the gap this feature exists to close.**

---

## Scope

- Delete the task-local `evaluate_closeout_gate` (L68–113) and its explanatory
  comment banner (L59–66) from `tests/sdd_scripts/test_e2e_closeout_contract.py`.
- Import the real gate instead:
  `from scripts.sdd.check_e2e_closeout import evaluate_closeout_gate`.
- Drop the now-absent `force` argument from every call site. The one test
  parametrized over `force` (`test_required_policy_blocks_on_missing_evidence_regardless_of_force`,
  L296) is rewritten to assert force's *structural* absence instead of passing it.
- Keep all 15 behavioral test bodies otherwise unchanged — same fixtures, same
  on-disk evidence artifacts, same assertions.
- Update the module docstring (L1–17), which currently describes the function as
  task-local, to say the suite now exercises the shipped gate.

**NOT in scope**:
- The 5 `test_each_surface_*` doc-surface tests (L488–521) — TASK-4462 owns them,
  because they assert what the twins say and the twins do not change until then.
- `.claude/commands/sdd-done.md` / `.agents/skills/sdd-done/SKILL.md`.
- `scripts/sdd/check_e2e_closeout.py` — if a behavioral test fails against it,
  the script is wrong; report the drift rather than weakening the test.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_e2e_closeout_contract.py` | MODIFY | Import the real gate; delete the local copy; drop `force` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.check_e2e_closeout import evaluate_closeout_gate  # created by TASK-4460
```

### Existing Signatures to Use
```python
# scripts/sdd/check_e2e_closeout.py  (TASK-4460)
async def evaluate_closeout_gate(
    *, policy: str, plan_path: Optional[Path], worktree: Path
) -> tuple[bool, list[str]]: ...
# NOTE: no `force` parameter -- that is the point of the change.
```

### Existing structure being edited (verified at `c26bf74bf`)
```python
# tests/sdd_scripts/test_e2e_closeout_contract.py
# L59-66   comment banner describing the task-local function  -> DELETE
# L68-113  async def evaluate_closeout_gate(..., force: bool) -> DELETE
# L284-486 the 15 behavioral tests                            -> keep, drop `force` args
# L488-521 the 5 test_each_surface_* doc tests                -> DO NOT TOUCH (TASK-4462)
```
These imports stay — the tests still build real evidence with them:
```python
from parrot.e2e.errors import E2EConfigError, E2EEvidenceError        # L42
from parrot.e2e.evidence import capture_identity, verify_evidence     # L43
from parrot.e2e.models import E2EVerdict, ScenarioResult, SourceIdentity, VerificationResult  # L44
from parrot.e2e.plan import load_plan                                 # L45
```

### Does NOT Exist
- ~~`evaluate_closeout_gate(..., force=...)`~~ — the real gate takes no `force`
- ~~`parrot.e2e.evaluate_closeout_gate`~~ — the gate lives in `scripts/sdd/`, not in `parrot.e2e`
- ~~`VerificationResult.passed`~~ — the fields are `status` / `gate_satisfied`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "tests/sdd_scripts/test_e2e_closeout_contract.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:tests/sdd_scripts/test_e2e_closeout_contract.py#evaluate_closeout_gate",
    "sym:packages/ai-parrot-server/src/parrot/e2e/evidence.py#verify_evidence"
  ]
}
```

---

## Implementation Notes

**Why the `force` parametrization is rewritten, not deleted**: that test is the
only place AC9's "generic force cannot bypass required E2E" is asserted. Deleting
it would lose the claim entirely. Replacing a runtime `force=True/False` sweep
with a signature assertion makes the claim *stronger* — force cannot be passed
at all — while keeping the missing-evidence blocking assertion it also carried.

**Import path**: `scripts/` is imported as a package elsewhere in this suite
(`python -m scripts.sdd.*`), and `scripts/sdd/__init__.py` exists, so a plain
`from scripts.sdd.check_e2e_closeout import ...` resolves from the repo root.
Verify this runs from the repo root before assuming a `sys.path` shim is needed —
the file already inserts `packages/ai-parrot-server/src` (L38–40) for a different
reason and that line stays.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4460 landed: `scripts/sdd/check_e2e_closeout.py` exists and
   `pytest tests/sdd_scripts/test_check_e2e_closeout.py -q` is green.
2. Replace the import block and delete the local function (Block 1).
3. Sweep every `evaluate_closeout_gate(` call site, removing `force=...`.
4. Rewrite the force-parametrized test (Block 2).
5. Update the module docstring to describe the new arrangement.
6. Run the Validation Command; `ruff check` and `black`.

### Block 1 — import swap and deletion

```python
# AFTER — replace lines 59-113 (the banner + the whole local function)
# occurrences: 1 (verified: grep -c '^async def evaluate_closeout_gate($' tests/sdd_scripts/test_e2e_closeout_contract.py)
#
# Add to the import block near L45, after the parrot.e2e imports:
from scripts.sdd.check_e2e_closeout import evaluate_closeout_gate  # noqa: E402

# ...and delete L59-113 entirely (the "Task-local closeout decision function"
# banner and the async def it introduces). Nothing replaces them in-place.
```

**Why**: the deletion *is* the deliverable. Leaving the local copy — even
renamed or unused — means the suite can still pass while the shipped gate is
broken, which is exactly the failure mode `issue:4b887b8e3ce0` describes.

### Block 2 — rewrite the force test

```python
# AFTER — replaces the body at tests/sdd_scripts/test_e2e_closeout_contract.py:296
# occurrences: 1 (verified: grep -c 'test_required_policy_blocks_on_missing_evidence_regardless_of_force')
async def test_required_policy_cannot_be_bypassed_by_force(git_worktree: Path) -> None:
    """AC9: force is structurally unable to reach the gate, and missing
    evidence still blocks under `required`."""
    import inspect

    assert "force" not in inspect.signature(evaluate_closeout_gate).parameters
    # FILL IN: keep this test's original missing-evidence arrangement and assert
    # `allowed is False` -- bounded by the pre-change body at L296-305; drop only
    # the @pytest.mark.parametrize("force", ...) decorator and the force= kwarg.
```

**Why**: pairing the structural assertion with the original blocking assertion
keeps both halves of AC9 in one place — force cannot be supplied, *and* the
`required` policy still refuses missing evidence.

### FILL IN checklist

- [ ] Original missing-evidence arrangement preserved in the rewritten force test
- [ ] Every other `evaluate_closeout_gate(` call site has `force=` removed
- [ ] Module docstring (L1–17) updated to describe the shipped-gate arrangement

---

## Acceptance Criteria

- [ ] `tests/sdd_scripts/test_e2e_closeout_contract.py` imports
      `evaluate_closeout_gate` from `scripts.sdd.check_e2e_closeout`.
- [ ] The task-local definition (L68–113) and its banner are **gone** — a repo
      grep finds exactly one definition of the function, in `scripts/sdd/`.
- [ ] All 15 behavioral tests pass unchanged in substance against the real gate.
- [ ] AC9's force claim is asserted by signature introspection, and the
      missing-evidence blocking assertion it carried is retained.
- [ ] The 5 `test_each_surface_*` tests are untouched and still pass.
- [ ] `ruff check` and `black --check` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`

---

## Test Specification

No new behavioral cases. The bar is that the existing 15 pass against the real
gate with no weakening: if one fails, fix `scripts/sdd/check_e2e_closeout.py`
(report it — it means TASK-4460's move was not faithful), never the assertion.

---

## Agent Instructions

1. Read L1–120 and L284–310 of the test file before editing.
2. Modify only the one file listed.
3. If a behavioral test fails, the script is wrong — record the drift in the
   Completion Note rather than relaxing the test.
4. Commit only that file:
   `test(sdd): TASK-4461 — retarget closeout contract at the real gate`.

---

## Completion Note

*(to be filled in on completion)*
