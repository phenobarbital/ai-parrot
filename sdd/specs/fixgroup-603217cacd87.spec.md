---
type: feature
base_branch: dev
projects: [sdd-tooling, ai-parrot-server]
tags: [sdd-done, e2e, closeout-gate, feat-581]
# This feature changes the E2E gate itself; it has no E2E *targets* of its own
# (no mcp-stdio/botmanager fixture is exercised). Its verification is ordinary
# pytest over tests/sdd_scripts/, so the policy is an explicit `none` rather
# than an omitted key that would default to `optional`.
e2e:
  policy: none
  scenario_ids: []
---

# Feature Specification: Code-enforced E2E closeout gate for `/sdd-done`

**Feature ID**: FEAT-703
**Date**: 2026-10-19
**Author**: sdd-fix (Claude)
**Status**: approved
**Target version**: 0.29.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:4b887b8e3ce0` (major, `feature_gap`, found in the FEAT-581 /
TASK-3543 code review):

> FEAT-581 AC9 states "Claude/Codex closeout checks the same evidence contract
> before mutations; generic force cannot bypass required E2E." The actual
> enforcement lives entirely in markdown instructions
> (`.claude/commands/sdd-done.md` Step 4.6, `.agents/skills/sdd-done/SKILL.md`
> step 4.5) telling the executing agent to abort — not in a code invariant.

Three facts make this worth fixing rather than documenting away:

1. **The decision table already exists and is already proven.**
   `evaluate_closeout_gate()` in `tests/sdd_scripts/test_e2e_closeout_contract.py`
   (L68–113) implements the complete required/optional/none/invalid table and is
   exercised by 15 behavioral tests against the *real*
   `parrot.e2e.evidence.verify_evidence` with on-disk evidence artifacts — never
   a mock. It is labelled a "task-local" reimplementation only because TASK-3543's
   Fixed Interfaces forbade it from publishing a cross-task signature.
2. **The production path is prose.** Step 4.6 is ~80 lines of narrative plus
   inline `python -c`/`jq` bash the agent is *asked* to run and interpret. An agent
   that misreads, truncates or skips it proceeds to stamp, push, PR, merge and
   clean up. There is no invariant, only an instruction.
3. **The contrast is already in-tree.** The dev-loop QA node ANDs the same gate
   into `passed` in real Python (`packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`),
   so AC10 is solidly enforced while AC9 is not.

A prior `/sdd-fix` run released this issue as "code enforcement requires new
feature design, not a quick fix". That judgement predates the observation in (1):
the design is not new, it is a *promotion* of proven code out of a test file.

### Goals

- Make the closeout E2E gate a **code invariant**: one script whose exit code
  decides whether closeout may mutate anything, rather than prose an agent must
  interpret.
- Keep exactly the decision table already proven by the 15 behavioral tests —
  this feature changes *where the table lives*, never *what it decides*.
- Retarget the contract test at the real production function so the suite stops
  proving a reimplementation and starts proving the shipped gate.
- Preserve the structural guarantee that `--force` cannot reach the gate: the
  gate takes no force parameter, so there is nothing to bypass.

### Non-Goals (explicitly out of scope)

- Changing `verify_evidence` itself. It is sound, read-only, takes no `force`,
  and stays untouched.
- Changing what `parrot e2e verify` does, its exit codes, or the evidence format.
- Rewording FEAT-581's AC9 (the alternative resolution the issue offered; the
  user chose code enforcement instead, so AC9's existing wording becomes true).
- Enforcing any *other* `/sdd-done` gate (task state, lint, merge blockers).
  Those remain prose-level, exactly as today — this feature does not set a
  precedent obligation to convert them.
- Making `ai-parrot-server` a hard dependency of the SDD tooling.

---

## 2. Architectural Design

### Overview

Promote the proven decision function into `scripts/sdd/check_e2e_closeout.py`,
a standalone gate script following the established `scripts/sdd/check_*.py`
house pattern (`check_task_state.py`, `check_task_graph.py`,
`check_id_collisions.py`): `main(argv) -> int`, argparse, human-readable stdout,
`raise SystemExit(main())`.

Both closeout twins then collapse their ~80 lines of prose into a single
invocation whose exit code is not open to interpretation.

```
/sdd-done Step 4.6  ──invoke──→  scripts/sdd/check_e2e_closeout.py
.agents/…/SKILL.md step 4.5 ─┘          │
                                        ├─ read spec frontmatter e2e.policy
                                        ├─ resolve plan path
                                        ├─ parrot.e2e.evidence.verify_evidence()
                                        └─ decision table → exit 0 | 1
                                                   ▲
tests/sdd_scripts/test_e2e_closeout_contract.py ───┘ (imports the REAL gate)
```

### Key design decisions

**In-process validation, not a `parrot e2e verify` subprocess.** The current
prose shells out to the CLI and parses stdout with `jq`. The script instead
calls `verify_evidence` directly — which is what the 15 proven tests already do.
This removes the `jq` dependency and the "stdout is not valid JSON" failure mode
entirely, and makes the script's behaviour identical to the behaviour the tests
certify.

**Optional-install tolerance.** `parrot.e2e` ships from `ai-parrot-server`, an
optional install. A failed import is treated exactly like `MISSING` evidence —
the same fail-closed outcome the prose already specifies for "CLI unavailable".
It must never crash the gate with a traceback and must never be read as a pass.

**No `force` parameter anywhere.** The gate's signature omits force entirely, so
the "generic force cannot bypass required E2E" claim becomes structural rather
than documented. `--force` keeps its real scope (per-task partial evidence in
Step 6, ledger merge blockers in Step 9) untouched.

**Binary exit code, rich JSON.** Exit `0` = closeout may proceed (covers `none`
exempt, `optional` advisory, and `required` satisfied); exit `1` = abort. The
nuance the twins report to the user (`E2E: <policy> — <status>`) travels in the
JSON payload on stdout, not in the exit code, so callers never have to map a
4-way status onto control flow themselves.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.e2e.evidence.verify_evidence` | calls | read-only validator, unchanged |
| `parrot.e2e.models.VerificationResult` | consumes | `status` / `gate_satisfied` / `reason_codes` |
| `parrot.e2e.errors.E2EEvidenceError`, `E2EConfigError` | catches | → synthesized `BLOCKED`, fail-closed |
| `.claude/commands/sdd-done.md` Step 4.6 | replaces prose | single invocation + exit-code branch |
| `.agents/skills/sdd-done/SKILL.md` step 4.5 | replaces prose | Codex twin, same invocation |
| `tests/sdd_scripts/test_e2e_closeout_contract.py` | retargets | imports the real gate |

### New Public Interfaces

```python
# scripts/sdd/check_e2e_closeout.py  (new)

async def evaluate_closeout_gate(
    *, policy: str, plan_path: Optional[Path], worktree: Path
) -> tuple[bool, list[str]]:
    """Return ``(allowed, reason_codes)`` for a feature's E2E closeout gate.

    Accepts no ``force`` argument by construction: FEAT-581 AC9's "generic
    force cannot bypass required E2E" is structural here, not documented.
    """


def resolve_policy(spec_path: Path) -> str:
    """Return ``required``/``optional``/``none``, or ``invalid`` when the spec's
    ``e2e.policy`` is present but malformed.

    A spec with no ``e2e`` key at all returns ``optional``; a malformed value is
    never coerced to a safe default (it is gated exactly like ``required``).
    """


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Exit 0 when closeout may proceed, 1 when it must abort."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Gate script | yes | Decision table is a verbatim move of a proven function; signatures fixed above; house pattern fixed by `check_task_state.py` | — |
| M2: Closeout twin rewiring | yes | Exact invocation + exit-code branch fixed in §7; both files edited identically | — |
| M3: Contract test retarget | yes | Import swap; 15 existing tests keep their bodies; new CLI tests enumerated in §4 | — |

### Module 1: Closeout gate script
- **Path**: `scripts/sdd/check_e2e_closeout.py` (CREATE)
- **Responsibility**: Resolve the spec's E2E policy, locate the plan, run the
  read-only validator, apply the decision table, emit JSON on stdout and return
  the process exit code.
- **Depends on**: `parrot.e2e` (optional install, import guarded)
- **Interface Skeleton**:
  ```python
  # scripts/sdd/check_e2e_closeout.py  (new)
  async def evaluate_closeout_gate(
      *, policy: str, plan_path: Optional[Path], worktree: Path
  ) -> tuple[bool, list[str]]:
      """Return (allowed, reason_codes); takes no `force` by construction."""

  def resolve_policy(spec_path: Path) -> str:
      """`required`|`optional`|`none`, or `invalid` for a malformed value."""

  def main(argv: Optional[Sequence[str]] = None) -> int:
      """Exit 0 = proceed, 1 = abort closeout."""
  ```
- **Decision table** (unchanged from the proven original):

  | Policy | Plan / evidence state | Result |
  |---|---|---|
  | `none` | never read | allow — `e2e_policy_none` |
  | `optional` | no plan file | allow — `e2e_optional_no_plan` |
  | `optional` | any status, incl. FAIL/BLOCKED/tampered | allow (advisory, reported honestly) |
  | `required` / `invalid` | no plan file | **abort** — `e2e_required_missing_plan` |
  | `required` / `invalid` | `PASS` **and** `gate_satisfied` | allow — `e2e_required_satisfied` |
  | `required` / `invalid` | anything else | **abort** — `e2e_required_not_satisfied:<status>` |
  | `required` / `invalid` | validator raised `E2E*Error` | **abort** — synthesized `BLOCKED`, fail-closed |
  | any non-`none` | `parrot.e2e` not importable | treated as `MISSING` (abort under required) |

### Module 2: Closeout twin rewiring
- **Path**: `.claude/commands/sdd-done.md` (Step 4.6) and
  `.agents/skills/sdd-done/SKILL.md` (step 4.5) (MODIFY)
- **Responsibility**: Replace the narrative policy-parsing / `jq` / decision
  bullets with one invocation and an exit-code branch; keep the user-facing
  `E2E: <policy> — <status>` reporting line and the `--force` clarification.
- **Depends on**: Module 1

### Module 3: Contract test retarget
- **Path**: `tests/sdd_scripts/test_e2e_closeout_contract.py` (MODIFY)
- **Responsibility**: Delete the task-local `evaluate_closeout_gate` and import
  the real one; keep all 15 behavioral test bodies (they call the same signature
  minus `force`); add CLI-level tests for exit codes and the import-guard path;
  update the 5 doc-surface tests so they assert the twins *invoke the script*
  rather than restate the table in prose.
- **Depends on**: Modules 1 and 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| 15 existing `test_required_*` / `test_optional_*` / `test_invalid_*` / `test_none_*` | M1 | Unchanged bodies, now exercising the real gate |
| `test_resolve_policy_missing_e2e_key_defaults_optional` | M1 | No `e2e` key → `optional` |
| `test_resolve_policy_malformed_value_is_invalid` | M1 | Present-but-malformed → `invalid`, never coerced |
| `test_gate_has_no_force_parameter` | M1 | Introspects the signature: force is structurally absent |
| `test_cli_exits_zero_when_gate_allows` | M1 | `main()` → 0 and JSON on stdout |
| `test_cli_exits_nonzero_when_required_gate_blocks` | M1 | `main()` → 1, reason codes present |
| `test_cli_treats_unimportable_parrot_e2e_as_missing` | M1 | Import guard fails closed, no traceback |

### Integration Tests

| Test | Description |
|---|---|
| `test_each_surface_invokes_the_gate_script` | Both twins call `check_e2e_closeout.py` before any mutating step |
| `test_each_surface_states_force_never_bypasses_required_gate` | Retained from the existing suite |

### E2E Scenarios

Omitted deliberately — `e2e.policy: none` (see frontmatter rationale). This
feature exercises no E2E target; its verification is ordinary pytest.

---

## 5. Acceptance Criteria

- [ ] `scripts/sdd/check_e2e_closeout.py` exists and implements the §3 decision
      table verbatim — same outcomes as the function it replaces.
- [ ] `evaluate_closeout_gate` accepts **no** `force` parameter; a test asserts
      this by signature introspection.
- [ ] Exit code is `0` when closeout may proceed and `1` when it must abort;
      stdout is a single JSON object carrying `policy`, `status`,
      `gate_satisfied` and `reason_codes`.
- [ ] A missing/unimportable `parrot.e2e` is handled as `MISSING` (fails closed
      under `required`, advisory under `optional`), never a traceback, never a pass.
- [ ] `tests/sdd_scripts/test_e2e_closeout_contract.py` imports the real gate;
      the task-local reimplementation is deleted, and all 15 behavioral tests
      still pass against it.
- [ ] Both closeout twins invoke the script before any stamp/push/PR/merge/cleanup
      step, and their prose no longer restates the decision table.
- [ ] `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q` passes.
- [ ] `ruff check` and `black --check` clean on every changed file.

---

## 6. Codebase Contract

> Verified against `c26bf74bf` (2026-10-19).

### Verified Imports
```python
from parrot.e2e.errors import E2EConfigError, E2EEvidenceError   # errors.py:63 (reason_code kwarg)
from parrot.e2e.evidence import verify_evidence                  # evidence.py:502
from parrot.e2e.models import VerificationResult                 # models.py:577
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/e2e/evidence.py:502
async def verify_evidence(plan_path: Path, *, worktree: Path) -> VerificationResult: ...

# packages/ai-parrot-server/src/parrot/e2e/models.py:577
class VerificationResult(_E2EBaseModel):
    status: _VerificationStatusLiteral   # line 590 — PASS | FAIL | BLOCKED | MISSING
    gate_satisfied: bool                 # line 591
    reason_codes: list[str]

# packages/ai-parrot-server/src/parrot/e2e/errors.py:63
def __init__(self, message: str, *, reason_code: Optional[str] = None) -> None: ...
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `evaluate_closeout_gate` | `verify_evidence()` | awaited call | `evidence.py:502` |
| `evaluate_closeout_gate` | `VerificationResult.status` / `.gate_satisfied` | attribute read | `models.py:590-591` |
| `main()` | `resolve_policy()` | call | this spec, M1 |
| Step 4.6 / step 4.5 | `check_e2e_closeout.py` | subprocess + exit code | M2 |

### Does NOT Exist (Anti-Hallucination)
- ~~`scripts/sdd/check_e2e_closeout.py`~~ — created by this feature
- ~~a public `parrot.e2e.evaluate_closeout_gate`~~ — the only copy today is
  task-local in the test file (L68–113) and is **deleted** by M3
- ~~a `force` parameter on `verify_evidence`~~ — it takes none, and must not gain one
- ~~`VerificationResult.passed`~~ — the fields are `status` / `gate_satisfied`
- ~~a `parrot e2e verify --json` flag~~ — the CLI already emits JSON on stdout;
  M1 does not shell out to it at all

### Edit Sites (Blueprint Anchors)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `scripts/sdd/check_e2e_closeout.py` | CREATE | — | — | — |
| `.claude/commands/sdd-done.md` | MODIFY | `### 4.6. Verify E2E Evidence (FEAT-581)` | `sdd-done.md:192` | 1 |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | `4.6. Verify E2E evidence (FEAT-581), before any stamp/push/merge-blocker/PR/` | `SKILL.md:98` | 1 |
| `tests/sdd_scripts/test_e2e_closeout_contract.py` | MODIFY | `async def evaluate_closeout_gate(` | `test_e2e_closeout_contract.py:68` | 1 |

---

## 7. Implementation Notes & Constraints

### The exact twin invocation (both surfaces, identical)

```bash
GATE_JSON=$(python -m scripts.sdd.check_e2e_closeout \
    --spec "<spec-path>" --feat-id "$FEAT_ID" --worktree "$WORKTREE_PATH")
GATE_EXIT=$?
# exit 0 = proceed; exit 1 = abort closeout now, before Step 5's report.
```

On a non-zero exit the twins keep today's refusal message verbatim — including
the "`--force` only overrides per-task partial/missing evidence (Step 6) and
ledger merge blockers (Step 9), never a required E2E gate (spec AC9)" line — and
`--dry-run` still shows the refusal and stops the same way.

### Patterns to Follow
- House gate-script shape: `main(argv) -> int` + `raise SystemExit(main())`,
  as in `scripts/sdd/check_task_state.py`.
- `asyncio.run()` once inside `main()`; the gate itself stays `async` so the
  existing async tests call it unchanged.
- Google-style docstrings, strict type hints, 120-column lines, `black` + `ruff`.

### Known Risks / Gotchas
- **Twin drift**: `.claude/commands/sdd-done.md` and `.agents/skills/sdd-done/SKILL.md`
  must be edited together; the doc-surface tests fail if they diverge.
  `.agents/` may need `git add -f` — check the ignore rules before committing.
- **Deleting the test-local function** is what makes the suite meaningful; a task
  that keeps both copies silently re-creates the gap this feature closes.
- **Import guard placement**: import `parrot.e2e` lazily *inside* the gate, not at
  module top level, so the script remains runnable (and testable) where
  `ai-parrot-server` is absent.
- The contract test inserts `packages/ai-parrot-server/src` on `sys.path`
  (test file L38–40); the script must not rely on that test-only convention.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `PyYAML` | existing | spec frontmatter parsing (already used by the inline snippet) |

---

## 8. Open Questions

- [ ] None blocking. The scope fork (code-enforce vs. soften AC9) was decided by
      the user on 2026-10-19 in favour of code enforcement.

---

## 9. Design Research Cross-Check

> Status: skipped — this feature promotes an already-reviewed, already-proven
> decision function rather than introducing new design. The original design was
> reviewed under TASK-3543.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-19 | sdd-fix (Claude) | Initial draft from `issue:4b887b8e3ce0` |
| 0.2 | 2026-10-19 | sdd-fix (Claude) | Approved — scope fork (code-enforce vs. soften AC9) decided by the user in favour of code enforcement |
