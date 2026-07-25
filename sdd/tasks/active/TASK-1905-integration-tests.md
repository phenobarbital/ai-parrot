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

*(Agent fills this in when done)*
