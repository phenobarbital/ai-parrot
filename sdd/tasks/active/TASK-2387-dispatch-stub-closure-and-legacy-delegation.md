# TASK-2387: Close the executor stub gap and delegate the legacy tool

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2384, TASK-2385, TASK-2386
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** (Goal G1). **This is the task that fixes the defect
this whole feature is built on.**

`executor.py::_dispatch_step` lines 298-311 match eight action types, log a
warning, and `return True`. Any plan using them reports success while doing
nothing — against an accounting system that means later steps operate on a
login page and records are silently wrong. TASK-2384/2385/2386 built the real
implementations; this task deletes the stub and wires them, then collapses the
legacy duplicates in `tool.py` into delegations so exactly one implementation
of each action survives.

This mirrors what FEAT-222 did for `Loop`/`Conditional` (its spec §1, gap 4).

Implements spec **Module 2**.

---

## Scope

- **Delete** the stub branch at `executor.py:298-311` entirely.
- Dispatch each of the eight action types to its `session_actions.exec_*`
  counterpart, passing the local `_dispatch` closure as `dispatch_step_fn`
  exactly as the `loop`/`conditional` branches already do (executor.py:281-297).
- Ensure an **unknown** action type still returns `False` (the existing `else`
  branch) — never `True`.
- Rewrite the eight `tool.py` handlers as thin delegations to `session_actions`,
  deleting the duplicated bodies at tool.py:1807, 1826, 1841, 1913, 2086, 2175,
  2202, 2336.
- Add a regression test proving no action type reaches a `return True` stub.

**NOT in scope**: changing any action's behaviour; the `credential_provider`
field (TASK-2389); plan validation (TASK-2388).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | Delete stub branch, dispatch to session_actions |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py` | MODIFY | Collapse 8 duplicate handlers into delegations |
| `packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py` | CREATE | Regression: no silent-success path survives |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot_tools.scraping.session_actions import (   # created by TASK-2384/2385/2386
    exec_authenticate, exec_get_cookies, exec_set_cookies,
    exec_await_human, exec_await_keypress, exec_await_browser_event,
    exec_upload_file, exec_wait_for_download,
)
from parrot_tools.scraping.advanced_actions import exec_loop, exec_conditional  # verified: advanced_actions.py:229,313
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
async def execute_plan_steps(                       # line 42
    driver, plan=None, steps=None, selectors=None, config=None, base_url=None
) -> ScrapingResult: ...
async def _dispatch_step(...)                       # line 229
    # existing real branches: navigate(251) wait(253) click(255) fill(257)
    #   scroll(259) extract(267) screenshot(275) select(279) loop(281) conditional(291)
    #
    # THE STUB TO DELETE — lines 298-311:
    #   elif action_type in ("get_cookies","set_cookies","authenticate",
    #                        "await_human","await_keypress","await_browser_event",
    #                        "upload_file","wait_for_download"):
    #       logger.warning("Action '%s' requires the full WebScrapingTool; skipping...")
    #       return True
    #   else:
    #       logger.warning("Unknown action type: %s", action_type)
    #       return False          <-- KEEP this else branch

    # the loop/conditional branches show the dispatch-closure pattern to copy:
    #   async def _dispatch(d, s, u, t, _caller_se):
    #       return await _dispatch_step(d, s, u, t, step_extracted)
    #   return await exec_loop(driver, action, _dispatch, base_url, timeout)

# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py — handlers to collapse
_get_cookies:1807  _set_cookies:1826  _handle_authentication:1841
_await_browser_event:1913  _await_human:2086  _await_keypress:2175
_wait_for_download:2202  _upload_file:2336
# dispatch site for authenticate: line 747  ->  self._handle_authentication(action)
```

### Does NOT Exist

- ~~a generic "advanced action" fallback that logs and continues~~ — do NOT add one. An unimplemented action must fail the step. Reintroducing a permissive fallback recreates the exact bug this task removes.
- ~~`WebScrapingToolkit.execute_advanced_action()`~~ — no such method.

---

## Implementation Notes

### Key Constraints
- **Never `return True` for an action you did not execute.** This is the single
  most important line in this task. Review the final diff for any `return True`
  that is not preceded by real work.
- Do not change public behaviour of `WebScrapingToolkit` or `WebScrapingTool` —
  existing scraping tests must pass unchanged (spec AC-18).
- After collapsing `tool.py`, `grep -c "async def _await_human"` in that file
  must be 0 or the handler must be a one-line delegation; there must be exactly
  one real implementation per action across the package.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] `grep -n 'requires the full WebScrapingTool' executor.py` returns nothing
- [ ] All eight action types execute for real through `execute_plan_steps`
- [ ] An unknown action type still returns `False`
- [ ] `tool.py` contains no duplicated body for the eight actions — each is a delegation
- [ ] Existing scraping tests pass unchanged (no public API break)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.plan import ScrapingPlan

STUBBED = ["authenticate","upload_file","wait_for_download","get_cookies",
           "set_cookies","await_human","await_keypress","await_browser_event"]


class TestStubClosure:
    @pytest.mark.parametrize("action_type", STUBBED)
    async def test_no_silent_success(self, action_type, spy_driver, monkeypatch):
        """Every formerly-stubbed action must actually call its impl."""
        called = {}
        # patch the corresponding session_actions.exec_* and assert it ran
        ...
        plan = ScrapingPlan(url="http://x/", objective="t", steps=[{"action": action_type}])
        await execute_plan_steps(spy_driver, plan=plan)
        assert called.get(action_type), f"{action_type} still silently succeeded"

    async def test_unknown_action_returns_false(self, spy_driver):
        plan = ScrapingPlan(url="http://x/", objective="t", steps=[{"action": "teleport"}])
        result = await execute_plan_steps(spy_driver, plan=plan)
        assert not result.success or result.step_errors
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2387-dispatch-stub-closure-and-legacy-delegation.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
