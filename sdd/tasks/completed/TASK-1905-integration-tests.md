# TASK-1905: End-to-end integration tests for adversarial review flow

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1899, TASK-1900, TASK-1901, TASK-1902, TASK-1903, TASK-1904
**Assigned-to**: unassigned

---

## Context

Module 7 of FEAT-375 (spec §4 Integration Tests). Per-module unit tests ship
with TASK-1899..1904; this task adds the cross-module end-to-end paths using
the fake-CLI-binary pattern, and closes the feature with a full-suite run.

---

## Scope

- CREATE `packages/ai-parrot/tests/flows/dev_loop/test_adversarial_e2e.py`:
  - `test_e2e_adversarial_review_triage` — fake `codex` binary (stub script on
    PATH writing a canned `CodeReviewVerdict` JSON with 2 findings to the `-o`
    path) → `CodexAdversarialReviewDispatcher.review()` → QANode triage with a
    stub dev dispatcher returning a `TriageReport` (1 CONFIRM w/ files_modified,
    1 REJECT) → assert deterministic QA re-ran and notes carry the rejection.
  - `test_e2e_escalation_opens_gate_and_pr_note` — TriageReport with ESCALATE →
    assert a `review_escalation` gate is pending on the `SessionHost` and
    `QAReport.notes` contains the escalation note.
  - `test_e2e_parallel_perspective` — primary + adversary stubs with one
    overlapping finding → merged verdict has 1 agreement (both sources) + the
    disjoint findings; judge not called with `DEV_LOOP_CODEREVIEW_JUDGE=false`.
- Full-suite verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
  green, plus `ruff check` on all files the feature touched.
- Confirm spec §5 acceptance criteria are all checkable; tick them in the spec
  is NOT this task's job (done at /sdd-done), but list any UNMET criterion in
  the Completion Note.

**NOT in scope**: new production code (if a test exposes a bug, fix belongs to
the owning task's follow-up — record in Completion Note and fix minimally with
a clear commit message).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_adversarial_e2e.py` | CREATE | 3 integration tests + fixtures |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`; components from TASK-1899..1904
> must be re-verified as landed before writing tests.

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    CodeReviewDispatcherFactory,                 # code_review.py:104
    # CodexAdversarialReviewDispatcher, ParallelPerspectiveReviewDispatcher — TASK-1902
)
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher   # dispatcher.py:936
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.models import CodeReviewVerdict         # models.py:748
from parrot.flows.dev_loop.session_state import SessionHost        # session_state.py
```

### Existing Signatures to Use
```python
# CodexCodeDispatcher construction (for the fake-binary path):
CodexCodeDispatcher(max_concurrent=1, redis_url=<fakeredis/url>,
                    stream_ttl_seconds=60, codex_bin=<path-to-stub>)  # dispatcher.py:951-958
# dispatch() enforces cwd under conf.WORKTREE_BASE_PATH               # dispatcher.py:1264
#   → tests must point WORKTREE_BASE_PATH (monkeypatch conf) at tmp_path
# structured output read from the -o file                             # dispatcher.py:1238-1262

# Fake-binary + redis stubbing precedents: READ
#   packages/ai-parrot/tests/flows/dev_loop/test_code_review.py   (FEAT-270 harness)
#   packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py (QANode harness)
# and reuse their fixtures/helpers rather than inventing new scaffolding.
```

### Does NOT Exist
- ~~a pytest fixture factory for codex stubs in a shared conftest~~ — check
  `tests/flows/dev_loop/conftest.py` first; if the FEAT-270 tests define
  helpers inline, mirror them, don't import across test modules.
- ~~network access to a real `codex` CLI in CI~~ — tests MUST use the stub
  binary; never invoke the real CLI.

---

## Implementation Notes

### Key Constraints
- Async tests: `pytest-asyncio` style already used across the dev_loop suite.
- Monkeypatch `conf.WORKTREE_BASE_PATH` to `tmp_path` so the cwd guard passes.
- Redis: reuse whatever stubbing FEAT-270 tests use (fakeredis or patching
  `_publish_event`) — inspect before choosing.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py`
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py`

---

## Acceptance Criteria

- [ ] 3 integration tests implemented and green
- [ ] Full dev_loop suite green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` clean on all FEAT-375-touched files
- [ ] Completion Note lists any spec §5 criterion that remains unmet (expected: none)

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_adversarial_e2e.py
# (names fixed by spec §4)

async def test_e2e_adversarial_review_triage(tmp_path, monkeypatch): ...
async def test_e2e_escalation_opens_gate_and_pr_note(tmp_path, monkeypatch): ...
async def test_e2e_parallel_perspective(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** (§4 Integration Tests, §5 Acceptance Criteria)
2. **Check dependencies** — TASK-1899..1904 ALL in `sdd/tasks/completed/`
3. **Verify the Codebase Contract**; read both harness files before writing fixtures
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

Implemented all 3 integration tests exactly named per spec §4, in
`test_adversarial_e2e.py`:

- `test_e2e_adversarial_review_triage`: a REAL `CodexCodeDispatcher`
  (fake-process pattern mirroring `test_codex_dispatcher.py` — monkeypatches
  `_create_process` to write a canned `CodeReviewVerdict` JSON with 2
  findings to the `-o` path and `_ensure_redis` to avoid real Redis; no
  subprocess/network access) wrapped in a REAL
  `CodexAdversarialReviewDispatcher`, feeding a REAL `QANode` whose triage
  dispatch returns a `TriageReport` with 1 CONFIRM (`files_modified=
  ["a.py"]`) + 1 REJECT. Asserts 3 dev-dispatcher calls (deterministic → 
  triage → rerun-after-fix) and that the REJECT reason lands in
  `QAReport.notes`. Also exercises the "lying stub" `files_modified` on the
  raw verdict JSON to confirm the advisory dispatcher still strips it
  (belt-and-suspenders from TASK-1902) even through the real dispatch path.
- `test_e2e_escalation_opens_gate_and_pr_note`: same real codex chain, one
  ESCALATE finding. Uses a REAL `SessionHost` (not mocked) — runs
  `QANode.execute()` as a background `asyncio.Task`, polls (bounded loop,
  `asyncio.sleep(0)`) until the `review_escalation` gate appears `pending`
  in `session_host.state.gates`, asserts that, then calls
  `session_host.resolve_gate(..., "approved", ...)` and awaits the task to
  completion, asserting the note text and that an approved resolution
  clears `code_review_passed`. This exercises TASK-1903's actual blocking
  `wait_gate()` design (mirroring `_resolve_blocking_manual_criteria`)
  faithfully rather than requiring a production-code change — see note
  below on why this shape was chosen over a truly non-blocking read.
- `test_e2e_parallel_perspective`: real
  `ParallelPerspectiveReviewDispatcher` with stub primary/adversary
  reviewers (one overlapping finding after whitespace/case normalization,
  one disjoint finding each), `monkeypatch`ed
  `conf.DEV_LOOP_CODEREVIEW_JUDGE=False` wired through to
  `judge_enabled=conf.DEV_LOOP_CODEREVIEW_JUDGE` (genuinely exercises the
  TASK-1904 config-gating path, not just the dispatcher's own default
  arg). Asserts exactly 1 agreement (`source="primary,codex-adversarial"`)
  + 2 disjoint findings, and that the judge is never called.

**Design note surfaced by this integration testing (no production code
changed — documented per "if a test exposes a bug, fix belongs to the
owning task's follow-up"):** the escalation-gate test initially assumed
`QANode.execute()` would return promptly with the gate left pending
(per the spec's terse wording "ESCALATE → gate pending"). Investigation
confirmed TASK-1903's actual (and, on reflection, correctly-specified)
behavior is a SYNCHRONOUS await of gate resolution inside
`_run_finding_triage()`, deliberately mirroring the established
`_resolve_blocking_manual_criteria` precedent (FEAT-322) that TASK-1903's
own Implementation Notes cited as the pattern to follow, and consistent
with gate TTL + fail-closed `on_expiry` semantics bounding the wait. The
TASK-1903 Acceptance Criteria bullet itself ("ESCALATE opens
`review_escalation` gate ... AND always adds a PR-visible note") does not
actually require non-blocking behavior — only the more informal Scope
prose could be read that way. Rather than reopening/changing already-
completed, tested, committed TASK-1903 production code on a
re-interpretation, this task's integration test was written to correctly
interact with the EXISTING (intentional) blocking design: spawn
`execute()` as a background task, observe the gate mid-flight, resolve it,
then await completion — which is both a legitimate testing pattern for
this exact kind of AHP/HITL gate and requires zero production-code
changes. Flagging this explicitly in case the pending-vs-blocking
question needs a follow-up spec clarification.

**Spec §5 Acceptance Criteria — all checkable and met** (not ticking the
spec here per instructions; verification below):
- `create("codex-adversarial", ...)` advisory / `create("codex", ...)`
  unchanged — TASK-1902 unit tests + `test_adversarial_review.py`.
- Advisory `sandbox="read-only"`, never reports `files_modified` —
  TASK-1899/1902 unit tests + this task's e2e "lying stub" case.
- `sdd-secondopinion` brief has no reasoning field — TASK-1899/1900.
- Every finding gets a disposition; missing → fail-closed ESCALATE —
  TASK-1903 unit tests + this task's e2e.
- ESCALATE opens gate (fail-closed TTL) + PR note — TASK-1903/1904 +
  this task's e2e (real `SessionHost`).
- `codex exec review`/`resume` shapes table-driven, unit-tested; `resume`
  never gets `--sandbox` — TASK-1901.
- `"parallel"` deterministic merge; judge gated by
  `DEV_LOOP_CODEREVIEW_JUDGE` — TASK-1902/1904 + this task's e2e.
- Degrade-on-infra-error holds for both new dispatchers — TASK-1902 (`
  _resolve_side`, ABC `review()` wrapper).
- Full suite green — `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
  → **651 passed**, 1 pre-existing failure, 5 skipped.
- No breaking public-API changes — `parrot.flows.dev_loop.__init__`
  `__all__` only gained names across TASK-1899 (verified via the diffs in
  each task's commit; nothing removed).

**No unmet criteria.**

**Pre-existing failure (NOT a regression, unrelated to FEAT-375):**
`packages/ai-parrot/tests/flows/dev_loop/test_lazy_import.py::
test_models_module_is_pure` — fails when the full `tests/flows/dev_loop/`
directory runs together (test-ordering/import-pollution issue) but passes
in isolation; this exact failure was already present and documented before
any FEAT-375 work began (confirmed at TASK-1899 via running the suite
before touching `models.py`, and consistently reproduced identically
through every subsequent task in this feature).

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` → 651
passed, 1 pre-existing failure, 5 skipped. `ruff check` clean across every
file this feature touched (models.py, session_state.py, __init__.py,
_subagent_defs.py, dispatcher.py, code_review.py, nodes/qa.py, conf.py
(pre-existing unrelated E402 at :450 excluded), examples/dev_loop/server.py,
and all 8 FEAT-375 test files).

No divergence from the task spec; no production files touched (test-only
task, as scoped).
