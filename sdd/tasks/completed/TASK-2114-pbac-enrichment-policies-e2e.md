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
- ~~Argument-level ABAC~~ — explicitly out of scope; assert tool args are NOT in policy attributes.

**Codebase Contract corrections (verified 2026-08-04)**:
1. **`policies/` directory already exists** at repo root (`policies/tools.yaml`,
   `agents.yaml`, `mcp.yaml`, `defaults.yaml`, `README.md`) and is loaded
   automatically at startup by `setup_pbac(app, policy_dir="policies")` —
   confirmed via `policies/README.md`: "All `*.yaml` files in this directory
   are loaded automatically at startup" and policy names must be "unique
   across ALL policy files". **A broad `resources: ["tool:*"]` DENY sample
   would become a live, active production policy gating every tool for
   every user outside business hours** — not a neutral template. To avoid
   an unreviewed production behavior change, the two sample policies use a
   narrowly-scoped, non-colliding demo resource pattern
   (`tool:demo_business_hours_only`) instead of a wildcard — fully
   loadable/functional (used by the e2e test) but inert for every real tool.
2. **`PolicyLoader.load_from_dict()` does NOT forward arbitrary top-level
   policy keys into `ResourcePolicy.attributes`** — verified against the
   installed `navigator_auth.abac.policies.evaluator.PolicyLoader.
   load_from_dict()` (constructs `ResourcePolicy(name=..., description=...,
   effect=..., resources=..., actions=..., subjects=..., conditions=...,
   environment=..., priority=..., enforcing=...)` — an explicit, closed
   kwarg list; no `**policy_data` passthrough). This means an
   `enforcement: fail_open` key in a YAML file is **silently dropped** when
   loaded via the standard `load_from_file`/`load_from_directory` path in
   the currently-pinned navigator-auth version — it only reaches
   `ResourcePolicy.attributes` (and thus `PBACToolCallGuardrail.
   _policy_enforcement()`, TASK-2110) when a `ResourcePolicy` is
   constructed **directly in Python** with `enforcement="fail_open"` as an
   extra kwarg (`AbstractPolicy.__init__`'s `**kwargs` → `self.attributes`,
   `abstract.py:122`, unaffected by the loader gap). The sample
   `tool-business-hours-soft.yaml` still documents the intended YAML syntax
   (forward-compatible once/if navigator-auth adds passthrough), but the
   e2e fail-open test constructs its `ResourcePolicy` directly to actually
   exercise the code path — documented as a known navigator-auth version
   limitation in `docs/security/pbac-guardrails.md`, not something this
   feature can or should fix (would require patching a pinned third-party
   package).
3. **`PolicyEvaluator._build_user_context(ctx)` (evaluator.py:295-306) only
   forwards `username`, `groups`, `roles` into the Rust evaluation engine**
   — `job_code`/`department_code`/`programs` are NOT read by
   `check_access()` regardless of what `EvalContext.userinfo` carries.
   Attribute enrichment is still implemented as specified (merges
   `EmployeeProfile` fields into `eval_ctx.userinfo`, verified mutable via
   `EvalContext.__setattr__`/`.store` in `navigator_auth/abac/context.py`)
   — `groups` enrichment has a REAL effect on evaluation (subject-group
   matching); `job_code`/`department_code`/`programs` are enriched onto the
   context for forward-compatibility/future policies but do not currently
   change any ALLOW/DENY outcome. Documented as a navigator-auth limitation
   in `docs/security/pbac-guardrails.md`, not a bug in this feature.
4. Test path corrected from
   `packages/ai-parrot/tests/bots/guardrails/test_pbac_e2e.py` (no such
   directory) to `packages/ai-parrot/tests/integration/test_pbac_guardrails_e2e.py`
   (mirrors `tests/integration/test_guardrails_output.py`'s location for
   integration/e2e-style guardrail tests).

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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-04
**Notes**: Added optional `userinfo_service` param + `_enrich_eval_context()`
to `PBACToolCallGuardrail` — merges `EmployeeProfile` attributes
(job_code/department_code/groups/programs) onto `EvalContext.userinfo`;
profile-fetch failures are logged and never block the call. Added
`policies/tool-business-hours.yaml` (+ `-soft` fail_open variant), scoped
to a demo-only resource pattern rather than a wildcard to avoid an
unreviewed production behavior change (every `*.yaml` in `policies/` loads
automatically at startup, per `policies/README.md`); each includes a
baseline ALLOW rule + a DENY-outside-hours override rule at equal priority
(DENY wins on match, per the documented priority/conflict rules) — verified
both files load cleanly alongside the existing policy set with no name
collisions (31 total policies, 0 duplicates). Added deprecation docstring
notes (no behavioral change) to `UserInfo`/`UserProfileKB`. Wrote
`docs/security/pbac-guardrails.md` covering the three enforcement layers,
guard-chain order, fail modes, sample policy YAML, the server-clock
limitation, and two documented navigator-auth version gaps (see below). 7
new e2e tests (business-hours DENY inside/outside a frozen clock, fail-open
downgrade against a real `ResourcePolicy`, telemetry never carries
content/args, KB regression, Layer-2 resolver still active, tool arguments
never reach policy evaluation) all pass against a REAL `PolicyEvaluator`;
full regression suite across guardrails/auth/tools/grants/confirmation
(227 tests) passes; `ruff check` clean on all changed files (`stores/kb/
user.py`'s 24 pre-existing lint errors are unchanged from baseline,
confirmed via `git stash`).

**Deviations from spec**: Two genuine navigator-auth version gaps were
discovered and are now documented (not "fixed", since that would mean
patching a pinned third-party package outside this feature's scope):
(1) `PolicyLoader.load_from_dict()` does not forward arbitrary top-level
YAML keys (like `enforcement:`) into `ResourcePolicy.attributes` — the
sample `-soft.yaml` documents the intended syntax for forward-compat, but
the e2e fail-open test constructs its `ResourcePolicy` directly in Python
to actually exercise the downgrade path. (2)
`PolicyEvaluator._build_user_context()` only forwards `username`/`groups`/
`roles` to the Rust evaluation engine — attribute enrichment is fully
implemented as specified and available on `EvalContext.userinfo`, but only
the `groups` enrichment currently changes any ALLOW/DENY outcome;
`job_code`/`department_code`/`programs` are enriched for
forward-compatibility. Sample policies are scoped to a demo-only resource
name (`tool:demo_business_hours_only[_soft]`) instead of `tool:*`, since
this directory's files are loaded live at startup (confirmed via
`policies/README.md` and by loading the full directory with the new files
present — no collisions). Test path corrected to
`packages/ai-parrot/tests/integration/test_pbac_guardrails_e2e.py` (no
`tests/bots/guardrails/` directory exists). All findings documented in the
task's corrected Codebase Contract section above before implementing.

**Post-review follow-up fix** (adversarial code review, same session):
`PolicyEvaluator.check_access()` was found to catch its own Rust-engine
exceptions internally and return a normal DENY `EvaluationResult`
(`matched_policy=None`, `reason="Evaluation engine error: ..."`) instead of
raising — making `PBACToolCallGuardrail`'s exception-based fail-mode
handling unreachable for this real failure, and leaking the raw internal
error string to the LLM as the denial message. Fixed in `check()` by
detecting this specific result shape and routing it through the same
`_policy_enforcement()`/fail-mode contract as a raised exception (sanitized
`"Policy engine is temporarily unavailable."` message, `enforcement:
fail_open` override still honored). Added 3 regression tests (2 unit,
mocking the exact `EvaluationResult` shape; 1 e2e, driving a genuine
failure through the real, unmodified `PolicyEvaluator.check_access()` by
patching `evaluate_single`) plus a documentation update
(`docs/security/pbac-guardrails.md`) explaining both failure shapes and the
already-documented subject/condition-blindness of the fail-open lookup.
230 tests pass; `ruff check` clean. See commit
"fix(pbac-guardrails): route internal engine-error DENY through fail-mode
contract".
