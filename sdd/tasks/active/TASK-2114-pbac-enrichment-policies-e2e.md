# TASK-2114: PBAC Attribute Enrichment + Sample Policies + E2E Tests

**Feature**: FEAT-406 — PBAC Guardrails
**Spec**: `sdd/specs/pbac-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2111, TASK-2113
**Assigned-to**: unassigned

---

## Context

This is the join task that connects both lanes. It wires `EmployeeProfile` attributes
into the `PBACToolCallGuardrail`'s `EvalContext` (optional enrichment — the guardrail
works without it, but profile attributes enable richer policies), adds sample
business-hours DENY policies with the `enforcement:` key, adds the deprecation note
to `stores/kb/user.py`, writes documentation, and covers the full end-to-end test
suite.

Implements spec §3 Module 6.

---

## Scope

- **PBAC attribute enrichment** in `bots/guardrails/builtin/pbac.py`:
  - Optional `UserInfoService` dependency injected at guardrail construction
  - When available, fetch `EmployeeProfile` and project selected attributes
    (job_code, department_code, groups, programs) into the `EvalContext`
  - Profile fetch failure → log warning, continue with session-only attributes
    (never block due to profile unavailability)
- **Sample policies** in `policies/`:
  - `tool-business-hours.yaml` — DENY rule for tools outside business hours
    with `enforcement: fail_closed` (default)
  - `tool-business-hours-soft.yaml` — same but with `enforcement: fail_open`
    (demonstrates the per-policy downgrade)
  - Include `retry_hint` in the policy response message
- **Deprecation note** in `stores/kb/user.py`:
  - Add docstring note to `UserInfo` and `UserProfileKB` pointing to
    `UserInfoService` as the preferred structured source (no behavioral changes)
- **Documentation** at `docs/security/pbac-guardrails.md`:
  - Three enforcement layers (L1 filtering, L2 resolver, L3 guardrail)
  - Guard-chain order diagram
  - Sample policy YAML with explanation
  - Server-clock limitation note
- **End-to-end integration tests**:
  - `test_business_hours_deny_e2e` — frozen clock outside window → forbidden; inside → executes
  - `test_telemetry_no_content` — TOOL_CALL telemetry has name/stage/action/duration, never content/args
  - `test_kb_regression` — `UserInfo`/`UserProfileKB` behavior unchanged
  - `test_layer2_resolver_still_active` — `PBACPermissionResolver.can_execute` still invoked
  - `test_arguments_not_in_policy_attributes` — tool-call args NOT projected into policy eval

**NOT in scope**: Final-response guardrails, argument-level ABAC, per-policy
timezone, availability windows in tool descriptions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` | MODIFY | Add optional `UserInfoService` + profile enrichment in `check()` |
| `policies/tool-business-hours.yaml` | CREATE | Sample DENY policy (business hours) |
| `policies/tool-business-hours-soft.yaml` | CREATE | Sample fail_open variant |
| `packages/ai-parrot/src/parrot/stores/kb/user.py` | MODIFY | Add deprecation docstring note only |
| `docs/security/pbac-guardrails.md` | CREATE | Documentation for the three enforcement layers |
| `packages/ai-parrot/tests/bots/guardrails/test_pbac_e2e.py` | CREATE | Integration / e2e tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.builtin.pbac import PBACToolCallGuardrail  # TASK-2110
from parrot.auth.userinfo import UserInfoService, EmployeeProfile       # TASK-2112
from parrot.auth import PBACPermissionResolver, setup_pbac              # auth/__init__.py
from navigator_auth.abac.context import EvalContext
from navigator_auth.abac.policies.environment import Environment
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/stores/kb/user.py:11
class UserInfo(AbstractKnowledgeBase):         # always_active=True
    """..."""                                   # add deprecation note HERE

# packages/ai-parrot/src/parrot/stores/kb/user.py:78
class UserProfileKB(AbstractKnowledgeBase):
    """..."""                                   # add deprecation note HERE

# packages/ai-parrot/src/parrot/auth/resolver.py:247
class PBACPermissionResolver(AbstractPermissionResolver):
    async def can_execute(self, context, tool_name, required_permissions) -> bool

# EvalContext — accepts arbitrary attribute dicts at construction
# Environment — is_business_hours from module config; accepts explicit hour/minute
```

### Does NOT Exist
- ~~`PBACToolCallGuardrail.userinfo_service`~~ — attribute enrichment not yet wired; this task adds it.
- ~~`EvalContext.employee_profile`~~ — not a direct field; profile attributes are projected as flat attributes.
- ~~Per-policy timezone~~ — `Environment` business hours are global; no per-policy tz.
- ~~`policies/` directory with tool policies~~ — may or may not exist; verify before creating.
- ~~Argument-level ABAC~~ — explicitly out of scope; assert tool args are NOT in policy attributes.

---

## Implementation Notes

### Pattern to Follow
For attribute enrichment in `pbac.py`:
```python
async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
    # ... existing permission_context check, EvalContext build ...
    # Optional profile enrichment
    if self._userinfo_service is not None:
        try:
            profile = await self._userinfo_service.get_profile(user_id)
            if profile:
                # Project selected attributes into eval context
                eval_attrs.update({
                    "job_code": profile.job_code,
                    "department_code": profile.department_code,
                    "groups": profile.groups,
                    "programs": profile.programs,
                })
        except Exception:
            self.logger.warning("Profile enrichment failed for user %s", user_id)
    # ... continue with check_access() ...
```

### Sample Policy YAML
```yaml
# policies/tool-business-hours.yaml
name: tool-business-hours
description: Deny tool calls outside business hours
resource_type: TOOL
resource_name: "*"
effect: DENY
conditions:
  is_business_hours: false
response: "This tool is only available during business hours (Mon-Fri 08:00-18:00)"
enforcement: fail_closed
```

### Key Constraints
- Profile fetch failure must NEVER cause a tool-call denial — log and continue
- Deprecation notes in `stores/kb/user.py` are docstring-only — no behavioral changes
- Telemetry must never include tool arguments or content
- `PBACPermissionResolver` must still be invoked (defense-in-depth)
- Document the server-clock limitation in docs

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` — from TASK-2110
- `packages/ai-parrot/src/parrot/auth/agent_guard.py` — EvalContext construction pattern
- `packages/ai-parrot/src/parrot/stores/kb/user.py` — KBs to annotate
- `packages/ai-parrot/src/parrot/auth/resolver.py:247` — Layer-2 resolver

---

## Acceptance Criteria

- [ ] Profile attributes (job_code, department_code, groups, programs) projected into EvalContext when UserInfoService available
- [ ] Profile fetch failure → warning log, NOT a tool-call denial
- [ ] Sample `tool-business-hours.yaml` policy: outside window → denied with operator message; inside → passes
- [ ] Sample `tool-business-hours-soft.yaml` with `enforcement: fail_open`
- [ ] `UserInfo`/`UserProfileKB` docstrings have deprecation notes; behavior unchanged
- [ ] `docs/security/pbac-guardrails.md` documents three layers, guard order, sample YAML, server-clock caveat
- [ ] E2E: business-hours DENY + frozen clock → forbidden ToolResult; inside window → tool executes
- [ ] E2E: telemetry has name/stage/action/duration, never content/arguments
- [ ] E2E: `UserInfo`/`UserProfileKB` behavior regression passes
- [ ] E2E: `PBACPermissionResolver.can_execute` still invoked alongside guardrail
- [ ] E2E: tool-call arguments NOT projected into policy attributes
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/guardrails/test_pbac_e2e.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/guardrails/test_pbac_e2e.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


@pytest.fixture
def shared_evaluator(tmp_path):
    """PolicyEvaluator loaded from sample business-hours DENY policy."""

@pytest.fixture
def frozen_environment(monkeypatch):
    """Patch Environment clock to deterministic inside/outside business hours."""

@pytest.fixture
def fake_vw_users(monkeypatch):
    """Stub asyncdb fetch_one for auth.vw_users rows."""


class TestBusinessHoursE2E:
    async def test_business_hours_deny_e2e(self, shared_evaluator, frozen_environment):
        """Outside business hours → forbidden ToolResult; inside → executes."""

    async def test_business_hours_fail_open(self, shared_evaluator):
        """Policy with enforcement=fail_open + engine error → passes through."""


class TestTelemetry:
    async def test_telemetry_no_content(self):
        """TOOL_CALL telemetry has name/stage/action/duration, never content/args."""


class TestRegressions:
    async def test_kb_regression(self, fake_vw_users):
        """UserInfo/UserProfileKB behavior unchanged with feature enabled."""

    async def test_layer2_resolver_still_active(self):
        """PBACPermissionResolver.can_execute still invoked alongside guardrail."""

    async def test_arguments_not_in_policy_attributes(self):
        """Tool-call arguments NOT projected into policy eval attributes."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2111 and TASK-2113 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm all files from prior tasks exist
4. **Verify `policies/` directory** exists; create if needed
5. **Update status** in `sdd/tasks/index/pbac-guardrails.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2114-pbac-enrichment-policies-e2e.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
