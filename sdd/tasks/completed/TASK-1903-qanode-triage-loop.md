# TASK-1903: QANode advisory-finding triage loop (CONFIRM/REJECT/ESCALATE)

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1899, TASK-1902
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-375 (spec §3, goals G3+G4; resolved U2 + escalation Q&A).
When the configured reviewer is advisory, its findings are NOT auto-fixed by
the reviewer. QANode must route them to the primary worker for explicit
triage: CONFIRM → fix (reuse the existing rerun path), REJECT → reason
recorded, ESCALATE → HITL gate + PR-visible note. Never silently concede,
never silently drop.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`:
  - After `_run_code_review()` (call site `qa.py:157`), detect
    `getattr(self._codereview_dispatcher, "advisory", False)`.
  - When advisory AND findings exist (excluding `_CODE_REVIEW_SKIP_PREFIX`
    entries): call new `_run_finding_triage(shared, research, brief, findings)`:
    1. Build `TriageBrief` (findings as `AdversarialFinding`,
       acceptance_criteria, worktree_path, summary). NO caller reasoning.
    2. Dispatch the primary dev dispatcher (`self` already holds the
       `ClaudeCodeDispatcher` used for the default reviewer — `qa.py:92-103`)
       with `output_model=TriageReport`, `subagent="sdd-worker"` profile
       (write-enabled: the worker may fix CONFIRMed findings and commit).
    3. Validate: every input finding present in the report WITH a disposition.
       If any missing → retry the dispatch ONCE; still missing → treat the
       missing ones as ESCALATE (fail-closed).
    4. CONFIRM: collect `report.files_modified` → reuse the existing
       deterministic-QA rerun (`qa.py:164-173` pattern, `cwd_override` same).
    5. REJECT: append `"rejected: <message> — <triage_reason>"` lines to
       `QAReport.notes`.
    6. ESCALATE: for each, `session_host.open_gate(kind="review_escalation",
       node_id=self.node_id, title=..., instructions=finding.message,
       ttl_seconds=<conf DEV_LOOP_GATE_TTL_REVIEW_ESCALATION via getattr
       fallback 86400>, on_expiry="fail")` — only when a `SessionHost` is
       available in `shared` (mirror how `_resolve_blocking_manual_criteria`
       obtains it); ALWAYS append an escalation note to `QAReport.notes`
       (PR-visible) even when no session host exists.
  - QA pass/fail semantics: advisory findings triaged CONFIRM-and-fixed or
    REJECT do not fail QA by themselves (deterministic gate remains the hard
    guarantee); any ESCALATE → `code_review_passed=False` until the gate
    resolves (blocking-gate await mirrors `_resolve_blocking_manual_criteria`).
  - Non-advisory dispatchers: behavior byte-identical (regression tests).
- Unit tests (see Test Specification).

**NOT in scope**: dispatcher classes (TASK-1902), conf.py key definition
(TASK-1904 — use `getattr` fallback), models (TASK-1899).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | advisory detection + `_run_finding_triage()` |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.models import (   # TASK-1899 — verify landed
    AdversarialFinding, TriageBrief, TriageReport,
)
from parrot.flows.dev_loop.session_state import SessionHost  # open_gate: session_state.py:861
```

### Existing Signatures to Use
```python
# nodes/qa.py:51
_CODE_REVIEW_SKIP_PREFIX = "code-review could not run:"

# nodes/qa.py:92-103 — QANode wiring (constructor keyword)
codereview_dispatcher: Optional[AbstractCodeReviewDispatcher] = None
# None → ClaudeCodeReviewDispatcher(dispatcher=dispatcher)          # 101-102
# stored via object.__setattr__(self, "_codereview_dispatcher", …)  # 103

# nodes/qa.py:147-221 — gate sequencing in execute():
#   report = await self._run_deterministic_qa(shared, research, brief, executable)  # 147-149
#   cr_passed, cr_findings, files_modified = await self._run_code_review(...)       # 157-159
#     (findings arrive as List[str] — see _run_code_review below)
#   if files_modified: re-run deterministic QA with cwd_override                    # 164-173
#   update = {"passed": deterministic and cr_passed and blocking_passed,
#             "code_review_passed": cr_passed, "code_review_findings": cr_findings} # 184-188
#   skip handling appends note to report.notes                                      # 189-204

# nodes/qa.py:282-320
async def _run_code_review(self, shared, research, brief)
    -> tuple[bool, List[str], List[str]]:  # (passed, findings-as-strings, files_modified)
    # verdict = await self._codereview_dispatcher.review(brief=_CodeReviewBrief(...),
    #     run_id=..., node_id=..., cwd=..., session_host=...)        # 305
    # NOTE: it stringifies findings — for triage you need the STRUCTURED verdict;
    # either extend _run_code_review to also return the verdict, or store it on
    # shared — pick one, keep the 3-tuple contract for existing callers/tests.

# nodes/qa.py:227-235 — deterministic rerun helper (reuse for CONFIRM fixes)
async def _run_deterministic_qa(self, shared, research, brief, executable,
                                *, cwd_override: Optional[str] = None) -> QAReport

# session_state.py:861-871
def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
              instructions: str = "", payload_ref: str = "",
              ttl_seconds: Optional[int] = None,
              on_expiry: Literal["fail", "approve"] = "fail") -> Tuple[str, ActionEnvelope]

# _resolve_blocking_manual_criteria (qa.py, listed in wiki API outline) —
# mirror ITS session-host acquisition and gate-await pattern for ESCALATE.
```

### Does NOT Exist
- ~~`QANode.triage_dispatcher`~~ — triage uses the SAME dev dispatcher QANode already holds (`self`, wired at :92-103); do not add a new constructor param unless the primary dispatcher is truly unreachable (then mirror `codereview_dispatcher` wiring).
- ~~`conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION`~~ — lands in TASK-1904; `getattr(conf, "...", 86400)` until then.
- ~~`CodeReviewVerdict.triage`~~ / a disposition field on `CodeReviewVerdict` — dispositions live on `AdversarialFinding` inside `TriageReport`.
- ~~`AbstractCodeReviewDispatcher.review()` returning `TriageReport`~~ — it returns `CodeReviewVerdict`; triage is a SEPARATE dispatch owned by QANode.

---

## Implementation Notes

### Pattern to Follow
`_resolve_blocking_manual_criteria` is the in-file precedent for opening gates
and awaiting resolution; the `files_modified` rerun at `qa.py:164-173` is the
precedent for CONFIRM fixes.

### Key Constraints
- Fail-closed: undispositioned findings escalate after one retry.
- Loud-skip convention preserved: skip-prefixed findings never enter triage.
- All notes appended to `QAReport.notes` follow the existing `sep` pattern (`qa.py:201-204`).
- Keep `_run_code_review`'s public 3-tuple shape — existing tests
  (`test_qa_codereview.py`) assert on it.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py` — QANode gate test harness to extend/mirror

---

## Acceptance Criteria

- [ ] Advisory reviewer + findings → triage dispatch happens; non-advisory path byte-identical
- [ ] CONFIRM with `files_modified` → deterministic QA re-runs
- [ ] REJECT reasons appear in `QAReport.notes`
- [ ] ESCALATE opens `review_escalation` gate (when session host present) AND always adds a PR-visible note
- [ ] Missing disposition → one retry → fail-closed to ESCALATE
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py -v` green
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py
# Harness: stub advisory reviewer returning a fixed CodeReviewVerdict;
# stub dev dispatcher whose dispatch() returns a canned TriageReport.
# Mirror the fixture style of test_qa_codereview.py.

async def test_triage_confirm_triggers_rerun(...):
    """CONFIRM finding with files_modified → _run_deterministic_qa called twice."""

async def test_triage_reject_recorded_in_notes(...):
    """REJECT disposition → triage_reason lands in QAReport.notes."""

async def test_triage_escalate_opens_gate_and_note(...):
    """ESCALATE → open_gate(kind='review_escalation') + note in QAReport.notes."""

async def test_missing_disposition_fails_closed(...):
    """Report omits one finding → one retry → treated as ESCALATE."""

async def test_non_advisory_path_unchanged(...):
    """advisory=False reviewer → no triage dispatch, legacy flow intact."""

async def test_skip_prefixed_findings_bypass_triage(...):
    """'code-review could not run:' findings never enter triage."""
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview + Component Diagram, §3 Module 5)
2. **Check dependencies** — TASK-1899, TASK-1902 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

Implemented as specified, resolving two mechanism choices the task left
open (both flagged here per "when in doubt" guidance rather than guessed
silently):

- **Structured verdict access** (contract note: "either extend
  `_run_code_review` to also return the verdict, or store it on shared —
  pick one, keep the 3-tuple contract"). Chose the `shared` route:
  `_run_code_review` now stashes the raw `CodeReviewVerdict` (or `None` on
  degrade) at `shared["_code_review_verdict"]`; the public 3-tuple return
  is untouched (`test_qa_codereview.py` passes unmodified). A new
  `_collect_triage_findings(shared)` reads it back, filters skip-prefixed
  messages, and coerces any plain `CodeReviewFinding` into
  `AdversarialFinding` defensively (in practice TASK-1902's dispatchers
  already tag their findings, so this coercion is a no-op belt-and-suspenders
  path).
- **ESCALATE blocking semantics**: the Scope/Acceptance-Criteria text says
  "any ESCALATE → `code_review_passed=False` until the gate resolves
  (blocking-gate await mirrors `_resolve_blocking_manual_criteria`)".
  Implemented literally: for every ESCALATE, `open_gate(kind=
  "review_escalation", ...)` is called (only when a `SessionHost` is
  present in `shared`), all escalated gate ids are gathered via
  `asyncio.gather(*[session_host.wait_gate(gid) ...])` (same pattern as
  `_resolve_blocking_manual_criteria`), and `escalation_passed = all(gate
  .status == "approved" for gate in resolved)`. When there ARE findings to
  triage, `cr_passed` is **replaced** (not ANDed) by `escalation_passed` —
  this matches "CONFIRM-and-fixed / REJECT do not fail QA by themselves"
  (the raw advisory verdict's own `passed` opinion is superseded once
  every finding has gone through triage; only an unresolved/rejected
  escalation now blocks). When no `SessionHost` exists (legacy
  construction), the note is still always appended but no gate opens and
  `escalation_passed` stays `True` (fail-open only in the sense that we
  cannot block without a host — mirrors `_resolve_blocking_manual_criteria`'s
  no-host degrade). Covered by both
  `test_triage_escalate_opens_gate_and_note` (approved → passes) and
  `test_escalate_rejected_gate_fails_code_review` (rejected →
  `code_review_passed=False`, `report.passed=False`) — the latter goes
  beyond the minimal Test Specification to lock in this semantic.
- CONFIRM fixes: `report.files_modified` from the `TriageReport` is merged
  into the SAME `files_modified` list that already triggers the existing
  `qa.py:164-173` rerun block (inserted the triage call between
  `_run_code_review()` and that `if files_modified:` check) — reuses the
  rerun path exactly as instructed, no duplicated logic.
- Missing-disposition fail-closed: one retry dispatch, then any finding
  still lacking a disposition is synthesized with
  `disposition="escalate"` + an explanatory `triage_reason`, entering the
  same ESCALATE branch (gate + note).
- Write-enabled triage profile mirrors `development.py`'s single-agent
  `sdd-worker` profile exactly (`permission_mode="acceptEdits"`,
  `allowed_tools=["Read","Edit","Write","Bash","Grep","Glob"]`,
  `setting_sources=["project"]`) since the worker may fix CONFIRMed
  findings and commit.
- `getattr(conf, "DEV_LOOP_GATE_TTL_REVIEW_ESCALATION", 86400)` used as
  instructed (TASK-1904 will add the real conf key).
- Non-advisory path verified byte-identical: `getattr(self
  ._codereview_dispatcher, "advisory", False)` gates the entire new
  branch; all 11 pre-existing `test_qa_codereview.py` tests pass
  unmodified, including the `MagicMock()`-as-reviewer case (its verdict
  has empty findings, so `_collect_triage_findings` returns `[]` and the
  triage dispatch never fires even though `MagicMock().advisory` is
  truthy by default — noted as a latent test-authoring footgun for any
  *future* test that gives a bare, un-speced `MagicMock()` reviewer real
  findings without explicitly setting `.advisory = False`).

`test_qa_triage.py`: 7 tests, one per Test Specification scaffold, plus
`test_escalate_rejected_gate_fails_code_review` for the ESCALATE
pass/fail semantics above.

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py
packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py -v` → 18
passed. Full suite `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` →
645 passed, 1 pre-existing failure (`test_models_module_is_pure`, same
known ordering-pollution issue noted in TASK-1899/1900/1901/1902), 5
skipped. `ruff check` clean on both touched files.

No divergence from the task spec; no files touched outside the declared
list.
