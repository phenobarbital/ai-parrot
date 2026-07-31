---
type: Wiki Overview
title: 'Brainstorm: HITL Tool-Call Confirmation'
id: doc:sdd-proposals-hitl-confirmation-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents in AI-Parrot can invoke any tool the LLM decides to call, immediately
  and
relates_to:
- concept: mod:parrot.auth.confirmation
  rel: mentions
- concept: mod:parrot.auth.grants
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.manager
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: HITL Tool-Call Confirmation

**Date**: 2026-06-12
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Agents in AI-Parrot can invoke any tool the LLM decides to call, immediately and
without a human checkpoint. For **side-effecting / irreversible operations**
(registrar un check-in/check-out, enviar un correo, crear un ticket, mover dinero)
this is risky: a hallucinated argument or a misread intent executes for real before
the user can intervene.

We want a declarative **"confirm-before-execute"** Human-in-the-Loop mode: a tool
can be marked as *requiring confirmation*, and when the LLM decides to call it, the
agent does **not** execute immediately. Instead it sends the user a **briefing**
("Voy a ejecutar `workday_checkin` con estos valores: …") and waits for the user to
approve, **edit**, or cancel. Only on approval does the tool actually run.

Canonical example: el usuario pide registrar su check-in. El LLM elige
`workday_checkin`. El tool está marcado como `requires_confirmation`. En vez de
ejecutarlo, el agente responde *"voy a ejecutar workday_checkin con
{employee_id: 123, time: '09:00'}, ¿confirmas? (Sí / No / editar)"*. El usuario
responde **Yes/True** → se ejecuta; **No/False** → se cancela; o devuelve valores
corregidos → se ejecuta con los valores nuevos.

**Affected:** end users (gain a safety checkpoint), agent authors (declare
confirmation per tool), and the runtime tool-dispatch path.

## Constraints & Requirements

- **Declarative per-tool**: confirmation is metadata on the tool
  (`routing_meta["requires_confirmation"]`), exposable via the `@tool` decorator,
  `AbstractTool`, and at toolkit level. (Decided in discovery.)
- **Reuse, don't reinvent**: the FEAT-211 Grant subsystem already gates tool calls
  at the **same dispatch point** in `ToolManager.execute_tool()` and already does
  HITL approval via `HumanInteractionManager`. The new feature must be a
  **separate-but-sibling guard** (`ConfirmationGuard`), not a fork of that logic
  and not a second parallel HITL stack.
- **Both wait strategies**: support `WaitStrategy.BLOCK` (synchronous wait — CLI,
  web long-poll) and `WaitStrategy.SUSPEND` (pause + Redis rehydration — Telegram/
  Teams async). Reuse the existing `WaitStrategy` enum.
- **Configurable briefing**: each tool may declare its own briefing template in
  `routing_meta`; fall back to a raw `tool + param=value` listing when no template
  is set.
- **Approve / cancel / edit**: the user may approve as-is, cancel, **or return
  corrected values** that replace the parameters before execution (requires
  re-validation against the tool's `args_schema`).
- **Per-call with optional window**: confirmation is requested on **every** call by
  default, but a tool may declare `confirm_window_seconds` to skip re-asking within
  that window (mirrors the FEAT-211 grant-window pattern).
- **Graceful rejection**: a `No` / timeout / no-response must return a
  `ToolResult(success=False, status="cancelled"|"timeout")` back to the LLM so the
  agent keeps running and can react — it must **not** kill the agent run.
- Async throughout; Pydantic models; `self.logger`; no blocking I/O.

---

## Options Explored

### Option A: Dedicated `ConfirmationGuard` — sibling to `GrantGuard`

A new governor object, **symmetric** to `GrantGuard` (FEAT-211), wired into
`ToolManager` via `set_confirmation_guard()` / `confirmation_guard` property and
invoked inside `execute_tool()` right next to the existing grant check (before
`tool.execute()`). It owns the full confirm-before-execute lifecycle:

1. Read `tool.routing_meta` — if no `requires_confirmation`, return `allowed` and
   the dispatch continues unchanged (purely additive, like the grant path).
2. Check an in-memory/Redis **confirmation window** keyed by
   `(owner, tool, args-hash)`; if a recent approval covers it and
   `confirm_window_seconds` is set, skip the prompt.
3. Build a **briefing** from the tool's `confirm_template` (rendered against the
   parameters) or a raw `tool + param=value` listing.
4. Ask the human via `HumanInteractionManager`:
   - `InteractionType.APPROVAL` for plain Yes/No.
   - `InteractionType.FORM` (seeded with current params as `form_schema`) when the
     tool allows **edit-before-execute**, so the user can return corrected values.
   - Honour `WaitStrategy.BLOCK` (`request_human_input`) vs `SUSPEND`
     (`request_human_input_async` → raise `HumanInteractionInterrupt`).
5. On approval → return a decision carrying the (possibly edited & re-validated)
   parameters; `ToolManager` executes with those. On reject/timeout → `ToolManager`
   returns a `ToolResult(success=False, status="cancelled"/"timeout")` to the LLM.

✅ **Pros:**
- Clean separation of concerns: **Grant = prior authorization** ("can this user
  ever use this tool?"); **Confirmation = in-the-moment review** ("execute *this
  specific call* with *these* values?"). They compose — a tool can require both.
- Drops into the exact, already-proven insertion point (one symmetric `if guard is
  not None` block beside the grant block). Zero impact when no guard is set.
- Reuses the entire HITL stack: `HumanInteractionManager`, channels
  (web/Telegram/Teams/CLI), `WaitStrategy`, consensus, escalation policies.
- Edit-before-execute maps naturally onto the existing `InteractionType.FORM` +
  `form_schema` mechanism — no new channel work.
- Confirmation-window reuses the grant-window idea without entangling code.

❌ **Cons:**
- Two guards now live at the dispatch point; ordering and combined semantics
  (grant THEN confirm) must be specified and tested.
- Edit-before-execute requires re-validating user-supplied values against
  `args_schema` and rejecting/looping on bad input — real surface area.
- A new `ConfirmationGuard` + config + window store is net-new code (though small
  and modelled on FEAT-211).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (already a dep) | `ConfirmationDecision`, `ConfirmationConfig` models | mirror `GuardDecision`/`GrantConfig` |
| `redis` (already used by HITL) | confirmation-window store + SUSPEND rehydration | reuse existing manager Redis |
| _none new_ | — | feature is pure-Python on existing infra |

🔗 **Existing Code to Reuse:**
- `parrot/auth/grants.py` — `GrantGuard` / `GuardDecision` / `GrantConfig` as the
  structural template for `ConfirmationGuard`.
- `parrot/tools/manager.py:1200-1228` — the dispatch block; insert the confirm
  check symmetrically beside the grant check.
- `parrot/tools/manager.py:307-330` — `set_grant_guard()` / `grant_guard` wiring to
  mirror for `set_confirmation_guard()`.
- `parrot/human/manager.py` — `request_human_input()` (BLOCK) /
  `request_human_input_async()` (SUSPEND).
- `parrot/human/models.py` — `InteractionType.APPROVAL` / `.FORM`, `WaitStrategy`,
  `InteractionResult`, `HumanInteraction`.
- `parrot/tools/abstract.py` — `AbstractTool.routing_meta`, `ToolResult`.
- `parrot/tools/decorators.py` — `@tool` decorator (extend `_tool_metadata`).
- `agents/expense_approval.py` — reference for tiered escalation on timeout.

---

### Option B: Extend `GrantGuard` with a "confirm-each-call" mode

No new guard. Add a `confirm` mode to `GrantGuard` so that, for tools flagged
`requires_confirmation`, the existing guard always asks HITL approval per call
(instead of minting a reusable window grant).

✅ **Pros:**
- Least new code; one guard to wire and reason about.
- Confirmation and authorization share one config object and one Redis namespace.

❌ **Cons:**
- Conflates two genuinely different concepts (authorization vs. per-call review),
  making both harder to evolve — e.g. a tool that needs a grant **and** a per-call
  confirmation becomes awkward to express.
- `GrantGuard.authorize()` is already non-trivial; bolting on briefing templates,
  edit-before-execute, and a separate window semantics bloats it.
- Contradicts the discovery decision ("separate-but-sibling gate").

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | extend `GrantConfig`/`GuardDecision` | overloads existing models |

🔗 **Existing Code to Reuse:**
- `parrot/auth/grants.py:338-540` — `GrantGuard.authorize()` (would be modified
  rather than mirrored).

---

### Option C: Decentralized confirmation via toolkit `_pre_execute` hook / tool wrapper

No central guard. Confirmation lives at the **tool/toolkit** level: a
`ConfirmationMixin` (or a wrapping decorator) overrides
`AbstractToolkit._pre_execute()` (or wraps `AbstractTool.execute()`) so each
confirming tool asks HITL on its own before running its body.

✅ **Pros:**
- No changes to `ToolManager`; works even for tools dispatched outside the central
  path. Confirmation logic travels with the tool.
- Each tool fully owns its briefing/UX.

❌ **Cons:**
- **Decentralized = inconsistent**: every confirming tool must opt into the mixin
  correctly; easy to forget, no single choke-point to audit.
- Duplicates window/edit/escalation logic across tools or forces a shared helper
  anyway (which is just Option A in disguise, minus the clean injection point).
- Harder to combine deterministically with the grant guard's ordering.
- A wrapper around `execute()` complicates the BLOCK/SUSPEND interrupt flow that
  `ToolManager` currently understands.

📊 **Effort:** Medium (deceptively — the per-tool duplication adds up)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| _none new_ | — | uses existing toolkit hooks |

🔗 **Existing Code to Reuse:**
- `parrot/tools/toolkit.py` — `AbstractToolkit._pre_execute()` / `_post_execute()`
  hooks.
- `parrot/human/tool.py` — `HumanTool` as a pattern for in-tool HITL asks.

---

## Recommendation

**Option A** is recommended.

It honours the discovery decision (a separate-but-sibling guard), and it is the
only option that keeps **authorization** (Grant, FEAT-211) and **confirmation**
(this feature) as orthogonal, composable concerns while reusing 100% of the
existing HITL machinery (manager, channels, wait strategies, escalation). The cost
we accept is a second guard at the dispatch point and the need to specify guard
ordering — a bounded, testable concern — in exchange for not overloading
`GrantGuard` (Option B) and not scattering confirmation logic across every tool
(Option C). Edit-before-execute and the confirmation window both land on existing
primitives (`InteractionType.FORM` + `form_schema`, and the grant-window pattern),
so the net-new surface is small and modelled directly on proven FEAT-211 code.

---

## Feature Description

### User-Facing Behavior

When an agent decides to call a tool marked `requires_confirmation`, the user
receives a **briefing** instead of an immediate result, e.g.:

> 🔔 Voy a ejecutar **workday_checkin** con estos valores:
> • employee_id: 123
> • time: "09:00"
> ¿Confirmas? **Sí / No** (o envía los valores corregidos)

The user replies:
- **Yes / True / Sí** → the tool runs with the proposed values; the agent continues
  with the real result.
- **No / False** → the tool is cancelled; the agent is told and can offer an
  alternative or ask again.
- **Edited values** (when the tool allows editing) → the corrected values are
  validated against the tool's schema and the tool runs with them.

Briefings render via the tool's configurable template when present; otherwise a
plain `tool + param=value` listing. Delivery uses whatever HITL channel the agent
is on (web socket card, Telegram/Teams buttons, or CLI prompt).

### Internal Behavior

1. The LLM emits a tool call; `ToolManager.execute_tool()` resolves the
   `AbstractTool`.
2. **Grant guard** runs first (if configured) — authorization. If denied, return
   `forbidden`.
3. **Confirmation guard** runs next (if configured):
   - No `requires_confirmation` meta → `allowed`, continue unchanged.
   - Active confirmation **window** covers `(owner, tool, args-hash)` → skip prompt.
   - Otherwise build the briefing and ask the human:
     - `APPROVAL` (Yes/No) or `FORM` (edit-before-execute) interaction.
     - `BLOCK` → `request_human_input()` awaits the result in-process.
     - `SUSPEND` → `request_human_input_async()` then raise
       `HumanInteractionInterrupt`; the run rehydrates on response.
   - Map the `InteractionResult`:
     - approved → decision `allowed=True` with (edited, re-validated) `parameters`;
       optionally record the window.
     - rejected → `allowed=False, status="cancelled"`.
     - timed out / no response → `allowed=False, status="timeout"`.
4. On `allowed`, `ToolManager` dispatches `tool.execute(**parameters)` with the
   confirmed parameters. On not-allowed, it returns
   `ToolResult(success=False, status="cancelled"|"timeout")` to the LLM.

Declaration surface:
- `@tool(requires_confirmation=True, confirm_template=..., confirm_window_seconds=...,
  allow_edit=True)` → stored in `_tool_metadata` → projected into `routing_meta`.
- `AbstractTool.routing_meta["requires_confirmation"] = True` directly.
- Toolkit-level: a set/list of tool names (or a toolkit flag) that marks its
  generated tools as confirming.

### Edge Cases & Error Handling

- **Edited values fail schema validation** → re-prompt (bounded retries) or cancel
  with a clear error; never execute with invalid params.
- **No HITL manager / channel configured** but tool requires confirmation →
  fail-closed (cancel) with an explanatory `ToolResult`, mirroring GrantGuard's
  fail-closed stance.
- **SUSPEND mid-confirmation then process restarts** → state persists in Redis;
  rehydration resumes the call.
- **Window race / stale window** → window keyed by args-hash so different arguments
  always re-confirm; expiry via Redis TTL.
- **Timeout vs explicit No** → both cancel, but distinct `status` so the LLM (and
  optional escalation policy) can treat them differently.
- **Confirmation + Grant both required** → ordering is grant→confirm; document and
  test the combined path.
- **Non-`AbstractTool` callables** (plain functions/coroutines) — define whether
  confirmation applies only to `AbstractTool` (as Grant does today) or is extended.

---

## Capabilities

### New Capabilities
- `hitl-confirmation`: declarative confirm-before-execute gate for tool calls,
  implemented as a `ConfirmationGuard` sibling to the FEAT-211 grant guard.

### Modified Capabilities
- `tool-call-grants` (FEAT-211) — not changed in behavior, but now coexists with a
  second guard at the same dispatch point; ordering/composition documented.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/manager.py` | modifies | add `set_confirmation_guard()`/property + a symmetric confirm block in `execute_tool()` beside the grant block (≈1200-1228) |
| `parrot/auth/` (new `confirmation.py`) | extends | new `ConfirmationGuard`, `ConfirmationDecision`, `ConfirmationConfig` modelled on `grants.py` |
| `parrot/tools/abstract.py` | extends | new well-known `routing_meta` keys (`requires_confirmation`, `confirm_template`, `confirm_window_seconds`, `allow_edit`) |
| `parrot/tools/decorators.py` | modifies | `@tool(...)` gains confirmation kwargs → `_tool_metadata` → `routing_meta` |
| `parrot/tools/toolkit.py` | extends | toolkit-level declaration of confirming tools |
| `parrot/human/manager.py` & channels | depends on | reused as-is for APPROVAL/FORM asks (no change expected) |
| `agents/` sample | extends | a small demo agent (e.g. `workday_checkin`) showing the feature |

---

## Code Context

### User-Provided Code

The user described the desired behavior in prose (no code pasted). Verbatim intent:

> Existe un tipo de Human-in-the-loop interaction que es referente a "confirmar" las
> operaciones antes de realizarlas; hay que declarar que ciertos "tool-calling"
> requieran confirmación humana del usuario ejecutante. El LLM sabe que debe invocar
> el tool `workday_checkin`, pero hemos definido (metadata del toolkit) que dicho
> tool requiere confirmación; entonces la IA, en vez de ejecutar el tool
> inmediatamente, envía un "briefing" indicando "voy a ejecutar el tool … con los
> siguientes valores …", y el usuario responde Yes|No / True|False para ejecutar o
> cancelar (y puede editar los valores).

### Verified Codebase References

#### Classes & Signatures
```python
# parrot/tools/manager.py:1200-1228 — the dispatch point (confirm block goes here)
elif isinstance(tool, AbstractTool):
    # === Grant guard check (FEAT-211) ===
    if self._grant_guard is not None:
        decision = await self._grant_guard.authorize(
            tool=tool, parameters=parameters, permission_context=permission_context,
        )
        if not decision.allowed:
            return ToolResult(success=False, status="forbidden",
                              error=f"Grant denied: {decision.reason}", result=None)
    # === End grant guard ===
    exec_kwargs = dict(parameters)
    ...
    result = await tool.execute(**exec_kwargs)   # line 1228

# parrot/tools/manager.py:307-330 — guard wiring to mirror for confirmation
def set_grant_guard(self, guard: "GrantGuard") -> None: ...   # line 307
@property
def grant_guard(self) -> Optional["GrantGuard"]: ...          # line 324

# parrot/auth/grants.py:320-384 — structural template for the new guard
class GuardDecision(BaseModel):       # line 320
    allowed: bool                     # line 330
    reason: str                       # line 331
    grant: Optional[Grant] = None     # line 332

class GrantGuard:                     # line 338
    def __init__(self, store, human_manager=None, config=None) -> None: ...  # line 360
    async def authorize(self, *, tool, parameters,
                        permission_context=None) -> GuardDecision: ...        # line 378

# parrot/tools/abstract.py:46-65 — the result type returned on cancel/timeout
class ToolResult(BaseModel):                      # line 46
    success: bool = Field(default=True)           # line 48
    status: str = Field(default="success")        # line 49
    result: Any                                   # line 50
    error: Optional[str] = Field(default=None)    # line 51
    metadata: Dict[str, Any] = ...                # line 52

# parrot/tools/abstract.py — per-instance metadata bag (declaration surface)
class AbstractTool(EventEmitterMixin, ABC):       # line 81
    routing_meta: Dict = None                     # line 100 (per-instance, line 140)

# parrot/human/models.py — HITL primitives reused as-is
class InteractionType(str, Enum):                 # line 60
    FREE_TEXT = "free_text"; SINGLE_CHOICE = ...; MULTI_CHOICE = ...
    APPROVAL = "approval"                          # line 66
    FORM = "form"                                  # line 67  (requires form_schema)
class WaitStrategy(str, Enum):                    # line 31 (in models.py)
    BLOCK = "block"; SUSPEND = "suspend"; HOT_THEN_SUSPEND = "hot"
class HumanInteraction(BaseModel):                # line 380
    question: str; interaction_type: InteractionType
    form_schema: Optional[Dict[str, Any]]         # line 390 (required for FORM)
    timeout: float = 7200.0; timeout_action: TimeoutAction = CANCEL  # 398-399
class InteractionResult(BaseModel):               # line 498
    status: InteractionStatus                     # line 502
    responses: List[HumanResponse]                # line 503
    consolidated_value: Any = None                # line 504
    timed_out: bool = False                        # line 505

# parrot/human/manager.py — the two ask entry points
class HumanInteractionManager:                                    # line 51
    async def request_human_input(self, interaction, channel) -> InteractionResult:   # line 321 (BLOCK)
    async def request_human_input_async(self, interaction, channel, schedule_timeout=False) -> str:  # line 502 (SUSPEND)

# parrot/tools/decorators.py:55-110 — @tool stores _tool_metadata (extend here)
def tool(_func=None, *, name=None, description=None, schema=None,
         auto_register=False): ...                # line 55
    func._tool_metadata = {'name':..., 'description':..., 'schema':...,
                           'function':..., 'auto_register':...}   # line 104
```

#### Verified Imports
```python
# Confirmed to exist:
from parrot.tools.abstract import AbstractTool, ToolResult        # tools/abstract.py:46,81
from parrot.auth.grants import GrantGuard, GuardDecision          # auth/grants.py:320,338
from parrot.human.manager import HumanInteractionManager          # human/manager.py:51
from parrot.human.models import (
    InteractionType, WaitStrategy, HumanInteraction, InteractionResult,
)                                                                 # human/models.py
# Interrupt used by the SUSPEND path (referenced from human/tool.py):
from parrot.human... import HumanInteractionInterrupt             # verify exact module at spec time
```

#### Key Attributes & Constants
- `AbstractTool.routing_meta` → `Dict` (parrot/tools/abstract.py:100) — existing
  precedent key `"requires_grant"` set by FEAT-211; new feature adds
  `"requires_confirmation"`, `"confirm_template"`, `"confirm_window_seconds"`,
  `"allow_edit"`.
- `GuardDecision.allowed` / `.reason` → `bool` / `str` (parrot/auth/grants.py:330-331).
- `ToolResult.status` → `str` (parrot/tools/abstract.py:49) — confirm path returns
  `"cancelled"` / `"timeout"` (compare `"forbidden"` already special-cased at
  manager.py:1233).
- `HumanInteraction.form_schema` (parrot/human/models.py:390) — required when
  `interaction_type == FORM`; vehicle for edit-before-execute.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.auth.confirmation.ConfirmationGuard`~~ — does NOT exist yet; to be created.
- ~~`AbstractTool.requires_confirmation`~~ — no such attribute; it is a
  `routing_meta` key, not a class field.
- ~~`routing_meta["requires_confirmation"]`~~ — not present today; only
  `"requires_grant"`, `"grant_window_seconds"`, `"description"`, `"not_for"` are
  established keys.
- ~~`ToolManager.set_confirmation_guard()`~~ / ~~`confirmation_guard`~~ — does NOT
  exist; only `set_grant_guard()` / `grant_guard` (manager.py:307,324).
- ~~`InteractionType.CONFIRM`~~ — not a member; use `APPROVAL` (Yes/No) or `FORM`
  (edit). Members are FREE_TEXT, SINGLE_CHOICE, MULTI_CHOICE, APPROVAL, FORM.
- ~~`@tool(requires_confirmation=...)`~~ — the decorator does NOT accept this kwarg
  today (only name/description/schema/auto_register); it must be added.
- ~~A `briefing` concept anywhere in the codebase~~ — net-new; no existing helper.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The guard core (`ConfirmationGuard` + models +
  window store) is one cohesive unit that several other pieces depend on, so it is
  the critical-path task. After it lands, the **declaration surface** (decorator,
  `AbstractTool` keys, toolkit-level marking) and the **demo agent / docs** can
  proceed in parallel. Tests split cleanly per layer.
- **Cross-feature independence**: Touches `parrot/tools/manager.py` (shared with
  FEAT-211 grant path) and `parrot/tools/decorators.py`. The HITL stack
  (`parrot/human/manager.py`, channels) is reused but should NOT need edits — if it
  does, that risks colliding with `hitl_web`/FEAT-146 work. Coordinate around the
  manager dispatch block to avoid conflicting edits with any in-flight grant work.
- **Recommended isolation**: `per-spec` — most tasks converge on the same two files
  (`manager.py`, `decorators.py`) and on the guard core they all depend on, so
  sequential execution in one worktree avoids merge churn.
- **Rationale**: The guard is a single dependency hub and the dispatch-point edit is

…(truncated)…
