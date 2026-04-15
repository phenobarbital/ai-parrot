# TASK-716: Integration Tests for PBAC Policy Rules

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-708, TASK-710, TASK-712, TASK-713, TASK-714
**Assigned-to**: unassigned

---

## Context

> End-to-end integration tests verifying the full policy flow: bot declares rules →
> registry registers with PDP → retrieval() enforces → handlers filter.
> Implements Spec Module 10 (integration tests).

---

## Scope

- Create integration test file `tests/auth/test_policy_rules_integration.py`.
- Test scenarios:
  1. Bot with `policy_rules` → `retrieval()` denies unauthorized user.
  2. Two bots with different policies → `ChatbotHandler._get_all()` returns only allowed.
  3. Per-agent YAML in `policies/agents/` → evaluator uses it for filtering.
  4. `ToolList.get()` filters tools based on policy.
  5. Bot without policy_rules → access allowed by default (fail-open).
- Use mocked PDP/evaluator (no need for real navigator-auth instance).
- Verify audit logging on denial.

**NOT in scope**: Performance benchmarks, MCP filtering, real HTTP server tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/auth/test_policy_rules_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All imports verified in prior tasks
from parrot.auth.models import PolicyRuleConfig
from parrot.registry import AgentRegistry, BotConfig
from navigator_auth.abac.policies.resources import ResourceType
from navigator_auth.abac.context import EvalContext
```

### Does NOT Exist
- ~~`parrot.auth.test_helpers`~~ — no test helpers module; create mocks inline
- ~~`PolicyEvaluator.reset()`~~ — no reset method; create fresh instances

---

## Implementation Notes

### Key Constraints
- Mock the PDP and evaluator — don't require navigator-auth ABAC to be fully running.
- Use `MagicMock` for `app['abac']` with `_evaluator` attribute.
- Test the flow, not the PDP internals.

---

## Acceptance Criteria

- [ ] All 5 integration test scenarios pass
- [ ] Tests pass: `pytest tests/auth/test_policy_rules_integration.py -v`
- [ ] No dependency on running services

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify all dependent tasks are done
3. **Write** comprehensive integration tests
4. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
