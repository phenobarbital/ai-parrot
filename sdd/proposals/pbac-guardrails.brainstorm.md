---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: PBAC Guardrails — Policy-Driven Tool-Call Denial + UserinfoTool

**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

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
and (b) is available to the LLM as queryable, JSON-based data. The refactor:
a shared **UserInfoService** as single source of truth, exposed to the LLM as a
per-agent activatable **UserinfoTool**.

**Affected**: end users (clear denial explanations instead of silent failures or
hallucinated excuses), operators/security teams (auditable, policy-driven runtime
enforcement beyond "superusers vs groups"), agent developers (structured user
profile instead of prose facts).

**Scope decisions (from interactive discovery)**:
- v1 covers the **TOOL_CALL** guardrail only. Final-response (topic/content)
  guardrails are explicitly deferred — no output classification in this feature.
- v1 evaluates the tuple **(user, tool, environment)** — no argument-level ABAC
  (consistent with FEAT-077's non-goal).
- Fail mode is **configurable per policy**, defaulting to `fail_closed`
  (deny with reason `policy_engine_unavailable`).
- UserinfoTool exposes a **curated** Pydantic profile; the existing KBs
  **coexist** (gradual deprecation, no forced migration of legacy agents).

## Constraints & Requirements

- Must build on the FEAT-396 guardrails infrastructure (`parrot/bots/guardrails`):
  `Guardrail` ABC, `GuardrailPipeline`, registry, telemetry — not a parallel system.
- Must reuse the **shared** `PolicyEvaluator` wired by `setup_pbac()` (FEAT-077):
  guardrail, Guardian, and `PBACPermissionResolver` must reach consistent decisions.
- navigator-auth `>0.20.9` (already a dependency); its Rust policy engine keeps
  per-call evaluation latency negligible — no caching layer needed in the guardrail.
- DENY must reach the LLM as a structured tool error (policy name + reason
  category), never the raw policy internals; the agent loop must continue (a
  denial is a normal turn, not an exception).
- The existing `PBACPermissionResolver` Layer-2 net and `GrantGuard`/
  `ConfirmationGuard` (FEAT-211/235) must keep working unchanged.
- Async-first; Pydantic models for all new data structures; no blocking I/O.
- UserinfoTool must be activatable **per agent** (standard tool registration),
  and must not leak sensitive internal identifiers in v1 (curated field set).

---

## Options Explored

### Option A: New `TOOL_CALL` stage in the FEAT-396 pipeline + `PBACToolCallGuardrail` builtin

Extend `GuardrailStage` with a `TOOL_CALL` member (pre-execution). The agent's
tool dispatch path runs the TOOL_CALL pipeline before executing: `content` is a
compact serialized representation of the call (`"<tool_name>(<args JSON>)"` for
telemetry/log purposes), while `ctx.extras` carries the structured payload:
`{"tool_name": ..., "arguments": {...}, "permission_context": ...}`.

A new builtin guardrail `pbac` (`PBACToolCallGuardrail`) registered in the
guardrails registry evaluates `PolicyEvaluator.check_access()` with an
`EvalContext` built from the session/`PermissionContext` plus environment
attributes (timestamp, weekday, channel). On DENY it returns
`GuardrailResult(action=BLOCK, reason="policy:<policy_name>:<category>")` with a
non-content `report` carrying the structured denial (policy id, human-readable
reason like "outside business hours", retry hint). The pipeline outcome is
translated by the tool-dispatch site into a
`ToolResult(success=False, status="forbidden", error=<explainable reason>)` — the
same pattern `GrantGuard` uses — so the LLM sees the denial and explains it.

Fail mode: the guardrail's `on_error` defaults to `fail_closed`; a policy-level
annotation (e.g. `enforcement: fail_open` in the tool's policy YAML) lets
low-risk read-only tools degrade gracefully.

UserInfoService + UserinfoTool (shared across all options): a service that loads
the curated employee profile from `auth.vw_users` once per session (TTL cache,
reusing the `TTLCache` pattern in `stores/kb/user.py`), feeding **both** the
PBAC `EvalContext` construction and the `UserinfoTool` (an `AbstractTool`
returning the profile as JSON). Existing KBs stay untouched.

✅ **Pros:**
- One uniform guardrails surface: config (`guardrails=["pbac"]` or
  `{"name": "pbac", ...}`), priority bands, telemetry, `on_error` contract, and
  `AIMessage.metadata["guardrails"]` reporting all come for free.
- The TOOL_CALL stage is generic infrastructure: future guardrails (rate
  limiting, cost caps, arg-level ABAC v2) plug into the same stage.
- Explicit DENY semantics complement (not replace) Layer-1 invisibility and the
  Layer-2 silent net — three defensible layers with distinct UX.
- Telemetry-ready: every evaluation is a `GuardrailTelemetryEntry` (name, stage,
  action, duration) — free audit trail without content leakage.

❌ **Cons:**
- Touches shared enum/infra (`GuardrailStage`) — every stage-keyed dict
  (`build_pipelines_from_config` builds one pipeline per stage) and the
  bot-wiring code must handle the new stage; small blast radius but real.
- The `check(content: str)` contract is string-first; structured tool-call data
  rides in `extras` — a mild impedance mismatch (precedent exists: the
  TOOL_OUTPUT `scrub()` escape hatch in `tools/abstract.py`).
- Two evaluation points against the same evaluator per call (guardrail +
  Layer-2 resolver) — negligible cost (Rust engine + 30s TTL cache), but must
  be documented to avoid confusion.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth>0.20.9` | PBAC engine (`PolicyEvaluator`, `EvalContext`, `Environment`) | Already a dependency; Rust core, near-zero eval latency |
| `asyncdb` | `auth.vw_users` profile query for UserInfoService | Already used by `stores/kb/user.py` |
| `pydantic>=2` | `EmployeeProfile` model, guardrail result payloads | Already core |

🔗 **Existing Code to Reuse:**
- `parrot/bots/guardrails/base.py` — `Guardrail` ABC, `GuardrailStage`, `GuardrailResult` (BLOCK + report), `GuardrailContext.extras`.
- `parrot/bots/guardrails/pipeline.py` — `GuardrailPipeline` (BLOCK short-circuit, telemetry, `on_error`).
- `parrot/bots/guardrails/registry.py` — `register_guardrail()` lazy-factory pattern for the `"pbac"` name.
- `parrot/auth/agent_guard.py` — `EvalContext` construction from session + `evaluator.check_access()` call shape (lines 181–267).
- `parrot/auth/pbac.py` — `setup_pbac()` shared-evaluator wiring.
- `parrot/tools/manager.py:1422` — `execute_tool()` guard-chain pattern (`GrantGuard` → `ConfirmationGuard`) and its `ToolResult(status="forbidden")` denial shape.
- `parrot/stores/kb/user.py` — `auth.vw_users` query + `TTLCache` usage to lift into UserInfoService.
- `parrot/stores/kb/cache.py` — `TTLCache` for per-session profile caching.

---

### Option B: `PolicyGuard` in the ToolManager guard chain (no pipeline involvement)

Skip the guardrails pipeline entirely. Add a third guard to
`ToolManager.execute_tool()`'s existing chain — `GrantGuard` (FEAT-211) →
`ConfirmationGuard` (FEAT-235) → **`PolicyGuard`** — with the same
`authorize(tool, parameters, permission_context) -> GuardDecision` contract.
On deny, return `ToolResult(status="forbidden", error="Policy denied: <reason>")`.

✅ **Pros:**
- Smallest diff: one new class + one call site; the guard-chain precedent is
  established and battle-tested twice.
- Perfect insertion point: `execute_tool()` already receives
  `permission_context` — no context plumbing needed.
- No changes to shared guardrails infra.

❌ **Cons:**
- Invisible to the guardrails system the team just built (FEAT-396): no unified
  config (`guardrails=[...]`), no per-stage telemetry, no `on_error` contract,
  no `metadata["guardrails"]` reports — policy enforcement becomes a fourth
  bespoke mechanism (resolver, grants, confirmation, now this).
- Locks enforcement to `ToolManager`; direct `AbstractTool.execute()` calls
  (tests, programmatic flows) bypass it — same blind spot Layer 2 was created
  to close.
- Explicitly contradicts the direction chosen during discovery ("se implementa
  como un Guardrail en el Toolcall").

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth>0.20.9` | PBAC engine | Same as Option A |

🔗 **Existing Code to Reuse:**
- `parrot/auth/grants.py` — `GrantGuard`/`GuardDecision` contract to mirror.
- `parrot/tools/manager.py:1422` — guard-chain insertion point.
- `parrot/auth/agent_guard.py` — `EvalContext` construction.

---

### Option C (unconventional): Agent-loop batch interceptor + prompt-visible availability windows

Intercept **one level higher**: when the LLM response containing `tool_calls`
is parsed (before any dispatch), evaluate **all** requested calls in a single
batch against the `PolicyEvaluator`, rewrite denied calls into synthetic tool
error messages, and dispatch only the allowed subset. Additionally, render each
tool's policy conditions into its **description** at tool-listing time
("available Mon–Fri 08:00–18:00 America/Chicago"), so the LLM can often avoid
the denied call altogether and answer from prior knowledge of the constraint.

✅ **Pros:**
- Batch evaluation: one engine round-trip for N parallel tool calls.
- Proactive UX: the LLM knows the constraint *before* calling — fewer wasted
  turns, better refusal phrasing ("that tool opens again at 8:00").
- The description-annotation half is valuable **regardless** of which
  enforcement option wins (cheap add-on).

❌ **Cons:**
- The interception point (agent loop response parsing) is provider- and
  loop-shaped: Agent, AgentsFlow nodes, and streaming paths each parse tool
  calls differently — high risk of partial coverage.
- Prompt-visible windows are advisory only; enforcement still needs a runtime
  check, so this option cannot stand alone.
- Description mutation must be per-request (policies are user-relative), which
  conflicts with tool-schema caching.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth>0.20.9` | Batch policy evaluation | `check_access` called per resource; batch is N cheap calls |

🔗 **Existing Code to Reuse:**
- `parrot/tools/manager.py:1732` — `execute_tool_call()` (LLM tool-call envelope path).
- `parrot/auth/agent_guard.py` — evaluation call shape.

---

## Recommendation

**Option A** is recommended because:

- It matches the architectural direction already taken: FEAT-396 exists
  precisely so that new controls plug into **one** pluggable surface instead of
  accreting bespoke mechanisms. Option B would add a fourth parallel
  enforcement idiom the day after the team unified three of them.
- The cost driving Option B's appeal (touching `GuardrailStage`) is a
  one-time, low-risk enum extension — `build_pipelines_from_config()` already
  builds pipelines generically per stage member, so most of the infra adapts
  automatically.
- The concrete hook point inside `ToolManager.execute_tool()` is the **same**
  in A and B; A simply routes it through `GuardrailPipeline`, buying config,
  telemetry, priorities, and `on_error` semantics for free. We trade a slightly
  larger surface now for every future TOOL_CALL guardrail (rate limits, cost
  caps, arg-ABAC v2) being a drop-in.
- Option C's genuinely good idea — policy conditions annotated into tool
  descriptions — is carried forward as an **optional enhancement** (open
  question Q5), not as the enforcement mechanism.

What we consciously trade off: double evaluation per call (guardrail +
Layer-2 resolver) against the same shared evaluator. Accepted: the Rust engine
plus its 30s decision cache makes this sub-millisecond, and the redundancy is
defense-in-depth, not waste.

---

## Feature Description

### User-Facing Behavior

- A user asks an agent to run an action backed by a policy-protected tool
  outside its allowed window (e.g. a payroll-adjustment tool at 22:00). The
  tool **is visible** to the agent; the call is attempted; the PBAC guardrail
  denies it; the agent answers with the policy reason: *"No puedo ejecutar esa
  operación fuera del horario laboral (L–V 08:00–18:00). Puedo dejarla
  preparada para mañana."* — instead of a silent failure or a hallucinated
  excuse.
- Agents configured with `UserinfoTool` can answer identity-grounded questions
  ("¿quién es mi manager?", "¿en qué programa estoy?") from structured JSON
  instead of prose facts, and can pass exact fields (`user_id`, `job_code`) to
  other tools.
- Operators declare rules in the same policy YAML files FEAT-077/101
  established — e.g. a DENY rule on `resource: tool:payroll_adjust` with an
  `Environment` business-hours condition — with no agent code changes.
- Security/audit teams see every evaluation in guardrail telemetry
  (name/stage/action/duration, never content) plus the existing WARNING-level
  denial audit logs.

### Internal Behavior

1. **Stage**: `GuardrailStage.TOOL_CALL` is added to the FEAT-396 enum.
   `build_pipelines_from_config()` produces its pipeline automatically (it
   iterates the enum). Bots wire the TOOL_CALL pipeline onto their
   `ToolManager` the same way the TOOL_OUTPUT pipeline is stamped today.
2. **Hook**: inside `ToolManager.execute_tool()`, after the Grant and
   Confirmation guards and before dispatching to `tool.execute()`, the
   TOOL_CALL pipeline runs. `content` = compact serialized call;
   `ctx.extras` = `{"tool_name", "arguments", "permission_context"}`;
   `ctx.user_id` / `ctx.session_id` / `ctx.agent_name` from the calling bot.
   Empty pipelines short-circuit with zero overhead (existing behavior).
3. **Guardrail**: `PBACToolCallGuardrail` (registered as `"pbac"`, lazy
   factory) builds an `EvalContext` from the `PermissionContext`/session plus
   an `Environment` snapshot (timestamp, weekday, channel), asks the shared
   `PolicyEvaluator.check_access()` for `resource_type=TOOL,
   resource_name=<tool_name>`, and maps ALLOW→`PASS`,
   DENY→`BLOCK(reason="policy:<name>", report={structured denial})`.
4. **Denial translation**: a BLOCK outcome becomes
   `ToolResult(success=False, status="forbidden", error=<human-readable policy
   reason>)` — the LLM receives it as the tool's result and explains it; the
   agent loop continues normally.
5. **Fail mode**: guardrail default `on_error="fail_closed"` (engine
   exception ⇒ BLOCK `policy_engine_unavailable`). A per-policy annotation can
   downgrade specific tools/rules to fail-open; when the PBAC engine was never
   initialized (`setup_pbac()` returned `(None, None, None)`), the guardrail is
   simply not registered — existing fail-open bootstrap semantics preserved.
6. **UserInfoService**: new service owning the curated employee profile
   (`EmployeeProfile` Pydantic model: `user_id`, `username`, `display_name`,
   `email`, `job_code`, `title`, `department_code`, `groups`, `programs`,
   `manager_id`, `worker_type`). Loads from `auth.vw_users` via asyncdb,
   TTL-cached per user. Consumed by (a) `EvalContext`/attribute construction
   for PBAC and (b) `UserinfoTool`.
7. **UserinfoTool**: an `AbstractTool` (`userinfo`) returning the profile as
   JSON for the **current session user only** (identity comes from the
   session/`PermissionContext`, never from an LLM-supplied argument). Activated
   per agent via standard tool registration. Existing `UserInfo`/
   `UserProfileKB` KBs keep working; internally they can delegate to
   UserInfoService later (out of scope for v1 beyond a deprecation note).

### Edge Cases & Error Handling

- **No `permission_context`** (programmatic/test invocation without a request):
  guardrail passes through (enforcement is session-scoped, mirroring
  `enforce_agent_access()`'s `request is None` fail-open) — documented
  explicitly to avoid surprises.
- **PBAC engine down / policy dir missing**: guardrail not registered at
  bootstrap (engine absent) vs. registered-but-erroring (engine broke at
  runtime ⇒ `fail_closed` BLOCK unless policy opts out).
- **Tool denied by Layer 1 already**: invisible tools never reach TOOL_CALL —
  the guardrail only sees calls to visible tools; a hallucinated call to an
  unregistered tool still hits the existing `not_found` path first.
- **Parallel tool calls**: each call is evaluated independently; one denial
  never aborts sibling calls.
- **Clock/timezone**: business-hours conditions are evaluated by
  navigator-auth's `Environment`; the timezone source (server vs. policy-declared)
  is Open Question Q2.
- **Profile row missing** (user not in `auth.vw_users`): UserinfoTool returns a
  structured "profile unavailable" result (not an exception); PBAC attribute
  enrichment degrades to session-only attributes.
- **Denial-reason hygiene**: `GuardrailResult.reason` carries a category label,
  the `report` carries the operator-authored human message; raw policy YAML,
  rule internals, or other users' data never reach the LLM.
- **Streaming (`ask_stream`)**: tool calls execute identically mid-stream; the
  TOOL_CALL stage is orthogonal to OUTPUT_STREAM.

---

## Capabilities

### New Capabilities
- `pbac-toolcall-guardrail`: `GuardrailStage.TOOL_CALL` + `PBACToolCallGuardrail`
  builtin (`"pbac"`) + ToolManager pipeline hook + denial→`ToolResult` translation.
- `userinfo-service-tool`: `UserInfoService` (curated `EmployeeProfile`, TTL
  cache, PBAC attribute feed) + per-agent `UserinfoTool`.

### Modified Capabilities
- `guardrails-infrastructure` (FEAT-396): enum gains `TOOL_CALL`; registry gains
  the `"pbac"` name; bot wiring stamps one more pipeline.
- `policy-based-access-control` (FEAT-077): documentation of the third
  enforcement layer; optional per-policy fail-mode annotation.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/guardrails/base.py` | modifies | Add `GuardrailStage.TOOL_CALL` member (enum + docstring). |
| `parrot/bots/guardrails/registry.py` | extends | Register `"pbac"` lazy factory. |
| `parrot/bots/guardrails/builtin/` | extends | New `pbac.py` — `PBACToolCallGuardrail`. |
| `parrot/tools/manager.py` | modifies | Run TOOL_CALL pipeline in `execute_tool()` after grant/confirm guards; translate BLOCK → `ToolResult(status="forbidden")`. |
| `parrot/bots/` (bot wiring of pipelines) | modifies | Stamp the TOOL_CALL pipeline onto `ToolManager` (same seam as TOOL_OUTPUT stamping). |
| `parrot/auth/pbac.py` | extends | Expose the shared evaluator to guardrail construction (e.g. via app context / bot wiring). |
| `parrot/tools/` | extends | New `UserinfoTool` (`AbstractTool`). |
| new: `UserInfoService` module | depends on | asyncdb + `auth.vw_users` + `TTLCache`; consumed by tool + PBAC context building. |
| `parrot/stores/kb/user.py` | unchanged (deprecation note) | KBs coexist in v1. |
| `policies/*.yaml` | extends | Sample tool policies incl. business-hours DENY + optional `enforcement:` fail-mode key. |

No breaking changes: empty TOOL_CALL pipelines short-circuit; agents without
`guardrails=["pbac"]` and deployments without `setup_pbac()` behave exactly as
today. New dependency: none (navigator-auth already required).

---

## Code Context

### User-Provided Code

_None — user described the existing `parrot/bots/guardrails` infra verbally;
verified below._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/guardrails/base.py:15
class GuardrailStage(str, Enum):
    INPUT = "input"                    # line 24
    TOOL_OUTPUT = "tool_output"        # line 25
    OUTPUT = "output"                  # line 26
    OUTPUT_STREAM = "output_stream"    # line 27
    # NOTE: no TOOL_CALL member today — this feature adds it.

# From packages/ai-parrot/src/parrot/bots/guardrails/base.py:30
class GuardrailAction(str, Enum):
    PASS = "pass"; TRANSFORM = "transform"; FLAG = "flag"; BLOCK = "block"

# From packages/ai-parrot/src/parrot/bots/guardrails/base.py:45
class GuardrailResult(BaseModel):
    action: GuardrailAction
    content: str | None = None
    report: dict[str, Any] | None = None   # BLOCK may attach a non-content report (pipeline.py:186-191)
    reason: str | None = None              # category label, never offending content

# From packages/ai-parrot/src/parrot/bots/guardrails/base.py:63
class GuardrailContext(BaseModel):
    stage: GuardrailStage
    agent_name: str
    user_id: str | None = None
    session_id: str | None = None
    method: str = ""
    tool_name: str | None = None           # today only populated at TOOL_OUTPUT
    extras: dict[str, Any] = Field(default_factory=dict)

# From packages/ai-parrot/src/parrot/bots/guardrails/base.py:87
class Guardrail(ABC):
    name: str
    stages: set[GuardrailStage]
    priority: int                          # bands: 0-99 sanitizers, 100-199 transformers, 200+ observers
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...  # line 115

# From packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py:84
class GuardrailPipeline:
    def __init__(self, on_telemetry: Callable[[GuardrailTelemetryEntry], None] | None = None) -> None  # line 99
    def add(self, guardrail: Guardrail) -> None                                # line 112
    @property
    def has_guardrails(self) -> bool                                           # line 122
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 138
    # Empty pipeline short-circuits (line 149); BLOCK short-circuits chain (line 183)

# From packages/ai-parrot/src/parrot/bots/guardrails/config.py:39
def build_pipelines_from_config(
    guardrails: list[str | dict[str, Any] | Guardrail] | None = None,
    legacy_flags: dict[str, Any] | None = None,
    on_telemetry: Callable[[GuardrailTelemetryEntry], None] | None = None,
) -> dict[GuardrailStage, GuardrailPipeline]
    # Builds one pipeline per GuardrailStage member (line 100-102) — a new enum
    # member is picked up automatically.

# From packages/ai-parrot/src/parrot/bots/guardrails/registry.py:41
def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None
# From registry.py:52 — _make_lazy_factory(module_path, class_name) lazy-import pattern
# From registry.py:95 — build_guardrails(spec) coerces str | dict | Guardrail entries

# From packages/ai-parrot/src/parrot/tools/manager.py:1422
class ToolManager:
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any
    # Guard chain precedent inside: GrantGuard (FEAT-211) then ConfirmationGuard
    # (FEAT-235), each returning ToolResult(success=False, status="forbidden"/
    # "cancelled", error=...) on denial. TOOL_OUTPUT pipeline is stamped onto
    # tools via tool._tool_output_pipeline (defensive re-stamp in execute_tool).
    async def execute_tool_call(self, ...)   # manager.py:1732 — LLM envelope path

# From packages/ai-parrot/src/parrot/auth/resolver.py:44 (AbstractPermissionResolver)
async def can_execute(
    self, context: PermissionContext, tool_name: str, required_permissions: set[str]
) -> bool
# From resolver.py:247 — class PBACPermissionResolver(AbstractPermissionResolver)
#   __init__(self, evaluator: "PolicyEvaluator", logger: Optional[logging.Logger] = None)  # line 275
#   Layer-2 safety net inside AbstractTool.execute(); MUST share evaluator with Guardian.

# From packages/ai-parrot/src/parrot/auth/pbac.py:35
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]"
# Graceful degradation: returns (None, None, None) when navigator-auth missing
# or policy_dir absent — app continues fail-open.

# From packages/ai-parrot/src/parrot/auth/agent_guard.py
#   line 181: from navigator_auth.abac.context import EvalContext
#   line 252: from navigator_auth.abac.policies.environment import Environment
#   line 267: result = evaluator.check_access(...)  — established call shape
#   Fail-open precedents: evaluator is None → return (line 241);
#   request is None (programmatic call) → return (line 244).

# From packages/ai-parrot/src/parrot/stores/kb/user.py:11
class UserInfo(AbstractKnowledgeBase):     # always_active=True, priority=10
    async def search(self, query: str, user_id: int, **kwargs) -> List[Dict]  # line 43
    # SELECT user_id, display_name, username, email, job_code, associate_id,
    #        associate_oid, title, worker_type, manager_id FROM auth.vw_users  (lines 51-55)
# From user.py:78 — class UserProfileKB(AbstractKnowledgeBase)
    # SELECT first_name, last_name, email, job_code, title, department_code,
    #        groups, programs FROM auth.vw_users  (lines 116-124)
# From user.py:27 — TTLCache(max_size=500, default_ttl=600) usage pattern

# From packages/ai-parrot/src/parrot/auth/context.py:38
@dataclass(frozen=True)
class UserContext:
    channel: str; user_id: str; display_name/email/session_id: Optional[str]; metadata: Dict
# context.py:33 — _pctx_var: ContextVar["PermissionContext | None"] for async propagation
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.guardrails import (          # bots/guardrails/__init__.py:14-25
    Guardrail, GuardrailAction, GuardrailContext, GuardrailPipeline,
    GuardrailResult, GuardrailStage, PipelineOutcome,
    build_guardrails, build_pipelines_from_config, register_guardrail,
)
from parrot.auth import (                     # auth/__init__.py
    PermissionContext, UserSession, PBACPermissionResolver, setup_pbac, UserContext,
)
from navigator_auth.abac.context import EvalContext            # used at agent_guard.py:181
from navigator_auth.abac.policies.environment import Environment  # used at agent_guard.py:252
```

#### Key Attributes & Constants
- `Guardrail.on_error` → `Literal["fail_open", "fail_closed"]`, default `"fail_open"` (base.py:112) — PBAC guardrail must override to `"fail_closed"`.
- `PipelineOutcome.blocked/reason/flag_reports` (pipeline.py:77-80) — the denial translation source.
- Guardrail registry names in use: `"prompt_injection"`, `"secrets"`, `"moderation"`, `"groundedness"`; reserved: `"pii"`, `"pseudonymize"` (registry.py:35-38, 146-165) — `"pbac"` is free.
- `navigator-auth>0.20.9` pinned at `packages/ai-parrot/pyproject.toml:66`.
- `ToolResult(success, status, error, result)` denial shape: `status="forbidden"` precedent at manager.py (GrantGuard block).

### Does NOT Exist (Anti-Hallucination)
- ~~`GuardrailStage.TOOL_CALL`~~ — the enum has only INPUT / TOOL_OUTPUT / OUTPUT / OUTPUT_STREAM today; this feature introduces it.
- ~~`"pbac"` guardrail name / `PBACToolCallGuardrail`~~ — not in the registry or `builtin/` (only `legacy_pipeline`, `moderation`, `prompt_injection`, `secrets`).
- ~~`UserinfoTool` / `UserInfoService` / `EmployeeProfile`~~ — no structured user-profile tool or service exists; only the KB classes in `stores/kb/user.py`.
- ~~Pre-execution guardrail hook in `ToolManager`~~ — guardrails currently run only at TOOL_OUTPUT (via `tool._tool_output_pipeline` in `tools/abstract.py`); nothing runs before `tool.execute()` except Grant/Confirmation guards and the Layer-2 resolver.
- ~~Per-policy fail-mode annotation (`enforcement:` key)~~ — `on_error` exists only as a per-guardrail class attribute; policy-level fail-mode is new.
- ~~Argument-level ABAC~~ — explicitly a FEAT-077 non-goal; still out of scope in this v1.
- ~~Final-response/topic classification guardrail~~ — no content classifier exists; deferred by design.
- ~~`Guardian.check_tool_call()` or batch `check_access()`~~ — evaluation is per-resource via `PolicyEvaluator.check_access()`.

---

## Parallelism Assessment

- **Internal parallelism**: Two nearly independent lanes. Lane 1 (guardrail):
  enum + builtin + registry + `ToolManager` hook + bot wiring (sequential within
  itself — the stage must exist before the builtin/hook). Lane 2 (UserinfoTool):
  `UserInfoService` + `EmployeeProfile` + tool + tests — touches none of Lane 1's
  files. The only join point is `PBACToolCallGuardrail` optionally enriching
  `EvalContext` with UserInfoService attributes (a thin, final integration task).
- **Cross-feature independence**: `parrot/bots/guardrails/*` was just landed by
  FEAT-396 and `tools/manager.py` is a high-traffic file (FEAT-380 compression,
  FEAT-211/235 guards) — verify no in-flight feature is editing
  `execute_tool()` before starting. `sdd/state/FEAT-404` is in flight; check its
  scope at spec time.
- **Recommended isolation**: `mixed` — Lane 2 (userinfo) can run in its own
  worktree in parallel; Lane 1 tasks stay sequential in the feature worktree.
- **Rationale**: disjoint file sets between lanes make conflicts unlikely, and
  the single integration task at the end absorbs the join; forcing full
  sequential execution would serialize ~40% of the work for no safety gain.

---

## Open Questions

- [x] Q1: Does the DENY reach the user directly or via the LLM? — *Owner: Jesus*: Via the LLM — BLOCK is translated to `ToolResult(status="forbidden", error=<reason>)` so the agent verbalizes the denial; the agent loop continues.
- [ ] Q2: Timezone source for business-hours `Environment` conditions — server clock, policy-declared tz, or user-profile tz? Needs confirmation of what navigator-auth's `Environment` supports today. — *Owner: Jesus*
- [ ] Q3: Exact syntax for the per-policy fail-mode annotation (e.g. `enforcement: fail_open` key in policy YAML) — does navigator-auth's `ResourcePolicy` schema allow custom keys, or does this live in a parrot-side sidecar config? — *Owner: Jesus*
- [ ] Q4: Should `PBACPermissionResolver` (Layer 2) stay active alongside the TOOL_CALL guardrail (double evaluation, defense-in-depth) or be bypassed when the guardrail already evaluated the same call? Proposal: keep both; shared evaluator + 30s cache makes cost negligible. — *Owner: Jesus*
- [ ] Q5: Adopt Option C's add-on — rendering policy availability windows into tool descriptions at listing time (per-request, user-relative) — in this feature or as a follow-up? — *Owner: Jesus*
- [ ] Q6: `UserinfoTool` field set final review: is `manager_id` (an internal id) useful to the LLM, or should the service resolve it to the manager's display name? — *Owner: Jesus*
- [ ] Q7: How is the shared `PolicyEvaluator` handed to guardrail construction? (`build_pipelines_from_config` builds from names/dicts; the `"pbac"` factory needs the evaluator instance — likely a `Guardrail` instance passed in bot wiring, or an app-context lookup.) — *Owner: dev at spec time*
