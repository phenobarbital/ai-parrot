# TASK-903: Integration smoke + README updates for FEAT-132

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-896, TASK-897, TASK-898, TASK-899, TASK-900, TASK-901, TASK-902
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 + §4 Integration Tests. After all the implementation
tasks land, this task wraps the feature with a documentation pass and
the integration tests called out in the spec.

The integration tests are `@pytest.mark.live` — they require a real
Jira sandbox + a real Anthropic key. They're part of the spec but
can be skipped in CI. The test scaffolding still needs to land in
the repo so operators with credentials can run them.

---

## Scope

- Add three integration tests to
  `packages/ai-parrot/tests/flows/dev_loop/integration/test_kind_routing.py`
  (new file). Mark with `@pytest.mark.live`. The tests:
  - `test_end_to_end_bug_kind_creates_bug_ticket`
  - `test_end_to_end_enhancement_kind_creates_story_ticket`
  - `test_end_to_end_reused_ticket_skips_plan_comment`
- Update `examples/dev_loop/README.md`:
  - New section "Routing by kind" describing the
    `IntentClassifierNode → BugIntakeNode | ResearchNode` topology
    with a one-line ASCII diagram.
  - Document the `DEV_LOOP_PLAN_LLM` env var (TASK-897 added the
    setting; this task documents the user-facing knob with a usage
    example).
  - Update the curl example to include `"kind"` and to mention the
    `existing_issue_key` field.
- Update `sdd/proposals/feat-129-upgrades.brainstorm.md` only if it
  exists — otherwise skip (no brainstorm was authored for this
  feature).
- Add a one-paragraph "FEAT-132 upgrades" section to the top of the
  bundled README so a new operator immediately sees what changed.

**NOT in scope**:
- Re-running the FEAT-129 spec or its READMEs.
- Touching the dispatcher / observability tier.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_kind_routing.py` | CREATE | Three live integration tests. |
| `examples/dev_loop/README.md` | MODIFY | Routing-by-kind section, plan-LLM section, updated curl. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest

from parrot.flows.dev_loop import (
    WorkBrief, ShellCriterion, ManualCriterion,
    ClaudeCodeDispatcher, build_dev_loop_flow,
    IntentClassifierNode,                                    # post-TASK-898
)
from parrot import conf
```

### Existing Signatures to Use

```python
# Existing live-test pattern under
# tests/flows/dev_loop/integration/test_concurrency.py — copy its
# fixture style (skip-on-missing-env + pytest.mark.live).

# Form-builder helper for synthesising payloads at integration time:
from examples.dev_loop.server import _build_brief_from_form  # via importlib
# (tests should not import examples directly; load via importlib —
#  see TASK-902's test_examples_form.py for the pattern.)
```

### Does NOT Exist

- ~~`examples.dev_loop` as an importable package~~ — `examples/` is
  not a Python package. Tests that need helpers from it must use
  `importlib.util.spec_from_file_location`.
- ~~A `LiveJiraFixture` class~~ — write the skip-marker fixture
  inline; check `os.environ["JIRA_INSTANCE"]` etc. and `pytest.skip`
  if missing.

---

## Implementation Notes

### Pattern to Follow

```python
# tests/flows/dev_loop/integration/test_kind_routing.py
import os
import pytest

from parrot.flows.dev_loop import WorkBrief, ShellCriterion

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


def _need_env(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"missing env vars: {missing}")


async def test_end_to_end_bug_kind_creates_bug_ticket(jira_toolkit):
    _need_env("JIRA_INSTANCE", "JIRA_API_TOKEN", "ANTHROPIC_API_KEY")
    # Build a minimal brief with kind="bug" and a unique summary so
    # _find_existing_issue doesn't false-match.
    ...

async def test_end_to_end_enhancement_kind_creates_story_ticket(jira_toolkit):
    ...

async def test_end_to_end_reused_ticket_skips_plan_comment(jira_toolkit):
    ...
```

### Key Constraints

- All three tests MUST `pytest.skip` if the live env is unavailable.
- They should NOT leave Jira detritus — emit a unique summary
  prefix per test run (e.g. `feat-132-smoke-<uuid>`) so the test
  author can clean up manually if needed.
- Plan-comment assertion uses `jira_toolkit.jira_get_comments(issue)`
  (verify method name) and asserts the first comment body starts
  with `Plan for run-`.

### References in Codebase

- `tests/flows/dev_loop/integration/test_concurrency.py` — existing
  live-test scaffolding template.

---

## Acceptance Criteria

- [ ] Three tests exist in the new
  `tests/flows/dev_loop/integration/test_kind_routing.py`; each
  skips cleanly when live env is missing.
- [ ] README has a "Routing by kind" section with the routing
  diagram.
- [ ] README documents `DEV_LOOP_PLAN_LLM` (env override) and the
  `kind` field.
- [ ] The curl example shows `"kind"` and an optional
  `"existing_issue_key"`.
- [ ] No regressions in the standard suite:
  `pytest packages/ai-parrot/tests/flows/dev_loop/ -q -m "not live"`.

---

## Test Specification

The acceptance criteria above plus the file-existence + skip-cleanly
contract are the test surface. The tests themselves are
gated behind `-m live` and require credentials; they will not run
in CI but will run on a developer's machine with the right env.

---

## Agent Instructions

1. Land all prior FEAT-132 tasks before starting this one.
2. Write the integration test file; verify the skip path works
   (`pytest tests/flows/dev_loop/integration/test_kind_routing.py -v`
   — all three tests SKIPPED is the expected output without env).
3. Update the README with the new sections.
4. Run the standard (non-live) suite to confirm no regressions.
5. Commit; move file; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
