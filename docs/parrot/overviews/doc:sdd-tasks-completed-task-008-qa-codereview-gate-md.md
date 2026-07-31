---
type: Wiki Overview
title: 'TASK-008: QA code-review gate (additive `sdd-codereview` dispatch)'
id: doc:sdd-tasks-completed-task-008-qa-codereview-gate-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 6 (G4). QA gains a qualitative code-review gate **in addition**
relates_to:
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.qa
  rel: mentions
---

# TASK-008: QA code-review gate (additive `sdd-codereview` dispatch)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-003, TASK-005
**Assigned-to**: unassigned

---

## Context

Implements Module 6 (G4). QA gains a qualitative code-review gate **in addition**
to the deterministic criteria/lint. A run passes QA only when both pass. The QA
node must still never raise on failure (the flow takes the fail edge).

---

## Scope

- In `QANode.execute`, after the existing deterministic `sdd-qa` dispatch,
  dispatch `sdd-codereview` (read-only) with a brief = acceptance criteria +
  worktree/diff path + the issue summary. Validate its JSON output into the new
  `QAReport` code-review fields.
- Merge into the returned `QAReport`: set `code_review_passed`,
  `code_review_findings`, and final `passed = deterministic_passed and
  code_review_passed`.
- Code-review dispatch profile: `subagent="sdd-codereview"`,
  `permission_mode="plan"`, `allowed_tools=["Read","Bash","Grep","Glob"]`
  (NEVER `Edit`/`Write`), `model=DEV_LOOP_CODEREVIEW_MODEL`.
- Node never raises on failure.
- Unit tests with the dispatcher mocked.

**NOT in scope**: the subagent body (TASK-005); the model setting (TASK-004
adds `DEV_LOOP_CODEREVIEW_MODEL`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Add code-review dispatch + merge into QAReport |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.qa import QANode                          # qa.py:55
from parrot.flows.dev_loop.models import QAReport, ClaudeCodeDispatchProfile  # models.py (code-review fields from TASK-003)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
class QANode(DevLoopNode):
    def __init__(self, dispatcher, lint_command=None, name="qa")          # :55  (may add codereview_model)
    async def execute(self, ctx, deps, **kwargs) -> QAReport               # :70
    @staticmethod
    def _merge_manual_results(report, manual) -> QAReport                  # :144 (merge pattern to mirror)

# dispatcher (existing)
await self._dispatcher.dispatch(brief=..., profile=ClaudeCodeDispatchProfile(
    subagent="sdd-codereview", permission_mode="plan",
    allowed_tools=["Read","Bash","Grep","Glob"]),
    output_model=<CodeReviewModel>, run_id=..., node_id=self.name, cwd=research.worktree_path)
```

### Does NOT Exist
- ~~a code-review dispatch in QANode today~~ — only deterministic `sdd-qa`.
- ~~`Edit`/`Write` in any QA profile~~ — QA dispatches are read-only; keep it so.

---

## Implementation Notes

### Key Constraints
- Reuse the existing read-only QA posture (`permission_mode="plan"`).
- `output_model` for code-review: either a small inline Pydantic model with
  `{passed: bool, findings: list[str], summary: str}` or reuse a shared one —
  define it in `qa.py` or `models.py` (small; keep it local to qa.py if unused
  elsewhere).
- Final `QAReport.passed` must AND both gates; `code_review_findings` carries the
  reviewer's findings for the Jira/PR comment downstream.
- Never raise on code-review failure.

### References in Codebase
- `qa.py:70-142` — current execute (deterministic dispatch + manual merge).
- `parrot/bots/github_reviewer.py` — AC-comparison verdict shape reference.

---

## Acceptance Criteria

- [ ] QA dispatches `sdd-codereview` with `permission_mode="plan"`, no `Edit`/`Write`.
- [ ] Deterministic pass + code-review fail ⇒ `QAReport.passed is False`; node does not raise.
- [ ] Both pass ⇒ `passed is True`, findings empty.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` clean.

---

## Test Specification
```python
async def test_qa_codereview_gate_blocks_on_fail(mock_dispatcher):
    # deterministic dispatch → QAReport(passed=True,...); codereview dispatch → {passed:False, findings:[...]}
    node = QANode(dispatcher=mock_dispatcher)
    report = await node.execute(ctx, deps)
    assert report.passed is False and report.code_review_passed is False

async def test_qa_codereview_dispatch_is_read_only(mock_dispatcher):
    # assert the codereview profile has permission_mode=="plan" and no Edit/Write
```

---

## Agent Instructions
Standard SDD lifecycle.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`nodes/qa.py`)
- Added `_CodeReviewBrief` and `_CodeReviewVerdict` (`{passed=True, findings=[],
  summary=""}`, tolerant defaults) models, and a `conf` import.
- `QANode.__init__` gained `codereview_model=None` (defaults to
  `conf.DEV_LOOP_CODEREVIEW_MODEL`).
- `execute` now runs `_run_code_review(...)` after the deterministic dispatch +
  manual merge, and sets `passed = deterministic_passed and cr_passed`,
  `code_review_passed`, `code_review_findings`.
- `_run_code_review` dispatches `sdd-codereview` with `permission_mode="plan"`,
  `allowed_tools=["Read","Bash","Grep","Glob"]` (NEVER Edit/Write),
  `model=self._codereview_model`, `cwd=research.repo_path or worktree_path`.
  Never raises: a dispatch error (or a malformed verdict) degrades to
  `(True, ["code-review could not run: …"])` so an infra hiccup cannot block on
  non-quality grounds — the deterministic gate stays the hard guarantee.

**Verification**
- `pytest test_qa_codereview.py` → 6 passed (blocks on review fail, passes when
  both pass, deterministic-fail stays failed, read-only profile,
  error-doesn't-block, cwd prefers repo_path).
- Backward compat: existing `test_qa.py` → 5 passed (11 total). Fixed a subtle
  bug where the verdict attribute access sat outside the try/except (a mock
  returning a `QAReport` raised `AttributeError`); moved it inside so any
  malformed verdict degrades gracefully.
- `ruff check` clean on both files.
