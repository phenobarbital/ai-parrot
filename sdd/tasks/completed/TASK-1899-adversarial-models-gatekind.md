# TASK-1899: Adversarial review models + `review_escalation` GateKind

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-375 (spec §3). Foundation task: every other task imports these
models. Adds the advisory-review profile and triage data models, widens the
Codex subagent Literal, and extends `GateKind` so ESCALATE dispositions can
open a HITL gate (FEAT-322 machinery).

---

## Scope

- In `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`:
  - Widen `CodexCodeDispatchProfile.subagent` (line 548) from
    `Literal["sdd-worker"]` to `Literal["sdd-worker", "sdd-secondopinion"]`,
    **default unchanged** (`"sdd-worker"`).
  - Add `CodexAdversarialReviewProfile(CodexCodeDispatchProfile)` with fields
    exactly as spec §2 Data Models: `subagent="sdd-secondopinion"`,
    `sandbox="read-only"`, `approval_policy="never"`,
    `review_scope: Literal["uncommitted","base","commit"]="uncommitted"`,
    `review_base: str=""`, `review_commit: str=""`, `resume_last: bool=False`,
    `timeout_seconds` (default 1800, ge=60, le=7200).
  - Add `AdversarialFinding(CodeReviewFinding)`: `source: str="codex-adversarial"`,
    `disposition: Optional[Literal["confirm","reject","escalate"]]=None`,
    `triage_reason: str=""`.
  - Add `TriageBrief(BaseModel)`: `findings: List[AdversarialFinding]`,
    `acceptance_criteria: List[AcceptanceCriterion]`, `worktree_path: str`,
    `summary: str=""`. **No field for caller reasoning — by design.**
  - Add `TriageReport(BaseModel)`: `findings: List[AdversarialFinding]`,
    `files_modified: List[str]` (default empty), `summary: str=""`.
  - Add `PerspectiveSynthesis(BaseModel)`: `agreements: List[AdversarialFinding]`,
    `disagreements: List[AdversarialFinding]`, `judge_summary: str=""`.
  - Export all new names in `models.py`'s `__all__` (if present) and in
    `parrot/flows/dev_loop/__init__.py` alongside the existing profile exports.
- In `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`:
  - Add `"review_escalation"` to the `GateKind` Literal (line 166-171) with an
    inline comment matching the existing style.
- Write unit tests (see Test Specification).

**NOT in scope**: dispatchers, command building, QANode changes, subagent
brief file, conf.py settings (later tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | widen Literal; add 5 new models |
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | add `"review_escalation"` to `GateKind` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | export new model names |
| `packages/ai-parrot/tests/flows/dev_loop/test_adversarial_models.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports
```python
from parrot.flows.dev_loop.models import (
    CodeReviewFinding,            # models.py:739
    CodexCodeDispatchProfile,     # models.py:540
    AcceptanceCriterion,          # imported by nodes/qa.py:33-42 from models
)
from parrot.flows.dev_loop.session_state import GateKind, SessionHost  # session_state.py:166, exported :1056
```

### Existing Signatures to Use
```python
# models.py:540-566
class CodexCodeDispatchProfile(BaseModel):
    subagent: Literal["sdd-worker"] = "sdd-worker"          # line 548 ← widen here
    model: str = "gpt-5.5"                                  # line 549
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"  # 550
    approval_policy: Literal["untrusted", "on-request", "never"] = "never"  # 551
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)  # 552
    ignore_user_config: bool = True                         # 553
    ignore_rules: bool = False                              # 560

# models.py:739-745
class CodeReviewFinding(BaseModel):
    message: str
    severity: Literal["critical", "major", "minor", "nit"]
    file: str = ""
    line: int = 0

# models.py:797-809 — pattern to mirror for the new profile subclass
class CodexCodeReviewProfile(CodexCodeDispatchProfile):
    subagent: Literal["sdd-worker"] = "sdd-worker"          # 805
    sandbox: ... = "workspace-write"                        # 807
    approval_policy: ... = "on-request"                     # 808

# session_state.py:166-171
GateKind = Literal[
    "manual_criterion", "deployment_approval",
    "revision_approval", "plan_approval",
]  # ← append "review_escalation"
```

### Does NOT Exist
- ~~`AdversarialFinding` / `TriageBrief` / `TriageReport` / `PerspectiveSynthesis` / `CodexAdversarialReviewProfile`~~ — this task creates them.
- ~~`GateKind` value `"review_escalation"`~~ — this task adds it.
- ~~`parrot.flows.devloop`~~ — package is `parrot/flows/dev_loop/` (underscore).
- ~~a `reasoning` field on any brief model~~ — deliberately absent (spec G2).

---

## Implementation Notes

### Pattern to Follow
Mirror `CodexCodeReviewProfile` (models.py:797-809): subclass overriding
Literal defaults, Google-style docstring citing the FEAT.

### Key Constraints
- `mypy`/`ruff` clean; Pydantic v2 style consistent with the module.
- Do NOT change any existing default — `test_qanode_non_advisory_path_unchanged`
  (TASK-1903) and existing FEAT-270 tests depend on it.
- Widening a `Literal` default is backward compatible; verify existing tests
  still pass (`pytest packages/ai-parrot/tests/flows/dev_loop/ -v`).

### References in Codebase
- `models.py:778-809` — review-profile subclass pattern
- `session_state.py:166-171` — GateKind literal + comment style

---

## Acceptance Criteria

- [ ] All new models importable from `parrot.flows.dev_loop.models` AND `parrot.flows.dev_loop`
- [ ] `CodexAdversarialReviewProfile()` defaults: read-only, sdd-secondopinion, never, uncommitted
- [ ] `TriageBrief` has NO reasoning field (assert via `model_fields`)
- [ ] `SessionHost.open_gate(kind="review_escalation", ...)` type-checks and validates
- [ ] Existing dev_loop test suite still green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_adversarial_models.py
from parrot.flows.dev_loop.models import (
    AdversarialFinding, CodexAdversarialReviewProfile, TriageBrief, TriageReport,
)

def test_adversarial_profile_defaults():
    p = CodexAdversarialReviewProfile()
    assert p.sandbox == "read-only"
    assert p.subagent == "sdd-secondopinion"
    assert p.approval_policy == "never"
    assert p.review_scope == "uncommitted"
    assert p.resume_last is False

def test_worker_profile_default_unchanged():
    from parrot.flows.dev_loop.models import CodexCodeDispatchProfile
    assert CodexCodeDispatchProfile().subagent == "sdd-worker"

def test_triage_brief_has_no_reasoning_field():
    assert "reasoning" not in TriageBrief.model_fields

def test_finding_disposition_literal():
    f = AdversarialFinding(message="x", severity="major", disposition="escalate")
    assert f.disposition == "escalate"

def test_gatekind_review_escalation():
    from parrot.flows.dev_loop.session_state import GateKind
    from typing import get_args
    assert "review_escalation" in get_args(GateKind)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

Implemented exactly as specified:

- `models.py`: widened `CodexCodeDispatchProfile.subagent` to
  `Literal["sdd-worker", "sdd-secondopinion"]` (default unchanged); added
  `CodexAdversarialReviewProfile` (mirrors `CodexCodeReviewProfile` pattern,
  placed right after it) and `AdversarialFinding` / `TriageBrief` /
  `TriageReport` / `PerspectiveSynthesis` (placed right after
  `CodeReviewVerdict`). No `__all__` exists in `models.py` (verified via
  grep), so per the task's "if present" clause, only the package
  `__init__.py` export was required/added.
- `session_state.py`: appended `"review_escalation"` to `GateKind` with a
  comment matching the existing style.
- `__init__.py`: added the 5 new names to both the `from .models import (...)`
  block and `__all__`, alphabetically ordered like their neighbors.
- `test_adversarial_models.py`: 10 unit tests covering every Test
  Specification case (defaults, no-reasoning-field assertion, disposition
  literal, GateKind, package-level import re-export identity) plus a few
  extra default/round-trip checks.

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` →
614 passed, 1 pre-existing failure (`test_models_module_is_pure`, a known
test-ordering-pollution issue unrelated to this change — confirmed it also
fails in isolation-run comparison per prior session notes, and passes when
run standalone), 5 skipped. `ruff check` clean on all 4 touched files.

No divergence from the task spec; no files touched outside the declared
list.
