---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: ToolManager ToolDefinition Enforcement Parity (G7 remediation)

**Date**: 2026-08-29
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`ToolManager.execute_tool()` bypasses `permission_context` **entirely** for the
`ToolDefinition` (`@tool`-decorated function) path
(`packages/ai-parrot/src/parrot/tools/manager.py:1549-1560`): the branch calls
`tool.function(**parameters)` directly, skipping every enforcement layer that
the `AbstractTool` branch runs — the TOOL_CALL guardrail pipeline (FEAT-406,
PBAC), GrantGuard (FEAT-211), ConfirmationGuard (FEAT-235), and the Layer 2
`resolver.can_execute()` check performed inside `AbstractTool.execute()`
(`abstract.py:875-890`).

This was a pre-existing internal gap, but **FEAT-469 (A2UI Agent Functions,
PR #1270) made it remotely reachable**: every non-hidden ToolManager tool is
now renderer-invocable via the A2UI RPC surface (`callAgentFunction` over the
dedicated HTTP endpoint and A2A `DataPart` envelopes), where the session
user's `PermissionContext` is *the only authorization barrier* (spec G7). For
`@tool` functions that barrier is currently decorative. The gap was escalated
in the PR #1270 body, logged per-call in `ToolManagerExecutor.call()`
(`outputs/a2ui/runtime/adapters.py:73-80`), and documented as a known
limitation in `docs/outputs/a2ui-agent-functions.md` §4.

A compensating fix (excluding `ToolDefinition` tools from A2UI dispatch) was
attempted and reverted during FEAT-469: it contradicted G7's resolved Open
Question ("every ToolManager tool is invocable, no opt-in") and broke
`test_e2e_http_call_agent_function`. **A ToolManager-level fix does not have
that problem** — G7 demands that every invocation pass `permission_context`
to `execute_tool` and that a denied tool produce `error{code:"FORBIDDEN"}`
(spec AC-G7, `a2ui-agent-functions.spec.md:392`). Enforcing inside the
manager *fulfills* G7; only the exclusion approach contradicted it.

A second, latent defect compounds it: `@tool(requires_confirmation=True,
confirm_template=..., confirm_window_seconds=..., allow_edit=...)` is an
advertised FEAT-235 API whose docstring promises HITL confirmation "via
ConfirmationGuard in ToolManager" (`decorators.py:80-92`) — but registration
drops `routing_meta` when converting the function to `ToolDefinition`
(`manager.py:783-788`), and the `ToolDefinition` branch never calls the
guard. The documented API is silently inert end-to-end.

**Affected**: any deployment exposing agents through A2UI (renderer RPC),
A2A, or MCP where `@tool`-decorated functions are registered; operators
relying on PBAC guardrails, resolver permissions, or `requires_confirmation`
believing they cover all tools uniformly.

## Constraints & Requirements

Decisions resolved interactively during discovery (Rounds 0–3):

- **Flow**: `type: feature`, `base_branch: dev` — the exploitable A2UI RPC
  surface exists only on `dev`; the fix must land before a release cut
  carries A2UI to `main`.
- **Parity scope**: the `ToolDefinition` path must run the **TOOL_CALL
  guardrail pipeline + ConfirmationGuard + Layer 2 resolver check**.
  GrantGuard stays `AbstractTool`-only (the `@tool` decorator has no
  `requires_grant` API), with a **registration-time warning** when a
  grant-requiring policy targets a `ToolDefinition` name, plus explicit docs.
- **Honor the FEAT-235 API**: preserve `routing_meta` on `ToolDefinition` so
  `@tool(requires_confirmation=True)` actually confirms — fixing the broken
  documented promise is in scope.
- **Fail-open without context preserved**: no `permission_context` (or no
  resolver) ⇒ no Layer 2 enforcement, mirroring `AbstractTool.execute()`'s
  `pctx is not None and resolver is not None` gate (`abstract.py:875`). No
  breakage for internal callers; the A2UI surface always supplies a context
  (G7 + the fail-closed A2A identity gate fixed in PR #1270).
- **`required_permissions` become declarable on `@tool`**: extend
  `ToolDefinition` and the `@tool` decorator with `required_permissions`
  (default empty set), mirroring `AbstractTool._required_permissions`.
- **`ToolManager.execute_tool_call()` in scope**: gains an optional
  `permission_context` parameter threaded into `execute_tool()` (note: it
  currently has no in-repo callers — the live LLM loop is
  `clients/base.py:_execute_tool` which already threads
  `self._permission_context`, base.py:1494-1496 — but it is public API).
- **Uniform structured audit logs**: one shared helper emits identical
  structured records (tool name, path kind, user_id, layer, decision) for
  allow/deny on both branches. No AuditLedger wiring (explicitly deferred).
- **Denials return `ToolResult(status="forbidden")`** exactly like the
  `AbstractTool` branch, so `ToolManagerExecutor._normalize()` and AC-G7's
  `error{code:"FORBIDDEN"}` mapping work unchanged.
- Backwards compatibility: the successful `ToolDefinition` path must keep
  returning the function's **raw** return value (A2UI's `_normalize()` and
  existing callers depend on it).
- Async-first, Google docstrings, strict typing, pytest after any logic
  change (project standards).

---

## Options Explored

### Option A: In-place branch parity inside `execute_tool()` (hoisted guards)

Keep the two-branch dispatch but give the `ToolDefinition` branch the same
pre-execution gauntlet, hoisted to manager level (plain functions cannot
receive `_permission_context`/`_resolver` kwargs the way
`AbstractTool.execute()` does):

1. Restructure `execute_tool()` so the TOOL_CALL guardrail pipeline
   (currently `AbstractTool`-only, manager.py:1579-1610) runs **before** the
   branch split — its `GuardrailContext` only needs
   `tool_name`/`arguments`/`permission_context`, nothing tool-instance-specific.
2. Add `routing_meta` and `required_permissions` fields to `ToolDefinition`
   (extending `__slots__`), populate them at every construction site
   (`manager.py:783, 794, 802` and the `@tool` metadata at
   `decorators.py:135-146`), and add a `required_permissions` parameter to
   the `@tool` decorator.
3. On the `ToolDefinition` branch, before invoking the function:
   ConfirmationGuard (`confirm()` only needs `.name` + `.routing_meta` —
   verified at `confirmation.py:417-436`) → Layer 2 check
   `await self._resolver.can_execute(pctx, tool.name, tool.required_permissions)`
   when both `pctx` and `self._resolver` are present. Deny ⇒
   `ToolResult(status="forbidden")`.
4. Registration-time warning when `routing_meta.get("requires_grant")` is
   truthy on a `ToolDefinition` (grant policies are inert on this path).
5. Shared `_log_enforcement_decision()` helper used by both branches.
6. Optional `permission_context` param on `execute_tool_call()`.

✅ **Pros:**
- Smallest diff that achieves the agreed parity; the `AbstractTool` branch
  ordering (pipeline → grant → confirm → execute) is untouched.
- No behavioural change for any caller that doesn't pass a context
  (fail-open preserved verbatim).
- `ConfirmationGuard`/guardrail pipeline are reused as-is — both already
  duck-type on `.name`/`.routing_meta`.
- Fixes the inert `@tool(requires_confirmation=True)` API with the same
  mechanism.
- Directly satisfies AC-G7 for every tool kind; the A2UI adapter's warning
  and doc caveat can be deleted.

❌ **Cons:**
- `execute_tool()` grows further (it is already the hottest, most guarded
  method in the manager); two branches still exist to keep in sync for
  future layers.
- `ToolDefinition.__slots__` extension touches a widely-constructed class
  (every construction site must be updated in the same change).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — (stdlib + existing internals) | No new dependencies | pytest / pytest-asyncio for tests (already in dev deps) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/manager.py:1579-1610` — TOOL_CALL guardrail block to hoist/share
- `packages/ai-parrot/src/parrot/auth/confirmation.py:416-436` — `ConfirmationGuard.confirm()` (duck-types on `.name`/`.routing_meta`)
- `packages/ai-parrot/src/parrot/auth/resolver.py:44-63` — `AbstractPermissionResolver.can_execute()` contract
- `packages/ai-parrot/src/parrot/tools/abstract.py:875-890` — the exact fail-open gate + forbidden `ToolResult` shape to mirror
- `packages/ai-parrot/src/parrot/tools/decorators.py:126-146` — `routing_meta` already built by `@tool`; just stop dropping it

---

### Option B: Normalize at registration — wrap every `@tool` into a `FunctionTool(AbstractTool)`

Eliminate the second execution path instead of hardening it: introduce a thin
`FunctionTool` subclass of `AbstractTool` that wraps a plain callable, and
have all `ToolDefinition`-producing registration paths (`manager.py:783, 794,
802`) construct it instead. `execute_tool()`'s `ToolDefinition` branch
becomes legacy/deprecated; every tool flows through the single, fully-guarded
`AbstractTool` lane (grants included, for free).

✅ **Pros:**
- One enforcement path forever — future guards automatically cover `@tool`
  functions; the class of bug is structurally eliminated.
- `@tool` functions gain the whole `AbstractTool` feature set (redaction,
  output pipeline, tracing, compression tee, even grants).

❌ **Cons:**
- Highest blast radius: `isinstance(tool, ToolDefinition)` checks exist
  across the codebase (schemas, MCP export, A2UI adapter, clients);
  `AbstractTool.execute()` wraps results in `ToolResult` while the
  `ToolDefinition` path returns raw values — preserving raw-return semantics
  through `FunctionTool` needs careful, riskier shimming.
- `AbstractTool.execute()` carries heavy machinery (tracing, redaction,
  pipelines) that simple `@tool` lambdas never needed — latent behavioural
  drift for every existing `@tool` user.
- Far more test churn than the security fix requires.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | No new dependencies | |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/abstract.py:837+` — `AbstractTool.execute()` as the single lane
- `packages/ai-parrot/src/parrot/tools/manager.py:739-818` — registration sites to redirect

---

### Option C (unconventional): Extract a `ToolEnforcementPipeline` chokepoint object

Pull the entire pre-execution gauntlet (guardrail pipeline → grant →
confirmation → Layer 2 resolver) out of `execute_tool()` into a dedicated,
ordered, tool-kind-aware `ToolEnforcementPipeline` strategy object. The
manager calls `decision = await self._enforcement.check(tool, parameters,
permission_context)` exactly once, before *any* dispatch, for *any* tool
kind; per-kind applicability (e.g. "grants don't apply to ToolDefinition")
lives declaratively in the pipeline stages, not in branch code.

✅ **Pros:**
- Best long-term shape: enforcement becomes testable in isolation,
  impossible to fork per-branch, and trivially extensible (future layers
  register a stage instead of editing `execute_tool()`).
- Uniform audit emission falls out naturally (the pipeline logs every
  stage decision).

❌ **Cons:**
- A refactor of the most security-critical method in the framework inside a
  security remediation — moves FEAT-406/211/235 battle-tested code, risking
  regressions in the layers that already work.
- Larger review surface; delays closing a live gap for architectural payoff
  that could be a follow-up.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | No new dependencies | |

🔗 **Existing Code to Reuse:**
- The three guard blocks in `manager.py:1573-1652` would move mostly verbatim into stages
- `parrot/bots/guardrails/base.py` — `GuardrailContext`/pipeline pattern to imitate

---

### Option D (rejected baseline, for completeness): Enforce only at the A2UI boundary

Do the resolver/confirmation checks inside `ToolManagerExecutor.call()`
instead of the manager. **Rejected**: leaves every other route to
`execute_tool()` (A2A `parrot/a2a/server.py:1103`, MCP, claude-agent bridge,
plan nodes `bots/flows/plan/node.py:431`, direct callers) exposed; it is the
same shape as the compensating fix already reverted in FEAT-469 and would
re-litigate G7. Not estimated further.

---

## Recommendation

**Option A** is recommended because:

- It closes the live, remotely-reachable gap with the smallest security-
  relevant diff, reusing the existing, battle-tested guard implementations
  unchanged — `ConfirmationGuard.confirm()` and the guardrail pipeline
  already duck-type on exactly the attributes `ToolDefinition` will gain.
- It resolves the PR #1270 escalation **within** G7's resolved design:
  every tool stays invocable; denials become real `FORBIDDEN`s (AC-G7).
- Option B's single-lane purity and Option C's pipeline chokepoint are both
  attractive, but each refactors far more battle-tested code than a
  security remediation should carry; either can be a follow-up brainstorm
  once the gap is closed. The trade-off accepted: two dispatch branches
  continue to exist and must be kept in parity by tests (a dedicated
  parity test asserting both branches deny identically mitigates this).

---

## Feature Description

### User-Facing Behavior

- A renderer (or any A2UI/A2A/MCP caller) invoking a `@tool`-decorated
  function without the required permissions now receives
  `error{code:"FORBIDDEN"}` instead of the function silently executing —
  identical to the `AbstractTool` behaviour. AC-G7 becomes true for every
  tool kind.
- `@tool(required_permissions={"reports:read"})` — new decorator parameter;
  the Layer 2 resolver receives the declared set (empty set = unrestricted,
  resolver still sees the tool name for name-based policies).
- `@tool(requires_confirmation=True, ...)` now actually triggers HITL
  confirmation through `ConfirmationGuard`, honoring the documented
  FEAT-235 contract (including `confirm_template`, `confirm_window_seconds`,
  `allow_edit`, and the fail-closed no-HITL-channel behaviour).
- Operators see a registration-time `WARNING` if a `ToolDefinition` carries
  `routing_meta["requires_grant"]` (grant policies remain inert on this
  path by design — anything needing grants must be an `AbstractTool`).
- `docs/outputs/a2ui-agent-functions.md` §4 known-limitation bullet and the
  per-call `WARNING` in `ToolManagerExecutor.call()` are removed; the doc
  now states enforcement is uniform.

### Internal Behavior

`execute_tool()` flow after the change:

1. Lookup (unchanged, `not_found` short-circuit).
2. **TOOL_CALL guardrail pipeline runs for both tool kinds** (hoisted above
   the branch split; context carries tool_name/arguments/permission_context).
   Blocked ⇒ `ToolResult(status="forbidden")` with the guardrail's message.
3. `ToolDefinition` branch, in order:
   a. **ConfirmationGuard** (if configured): `confirm(tool=..., parameters=...,
      permission_context=...)` — reads the now-preserved `routing_meta`.
      Denied ⇒ `ToolResult(status=cancelled|timeout)`. Edited parameters are
      honored, mirroring the `AbstractTool` branch.
   b. **Layer 2 resolver check** (manager-level, since plain functions take
      no `_permission_context` kwarg): when `permission_context is not None
      and self._resolver is not None`, `await self._resolver.can_execute(
      pctx, tool.name, tool.required_permissions)`. Denied ⇒
      `ToolResult(status="forbidden")` with the same message/metadata shape
      as `abstract.py:880-890`.
   c. Invoke `tool.function(**parameters)` (sync/async detection unchanged);
      return the **raw** result (unchanged contract).
4. `AbstractTool` branch: unchanged except the guardrail block moved above
   the split (identical ordering semantics: pipeline → grant → confirm →
   execute).
5. Every allow/deny decision on **both** branches goes through one shared
   structured-logging helper: tool name, tool kind
   (`tool_definition`/`abstract_tool`), user_id (or `anonymous`), layer
   (`guardrail`/`grant`/`confirmation`/`resolver`), decision, reason.
6. `execute_tool_call(content_block, permission_context=None)` threads the
   new optional parameter into `execute_tool()`.
7. Registration (`register_tool`/`add_tool` paths) copies
   `meta['routing_meta']` and `meta['required_permissions']` onto the
   `ToolDefinition`; dict/param-based constructions default them
   (`{}` / `set()`); a `requires_grant`-flagged `ToolDefinition` logs the
   inert-grant warning.

### Edge Cases & Error Handling

- **No `permission_context` / no resolver**: fail-open (no Layer 2 check),
  byte-for-byte the current semantics for internal callers and tests.
  Guardrail pipeline and ConfirmationGuard still run when configured (they
  do today on the AbstractTool path even without pctx — confirmation keys
  the window on `"anonymous"`).
- **Resolver raises**: propagate as today on the `AbstractTool` path — do
  not swallow into fail-open (a broken resolver must not silently allow).
- **`required_permissions` empty**: resolver still called with the empty
  set (resolver contract: empty = unrestricted, but name-based resolvers
  may still deny — matches `AbstractTool` semantics exactly).
- **ConfirmationGuard with edited parameters**: re-validated parameters
  replace the originals before the function call (mirrors manager.py:1649-1651).
- **Legacy pickled/duck-typed `ToolDefinition`s** (constructed positionally
  elsewhere): new slots get safe defaults via `__init__` defaults; absence
  of `routing_meta` treated as `{}` at every read site (`getattr` guard).
- **Raw-return invariant**: a successful `ToolDefinition` call still
  returns the raw function value — only *denials* introduce `ToolResult`s
  on this branch, which `ToolManagerExecutor._normalize()` and the client
  loop already handle (both stringify/normalize any shape).
- **E2E**: `test_e2e_http_call_agent_function` (allow path) must keep
  passing untouched; a new companion E2E proves the deny path returns
  `error{code:"FORBIDDEN"}` through the real A2UI HTTP surface.

---

## Capabilities

### New Capabilities
- `toolmanager-tooldefinition-enforcement`: uniform guardrail + confirmation +
  Layer 2 permission enforcement for `ToolDefinition`/`@tool` executions in
  `ToolManager.execute_tool()`, with declarable `required_permissions` on
  `@tool`, preserved `routing_meta`, uniform structured enforcement audit
  logging, and A2UI FORBIDDEN e2e coverage.

### Modified Capabilities
- `a2ui-agent-functions` (FEAT-469): §4 security-posture doc updated, the
  `ToolManagerExecutor.call()` known-gap warning removed, spec risk section
  amended to record that the manager-level fix **satisfies** G7 (formally
  resolving the PR #1270 escalation).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | modifies | `execute_tool()` branch parity; `ToolDefinition` new fields; registration metadata copy + inert-grant warning; `execute_tool_call()` optional pctx; shared enforcement-log helper |
| `packages/ai-parrot/src/parrot/tools/decorators.py` | extends | `@tool(required_permissions=...)`; metadata dict carries it; docstring corrected/confirmed |
| `packages/ai-parrot/src/parrot/auth/confirmation.py` | depends on | reused as-is (duck-types on `.name`/`.routing_meta`); type hint of `tool:` param loosened to the duck-typed protocol or `Union` |
| `packages/ai-parrot/src/parrot/auth/grants.py` | unchanged | explicitly out of scope for `ToolDefinition`; registration warning references it |
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py` | modifies | remove the known-gap `WARNING` block in `ToolManagerExecutor.call()` |
| `docs/outputs/a2ui-agent-functions.md` | modifies | §4 known-limitation bullet replaced with uniform-enforcement statement |
| `sdd/specs/a2ui-agent-functions.spec.md` | modifies | risk/§ amendment: G7 satisfied by manager-level enforcement (escalation closure) |
| `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py` | extends | new FORBIDDEN-path e2e beside `test_e2e_http_call_agent_function` |
| `packages/ai-parrot-tools/tests/test_manager_permissions.py` | extends | parity tests: both branches deny identically |
| `packages/ai-parrot/src/parrot/clients/base.py` | unchanged | already threads `_permission_context` (base.py:1494-1496) — verified, no change |

No new external dependencies. No breaking changes for callers that do not
pass a `permission_context`. Behaviour change (intended) for callers that DO
pass one plus a resolver/guardrails/confirmation config: `@tool` functions
can now be denied.

---

## Code Context

### User-Provided Code

Escalation text from PR #1270 body (source: `gh pr view 1270`):

> 🔴 `ToolManager.execute_tool()` bypasses `permission_context` entirely for
> the `ToolDefinition` (`@tool`-decorated) path — a pre-existing gap in
> `ToolManager` itself (not introduced by this feature). A compensating fix
> (excluding these tools from A2UI dispatch) was attempted and **reverted**:
> it contradicts spec G7's resolved Open Question ("every ToolManager tool is
> invocable, no opt-in") and broke `test_e2e_http_call_agent_function` […]
> **Please decide**: accept the documented risk, or follow up with a
> `ToolManager`-level fix before/after merge.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/manager.py:27-34
class ToolDefinition:
    __slots__ = ('name', 'description', 'input_schema', 'function')  # line 30
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable

# From packages/ai-parrot/src/parrot/tools/manager.py:1519-1524
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...
# ToolDefinition branch: lines 1549-1560 — direct tool.function(**parameters),
#   comment "ToolDefinition does not support permission enforcement".
# AbstractTool branch: TOOL_CALL guardrail pipeline 1579-1610;
#   GrantGuard 1616-1628; ConfirmationGuard 1636-1652 (edited params 1649-1651);
#   _permission_context/_resolver kwargs propagation 1656-1660.

# From packages/ai-parrot/src/parrot/tools/manager.py:1869-1891
async def execute_tool_call(self, content_block: Dict[str, Any]) -> Dict[str, Any]:
    # calls self.execute_tool(tool_name, tool_input) at line 1879 — NO permission_context.
    # NOTE: zero in-repo callers found (public API only).

# From packages/ai-parrot/src/parrot/tools/manager.py:739-818 (register_tool internals)
# @tool-function → ToolDefinition conversion at 783-788: copies ONLY
# name/description/schema/function from tool._tool_metadata — routing_meta dropped.
# dict path 794-799; explicit-params path 802-807.

# From packages/ai-parrot/src/parrot/tools/decorators.py:55-66
def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    auto_register: bool = False,
    requires_confirmation: bool = False,
    confirm_template: Optional[str] = None,
    confirm_window_seconds: int = 0,
    allow_edit: bool = False,
): ...
# Builds confirmation routing_meta at 126-133; stores func._tool_metadata
# (incl. 'routing_meta') at 135-146; sets func._is_tool.

# From packages/ai-parrot/src/parrot/tools/abstract.py:859-890 (inside AbstractTool.execute)
pctx = kwargs.pop("_permission_context", None)      # line 860
resolver = kwargs.pop("_resolver", None)            # line 861
if pctx is not None and resolver is not None:       # line 875 — fail-open gate
    required = getattr(self, "_required_permissions", set())
    allowed = await resolver.can_execute(pctx, self.name, required)
    # denial → ToolResult(success=False, status="forbidden",
    #   error=f"Permission denied: '{self.name}' requires {required}",
    #   metadata={tool_name, user_id, required_permissions})  # lines 880-890

# From packages/ai-parrot/src/parrot/auth/resolver.py:25,44-49
class AbstractPermissionResolver(ABC):
    async def can_execute(
        self, context: PermissionContext, tool_name: str,
        required_permissions: set[str],
    ) -> bool: ...   # empty set = unrestricted

# From packages/ai-parrot/src/parrot/auth/grants.py:338,379-385
class GrantGuard:
    async def authorize(self, *, tool: "AbstractTool", parameters: dict,
                        permission_context: Optional["PermissionContext"] = None,
                        ) -> GuardDecision: ...
    # gate: `if not tool.routing_meta.get("requires_grant")` → allow (line ~399)

# From packages/ai-parrot/src/parrot/auth/confirmation.py:416-436
class ConfirmationGuard:
    async def confirm(self, *, tool: "AbstractTool", parameters: dict,
                      permission_context: Optional["PermissionContext"] = None,
                      ) -> ConfirmationDecision: ...
    # gate at line 436: `if not (tool.routing_meta or {}).get("requires_confirmation")`
    # → only needs .routing_meta and .name → duck-type compatible with an
    #   extended ToolDefinition.

# From packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py:44-96
class ToolManagerExecutor:
    async def call(self, name: str, args: dict[str, Any], ctx: A2UICallContext) -> ToolResult:
        # known-gap WARNING for ToolDefinition at ~73-80 (to remove);
        # a2ui_audit INFO line at ~88-95; _normalize() wraps raw returns.

# From packages/ai-parrot/src/parrot/clients/base.py:1454,1494-1496
async def _execute_tool(...):  # client LLM loop
    perm_ctx = getattr(self, '_permission_context', None)   # line 1494
    ... execute_tool(tool_name, merged, permission_context=perm_ctx)  # 1496
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.tools.manager import ToolDefinition, ToolManager   # manager.py:27, ~248
from parrot.tools.decorators import tool                        # decorators.py:55
from parrot.auth.resolver import AbstractPermissionResolver     # resolver.py:25
from parrot.auth.grants import GrantGuard                       # grants.py:338
from parrot.auth.confirmation import ConfirmationGuard          # confirmation.py:~397
```

#### Key Attributes & Constants
- `ToolManager._resolver` → `Optional[AbstractPermissionResolver]` (manager.py:323, property 369, `set_resolver` 377)
- `ToolManager._grant_guard`, `ToolManager._confirmation_guard`, `ToolManager._tool_call_pipeline` — guard seams consulted in `execute_tool()` (manager.py:1579, 1616, 1636)
- `AbstractTool._required_permissions` → `set` (read via `getattr(..., set())`, abstract.py:876)
- Spec anchors: G7 at `sdd/specs/a2ui-agent-functions.spec.md:64-65`; AC-G7 at line 392; rejected per-surface allowlist in Non-Goals (~line 78)
- Known-limitation doc: `docs/outputs/a2ui-agent-functions.md` §4 ("Security posture")
- E2E allow-path test: `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py::test_e2e_http_call_agent_function`

### Does NOT Exist (Anti-Hallucination)
- ~~`ToolDefinition.routing_meta` / `ToolDefinition.required_permissions`~~ — do NOT exist yet; this feature adds them (`__slots__` is currently only the 4 fields)
- ~~`@tool(required_permissions=...)`~~ — decorator has NO such parameter today
- ~~`@tool(requires_grant=...)`~~ — never existed; grants remain AbstractTool-only after this feature too
- ~~Callers of `ToolManager.execute_tool_call()`~~ — none in-repo; the live LLM loop is `clients/base.py:_execute_tool` (a different method)
- ~~`AuditLedger` wiring inside `execute_tool()`~~ — `parrot/security/audit_ledger.py` and `parrot/auth/audit.py` exist but are NOT wired here, and deliberately stay unwired (Round 2 decision: structured logs only)
- ~~Layer 2 resolver check inside the manager for `AbstractTool`s~~ — for that branch it happens INSIDE `AbstractTool.execute()` via `_permission_context`/`_resolver` kwargs; do not add a duplicate manager-level check for AbstractTool

---

## Parallelism Assessment

- **Internal parallelism**: Low. Nearly everything funnels through
  `manager.py` (`ToolDefinition`, registration, `execute_tool`); the
  decorator, docs, and e2e-test tasks depend on those manager changes
  landing first. Only the docs/spec-amendment task is truly independent.
- **Cross-feature independence**: `manager.py` is a high-traffic file
  (FEAT-380/396/406 touched it recently) — check for in-flight worktrees
  touching `parrot/tools/manager.py` before starting. TASK-2570
  (`ToolManagerExecutor`) merged with PR #1270, no conflict.
- **Recommended isolation**: per-spec (single worktree, sequential tasks).
- **Rationale**: a security fix concentrated in one hot method benefits from
  a single review narrative; splitting worktrees over one file invites
  conflicts with zero wall-clock gain.

---

## Open Questions

- [x] Feature or hotfix? — *Owner: Jesus*: feature on `dev` (A2UI surface is dev-only; fix must land before any release cut carries A2UI to main).
- [x] Enforcement parity scope for the ToolDefinition path? — *Owner: Jesus*: resolver + TOOL_CALL guardrails + ConfirmationGuard (upgraded from "resolver + guardrails" after discovering the inert FEAT-235 `requires_confirmation` API — "honor the API"). GrantGuard stays AbstractTool-only.
- [x] Behaviour without permission_context? — *Owner: Jesus*: keep fail-open (mirror `abstract.py:875`'s pctx-AND-resolver gate).
- [x] Source of required_permissions for @tool functions? — *Owner: Jesus*: add `required_permissions` to `@tool` and `ToolDefinition` (default empty set).
- [x] Grant/confirmation residual on @tool? — *Owner: Jesus*: document + registration-time warning when a grant-requiring policy targets a ToolDefinition; confirmation is honored (not residual anymore).
- [x] `execute_tool_call()` in scope? — *Owner: Jesus*: yes — optional `permission_context` parameter, threaded through; fail-open default preserved.
- [x] Audit depth? — *Owner: Jesus*: uniform structured logs via a shared helper on both branches; NO AuditLedger wiring (deferred).
- [x] Extras? — *Owner: Jesus*: E2E FORBIDDEN test via the A2UI HTTP surface; remove known-limitation docs + adapter warning; amend a2ui-agent-functions spec to record G7 satisfied (closes the PR #1270 escalation); uniform audit of both paths.
- [ ] Should `ConfirmationGuard.confirm()` / `GrantGuard.authorize()` type hints be loosened to a `Protocol` (name + routing_meta) instead of `"AbstractTool"`, or is a docstring note enough? — *Owner: implementer (spec phase)*
- [ ] Does any downstream/plugin code construct `ToolDefinition` positionally (would break on new `__slots__` fields without defaults)? Verify in plugins repo before finalizing constructor signature. — *Owner: Jesus*
