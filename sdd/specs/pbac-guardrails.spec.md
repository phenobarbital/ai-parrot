---
type: feature
base_branch: dev
---

# Feature Specification: PBAC Guardrails — Policy-Driven Tool-Call Denial + UserinfoTool

**Feature ID**: FEAT-406
**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x.x
**Proposal**: `sdd/proposals/pbac-guardrails.brainstorm.md` (Option A)
**Builds on**: FEAT-396 (guardrails-infrastructure), FEAT-077 (policy-based-access-control), FEAT-101 (policy-rules-abstractbot)

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot already enforces PBAC at two layers (FEAT-077 / FEAT-101): handler-level
filtering via `Guardian.filter_resources()` (unauthorized tools become **invisible**
to the agent) and `PBACPermissionResolver` as a Layer-2 safety net inside
`AbstractTool.execute()` (silent deny + audit log). What is missing is a **third,
explainable enforcement point**: a Guardrail at the **tool-call** moment that
evaluates the navigator-auth policy engine (Rust core, near-zero latency) with its
full attribute richness — user attributes, capabilities, environment variables —
and returns a **structured, explicit DENY to the LLM** so the agent can tell the
user *why* the action was refused.

The canonical example: a `business-hours` DENY rule. The tool remains visible
(the user should know the capability exists), but calling it at 22:00 returns a
policy denial ("outside business hours") that the LLM verbalizes. Invisibility
(Layer 1) cannot express this; the Layer-2 resolver only returns a boolean and
hides the reason.

A second, coupled gap: the PBAC engine needs structured user attributes, but the
current `UserInfo` / `UserProfileKB` knowledge bases (`parrot/stores/kb/user.py`)
flatten `auth.vw_users` into prose "facts" injected into `<userdata>` in the
system prompt. There is no single structured source (`user_id`, `username`,
`job_code`, `groups`, `programs`, …) that (a) feeds PBAC evaluation server-side
and (b) is available to the LLM as queryable, JSON-based data.

### Goals

- Add a `TOOL_CALL` pre-execution stage to the FEAT-396 guardrails pipeline —
  generic infrastructure any future tool-call guardrail plugs into.
- Ship `PBACToolCallGuardrail` (`"pbac"`): evaluates the **shared**
  `PolicyEvaluator` (same instance as Guardian and `PBACPermissionResolver`,
  wired by `setup_pbac()`) per tool-call with `(user, tool, environment)`
  attributes.
- Translate a policy DENY into `ToolResult(success=False, status="forbidden",
  error=<operator-authored reason>)` so the LLM verbalizes the denial and the
  agent loop continues — a denial is a normal turn, never an exception.
- Fail mode: `on_error="fail_closed"` by default; per-policy downgrade via an
  `enforcement: fail_open` extra key in policy YAML (lands in
  `policy.attributes`, located via `PolicyResponse.rule`).
- Introduce `UserInfoService` — single source of truth for the curated,
  structured `EmployeeProfile` (from `auth.vw_users`, TTL-cached) — feeding both
  PBAC `EvalContext` construction and the new per-agent activatable
  `UserinfoTool`.
- Preserve every existing behavior: Layer 1 filtering, Layer-2 resolver,
  `GrantGuard`/`ConfirmationGuard`, existing KBs, and zero-overhead empty
  pipelines.

### Non-Goals (explicitly out of scope)

- **Final-response / topic guardrails** — no output-content classification in
  this feature (deferred by design; brainstorm discovery decision).
- **Argument-level ABAC** — v1 evaluates `(user, tool, environment)` only,
  consistent with FEAT-077's non-goal. Tool-call arguments are carried in
  `GuardrailContext.extras` but NOT projected into policy attributes.
- **Per-policy timezone** for business-hours conditions — v1 uses the server
  local clock + navigator's global `BUSINESS_HOURS_*`/`BUSINESS_DAYS` config
  (resolved Q2). `Environment` accepts explicit `timestamp`/`hour`/`minute`,
  so a v2 can inject tz-adjusted time without touching navigator-auth.
- **Policy availability windows rendered into tool descriptions** (the
  brainstorm's Option C add-on) — separate follow-up feature (resolved Q5).
- **Migration/removal of `UserInfo`/`UserProfileKB`** — the KBs coexist
  untouched in v1 (deprecation note only).
- A ToolManager-only `PolicyGuard` (brainstorm Option B) and an agent-loop
  batch interceptor (Option C) were rejected — see
  `sdd/proposals/pbac-guardrails.brainstorm.md`.

---

## 2. Architectural Design

### Overview

Option A from the brainstorm: extend the FEAT-396 guardrails infrastructure
with a pre-execution `GuardrailStage.TOOL_CALL` member and hook it into
`ToolManager.execute_tool()` **before** the existing guard chain — order:
**TOOL_CALL/PBAC → GrantGuard → ConfirmationGuard** (resolved during spec
review: policy evaluation is sub-ms and deterministic, so it must run before a
human is interrupted for confirmation or a grant is consumed on a call the
policy will deny anyway).

`content` for the TOOL_CALL pipeline is a compact serialized representation of
the call (for telemetry/log purposes); `ctx.extras` carries the structured
payload `{"tool_name", "arguments", "permission_context"}`.

`PBACToolCallGuardrail` builds an `EvalContext` from the
`PermissionContext`/session plus an `Environment` snapshot (server local clock;
navigator's global business-hours config), calls the shared
`PolicyEvaluator.check_access()` for `resource_type=TOOL,
resource_name=<tool_name>`, and maps:
- ALLOW → `GuardrailResult(action=PASS)`
- DENY → `GuardrailResult(action=BLOCK, reason="policy:<PolicyResponse.rule>",
  report={structured denial: policy id, human message from
  `PolicyResponse.response`, retry hint})`

The dispatch site translates a blocked `PipelineOutcome` into
`ToolResult(success=False, status="forbidden", error=<human-readable reason>)` —
the same denial shape `GrantGuard` uses — so the LLM sees the denial as the
tool's result and explains it to the user. The agent loop continues normally.

**Guardrail construction (resolved Q7)**: the `"pbac"` name is registered in
the guardrail registry for discoverability, but the concrete instance is
constructed by **bot wiring** — `PBACToolCallGuardrail(evaluator=...)` passed
as an instance entry in `guardrails=[...]` — because the registry's
kwargs-only factory cannot carry the shared evaluator. Explicit, testable, no
global state.

**Defense-in-depth (resolved Q4)**: `PBACPermissionResolver` (Layer 2) stays
active unchanged. The resolver covers invocation paths that bypass
`ToolManager` (direct `AbstractTool.execute()`); the shared evaluator + its 30s
decision cache make the double evaluation negligible.

**UserInfoService (resolved Q6)**: owns the curated `EmployeeProfile`
(Pydantic), loaded from `auth.vw_users` via asyncdb and TTL-cached per user.
`manager` is a nested `{user_id, display_name, email}` object resolved with one
extra lookup. Consumed by (a) PBAC `EvalContext`/attribute enrichment and
(b) `UserinfoTool`, which returns the profile as JSON for the **current session
user only** — identity always comes from the session/`PermissionContext`,
never from an LLM-supplied argument.

### Component Diagram

```
┌──────────────────────────── Startup ─────────────────────────────────┐
│ setup_pbac(app) ──→ PolicyEvaluator (shared) ──→ Guardian / PDP      │
│        │                     │                                       │
│        │                     ├──→ PBACPermissionResolver (Layer 2)   │
│        │                     └──→ PBACToolCallGuardrail(evaluator=…) │
│        │                            (built by bot wiring, passed as  │
│        │                             instance in guardrails=[...])   │
│ UserInfoService (auth.vw_users, TTLCache) ──→ EmployeeProfile        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────── Per tool-call ───────────────────────────────┐
│ LLM emits tool_call                                                  │
│   └─ ToolManager.execute_tool(tool_name, params, permission_context) │
│        ├─ 1. TOOL_CALL GuardrailPipeline.run()          ← NEW        │
│        │     └─ PBACToolCallGuardrail.check()                        │
│        │          ├─ EvalContext(session attrs [+ EmployeeProfile])  │
│        │          ├─ Environment(server clock, business hours)       │
│        │          └─ evaluator.check_access(TOOL, <tool_name>)       │
│        │               ├─ ALLOW → PASS (continue)                    │
│        │               └─ DENY  → BLOCK → ToolResult(                │
│        │                     status="forbidden",                     │
│        │                     error=PolicyResponse.response)  → LLM   │
│        ├─ 2. GrantGuard (FEAT-211, unchanged)                        │
│        ├─ 3. ConfirmationGuard (FEAT-235, unchanged)                 │
│        └─ 4. tool.execute()                                          │
│              └─ PBACPermissionResolver (Layer 2, unchanged)          │
└──────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GuardrailStage` (`bots/guardrails/base.py:15`) | modifies | Add `TOOL_CALL = "tool_call"` member + docstring line. |
| `build_pipelines_from_config` (`bots/guardrails/config.py:39`) | unchanged (behavioral) | Iterates the enum (config.py:100-102) — new stage's pipeline is built automatically. |
| Guardrail registry (`bots/guardrails/registry.py`) | extends | `register_guardrail("pbac", …)` lazy factory (discoverability; instance path is primary). |
| `bots/guardrails/builtin/` | extends | New `pbac.py` — `PBACToolCallGuardrail`. |
| `ToolManager.execute_tool()` (`tools/manager.py:1422`) | modifies | Run TOOL_CALL pipeline FIRST (before GrantGuard at ~manager.py:1477); translate BLOCK → `ToolResult(status="forbidden")`. New attr `_tool_call_pipeline` (mirror of `_tool_output_pipeline`, manager.py:290). |
| `AbstractBot` wiring (`bots/abstract.py:668,747`) | modifies | Stamp `tool_manager._tool_call_pipeline = self._guardrail_pipelines[GuardrailStage.TOOL_CALL]` (same seam as line 747); construct `PBACToolCallGuardrail(evaluator=…)` when PBAC is enabled and `"pbac"` requested. |
| `setup_pbac()` (`auth/pbac.py:35`) | unchanged | Already returns the shared evaluator; bot wiring consumes it. |
| `PBACPermissionResolver` (`auth/resolver.py:247`) | unchanged | Layer 2 stays active (resolved Q4). |
| `GrantGuard` / `ConfirmationGuard` (manager.py guard chain) | unchanged | Chain order becomes pbac → grant → confirm. |
| `parrot/auth/` | extends | New `userinfo.py` — `EmployeeProfile` + `UserInfoService`. |
| `parrot/tools/` | extends | New `userinfo.py` — `UserinfoTool(AbstractTool)`. |
| `parrot/stores/kb/user.py` | unchanged | KBs coexist; add deprecation note in docstring only. |
| `policies/*.yaml` | extends | Sample tool policies incl. business-hours DENY + `enforcement:` key. |

### Data Models

```python
# NEW — parrot/auth/userinfo.py (no implementation code; shapes only)
class ManagerRef(BaseModel):
    user_id: int | str
    display_name: str | None
    email: str | None

class EmployeeProfile(BaseModel):
    user_id: int | str
    username: str | None
    display_name: str | None
    email: str | None
    job_code: str | None
    title: str | None
    department_code: str | None
    groups: list[str]
    programs: list[str]
    worker_type: str | None
    manager: ManagerRef | None          # resolved Q6: nested object, not raw id

# NEW — bots/guardrails/builtin/pbac.py (denial report attached to
# GuardrailResult.report; never carries other users' data or raw policy YAML)
class PolicyDenialReport(BaseModel):    # or plain dict with these keys
    rule: str                           # PolicyResponse.rule
    message: str                        # PolicyResponse.response (operator-authored)
    tool_name: str
    retry_hint: str | None              # e.g. "available Mon-Fri 08:00-18:00"
```

### New Public Interfaces

```python
# bots/guardrails/builtin/pbac.py
class PBACToolCallGuardrail(Guardrail):
    name = "pbac"
    stages = {GuardrailStage.TOOL_CALL}
    priority = 10                       # sanitizer band (0-99): runs before any other TOOL_CALL guardrail
    on_error = "fail_closed"            # security control default (resolved Q3)
    def __init__(self, evaluator: "PolicyEvaluator", *, logger=None): ...
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...

# auth/userinfo.py
class UserInfoService:
    async def get_profile(self, user_id) -> EmployeeProfile | None: ...

# tools/userinfo.py
class UserinfoTool(AbstractTool):
    name = "userinfo"
    # returns the session user's EmployeeProfile as JSON; no identity argument
```

---

## 3. Module Breakdown

### Module 1: `TOOL_CALL` stage
- **Path**: `packages/ai-parrot/src/parrot/bots/guardrails/base.py`
- **Responsibility**: Add `GuardrailStage.TOOL_CALL = "tool_call"` + docstring;
  regression-verify `build_pipelines_from_config()` emits a pipeline for it and
  empty pipelines short-circuit with zero overhead.
- **Depends on**: nothing (first task).

### Module 2: `PBACToolCallGuardrail`
- **Path**: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py` (+ registry entry in `registry.py`)
- **Responsibility**: EvalContext/Environment construction, `check_access()`
  call, ALLOW/DENY mapping, fail-mode resolution (`on_error="fail_closed"`
  default; `enforcement: fail_open` read from the deciding policy's
  `attributes` via `PolicyResponse.rule`), denial report construction, no
  `permission_context` → PASS (session-scoped enforcement).
- **Depends on**: Module 1.

### Module 3: ToolManager hook + bot wiring
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`, `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: `_tool_call_pipeline` attr on ToolManager; run pipeline
  at the TOP of the guard chain in `execute_tool()` (pbac → grant → confirm);
  BLOCK → `ToolResult(status="forbidden", error=<report.message>)`; stamp the
  pipeline in bot wiring (abstract.py:747 seam); construct the guardrail with
  the shared evaluator when `"pbac"` is requested and PBAC is initialized;
  skip registration when `setup_pbac()` returned `(None, None, None)`.
- **Depends on**: Modules 1, 2.

### Module 4: `UserInfoService` + `EmployeeProfile`
- **Path**: `packages/ai-parrot/src/parrot/auth/userinfo.py` (+ export in `auth/__init__.py`)
- **Responsibility**: curated profile query over `auth.vw_users` (asyncdb, same
  lazy `querysource.conf` DSN pattern as `stores/kb/user.py:25-26`), manager
  sub-lookup, `TTLCache` per user, `None`/structured-unavailable on missing row.
- **Depends on**: nothing (parallel lane).

### Module 5: `UserinfoTool`
- **Path**: `packages/ai-parrot/src/parrot/tools/userinfo.py`
- **Responsibility**: `AbstractTool` subclass returning the session user's
  profile as JSON; identity from session/`PermissionContext` only; per-agent
  activation via standard tool registration; "profile unavailable" structured
  result.
- **Depends on**: Module 4.

### Module 6: PBAC attribute enrichment + sample policies + docs + e2e
- **Path**: `bots/guardrails/builtin/pbac.py` (enrichment), `policies/` samples,
  `docs/security/pbac-guardrails.md`, integration tests.
- **Responsibility**: optional `EmployeeProfile` attribute enrichment of
  `EvalContext` (thin join point between lanes); sample business-hours DENY
  policy YAML with `enforcement:` example; deprecation note in
  `stores/kb/user.py` docstring; end-to-end tests.
- **Depends on**: Modules 3, 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_tool_call_stage_member` | 1 | `GuardrailStage.TOOL_CALL == "tool_call"`; `build_pipelines_from_config()` returns a pipeline for it |
| `test_empty_tool_call_pipeline_zero_overhead` | 1 | Empty pipeline short-circuits (`has_guardrails` False path) |
| `test_pbac_allow_maps_to_pass` | 2 | ALLOW → PASS, content untouched |
| `test_pbac_deny_maps_to_block_with_report` | 2 | DENY → BLOCK; `reason="policy:<rule>"`; report carries `PolicyResponse.response` message |
| `test_pbac_no_permission_context_passes` | 2 | Missing `extras["permission_context"]` → PASS (session-scoped enforcement) |
| `test_pbac_engine_error_fail_closed` | 2 | evaluator raises → BLOCK `policy_engine_unavailable` (via pipeline `on_error`) |
| `test_pbac_enforcement_fail_open_downgrade` | 2 | Deciding policy has `attributes["enforcement"]=="fail_open"` → engine error passes through |
| `test_execute_tool_runs_tool_call_pipeline_first` | 3 | Pipeline runs BEFORE GrantGuard/ConfirmationGuard (order assertion via mocks) |
| `test_block_translates_to_forbidden_toolresult` | 3 | Blocked outcome → `ToolResult(success=False, status="forbidden", error=<message>)`; tool never executed |
| `test_no_pipeline_path_unchanged` | 3 | `_tool_call_pipeline is None` → behavior identical to today (regression) |
| `test_bot_wiring_stamps_tool_call_pipeline` | 3 | `tool_manager._tool_call_pipeline` is the bot's TOOL_CALL pipeline |
| `test_pbac_not_registered_without_engine` | 3 | `setup_pbac` degraded → `"pbac"` not in any pipeline; no errors |
| `test_profile_curated_fields` | 4 | `EmployeeProfile` exposes exactly the curated set; `manager` is nested `{user_id, display_name, email}` |
| `test_profile_cache_ttl` | 4 | Second call within TTL hits cache (single DB query) |
| `test_profile_missing_row` | 4 | Unknown user → `None` / structured unavailable, no exception |
| `test_userinfo_tool_session_identity_only` | 5 | Tool ignores any LLM-supplied identity argument; uses session user |
| `test_userinfo_tool_json_output` | 5 | Returns valid JSON matching `EmployeeProfile` schema |
| `test_layer2_resolver_still_active` | 6 | With guardrail active, `PBACPermissionResolver.can_execute` still invoked on `AbstractTool.execute()` (defense-in-depth, resolved Q4) |

### Integration Tests

| Test | Description |
|---|---|
| `test_business_hours_deny_e2e` | Sample business-hours DENY policy + frozen clock outside window → agent receives `forbidden` ToolResult with the operator message; agent loop continues; inside window → tool executes |
| `test_telemetry_no_content` | TOOL_CALL run emits `GuardrailTelemetryEntry` (name/stage/action/duration) and never the arguments/content |
| `test_kb_regression` | `UserInfo`/`UserProfileKB` behavior unchanged with the feature enabled |

### Test Data / Fixtures

```python
@pytest.fixture
def shared_evaluator(tmp_path):
    """PolicyEvaluator loaded from a temp policies/ dir with the sample
    business-hours DENY policy (enforcement key variants included)."""

@pytest.fixture
def frozen_environment(monkeypatch):
    """Patch navigator_auth Environment clock inputs to a deterministic
    timestamp inside/outside business hours."""

@pytest.fixture
def fake_vw_users(monkeypatch):
    """Stub asyncdb fetch_one for auth.vw_users rows (user + manager)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `GuardrailStage.TOOL_CALL` exists; `build_pipelines_from_config()` builds
      its pipeline automatically; empty TOOL_CALL pipelines add zero overhead
      (regression suite green).
- [ ] With a DENY policy matching a tool, the agent receives
      `ToolResult(success=False, status="forbidden", error=<PolicyResponse.response>)`,
      the tool body never executes, and the agent loop continues (no exception
      reaches the caller).
- [ ] Guard-chain order in `ToolManager.execute_tool()` is
      **TOOL_CALL/PBAC → GrantGuard → ConfirmationGuard**, asserted by test.
- [ ] Business-hours e2e: outside the configured window the call is denied with
      the operator-authored message; inside the window it executes (server
      clock + navigator global config — resolved Q2).
- [ ] Fail mode: engine exception ⇒ BLOCK `policy_engine_unavailable` by
      default; a policy with `enforcement: fail_open` in its YAML (landing in
      `policy.attributes`) downgrades to pass-through (resolved Q3).
- [ ] Missing `permission_context` (programmatic/test invocation) ⇒ PASS —
      enforcement is session-scoped, mirroring `enforce_agent_access()`.
- [ ] PBAC engine absent (`setup_pbac()` → `(None, None, None)`) ⇒ guardrail
      not registered; existing fail-open bootstrap semantics preserved.
- [ ] `PBACPermissionResolver` (Layer 2) remains active alongside the guardrail
      (resolved Q4) — verified by test.
- [ ] `PBACToolCallGuardrail` is constructed by bot wiring with the shared
      evaluator instance passed in `guardrails=[...]` (resolved Q7); no global
      evaluator state introduced.
- [ ] `UserinfoTool` returns the **session user's** curated `EmployeeProfile`
      as JSON; identity never taken from an LLM argument; `manager` is the
      nested `{user_id, display_name, email}` object (resolved Q6).
- [ ] Missing profile row ⇒ structured "profile unavailable" result, no
      exception.
- [ ] `UserInfo`/`UserProfileKB` untouched and passing their existing tests
      (KBs coexist — brainstorm decision).
- [ ] Telemetry: every TOOL_CALL evaluation records name/stage/action/duration
      and never content/arguments.
- [ ] Tool-call arguments are NOT projected into policy attributes (v1
      non-goal), asserted by test.
- [ ] All unit + integration tests pass (`pytest` on changed packages).
- [ ] Documentation added (`docs/security/pbac-guardrails.md`) covering the
      three enforcement layers and sample policy YAML.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against the working tree on 2026-08-03 (post-brainstorm re-check).

### Verified Imports

```python
from parrot.bots.guardrails import (          # bots/guardrails/__init__.py:14-25
    Guardrail, GuardrailAction, GuardrailContext, GuardrailPipeline,
    GuardrailResult, GuardrailStage, PipelineOutcome,
    build_guardrails, build_pipelines_from_config, register_guardrail,
)
from parrot.auth import (                     # auth/__init__.py
    PermissionContext, UserSession, PBACPermissionResolver, setup_pbac, UserContext,
)
from navigator_auth.abac.context import EvalContext            # used at auth/agent_guard.py:181
from navigator_auth.abac.policies.environment import Environment  # used at auth/agent_guard.py:252
from navigator_auth.abac.policies import PolicyResponse        # verified via inspect (installed >0.20.9)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/guardrails/base.py
class GuardrailStage(str, Enum):               # line 15 (re-verified at spec time)
    INPUT = "input"                            # line 24
    TOOL_OUTPUT = "tool_output"                # line 25
    OUTPUT = "output"                          # line 26
    OUTPUT_STREAM = "output_stream"            # line 27  ← TOOL_CALL does not exist yet

class GuardrailAction(str, Enum):              # line 30
    PASS = "pass"; TRANSFORM = "transform"; FLAG = "flag"; BLOCK = "block"

class GuardrailResult(BaseModel):              # line 45
    action: GuardrailAction
    content: str | None = None
    report: dict[str, Any] | None = None       # BLOCK may attach report (pipeline.py:186-191)
    reason: str | None = None

class GuardrailContext(BaseModel):             # line 63
    stage: GuardrailStage
    agent_name: str
    user_id: str | None = None
    session_id: str | None = None
    method: str = ""
    tool_name: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

class Guardrail(ABC):                          # line 87
    name: str
    stages: set[GuardrailStage]
    priority: int                              # bands: 0-99 / 100-199 / 200+
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"   # line 112
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult  # line 115

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class GuardrailPipeline:                       # line 84
    def __init__(self, on_telemetry=None) -> None                  # line 99
    def add(self, guardrail: Guardrail) -> None                    # line 112
    has_guardrails: bool                                           # line 122 (property)
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 138
    # empty short-circuit line 149; BLOCK short-circuit line 183

class PipelineOutcome(BaseModel):              # line 62
    content: str | None; blocked: bool; reason: str | None
    flag_reports: dict[str, dict[str, Any]]; telemetry: list[GuardrailTelemetryEntry]

# packages/ai-parrot/src/parrot/bots/guardrails/config.py
def build_pipelines_from_config(guardrails=None, legacy_flags=None, on_telemetry=None)
    -> dict[GuardrailStage, GuardrailPipeline]   # line 39; iterates enum at lines 100-102

# packages/ai-parrot/src/parrot/bots/guardrails/registry.py
def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None  # line 41
def build_guardrails(spec: list[str | dict | Guardrail]) -> list[Guardrail]   # line 95
# names taken: "prompt_injection", "secrets", "moderation", "groundedness";
# reserved: "pii", "pseudonymize" (lines 35-38, 146-165) — "pbac" is free

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    _tool_output_pipeline: Optional[Any] = None                    # line 290
    async def execute_tool(                                        # line 1422 (re-verified)
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any
    # GrantGuard check ~line 1477; ConfirmationGuard after it; re-stamp of
    # _tool_output_pipeline at lines 1473-1474; denial shape precedent:
    # ToolResult(success=False, status="forbidden", error=..., result=None)
    async def execute_tool_call(self, ...)                         # line 1732

# packages/ai-parrot/src/parrot/bots/abstract.py
# line 121: from .guardrails.config import build_pipelines_from_config
# line 668: self._guardrail_pipelines = build_pipelines_from_config(...)
# line 747: self.tool_manager._tool_output_pipeline =
#           self._guardrail_pipelines[GuardrailStage.TOOL_OUTPUT]   ← stamping seam to mirror

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):    # line 233
    async def _execute(self, **kwargs) -> Any                      # line 471 (abstract work method)
    async def execute(self, *args, **kwargs) -> ToolResult         # line 719 (Layer-2 resolver runs here)

# packages/ai-parrot/src/parrot/auth/resolver.py
class AbstractPermissionResolver:
    async def can_execute(self, context: PermissionContext, tool_name: str,
                          required_permissions: set[str]) -> bool  # line 44
class PBACPermissionResolver(AbstractPermissionResolver):          # line 247
    def __init__(self, evaluator: "PolicyEvaluator", logger=None)  # line 275

# packages/ai-parrot/src/parrot/auth/pbac.py
def setup_pbac(app, policy_dir="policies", cache_ttl=30, default_effect=None)
    -> tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]  # line 35 (re-verified)
    # degraded mode returns (None, None, None) — fail-open bootstrap

# packages/ai-parrot/src/parrot/auth/agent_guard.py — EvalContext construction pattern
# line 181: from navigator_auth.abac.context import EvalContext
# line 252: from navigator_auth.abac.policies.environment import Environment
# line 267: result = evaluator.check_access(...)
# fail-open precedents: evaluator None → return (line 241); request None → return (line 244)

# packages/ai-parrot/src/parrot/stores/kb/user.py
class UserInfo(AbstractKnowledgeBase):         # line 11 — always_active=True
    async def search(self, query: str, user_id: int, **kwargs) -> List[Dict]  # line 43
    # auth.vw_users columns (lines 51-55): user_id, display_name, username, email,
    # job_code, associate_id, associate_oid, title, worker_type, manager_id
class UserProfileKB(AbstractKnowledgeBase):    # line 78
    # columns (lines 116-124): first_name, last_name, email, job_code, title,
    # department_code, groups, programs
# TTLCache usage: line 27 — TTLCache(max_size=500, default_ttl=600); from .cache import TTLCache
# lazy DSN: lines 25-26 — lazy_import("querysource.conf") → AsyncDB('pg', dsn=_qs_conf.default_dsn)

# navigator_auth (installed, >0.20.9 — pinned at packages/ai-parrot/pyproject.toml:66)
# Verified via inspect on 2026-08-03:
# Environment (pydantic): time, timestamp (default datetime.now() — SERVER LOCAL, naive),
#   dow/day_of_week, hour, minute, date, day_segment, is_business_hours, is_weekend,
#   timezone (informational, default "UTC");
#   is_business_hours from module config BUSINESS_HOURS_START ("08:00"),
#   BUSINESS_HOURS_END ("18:00"), BUSINESS_DAYS ("1,2,3,4,5");
#   accepts explicit timestamp/hour/minute at construction (v2 tz path)
# AbstractPolicy.__init__(..., context: Optional[dict], environment, priority,
#   enforcing: bool, scopes, **kwargs) — unknown kwargs stored in self.attributes
# PolicyResponse(ClassDict): effect: PolicyEffect; response: str; rule: str; actions: list[str]
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GuardrailStage.TOOL_CALL` | `build_pipelines_from_config()` | enum iteration | `bots/guardrails/config.py:100-102` |
| `PBACToolCallGuardrail` | `PolicyEvaluator.check_access()` | direct call | pattern at `auth/agent_guard.py:267` |
| `PBACToolCallGuardrail` | policy fail-mode | `PolicyResponse.rule` → `policy.attributes` | inspect-verified (navigator_auth) |
| TOOL_CALL hook | `ToolManager.execute_tool()` | pipeline run before GrantGuard | `tools/manager.py:1422,1477` |
| pipeline stamping | `AbstractBot` wiring | `tool_manager._tool_call_pipeline = …` | seam at `bots/abstract.py:747` |
| `UserInfoService` | `auth.vw_users` | asyncdb `fetch_one` | pattern at `stores/kb/user.py:49-57` |
| `UserinfoTool` | `AbstractTool` | subclass, `_execute()` | `tools/abstract.py:233,471` |

### Does NOT Exist (Anti-Hallucination)

- ~~`GuardrailStage.TOOL_CALL`~~ — enum has only INPUT / TOOL_OUTPUT / OUTPUT / OUTPUT_STREAM today; **this feature introduces it**.
- ~~`"pbac"` registry name / `PBACToolCallGuardrail`~~ — not in `registry.py` or `builtin/` (only `legacy_pipeline`, `moderation`, `prompt_injection`, `secrets`).
- ~~`ToolManager._tool_call_pipeline`~~ — only `_tool_output_pipeline` exists (manager.py:290); the new attr is introduced by Module 3.
- ~~Pre-execution guardrail hook~~ — guardrails currently run only at TOOL_OUTPUT (via `tool._tool_output_pipeline` in `tools/abstract.py`); nothing runs before `tool.execute()` except Grant/Confirmation guards and the Layer-2 resolver.
- ~~`parrot/auth/userinfo.py` / `UserInfoService` / `EmployeeProfile` / `UserinfoTool` / `parrot/tools/userinfo.py`~~ — none exist; only the KB classes in `stores/kb/user.py`.
- ~~`enforcement` handling in navigator-auth~~ — navigator-auth does NOT interpret the `enforcement:` key; it merely stores it in `policy.attributes`. The interpretation is parrot-side (Module 2).
- ~~Per-policy timezone / business-hours windows~~ — `Environment` business hours are global module config; no per-policy tz support.
- ~~Argument-level ABAC~~ — no mechanism projects tool arguments into policy attributes; explicitly out of scope.
- ~~`Guardian.check_tool_call()` / batch `check_access()`~~ — evaluation is per-resource via `PolicyEvaluator.check_access()`.
- ~~Final-response/topic classification guardrail~~ — no content classifier exists; deferred by design.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Guard-chain denial shape: mirror `GrantGuard`'s
  `ToolResult(success=False, status="forbidden", error=..., result=None)`
  (`tools/manager.py` grant block).
- Pipeline stamping: mirror `bots/abstract.py:747`
  (`_tool_output_pipeline`) for the new `_tool_call_pipeline`.
- `EvalContext`/`Environment` construction: mirror
  `auth/agent_guard.py:181-267`, including its fail-open precedents
  (no evaluator / no session context → pass).
- Lazy DSN + `TTLCache`: mirror `stores/kb/user.py:25-30`.
- Registry lazy factory: mirror `registry.py:146-165` for the `"pbac"` name
  (name registration is for discoverability; the evaluator-carrying instance
  path via bot wiring is primary — resolved Q7).
- Async-first, Pydantic models, Google-style docstrings, `self.logger`.

### Known Risks / Gotchas

- **`tools/manager.py` is high-traffic** (FEAT-380 compression, FEAT-211/235
  guards): keep the TOOL_CALL hook additive and early-returning; do not
  reorder the existing grant → confirm sequence relative to each other.
- **Guard order changed vs. brainstorm body**: brainstorm text placed the
  pipeline after grant/confirm; spec review resolved **PBAC first** (avoid
  interrupting a human for a policy-doomed call). The brainstorm's Open
  Questions did not lock the order; this is the authoritative decision.
- **Denial-reason hygiene**: `GuardrailResult.reason` is a category label;
  the human message rides in `report`. Raw policy YAML, rule internals, or
  other users' data must never reach the LLM.
- **Parallel tool calls**: each call evaluated independently; one denial must
  not abort sibling calls.
- **Streaming**: TOOL_CALL is orthogonal to OUTPUT_STREAM; tool calls execute
  identically mid-stream.
- **Layer-1 interplay**: invisible (filtered) tools never reach TOOL_CALL;
  a hallucinated call to an unregistered tool hits the existing `not_found`
  path before the pipeline.
- **Server-clock business hours** (resolved Q2): deployments spanning
  timezones will evaluate against the server's local time — document this
  limitation in `docs/security/pbac-guardrails.md`.
- **`ClassDict` access**: `PolicyResponse` is a `ClassDict`; access fields
  defensively (`.get()`/`getattr`) in case older navigator-auth versions omit
  `rule`.
- **Concurrent SDD sessions** touch `sdd/` state on `dev` — commit SDD
  artifacts promptly (see repo memory on worktree clobbering).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>0.20.9` (already pinned) | `PolicyEvaluator`, `EvalContext`, `Environment`, `PolicyResponse` |
| `asyncdb` | existing | `auth.vw_users` profile query |
| `pydantic` | `>=2` (existing) | `EmployeeProfile`, denial report models |

No new dependencies.

---

## 8. Open Questions

> Decision trail carried from `sdd/proposals/pbac-guardrails.brainstorm.md`.

- [x] Q1: DENY reaches the user directly or via the LLM? — *Resolved in brainstorm*: Via the LLM — BLOCK → `ToolResult(status="forbidden", error=<reason>)`; the agent verbalizes the denial and the loop continues.
- [x] Q2: Timezone source for business-hours conditions — *Resolved in brainstorm*: v1 = server local clock + navigator global config (`BUSINESS_HOURS_START/END`, `BUSINESS_DAYS`); `Environment.timezone` informational; per-policy tz deferred (v2 can inject explicit `timestamp`/`hour`/`minute`).
- [x] Q3: Per-policy fail-mode syntax — *Resolved in brainstorm*: `enforcement: fail_open` extra key in policy YAML → `policy.attributes`; guardrail locates the deciding policy via `PolicyResponse.rule`. Default `fail_closed`.
- [x] Q4: Keep Layer-2 `PBACPermissionResolver` active? — *Resolved in brainstorm*: Yes, both (defense-in-depth); shared evaluator + 30s cache makes double evaluation negligible.
- [x] Q5: Option C add-on (availability windows in tool descriptions)? — *Resolved in brainstorm*: separate follow-up feature.
- [x] Q6: `manager_id` raw vs resolved? — *Resolved in brainstorm*: both — nested `manager: {user_id, display_name, email}`.
- [x] Q7: Evaluator → guardrail wiring? — *Resolved in brainstorm*: bot wiring constructs `PBACToolCallGuardrail(evaluator=...)` and passes the instance in `guardrails=[...]`; registry name is discoverability-only.
- [x] Q8 (new, spec review): Guard-chain position — *Resolved in spec review*: **PBAC first** (TOOL_CALL → grant → confirm), so a human is never interrupted to confirm a call the policy will deny.

---

## Worktree Strategy

- **Default isolation unit**: mixed.
- **Lane A (sequential, feature worktree)**: Module 1 → Module 2 → Module 3 →
  Module 6. Shared files (`bots/guardrails/*`, `tools/manager.py`,
  `bots/abstract.py`) force sequential execution.
- **Lane B (parallelizable)**: Module 4 → Module 5
  (`auth/userinfo.py`, `tools/userinfo.py`) — disjoint file set from Lane A;
  may run in its own worktree concurrently.
- **Join point**: Module 6 (EvalContext enrichment + e2e) — runs last, after
  both lanes merge.
- **Cross-feature dependencies**: none blocking. FEAT-404
  (bedrock-per-round-token) and FEAT-405 (novaclient-dev-loop) are in flight
  but touch `clients/` — no file overlap. Re-check `tools/manager.py` for
  in-flight edits at task start (high-traffic file).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Jesus Lara | Initial draft from brainstorm (Option A); Q8 guard order resolved (PBAC first) |
