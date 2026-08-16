# TASK-2110: Implement `PBACToolCallGuardrail`

**Feature**: FEAT-406 — PBAC Guardrails
**Spec**: `sdd/specs/pbac-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2109
**Assigned-to**: unassigned

---

## Context

With the `TOOL_CALL` stage in place (TASK-2109), this task implements the concrete
`PBACToolCallGuardrail` — the guardrail that evaluates the shared `PolicyEvaluator`
(from `setup_pbac()`) per tool-call and maps ALLOW → PASS, DENY → BLOCK with a
structured denial report. It also registers the `"pbac"` name in the guardrail
registry for discoverability (the primary wiring path is instance-based via bot
configuration).

Implements spec §3 Module 2.

---

## Scope

- Create `PBACToolCallGuardrail` in `bots/guardrails/builtin/pbac.py`:
  - `name = "pbac"`, `stages = {GuardrailStage.TOOL_CALL}`, `priority = 10`
  - `on_error = "fail_closed"` (security control default)
  - `__init__(self, evaluator, *, logger=None)` — stores the shared evaluator
  - `async def check(self, content, ctx)`:
    - Extract `permission_context` from `ctx.extras`; if missing → PASS
    - Build `EvalContext` from session attributes
    - Build `Environment` snapshot (server local clock, business-hours config)
    - Call `evaluator.check_access(resource_type="TOOL", resource_name=ctx.tool_name)`
    - ALLOW → `GuardrailResult(action=PASS)`
    - DENY → `GuardrailResult(action=BLOCK, reason="policy:<rule>", report={...})`
  - Per-policy fail-mode: check `policy.attributes.get("enforcement")` via
    `PolicyResponse.rule`; if `"fail_open"` and evaluator raises → PASS
- Create `PolicyDenialReport` (Pydantic or plain dict) with: `rule`, `message`,
  `tool_name`, `retry_hint`
- Register `"pbac"` in `registry.py` via lazy factory
- Write unit tests

**NOT in scope**: ToolManager integration (TASK-2111), UserInfoService (TASK-2112),
or attribute enrichment from EmployeeProfile (TASK-2114).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` | CREATE | `PBACToolCallGuardrail` + `PolicyDenialReport` |
| `packages/ai-parrot/src/parrot/bots/guardrails/registry.py` | MODIFY | Add `"pbac"` lazy factory registration |
| `packages/ai-parrot/tests/unit/test_guardrails_pbac.py` | CREATE | Unit tests |

**Codebase Contract corrections (verified 2026-08-04)**:
1. Test path corrected from `packages/ai-parrot/tests/bots/guardrails/test_pbac_guardrail.py`
   (no such directory exists) to `packages/ai-parrot/tests/unit/test_guardrails_pbac.py`,
   matching the flat `test_guardrails_*.py` convention (`test_guardrails_secrets.py`, etc.).
2. `builtin/__init__.py` does NOT need modification — verified it stays empty by design
   (lazy-import discipline, per its own docstring); registration happens only in `registry.py`.
3. **`PolicyEvaluator.check_access()` does NOT return `PolicyResponse`** (that type is
   returned by the lower-level `ResourcePolicy.evaluate()`/`is_allowed()`, not by the
   evaluator entry point). Verified via
   `packages/ai-parrot/.venv/lib/python3.11/site-packages/navigator_auth/abac/policies/evaluator.py:59-71,402-511`:
   `check_access(ctx, resource_type, resource_name, action, env=None, ...)` is a
   **synchronous** method (not async) returning an `EvaluationResult` dataclass:
   `allowed: bool`, `effect: PolicyEffect`, `matched_policy: Optional[str]`,
   `reason: str`, `evaluation_time_ms: float`, `cached: bool`. `action` is a
   required parameter — use `action="tool:execute"` (mirrors
   `auth/resolver.py:322-328`'s Layer-2 call). This is the pattern actually used by
   both `PBACPermissionResolver.can_execute()` (`auth/resolver.py:312-339`) and
   `enforce_agent_access()` (`auth/agent_guard.py:266-278`) — both read
   `result.allowed` / `result.matched_policy` / `result.reason`, never
   `PolicyResponse.rule`/`.response`. `PBACToolCallGuardrail` follows the same
   real pattern: `reason="policy:<matched_policy>"`,
   `report.message = result.reason`.
4. **EvalContext construction**: use the existing bridge
   `parrot.auth.permission.to_eval_context(permission_context: PermissionContext) -> EvalContext`
   (`auth/permission.py:209-252`) rather than constructing `EvalContext` by hand —
   this is the exact helper `PBACPermissionResolver` itself uses
   (`auth/resolver.py:19,319`), and `ctx.extras["permission_context"]` is a
   `PermissionContext` instance per the spec's payload shape.
5. `ResourceType` import corrected to
   `from navigator_auth.abac.policies.resources import ResourceType` (verified
   present, `ResourceType.TOOL` exists) — the spec's contract omitted this import.
6. **Per-policy `enforcement: fail_open` lookup**: no public evaluator method
   exposes a single policy's `.attributes` by resource. `PolicyEvaluator` has a
   private `_index` (`PolicyIndex`) with `get_for_resource_type(ResourceType) ->
   list[ResourcePolicy]` and each `ResourcePolicy.covers_resource(resource_type,
   resource_name) -> bool` / `.attributes: dict` (set from `AbstractPolicy.__init__`
   `**kwargs`, `abstract.py:122`). On an evaluator exception, the guardrail does a
   best-effort private-attribute lookup (`evaluator._index...`) to find the policy
   that would have covered this tool and check `attributes.get("enforcement")`;
   documented as best-effort/fragile (private API) with a safe fail-closed fallback
   if the lookup itself fails for any reason.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.base import (     # base.py:15,30,45,63,87
    Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage,
)
from parrot.bots.guardrails.registry import register_guardrail  # registry.py:41
from navigator_auth.abac.context import EvalContext              # used at auth/agent_guard.py:181
from navigator_auth.abac.policies.environment import Environment # used at auth/agent_guard.py:252
from navigator_auth.abac.policies import PolicyResponse          # verified via inspect
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/base.py:87
class Guardrail(ABC):
    name: str
    stages: set[GuardrailStage]
    priority: int                              # bands: 0-99 / 100-199 / 200+
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"  # line 112
    @abstractmethod
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult  # line 115

# packages/ai-parrot/src/parrot/bots/guardrails/base.py:63
class GuardrailContext(BaseModel):
    stage: GuardrailStage
    agent_name: str
    user_id: str | None = None
    session_id: str | None = None
    method: str = ""
    tool_name: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

# packages/ai-parrot/src/parrot/bots/guardrails/base.py:45
class GuardrailResult(BaseModel):
    action: GuardrailAction
    content: str | None = None
    report: dict[str, Any] | None = None
    reason: str | None = None

# packages/ai-parrot/src/parrot/auth/agent_guard.py — EvalContext construction pattern
# line 181: from navigator_auth.abac.context import EvalContext
# line 252: from navigator_auth.abac.policies.environment import Environment
# line 267: result = evaluator.check_access(...)
# fail-open precedents: evaluator None → return (line 241); request None → return (line 244)

# navigator_auth (installed, >0.20.9):
# Environment (pydantic): time, timestamp, dow, hour, minute, date, day_segment,
#   is_business_hours, is_weekend, timezone;
#   is_business_hours from module config BUSINESS_HOURS_START/END, BUSINESS_DAYS;
#   accepts explicit timestamp/hour/minute at construction
# PolicyResponse(ClassDict): effect, response (str), rule (str), actions (list[str])
# PolicyEffect enum: ALLOW, DENY (from navigator_auth.abac.policies)

# packages/ai-parrot/src/parrot/bots/guardrails/registry.py — lazy factory pattern
# lines 146-165: register_guardrail("prompt_injection", _make_lazy_factory(...))
```

### Does NOT Exist
- ~~`PBACToolCallGuardrail`~~ — does not exist; this task creates it.
- ~~`PolicyDenialReport`~~ — does not exist; this task creates it.
- ~~`"pbac"` registry name~~ — not registered; only prompt_injection/secrets/moderation/groundedness exist.
- ~~`GuardrailContext.permission_context`~~ — not a direct attribute; access via `ctx.extras["permission_context"]`.
- ~~`Environment.enforcement`~~ — navigator-auth does NOT interpret `enforcement:`; it's in `policy.attributes`.
- ~~`Guardian.check_tool_call()`~~ — does not exist; evaluation is per-resource via `PolicyEvaluator.check_access()`.

---

## Implementation Notes

### Pattern to Follow
Mirror `auth/agent_guard.py:181-267` for EvalContext/Environment construction and
fail-open precedents. Mirror existing builtin guardrails (e.g. `secrets.py`) for
the class structure.

```python
class PBACToolCallGuardrail(Guardrail):
    name = "pbac"
    stages = {GuardrailStage.TOOL_CALL}
    priority = 10
    on_error = "fail_closed"

    def __init__(self, evaluator, *, logger=None):
        self._evaluator = evaluator
        self.logger = logger or logging.getLogger(__name__)

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        permission_context = ctx.extras.get("permission_context")
        if permission_context is None:
            return GuardrailResult(action=GuardrailAction.PASS)
        # Build EvalContext, Environment, call check_access...
```

### Key Constraints
- `PolicyResponse` is a `ClassDict` — access fields with `.get()`/`getattr` defensively
- `on_error = "fail_closed"` is the class default; per-policy `enforcement: fail_open` overrides for specific policies only
- Denial report must never carry raw policy YAML, other users' data, or rule internals beyond the operator-authored message
- `content` for TOOL_CALL is a compact serialized repr (for telemetry); structured payload in `ctx.extras`

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/agent_guard.py` — EvalContext/Environment construction pattern
- `packages/ai-parrot/src/parrot/bots/guardrails/builtin/secrets.py` — builtin guardrail class structure
- `packages/ai-parrot/src/parrot/bots/guardrails/registry.py:146-165` — lazy factory pattern

---

## Acceptance Criteria

- [ ] `PBACToolCallGuardrail` class exists in `bots/guardrails/builtin/pbac.py`
- [ ] ALLOW → `GuardrailResult(action=PASS)`, content untouched
- [ ] DENY → `GuardrailResult(action=BLOCK, reason="policy:<rule>", report=...)`; report carries `PolicyResponse.response`
- [ ] Missing `extras["permission_context"]` → PASS
- [ ] Evaluator error + `on_error="fail_closed"` → BLOCK `policy_engine_unavailable`
- [ ] Policy with `enforcement: fail_open` in attributes → engine error passes through
- [ ] `"pbac"` registered in guardrail registry via lazy factory
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/guardrails/test_pbac_guardrail.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/guardrails/test_pbac_guardrail.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.bots.guardrails.base import (
    GuardrailAction, GuardrailContext, GuardrailStage,
)


@pytest.fixture
def mock_evaluator():
    evaluator = AsyncMock()
    return evaluator


@pytest.fixture
def tool_call_ctx():
    return GuardrailContext(
        stage=GuardrailStage.TOOL_CALL,
        agent_name="test-agent",
        user_id="user-1",
        tool_name="some_tool",
        extras={"permission_context": MagicMock()},
    )


class TestPBACToolCallGuardrail:
    async def test_pbac_allow_maps_to_pass(self, mock_evaluator, tool_call_ctx):
        """ALLOW response maps to PASS action."""

    async def test_pbac_deny_maps_to_block_with_report(self, mock_evaluator, tool_call_ctx):
        """DENY response maps to BLOCK with denial report."""

    async def test_pbac_no_permission_context_passes(self, mock_evaluator):
        """Missing permission_context in extras → PASS."""

    async def test_pbac_engine_error_fail_closed(self, mock_evaluator, tool_call_ctx):
        """Evaluator raises → BLOCK policy_engine_unavailable."""

    async def test_pbac_enforcement_fail_open_downgrade(self, mock_evaluator, tool_call_ctx):
        """Policy with enforcement=fail_open → engine error passes through."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2109 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports and signatures
4. **Update status** in `sdd/tasks/index/pbac-guardrails.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2110-pbac-tool-call-guardrail.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-04
**Notes**: Implemented `PBACToolCallGuardrail` + `PolicyDenialReport` in
`bots/guardrails/builtin/pbac.py`, registered `"pbac"` in `registry.py` via
lazy factory. ALLOW → PASS; DENY → BLOCK with `reason="policy:<matched_policy>"`
and a `PolicyDenialReport` in `report`; missing `permission_context` → PASS
(session-scoped enforcement); evaluator exception → BLOCK
`policy_engine_unavailable` by default, downgraded to PASS when the covering
policy's `attributes["enforcement"] == "fail_open"`. 8 new unit tests +
full guardrails/auth regression suite (154 tests) pass; `ruff check` clean.

**Deviations from spec**: The task's Codebase Contract described
`evaluator.check_access()` returning a `PolicyResponse` (`.rule`/`.response`
fields) — verified against the installed `navigator_auth` package
(`abac/policies/evaluator.py`) that this is stale: `check_access()` is
**synchronous** and returns an `EvaluationResult` dataclass
(`allowed`/`matched_policy`/`reason`), matching the real pattern already
used by `PBACPermissionResolver.can_execute()` and `enforce_agent_access()`.
Implemented against the verified real API instead (documented in the task's
corrected Codebase Contract section above) — `PolicyResponse` is only
returned by the lower-level `ResourcePolicy.evaluate()`/`is_allowed()`, not
by the evaluator entry point the guardrail calls.
EvalContext construction reuses the existing `parrot.auth.permission.
to_eval_context()` bridge (same one `PBACPermissionResolver` uses) rather
than hand-building `EvalContext`, per the corrected contract.
Per-policy `enforcement: fail_open` lookup (only reachable on an evaluator
exception, since `check_access()` itself fails closed internally for engine
errors) uses a best-effort private-attribute reach into
`evaluator._index.get_for_resource_type()` — no public accessor exists for
a single policy's `.attributes` by resource; documented as fragile
best-effort with a safe fail-closed fallback if the lookup itself fails.
Test file path corrected to `tests/unit/test_guardrails_pbac.py`
(no `tests/bots/guardrails/` directory exists); `builtin/__init__.py` left
unmodified — verified it intentionally stays empty (lazy-import discipline).
