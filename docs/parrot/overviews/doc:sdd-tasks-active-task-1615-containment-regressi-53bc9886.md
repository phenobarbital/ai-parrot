---
type: Wiki Overview
title: 'TASK-1615: Containment integration + non-regression test suite (G5)'
id: doc:sdd-tasks-active-task-1615-containment-regression-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5, §4 Integration Tests, G5. The unit tests live with their
  modules;
relates_to:
- concept: mod:parrot.security.command_sanitizer
  rel: mentions
- concept: mod:parrot.security.python_sanitizer
  rel: mentions
- concept: mod:parrot.security.redaction
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.pythonrepl
  rel: mentions
---

# TASK-1615: Containment integration + non-regression test suite (G5)

**Feature**: FEAT-252 — REPL Sandbox + Gemini Response Contract + Secret Scrubber
**Spec**: `sdd/specs/repl-sandbox-response-contract-scrubber.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1611, TASK-1612, TASK-1613, TASK-1614
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, §4 Integration Tests, G5. The unit tests live with their modules;
this task adds the **cross-cutting** assurance: the original incident is contained
end-to-end (defense in depth), the in-process REPL state path still works, and the
WS2 refactor never opened a redaction gap. It also locks the shipped `0f76129b1`
behavior so the consolidation can't silently regress it.

---

## Scope

- Add an end-to-end **incident-containment** test proving the `os.environ.keys()`
  scenario is stopped at **every** layer: (a) denied by the WS1 gate, (b) scrubbed by
  the WS3 seam if it somehow surfaces, (c) not echoed by the WS2 chokepoint.
- Add a **no-redaction-gap** test that asserts secrets never leak through any Gemini
  terminal after TASK-1613 removed the scattered calls.
- Add a **REPL state-preservation** test: `_inject_context_to_repl` + the dataset
  `_repl_locals_getter` path still work under the allowlist gate (no subprocess regression).
- Verify the `0f76129b1` tests still pass as part of the suite.

**NOT in scope**: implementing any of the four components (owned by TASK-1611..1614);
performance benchmarking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_feat252_containment.py` | CREATE | E2E incident-containment + no-gap + state-preservation |
| `packages/ai-parrot/tests/test_pythonrepl_security.py` | MODIFY | Add incident-scenario assertion if not covered by TASK-1614 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# all available after TASK-1611..1614
from parrot.security.command_sanitizer import SecurityPolicy, CommandSanitizer
from parrot.security.redaction import OutputScrubber, ScrubPolicy
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.abstract import AbstractTool, ToolResult
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/  — existing committed tests (must keep passing):
#   test_pythonrepl_security.py   (38 lines, from 0f76129b1)
#   test_google_client.py         (edited in 0f76129b1)

# integration anchors:
#   parrot/tools/agent.py:_inject_context_to_repl                 # line 404 (writes python_repl.globals)
#   parrot/tools/dataset_manager/tool.py:set_repl_locals_getter   # line 604
#   parrot/tools/abstract.py:AbstractTool.execute -> ToolResult   # line 473 (scrub seam)
#   parrot/clients/google/client.py:_resolve_final_response       # NEW (TASK-1613)
```

### Does NOT Exist
- ~~a pre-existing FEAT-252 integration test~~ — this task CREATES it.
- ~~a subprocess REPL to test~~ — Non-Goal; assert in-process state still works.
- Do not assume a global test runner config beyond `pytest packages/ai-parrot/tests`.

---

## Implementation Notes

### Pattern to Follow
- Use fakes/fixtures (the existing tests use fakes, not live LLM calls). Inject a
  fake `os.environ` fixture; never read real secrets.
- For the no-gap test, drive a fake Gemini response whose candidate text / tool
  result contains a secret and assert the final `AIMessage` text is scrubbed.

### Key Constraints
- Deterministic, no network, no real model calls.
- Assert **absence** of the secret value in outputs and logs (defense in depth across layers).

### References in Codebase
- Spec §4 Integration Tests (the three named tests).
- `sdd/state/FEAT-252/findings/F008-shared-state-coupling.md` — the state path to protect.

---

## Acceptance Criteria

- [ ] `test_incident_scenario_contained` passes: `os.environ.keys()` is denied AND scrubbed-if-surfaced AND not echoed.
- [ ] `test_no_redaction_gap_during_refactor` passes: no secret leaks through any Gemini terminal.
- [ ] `test_data_analysis_repl_state_preserved` passes: context injection + DataFrame getter still work.
- [ ] Full suite green: `pytest packages/ai-parrot/tests -v` (including the `0f76129b1` tests).
- [ ] `ruff check packages/ai-parrot/tests/test_feat252_containment.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_feat252_containment.py
import pytest

class TestIncidentContainment:
    async def test_incident_scenario_contained(self, repl_tool, fake_environ):
        res = await repl_tool.execute(code="import os; os.environ.keys()")
        # layer 1: denied by the gate (structured refusal, no values)
        assert "ODOO_EPSON_PRODUCTION_PASSWORD" not in str(res.result)

    def test_no_redaction_gap_during_refactor(self, gemini_client, secret_bearing_response):
        msg = gemini_client._resolve_final_response(
            secret_bearing_response.text, secret_bearing_response.tool_calls, None)
        assert "s3cr3t" not in msg

    async def test_data_analysis_repl_state_preserved(self, agent_with_repl):
        # context injection still lands in python_repl.globals; compute still runs
        ...
```

---

## Agent Instructions
(standard — verify all four dependencies are in `completed/` before starting.)

## Completion Note
*(Agent fills this in when done)*
