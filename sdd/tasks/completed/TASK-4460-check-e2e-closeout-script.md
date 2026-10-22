# TASK-4460: Closeout gate script `scripts/sdd/check_e2e_closeout.py`

**Feature**: FEAT-703 — Code-enforced E2E closeout gate for `/sdd-done`
**Spec**: `sdd/specs/fixgroup-603217cacd87.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:4b887b8e3ce0`

---

## Context

FEAT-581 AC9 claims "generic force cannot bypass required E2E", but the actual
closeout enforcement is ~80 lines of prose in `.claude/commands/sdd-done.md`
Step 4.6 that an agent is merely *asked* to follow. The complete, correct
decision table already exists as `evaluate_closeout_gate()` in
`tests/sdd_scripts/test_e2e_closeout_contract.py` (L68–113), proven by 15
behavioral tests against the real `parrot.e2e.evidence.verify_evidence` — but it
lives in a test file and so enforces nothing.

This task promotes that function into a real gate script. It is a **move, not a
redesign**: the decision table must behave identically.

---

## Scope

- CREATE `scripts/sdd/check_e2e_closeout.py` exposing `resolve_policy()`,
  `evaluate_closeout_gate()` and `main()` per the blueprint below.
- CREATE `tests/sdd_scripts/test_check_e2e_closeout.py` covering policy
  resolution, the structural absence of `force`, CLI exit codes, and the
  optional-install import guard.
- Copy the gate body **verbatim** from
  `tests/sdd_scripts/test_e2e_closeout_contract.py` L68–113, dropping only the
  `force` parameter and its `del force` line. Do not re-derive the reason-code
  strings — they are asserted by the 15 existing tests that TASK-4461 retargets.

**NOT in scope**:
- Editing `tests/sdd_scripts/test_e2e_closeout_contract.py` — TASK-4461 owns it.
  Leave its task-local copy of the function in place for now.
- Editing `.claude/commands/sdd-done.md` or `.agents/skills/sdd-done/SKILL.md` —
  TASK-4462 owns both.
- Any change to `parrot.e2e` (`verify_evidence`, models, errors, the CLI).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_e2e_closeout.py` | CREATE | The gate: policy resolution, decision table, CLI |
| `tests/sdd_scripts/test_check_e2e_closeout.py` | CREATE | Unit + CLI tests for the gate script |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.e2e.errors import E2EConfigError, E2EEvidenceError   # errors.py:63 (reason_code kwarg)
from parrot.e2e.evidence import verify_evidence                  # evidence.py:502
from parrot.e2e.models import VerificationResult                 # models.py:577
```
All three are imported **lazily, inside the gate** — `parrot.e2e` ships from
`ai-parrot-server`, an optional install.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/e2e/evidence.py:502
async def verify_evidence(plan_path: Path, *, worktree: Path) -> VerificationResult: ...

# packages/ai-parrot-server/src/parrot/e2e/models.py:577
class VerificationResult(_E2EBaseModel):
    status: _VerificationStatusLiteral   # line 590 — "PASS" | "FAIL" | "BLOCKED" | "MISSING"
    gate_satisfied: bool                 # line 591
    reason_codes: list[str]

# packages/ai-parrot-server/src/parrot/e2e/errors.py:63
def __init__(self, message: str, *, reason_code: Optional[str] = None) -> None: ...
```

### House pattern to follow
`scripts/sdd/check_task_state.py` — `main(argv) -> int`, `argparse`, human
output on stdout, module footer `if __name__ == "__main__": raise SystemExit(main())`.

### Does NOT Exist
- ~~`scripts/sdd/check_e2e_closeout.py`~~ — this task creates it
- ~~a public `parrot.e2e.evaluate_closeout_gate`~~ — the only copy is task-local
  in the test file
- ~~`VerificationResult.passed`~~ — the fields are `status` / `gate_satisfied`
- ~~a `force` parameter on `verify_evidence`~~ — it takes none
- ~~`parrot.e2e.evidence.verify_evidence` being importable everywhere~~ — it is
  an optional install; the import MUST be guarded

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "scripts/sdd/check_e2e_closeout.py", "action": "CREATE" },
    { "path": "tests/sdd_scripts/test_check_e2e_closeout.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/e2e/evidence.py#verify_evidence",
    "sym:packages/ai-parrot-server/src/parrot/e2e/models.py#VerificationResult",
    "sym:tests/sdd_scripts/test_e2e_closeout_contract.py#evaluate_closeout_gate"
  ]
}
```

---

## Implementation Notes

**Why a local `_GateResult` dataclass**: when `parrot.e2e` is not installed we
cannot construct a `VerificationResult`, but the gate still needs something with
`.status` / `.gate_satisfied` / `.reason_codes`. A tiny local dataclass gives the
two paths one duck-compatible shape, so the decision table below reads the same
either way.

**Why lazy imports**: a module-level `from parrot.e2e...` would make the script
unimportable — and untestable — anywhere `ai-parrot-server` is absent. The whole
point of the gate is that it fails *closed* with a reason code, never with a
traceback.

**Why no `force` parameter**: AC9's "generic force cannot bypass required E2E"
becomes structural. There is no argument to pass, so there is nothing to bypass.

---

## Implementation Blueprint

### Steps (in order)

1. Create `scripts/sdd/check_e2e_closeout.py` from the block below.
2. Copy the decision-table body verbatim from
   `tests/sdd_scripts/test_e2e_closeout_contract.py` L86–113 — do **not** retype
   the reason-code strings from memory; TASK-4461's 15 tests assert them exactly.
3. Create `tests/sdd_scripts/test_check_e2e_closeout.py` from the second block.
4. Run the Validation Commands; then `ruff check` and `black` both new files.

### Block 1 — `scripts/sdd/check_e2e_closeout.py` (CREATE)

```python
#!/usr/bin/env python
"""Code-enforced E2E evidence gate for the SDD closeout surfaces (FEAT-703).

Both `/sdd-done` twins invoke this before any stamp/push/PR/merge/cleanup step.
The decision table is the one proven in
``tests/sdd_scripts/test_e2e_closeout_contract.py`` against the real
``parrot.e2e.evidence.verify_evidence`` validator (FEAT-581 TASK-3543).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import yaml

_VALID_POLICIES = ("required", "optional", "none")
_GATED_POLICIES = ("required", "invalid")


@dataclass
class _GateResult:
    """Duck-compatible stand-in for ``VerificationResult`` (see Implementation Notes)."""

    status: str
    gate_satisfied: bool
    reason_codes: list[str] = field(default_factory=list)


def resolve_policy(spec_path: Path) -> str:
    """Return the spec's E2E policy, or ``invalid`` when it is malformed.

    A spec with no ``e2e`` key returns ``optional``. A present-but-malformed
    ``policy`` is NEVER coerced to a safe default -- it returns ``invalid``,
    which the gate treats exactly like ``required`` with missing evidence.
    """
    # FILL IN: parse YAML frontmatter from spec_path -- bounded by the exact
    # semantics in .claude/commands/sdd-done.md:209-220 (split on '---', 2;
    # yaml.safe_load; missing/unreadable file or absent `e2e` key -> "optional";
    # non-dict `e2e`, or a `policy` not in _VALID_POLICIES -> "invalid").


async def _verify(plan_path: Path, worktree: Path) -> Any:
    """Run the read-only validator, failing closed on absence or error."""
    try:
        from parrot.e2e.errors import E2EConfigError, E2EEvidenceError
        from parrot.e2e.evidence import verify_evidence
    except ImportError:
        # ai-parrot-server not installed: identical to MISSING evidence, never a pass.
        return _GateResult(status="MISSING", gate_satisfied=False, reason_codes=["e2e_validator_unavailable"])

    try:
        return await verify_evidence(plan_path, worktree=worktree)
    except (E2EEvidenceError, E2EConfigError) as exc:
        # Fails closed exactly like a synthesized BLOCKED VerificationResult:
        # a malformed/tampered/stale evidence blob is never treated as PASS.
        return _GateResult(
            status="BLOCKED", gate_satisfied=False, reason_codes=[exc.reason_code or "evidence_error"]
        )


async def evaluate_closeout_gate(
    *, policy: str, plan_path: Optional[Path], worktree: Path
) -> tuple[bool, list[str]]:
    """Return ``(allowed, reason_codes)`` for a feature's E2E closeout gate.

    Accepts no ``force`` argument by construction: FEAT-581 AC9's "generic force
    cannot bypass required E2E" is structural here, not merely documented.
    """
    # FILL IN: copy L86-113 of tests/sdd_scripts/test_e2e_closeout_contract.py
    # verbatim, replacing the inline try/except around verify_evidence with
    # `result = await _verify(plan_path, worktree)` -- bounded by AC1 (identical
    # outcomes) and the reason-code strings TASK-4461's tests assert.
```

**Why**: the gate is split into `_verify` (I/O + failure synthesis) and
`evaluate_closeout_gate` (pure decision) so the 15 existing behavioral tests can
drive the decision table directly, exactly as they do today.

### Block 2 — `scripts/sdd/check_e2e_closeout.py` CLI tail (same file, appended)

```python
def main(argv: Optional[Sequence[str]] = None) -> int:
    """Exit 0 when closeout may proceed, 1 when it must abort."""
    parser = argparse.ArgumentParser(description="Gate SDD closeout on validated E2E evidence.")
    parser.add_argument("--spec", type=Path, required=True, help="Path to the feature's spec file.")
    parser.add_argument("--feat-id", required=True, help="FEAT-<NNN>, used to locate the plan.")
    parser.add_argument("--worktree", type=Path, required=True, help="Feature worktree to validate against.")
    args = parser.parse_args(argv)

    policy = resolve_policy(args.spec)
    plan_path = args.worktree / "sdd" / "state" / args.feat_id / "e2e-plan.md"
    allowed, reason_codes = asyncio.run(
        evaluate_closeout_gate(policy=policy, plan_path=plan_path, worktree=args.worktree)
    )
    # FILL IN: derive `status` and `gate_satisfied` for the JSON payload --
    # bounded by AC3 (stdout is a single JSON object carrying policy, status,
    # gate_satisfied, reason_codes). Prefer threading them out of the gate over
    # re-parsing reason_codes.
    print(json.dumps({"policy": policy, "reason_codes": reason_codes, "allowed": allowed}))
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

**Why**: a binary exit code keeps the caller's control flow trivial (`0` =
proceed, `1` = abort) while the 4-way status the twins report to the user rides
along in the JSON — the twins must never have to map a status onto a decision
themselves, which is the prose-interpretation failure this feature removes.

### Block 3 — `tests/sdd_scripts/test_check_e2e_closeout.py` (CREATE)

```python
"""Unit and CLI contract for the FEAT-703 closeout gate script."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from scripts.sdd.check_e2e_closeout import evaluate_closeout_gate, main, resolve_policy


def test_gate_has_no_force_parameter() -> None:
    """AC2: force is structurally absent, so nothing can bypass the gate."""
    assert "force" not in inspect.signature(evaluate_closeout_gate).parameters


# FILL IN: the remaining cases -- bounded by §4 of the spec, one test each:
#   - resolve_policy: no `e2e` key -> "optional"
#   - resolve_policy: malformed value -> "invalid" (never coerced)
#   - resolve_policy: each of required/optional/none round-trips
#   - main(): exit 0 + JSON on stdout when the gate allows (policy none is the
#     cheapest allow path -- it never reads a plan)
#   - main(): exit 1 when policy is required and the plan file is absent
#   - _verify(): an unimportable parrot.e2e yields MISSING +
#     "e2e_validator_unavailable" and raises nothing (monkeypatch the import)
```

**Why**: these cover what the existing contract suite does not — policy parsing,
the CLI boundary and the optional-install guard. The decision table itself stays
covered by the 15 behavioral tests TASK-4461 retargets, so do not duplicate them
here.

### FILL IN checklist

- [ ] `resolve_policy` frontmatter parsing (Block 1)
- [ ] `evaluate_closeout_gate` body copied verbatim from the test file (Block 1)
- [ ] `status` / `gate_satisfied` threaded into the JSON payload (Block 2)
- [ ] Six remaining test cases (Block 3)

---

## Acceptance Criteria

- [ ] `scripts/sdd/check_e2e_closeout.py` exists with `resolve_policy`,
      `evaluate_closeout_gate` and `main`, and implements the spec §3 decision
      table with outcomes identical to the function it is moved from.
- [ ] `evaluate_closeout_gate` accepts no `force` parameter; a test asserts this
      by signature introspection.
- [ ] `main()` returns 0 when closeout may proceed and 1 when it must abort, and
      prints a single JSON object with `policy`, `status`, `gate_satisfied` and
      `reason_codes`.
- [ ] An unimportable `parrot.e2e` is reported as `MISSING` with
      `e2e_validator_unavailable` — no traceback, never a pass.
- [ ] `resolve_policy` returns `optional` for an absent `e2e` key and `invalid`
      for a malformed `policy`, never coercing to a safe default.
- [ ] `ruff check` and `black --check` clean on both new files.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_check_e2e_closeout.py -q`

---

## Test Specification

The deliverable includes its own tests (Block 3). They must pass with
`ai-parrot-server` installed **and** the import-guard case must pass when the
import is monkeypatched to fail. Do not add cases that duplicate the 15
behavioral tests in `test_e2e_closeout_contract.py` — TASK-4461 retargets those
at this same function.

---

## Agent Instructions

1. Read `tests/sdd_scripts/test_e2e_closeout_contract.py` L59–113 and
   `scripts/sdd/check_task_state.py` (tail) before writing code.
2. Create only the two files listed. Follow the Codebase Contract verbatim.
3. Copy the gate body verbatim — do not re-derive reason codes.
4. Run the Validation Command, then `ruff check` and `black`.
5. Commit only the two new files:
   `feat(sdd): TASK-4460 — code-enforced E2E closeout gate script`.

---

## Completion Note

**Completed by**: sdd-fix (Claude)
**Status**: done

- Created `scripts/sdd/check_e2e_closeout.py` with `resolve_policy`,
  `evaluate_closeout_gate`, `evaluate_closeout_gate_detailed` and `main`.
  The decision table was moved verbatim from
  `tests/sdd_scripts/test_e2e_closeout_contract.py` L86–113; reason-code
  strings are unchanged, which TASK-4461's 15 retargeted tests confirm.
- **Design refinement over the blueprint**: the blueprint left a `FILL IN` for
  threading `status`/`gate_satisfied` into the JSON payload. Rather than
  re-parsing reason codes or validating twice, the gate was split into
  `evaluate_closeout_gate_detailed()` (returns a `GateDecision` dataclass with
  allowed/policy/status/gate_satisfied/reason_codes) and the original 2-tuple
  `evaluate_closeout_gate()` as a thin wrapper. The 15 existing tests keep
  calling the tuple form unchanged; `main()` uses the detailed form. No
  duplicated decision logic.
- Synthetic statuses for the non-validator paths: `NONE` for `policy: none`,
  `MISSING` when no plan file exists.
- **Lint finding worth recording**: `ruff` raised `ASYNC240` on
  `plan_path.is_file()` inside the async gate — a blocking pathlib call on the
  event loop that the original test-local function also had (tests aren't linted
  under that rule). Fixed properly with
  `await asyncio.to_thread(plan_path.is_file)` rather than a `noqa`.
- Created `tests/sdd_scripts/test_check_e2e_closeout.py` (19 tests): policy
  resolution incl. 4 malformed-value cases, signature introspection proving
  `force` is absent from both gate functions, 5 CLI exit-code/JSON cases, the
  import-guard path (monkeypatched `builtins.__import__`), and wrapper parity.
- Validation: `pytest tests/sdd_scripts/test_check_e2e_closeout.py -q` → 19
  passed; `ruff check` and `black --check` clean on both files.
