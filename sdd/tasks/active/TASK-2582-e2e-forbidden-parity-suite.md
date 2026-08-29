# TASK-2582: E2E FORBIDDEN coverage + branch-parity regression suite

**Feature**: FEAT-474 — ToolManager ToolDefinition Enforcement Parity (G7 remediation)
**Spec**: `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2580, TASK-2581
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / Goal G8 (second half). FEAT-469's escalation is only
truly closed when a test proves, through the real A2UI HTTP surface, that a
denied `@tool` invocation returns `error{code:"FORBIDDEN"}` — making AC-G7
of the FEAT-469 spec true for every tool kind. This task adds that e2e plus
the cross-branch parity regression suite that keeps the two dispatch
branches from drifting apart again.

---

## Scope

- Add `test_e2e_http_call_agent_function_forbidden` to the A2UI e2e suite,
  modeled on the existing allow-path test
  (`test_a2ui_e2e.py:110 test_e2e_http_call_agent_function`): register a
  `@tool` function, configure a denying resolver (or role-gated PBAC), POST
  a `callAgentFunction` envelope, assert the response envelope carries
  `error` with `code == "FORBIDDEN"`, the function did NOT execute, and the
  `a2ui_audit` line logged the denied status.
- Confirm `test_e2e_http_call_agent_function` (allow path) passes untouched.
- Add the branch-parity suite: under one identical
  resolver/guardrail/confirmation configuration, a `@tool` function and an
  equivalent `AbstractTool` are BOTH denied with the same status and error
  shape (status `forbidden`, `Permission denied: '<name>' requires {...}`
  message, metadata keys).
- Add fail-open regressions (no pctx / no resolver ⇒ both kinds execute)
  and the raw-return regression for successful ToolDefinition calls, IF not
  already covered by TASK-2580's unit tests (extend, don't duplicate).
- Run the feature-owned suites plus a full-repo sanity pass; record results.

**NOT in scope**: implementation changes (if a test exposes a defect,
report it against TASK-2580 scope in the completion note and fix within
that file scope); performance/load testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py` | MODIFY | Add FORBIDDEN-path e2e test |
| `packages/ai-parrot-tools/tests/test_manager_permissions.py` | MODIFY | Branch-parity denial tests |
| `packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` | MODIFY | Any remaining fail-open/raw-return gaps |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Reuse the imports/fixtures already present in:
#   packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py
#     (aiohttp_client harness; allow-path test at line 110 is the template)
#   packages/ai-parrot-tools/tests/test_manager_permissions.py
#     (ToolManager resolver-injection fakes)
from parrot.tools.manager import ToolDefinition, ToolManager
from parrot.tools.decorators import tool
from parrot.auth.resolver import AbstractPermissionResolver
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py:110
async def test_e2e_http_call_agent_function(self, aiohttp_client, tmp_path):
    # THE template: shows the full envelope shape, endpoint path, auth/session
    # setup, and how the agent + ToolManager are wired for e2e. Mirror it.

# Denial shape produced by TASK-2580 (mirrors abstract.py:880-890):
# ToolResult(success=False, status="forbidden",
#   error="Permission denied: '<name>' requires {...}",
#   metadata={"tool_name", "user_id", "required_permissions"})

# A2UI error mapping: ToolResult.status "forbidden" →
# envelope error{code:"FORBIDDEN"} per FEAT-469 AC-G7
# (sdd/specs/a2ui-agent-functions.spec.md:392). Verify the mapping site in
# the a2ui runtime (grep for "FORBIDDEN") before asserting exact JSON.

# Security-posture fact (docs/outputs/a2ui-agent-functions.md §4):
# build_principal_context defaults roles to empty frozenset() ⇒ role-gated
# policies deny by default — usable to build the deny config without a
# custom resolver if the harness wires PBAC.
```

### Does NOT Exist
- ~~A deny-path e2e for agent functions~~ — this task ADDS the first one
- ~~`error{code:"PERMISSION_DENIED"}`~~ — the A2UI code is `"FORBIDDEN"`
  (AC-G7 wording); do not assert a different code
- ~~Grant-based denial for @tool functions~~ — grants are not enforceable on
  ToolDefinition (spec Non-Goal); build the deny via resolver/PBAC, not grants

---

## Implementation Notes

### Key Constraints
- The FORBIDDEN e2e must go through the HTTP surface (same harness as the
  allow test), not by calling `ToolManagerExecutor` directly — the point is
  proving the full chain.
- Prove non-execution with a side-effect probe (list append) in the `@tool`
  function, not just the error response.
- Parity test must compare status AND error message shape between branches
  to lock the `abstract.py:880-890` mirroring.
- pytest-asyncio conventions per the existing files; keep fixtures local to
  the suites being extended.
- Full-repo sanity pass: run the standard project pytest invocation and
  save evidence to `artifacts/logs/` (project convention).

### References in Codebase
- `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py:110` —
  allow-path template
- `packages/ai-parrot/tests/test_confirmation_e2e.py` — e2e-style guard
  test patterns

---

## Acceptance Criteria

- [ ] AC-10: `test_e2e_http_call_agent_function_forbidden` passes — denied
  `@tool` via A2UI HTTP ⇒ `error{code:"FORBIDDEN"}`, function not executed,
  audit line present
- [ ] AC-10: `test_e2e_http_call_agent_function` (allow) passes UNTOUCHED
- [ ] Branch-parity denial test passes (identical status/error shape)
- [ ] Fail-open + raw-return regressions covered (here or in TASK-2580 tests)
- [ ] Feature-owned suites green:
  `pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py packages/ai-parrot-tools/tests/test_manager_permissions.py packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py -v`
- [ ] Full-repo sanity pass: zero new regressions outside feature file scope
  (evidence in `artifacts/logs/`)
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py (addition)
async def test_e2e_http_call_agent_function_forbidden(self, aiohttp_client, tmp_path):
    """A renderer-invoked @tool function denied by the resolver returns
    error{code:'FORBIDDEN'} and never executes (FEAT-474 / FEAT-469 AC-G7)."""
    executed = []

    @tool(required_permissions={"secret:read"})
    def guarded_fn(x: int) -> str:
        """Guarded test function."""
        executed.append(x)
        return f"secret {x}"

    # ...same harness setup as test_e2e_http_call_agent_function (line 110),
    # plus a resolver that denies "secret:read"...
    # resp = POST callAgentFunction envelope for "guarded_fn"
    assert resp_envelope["error"]["code"] == "FORBIDDEN"
    assert executed == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2580 and TASK-2581 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code — especially the
   FORBIDDEN mapping site (grep the a2ui runtime) and the e2e harness shape
4. **Update status** in `sdd/tasks/index/toolmanager-tooldefinition-enforcement.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2582-e2e-forbidden-parity-suite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
