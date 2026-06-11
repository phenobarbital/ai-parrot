---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: HITL Tool-Call Confirmation

**Feature ID**: FEAT-235
**Date**: 2026-06-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.26.0

> Input: `sdd/proposals/hitl-confirmation.brainstorm.md` (Recommended Option A —
> Dedicated `ConfirmationGuard` sibling to `GrantGuard`).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

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

### Goals
- Declarative per-tool confirmation declared in `routing_meta`, exposable via the
  `@tool` decorator, `AbstractTool`, and at toolkit level.
- A dedicated `ConfirmationGuard`, **symmetric** to FEAT-211's `GrantGuard`, wired
  into `ToolManager` and invoked at the same dispatch point — purely additive.
- Support BOTH `WaitStrategy.BLOCK` (synchronous) and `WaitStrategy.SUSPEND`
  (pause + Redis rehydration).
- Configurable per-tool briefing template, with a raw `tool + param=value` fallback.
- User may **approve / cancel / edit**; edited values are re-validated against the
  tool's `args_schema` before execution.
- Per-call by default, with an optional `confirm_window_seconds` to skip re-asking.
- Graceful rejection: a No/timeout returns a cancelled/timeout `ToolResult` to the
  LLM; the agent run is NOT killed.

### Non-Goals (explicitly out of scope)
- Extending `GrantGuard` with a "confirm-each-call" mode — *rejected in brainstorm;
  see proposals/hitl-confirmation.brainstorm.md Option B* (conflates authorization
  with in-the-moment review).
- Decentralized per-tool confirmation via toolkit `_pre_execute` hooks — *rejected
  in brainstorm; see Option C* (no central audit choke-point).
- Changes to the HITL channel layer (`parrot/human/channels/*`) — the existing
  web/Telegram/Teams/CLI channels are reused as-is.
- Confirmation for non-`AbstractTool` callables (plain functions / `ToolDefinition`)
  — scoped to `AbstractTool` only, matching how `GrantGuard` operates today.

---

## 2. Architectural Design

### Overview

Introduce a new governor, `ConfirmationGuard`, modelled structurally on
`parrot/auth/grants.py:GrantGuard` (FEAT-211). It is wired into `ToolManager` via a
new `set_confirmation_guard()` setter and `confirmation_guard` property, and invoked
inside `execute_tool()` **immediately after** the existing grant check and **before**
`tool.execute()`. The combined dispatch order is locked as **grant → confirm**:
authorization first ("can this user ever use this tool?"), then in-the-moment
confirmation ("execute *this specific call* with *these* values?").

The guard lifecycle for an `AbstractTool`:

1. If `tool.routing_meta.get("requires_confirmation")` is falsy → return an
   `allowed` decision and let the dispatch continue unchanged (zero impact when no
   guard is configured or the tool is not marked).
2. Consult a **confirmation window** store keyed by `(owner, tool_name, args_hash)`;
   if a recent approval covers it and `confirm_window_seconds` is set, skip the
   prompt and allow.
3. Render a **briefing** from the tool's `confirm_template` (formatted against the
   parameters) or a raw `tool + param=value` listing when no template is set.
4. Ask the human via `HumanInteractionManager`:
   - `InteractionType.APPROVAL` (Yes/No) by default.
   - `InteractionType.FORM` (seeded with current params as `form_schema`) when the
     tool sets `allow_edit` AND the channel supports forms — enabling
     edit-before-execute.
   - `WaitStrategy.BLOCK` → `request_human_input()` (awaits in-process).
   - `WaitStrategy.SUSPEND` → `request_human_input_async()` then raise
     `HumanInteractionInterrupt`.
5. Map the `InteractionResult`:
   - **approved** → `ConfirmationDecision(allowed=True, parameters=<edited & re-validated>)`;
     optionally record the window.
   - **rejected** → `allowed=False, status="cancelled"`.
   - **timeout / no response** → `allowed=False, status="timeout"`.
6. `ToolManager` executes with `decision.parameters` when allowed; otherwise returns
   `ToolResult(success=False, status="cancelled"|"timeout", error=…)` to the LLM.

Fail-closed: if a tool requires confirmation but no `HumanInteractionManager` /
channel is available, the guard denies (cancels) with an explanatory `ToolResult`,
mirroring `GrantGuard`'s fail-closed stance.

### Component Diagram
```
LLM tool call
     │
     ▼
ToolManager.execute_tool()
     │ 1. GrantGuard.authorize()      (FEAT-211, existing) ── deny ─→ ToolResult(forbidden)
     │ 2. ConfirmationGuard.confirm() (NEW)
     │        │                         ── deny ─→ ToolResult(cancelled|timeout)
     │        ├─ routing_meta check (requires_confirmation?)
     │        ├─ ConfirmationWindowStore (owner, tool, args_hash)
     │        ├─ briefing renderer (confirm_template | raw listing)
     │        └─ HumanInteractionManager.request_human_input[_async]()
     │               └─ APPROVAL | FORM  ·  BLOCK | SUSPEND
     ▼
tool.execute(**decision.parameters)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ToolManager` (`parrot/tools/manager.py`) | extends | add `set_confirmation_guard()`/`confirmation_guard` (mirror `set_grant_guard`:307 / `grant_guard`:324) + a symmetric confirm block in `execute_tool()` beside the grant block (1205-1217); execute with `decision.parameters` at 1228 |
| `GrantGuard` (`parrot/auth/grants.py`) | sibling pattern | `ConfirmationGuard`/`ConfirmationDecision`/`ConfirmationConfig`/`ConfirmationWindowStore` mirror `GrantGuard`/`GuardDecision`/`GrantConfig`/`GrantStore` |
| `AbstractTool.routing_meta` (`parrot/tools/abstract.py:140`) | extends | new well-known keys: `requires_confirmation`, `confirm_template`, `confirm_window_seconds`, `allow_edit` |
| `@tool` decorator (`parrot/tools/decorators.py:55`) | modifies | new kwargs projected into `_tool_metadata` → `routing_meta` |
| `tools/spawn.py:147` | extends | add `effective_routing.setdefault("requires_confirmation", False)` next to the existing `requires_grant` default |
| `HumanInteractionManager` (`parrot/human/manager.py`) | uses | `request_human_input()` (BLOCK, :321) / `request_human_input_async()` (SUSPEND, :502) |
| `parrot/human/models.py` | uses | `InteractionType.APPROVAL`/`.FORM`, `WaitStrategy`, `HumanInteraction.form_schema`, `InteractionResult` |
| `parrot.core.exceptions.HumanInteractionInterrupt` | raises | SUSPEND path |
| `agents/expense_approval.py` | reference | tiered-escalation-on-timeout pattern (optional follow-on) |

### Data Models
```python
# parrot/auth/confirmation.py  (NEW — mirrors grants.py)

class ConfirmationConfig(BaseModel):
    """Configurable defaults for the confirmation subsystem.
    Mirrors GrantConfig (grants.py:95)."""
    window_seconds: int = Field(0, ge=0)          # 0 = always re-ask (per-call default)
    approval_timeout: float = Field(120.0, gt=0)  # wait before timing out (fail-closed)
    default_channel: str = "telegram"
    max_edit_retries: int = Field(1, ge=0)        # invalid edits before auto-cancel

class ConfirmationDecision(BaseModel):
    """Result of ConfirmationGuard.confirm(). Mirrors GuardDecision (grants.py:320)."""
    allowed: bool
    status: str = "confirmed"                     # confirmed | cancelled | timeout | not_required
    reason: str
    parameters: Optional[Dict[str, Any]] = None   # (possibly edited) re-validated params

class ConfirmationWindowStore(ABC):
    """Abstract window persistence. Mirrors GrantStore (grants.py:114).
    Key = (owner_id, tool_name, args_hash)."""
    @abstractmethod
    async def is_confirmed(self, owner_id: str, tool_name: str, args_hash: str) -> bool: ...
    @abstractmethod
    async def record(self, owner_id: str, tool_name: str, args_hash: str, *, window_seconds: int) -> None: ...

class InMemoryConfirmationWindowStore(ConfirmationWindowStore):
    """asyncio.Lock-guarded dict; Redis backend can follow (mirrors InMemoryGrantStore:185)."""
```

### New Public Interfaces
```python
# parrot/auth/confirmation.py
class ConfirmationGuard:
    def __init__(
        self,
        store: ConfirmationWindowStore,
        human_manager: Optional["HumanInteractionManager"] = None,
        config: Optional[ConfirmationConfig] = None,
    ) -> None: ...

    async def confirm(
        self,
        *,
        tool: "AbstractTool",
        parameters: dict,
        permission_context: Optional["PermissionContext"] = None,
    ) -> ConfirmationDecision: ...

# parrot/tools/manager.py (ToolManager)
def set_confirmation_guard(self, guard: "ConfirmationGuard") -> None: ...
@property
def confirmation_guard(self) -> Optional["ConfirmationGuard"]: ...

# parrot/tools/decorators.py
def tool(_func=None, *, name=None, description=None, schema=None, auto_register=False,
         requires_confirmation: bool = False, confirm_template: Optional[str] = None,
         confirm_window_seconds: int = 0, allow_edit: bool = False): ...
```

---

## 3. Module Breakdown

> One module per capability as a starting point; tasks derive from these.

### Module 1: Confirmation guard core
- **Path**: `packages/ai-parrot/src/parrot/auth/confirmation.py`
- **Responsibility**: `ConfirmationConfig`, `ConfirmationDecision`,
  `ConfirmationWindowStore` (ABC) + `InMemoryConfirmationWindowStore`, and
  `ConfirmationGuard.confirm()` — routing_meta gate, window check, briefing render,
  HITL ask (APPROVAL/FORM × BLOCK/SUSPEND), result mapping, fail-closed.
- **Depends on**: `parrot/auth/grants.py` (structural template), `parrot/human/*`,
  `parrot/tools/abstract.py`.

### Module 2: Briefing renderer + edit re-validation
- **Path**: `packages/ai-parrot/src/parrot/auth/confirmation.py` (helpers within, or
  a small `_briefing.py` sibling)
- **Responsibility**: render `confirm_template` against parameters (safe formatting)
  with a raw `tool + param=value` fallback; build `form_schema` from `args_schema`
  for edit-before-execute; re-validate returned values against `tool.args_schema`
  with bounded `max_edit_retries`.
- **Depends on**: Module 1, `AbstractTool.args_schema`.

### Module 3: ToolManager integration
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`
- **Responsibility**: `set_confirmation_guard()` / `confirmation_guard` property;
  invoke the guard in `execute_tool()` after the grant check, before `tool.execute()`;
  execute with `decision.parameters`; return cancelled/timeout `ToolResult` on deny.
- **Depends on**: Module 1.

### Module 4: Declaration surface
- **Path**: `packages/ai-parrot/src/parrot/tools/decorators.py`,
  `packages/ai-parrot/src/parrot/tools/spawn.py`,
  `packages/ai-parrot/src/parrot/tools/toolkit.py`
- **Responsibility**: `@tool(...)` confirmation kwargs → `_tool_metadata` →
  `routing_meta`; `spawn.py` `setdefault("requires_confirmation", False)`;
  toolkit-level marking of which generated tools require confirmation.
- **Depends on**: Module 1 (for the well-known key names).

### Module 5: Exports, demo agent & docs
- **Path**: `packages/ai-parrot/src/parrot/auth/__init__.py`,
  `agents/` demo (e.g. `workday_checkin`), `docs/`
- **Responsibility**: export `ConfirmationGuard` & friends alongside the Grant
  exports; a minimal demo agent showing the confirm flow; user docs.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_confirm_not_required_passthrough` | 1 | Tool without `requires_confirmation` → `allowed=True, status="not_required"`, no HITL call |
| `test_confirm_block_approved` | 1 | BLOCK + APPROVAL "yes" → `allowed=True`, params unchanged |
| `test_confirm_block_rejected` | 1 | BLOCK + "no" → `allowed=False, status="cancelled"` |
| `test_confirm_timeout` | 1 | No response within `approval_timeout` → `allowed=False, status="timeout"` |
| `test_confirm_suspend_raises_interrupt` | 1 | SUSPEND → `request_human_input_async` called, `HumanInteractionInterrupt` raised |
| `test_confirm_fail_closed_no_manager` | 1 | `requires_confirmation` + no `human_manager` → denied (cancelled) |
| `test_confirm_window_skips_prompt` | 1 | Within `confirm_window_seconds` for same args_hash → allowed, no HITL call |
| `test_confirm_window_reasks_on_diff_args` | 1 | Different args_hash → re-asks even within window |
| `test_briefing_uses_template` | 2 | `confirm_template` rendered against params |
| `test_briefing_raw_fallback` | 2 | No template → `tool + param=value` listing |
| `test_edit_revalidates_against_schema` | 2 | FORM edit with valid values → params replaced |
| `test_edit_invalid_then_cancel` | 2 | Invalid edit beyond `max_edit_retries` → cancelled |
| `test_decorator_projects_routing_meta` | 4 | `@tool(requires_confirmation=True, …)` → `routing_meta` keys present |
| `test_spawn_sets_confirmation_default` | 4 | `spawn.py` sets `requires_confirmation=False` default |

### Integration Tests
| Test | Description |
|---|---|
| `test_toolmanager_confirm_gate_block` | `ToolManager` with a `ConfirmationGuard`: marked tool prompts, approval → real execution |
| `test_toolmanager_confirm_cancel_returns_toolresult` | "No" → `ToolResult(success=False, status="cancelled")`, agent loop continues |
| `test_grant_then_confirm_order` | Tool requiring BOTH grant and confirmation: grant authorized first, then confirmation asked |
| `test_no_guard_path_unchanged` | No confirmation guard set → dispatch identical to today |

### Test Data / Fixtures
```python
@pytest.fixture
def confirming_tool():
    # AbstractTool with routing_meta={"requires_confirmation": True,
    #   "confirm_template": "Voy a ejecutar {tool} con {params}",
    #   "confirm_window_seconds": 0, "allow_edit": True}
    ...

@pytest.fixture
def fake_human_manager():
    # stub HumanInteractionManager whose request_human_input returns a
    # scripted InteractionResult (approve / reject / edited / timeout)
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] A `ConfirmationGuard` exists in `parrot/auth/confirmation.py`, structurally
      mirroring `GrantGuard`, exported from `parrot/auth/__init__.py`.
- [ ] `ToolManager` exposes `set_confirmation_guard()` + `confirmation_guard` and
      invokes the guard in `execute_tool()` **after** grant, **before**
      `tool.execute()`; dispatch is unchanged when no guard is set.
- [ ] A tool marked `routing_meta["requires_confirmation"]` triggers a briefing and
      is NOT executed until approved.
- [ ] BOTH `WaitStrategy.BLOCK` and `WaitStrategy.SUSPEND` are supported (SUSPEND
      raises `HumanInteractionInterrupt`).
- [ ] Briefing uses the per-tool `confirm_template` when present, else a raw
      `tool + param=value` listing.
- [ ] User can approve, cancel, OR edit; edited values are re-validated against the
      tool's `args_schema` (bounded by `max_edit_retries`) before execution.
- [ ] Confirmation is per-call by default; `confirm_window_seconds` skips re-asking
      within the window, keyed by `(owner, tool, args_hash)`.
- [ ] No / timeout / no-response returns `ToolResult(success=False,
      status="cancelled"|"timeout")` to the LLM; the agent run is NOT aborted.
- [ ] Fail-closed: `requires_confirmation` + no manager/channel → cancelled with a
      clear error.
- [ ] `@tool(requires_confirmation=…, confirm_template=…, confirm_window_seconds=…,
      allow_edit=…)` and `spawn.py` default are wired into `routing_meta`.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v -k confirmation`).
- [ ] No breaking changes to existing public API (grant path and no-guard path
      identical to today).
- [ ] Docs updated and a minimal demo agent added.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry below was re-verified
> against the working tree on 2026-06-12.

### Verified Imports
```python
# Confirmed to resolve:
from parrot.tools.abstract import AbstractTool, ToolResult            # tools/abstract.py:81,46
from parrot.auth import (                                             # auth/__init__.py:51-58
    Grant, GrantConfig, GrantStore, InMemoryGrantStore, GrantGuard, GuardDecision,
)
from parrot.human.manager import HumanInteractionManager             # human/manager.py:51
from parrot.human.models import (                                    # human/models.py
    InteractionType, WaitStrategy, HumanInteraction, InteractionResult,
)
from parrot.core.exceptions import HumanInteractionInterrupt         # core/exceptions.py:12
```

### Existing Class Signatures
```python
# parrot/tools/manager.py
def set_grant_guard(self, guard: "GrantGuard") -> None:              # line 307
@property
def grant_guard(self) -> Optional[GrantGuard]:                       # line 324
# execute_tool() dispatch block:
elif isinstance(tool, AbstractTool):                                 # line 1200
    if self._grant_guard is not None:                               # line 1205
        decision = await self._grant_guard.authorize(
            tool=tool, parameters=parameters, permission_context=permission_context)  # 1206
        if not decision.allowed:
            return ToolResult(success=False, status="forbidden",
                              error=f"Grant denied: {decision.reason}", result=None)   # 1212
    exec_kwargs = dict(parameters)                                  # line 1222
    result = await tool.execute(**exec_kwargs)                      # line 1228
    # forbidden ToolResults returned directly without post-processing  # line 1233

# parrot/auth/grants.py  (structural template for confirmation.py)
class GrantConfig(BaseModel):                                       # line 95
    window_seconds: int = Field(900, gt=0)                         # line 107
    approval_timeout: float = Field(120.0, gt=0)                   # line 108
    default_channel: str = "telegram"                              # line 109
class GrantStore(ABC):                                             # line 114
    async def grant(self, owner_id, scope, *, granted_by, window_seconds) -> Grant: ...  # 123
    async def is_allowed(self, owner_id: str, scope: str) -> bool: ...                    # 145
class InMemoryGrantStore(GrantStore):                              # line 185
class GuardDecision(BaseModel):                                    # line 320
    allowed: bool                                                  # line 330
    reason: str                                                    # line 331
    grant: Optional[Grant] = None                                  # line 332
class GrantGuard:                                                  # line 338
    def __init__(self, store, human_manager=None, config=None) -> None: ...  # line 360
    async def authorize(self, *, tool, parameters, permission_context=None) -> GuardDecision: ...  # 378
    # routing_meta gate: tool.routing_meta.get("requires_grant")   # line 398
    # window override:   tool.routing_meta.get("grant_window_seconds", ...)  # line 460

# parrot/tools/abstract.py
class ToolResult(BaseModel):                                       # line 46
    success: bool = Field(default=True)                            # line 48
    status: str = Field(default="success")                        # line 49
    result: Any                                                    # line 50
    error: Optional[str] = Field(default=None)                    # line 51
    metadata: Dict[str, Any] = Field(default_factory=dict)        # line 52
class AbstractTool(EventEmitterMixin, ABC):                       # line 81
    routing_meta: Dict = None                                     # line 100; per-instance at line 140
    # args_schema: Type[BaseModel] — tool input schema (used for edit re-validation)

# parrot/tools/decorators.py
def tool(_func=None, *, name=None, description=None, schema=None, auto_register=False):  # line 55
    func._tool_metadata = {'name':..., 'description':..., 'schema':...,
                           'function':..., 'auto_register':...}    # line 104

# parrot/tools/spawn.py
effective_routing.setdefault("requires_grant", False)             # line 147 (add confirmation peer)

# parrot/human/models.py
class InteractionType(str, Enum):                                 # line 60
    FREE_TEXT="free_text"; SINGLE_CHOICE=...; MULTI_CHOICE=...
    APPROVAL = "approval"                                         # line 66
    FORM = "form"                                                 # line 67 (requires form_schema)
class WaitStrategy(str, Enum):                                    # line 31
    BLOCK="block"; SUSPEND="suspend"; HOT_THEN_SUSPEND="hot"
class HumanInteraction(BaseModel):                               # line 380
    question: str; interaction_type: InteractionType
    form_schema: Optional[Dict[str, Any]]                        # line 390
    timeout: float = 7200.0; timeout_action: TimeoutAction       # 398-399
class InteractionResult(BaseModel):                             # line 498
    status: InteractionStatus                                   # line 502
    responses: List[HumanResponse]                              # line 503
    consolidated_value: Any = None                              # line 504
    timed_out: bool = False                                      # line 505

# parrot/human/manager.py
class HumanInteractionManager:                                  # line 51
    async def request_human_input(self, interaction, channel) -> InteractionResult: ...  # 321 (BLOCK)
    async def request_human_input_async(self, interaction, channel,
                                        schedule_timeout=False) -> str: ...               # 502 (SUSPEND)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ConfirmationGuard` | `ToolManager.execute_tool()` | invoked after grant, before execute | `tools/manager.py:1205-1228` |
| `ToolManager.set_confirmation_guard()` | (mirror of) `set_grant_guard()` | new setter/property | `tools/manager.py:307,324` |
| `ConfirmationGuard.confirm()` | `HumanInteractionManager.request_human_input[_async]()` | HITL ask | `human/manager.py:321,502` |
| `ConfirmationGuard` | `tool.routing_meta["requires_confirmation"]` | dict lookup (peer of `requires_grant`) | `auth/grants.py:398` |
| edit re-validation | `AbstractTool.args_schema` | pydantic validation | `tools/abstract.py` |
| SUSPEND path | `HumanInteractionInterrupt` | raise | `core/exceptions.py:12` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.auth.confirmation`~~ / ~~`ConfirmationGuard`~~ / ~~`ConfirmationDecision`~~
  / ~~`ConfirmationConfig`~~ / ~~`ConfirmationWindowStore`~~ — to be **created** by this feature.
- ~~`ToolManager.set_confirmation_guard()`~~ / ~~`ToolManager.confirmation_guard`~~ —
  do NOT exist yet; only `set_grant_guard()` / `grant_guard` (manager.py:307,324).
- ~~`AbstractTool.requires_confirmation`~~ — NOT a class attribute; it is a
  `routing_meta` key.
- ~~`routing_meta["requires_confirmation"]`~~ — not present today; only
  `requires_grant`, `grant_window_seconds`, `description`, `not_for` are established.
- ~~`InteractionType.CONFIRM`~~ — not a member; use `APPROVAL` (Yes/No) or `FORM` (edit).
- ~~`@tool(requires_confirmation=…)`~~ — the decorator does NOT accept this kwarg
  today (only name/description/schema/auto_register); it must be added.
- ~~A `briefing` helper anywhere~~ — net-new; no existing helper.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Mirror `grants.py` exactly** for structure (ABC store + in-memory impl + config
  + decision + guard); do not invent a new shape.
- Add the confirm block in `execute_tool()` as a **purely additive** `if
  self._confirmation_guard is not None:` block beside the grant block — the no-guard
  path must be byte-for-byte unchanged in behavior.
- Lock dispatch order **grant → confirm**.
- Async-first; Pydantic models for all structures; `self.logger`; no blocking I/O.
- Reuse `InteractionType.FORM` + `form_schema` for edit-before-execute; do not build
  new channel UI.
- Briefing rendering must use **safe** formatting (never `eval`); fall back to raw
  listing when a template references missing keys.

### Known Risks / Gotchas
- **Guard ordering / double-HITL**: a tool requiring both grant and confirmation
  could prompt the human twice. Document the grant→confirm order; consider a future
  optimization to coalesce, but out of scope here.
- **Edit on text-only channels**: FORM edits need a form-capable channel (web/Teams).
  On free-text channels (CLI/Telegram) the guard falls back to APPROVAL
  (approve/cancel only) — surface this so authors don't expect editing everywhere.
- **Invalid edited values**: must re-validate against `args_schema`; loop is bounded
  by `max_edit_retries` then auto-cancel — never execute with unvalidated params.
- **SUSPEND rehydration**: state must persist (Redis) so a restart mid-confirmation
  resumes; align with existing HITL suspend handling (`human/tool.py`,
  `agents/expense_approval.py`).
- **args_hash stability**: window key must hash normalized parameters (sorted keys,
  stable serialization) so identical calls match and different args re-confirm.
- **Default `confirm_window_seconds=0`** means always re-ask — the safe default.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | (existing) | `ConfirmationDecision` / `ConfirmationConfig` models |
| `redis` | (existing, HITL) | confirmation-window store + SUSPEND rehydration (reuse manager's Redis) |
| _none new_ | — | feature is pure-Python on existing infrastructure |

---

## 8. Open Questions

> Resolved items carried forward from the brainstorm (decided during discovery) and
> design decisions locked in this spec. Remaining `[ ]` items are deferrable to
> implementation.

- [x] Flow type / base branch — *Resolved in brainstorm*: `feature` on `dev`.
- [x] Declaration mechanism — *Resolved in brainstorm*: `routing_meta` +
  `@tool`/`AbstractTool` + toolkit-level.
- [x] Wait strategies — *Resolved in brainstorm*: support BOTH `BLOCK` and `SUSPEND`.
- [x] Relationship to FEAT-211 Grant — *Resolved in brainstorm*: separate-but-sibling
  `ConfirmationGuard` (Grant = prior authz; Confirmation = in-the-moment review).
- [x] Briefing content — *Resolved in brainstorm*: per-tool configurable template,
  with a raw `tool + param=value` fallback.
- [x] User response capability — *Resolved in brainstorm*: approve / cancel / **edit**
  (corrected values re-validated against `args_schema`).
- [x] Confirmation scope — *Resolved in brainstorm*: per-call by default, with optional
  `confirm_window_seconds` to skip re-asking.
- [x] Rejection/timeout behavior — *Resolved in brainstorm*: return a
  cancelled/timeout `ToolResult` to the LLM; the agent keeps running.
- [x] Guard ordering when a tool requires BOTH grant and confirmation — *Resolved in
  spec*: **grant → confirm** (authorize first, then confirm the specific call). See §2.
- [x] Confirmation scoped to `AbstractTool` only — *Resolved in spec*: yes, matching
  `GrantGuard`; non-`AbstractTool` callables are a Non-Goal. See §1.
- [ ] Edit-before-execute on free-text channels — *Owner: implementation*: default is
  FORM on form-capable channels (web/Teams), APPROVAL fallback on text-only channels
  (CLI/Telegram). Confirm whether a best-effort free-text→fields parse is wanted, or
  hard-fallback to approve/cancel only.
- [ ] `max_edit_retries` default value and re-prompt UX — *Owner: implementation*:
  proposed default `1` then auto-cancel.
- [ ] Confirmation-window store backend for production — *Owner: implementation*:
  in-memory ships first; Redis backend (mirroring a future `RedisGrantStore`) may
  follow.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (all tasks run sequentially in one worktree).
- **Rationale**: Most tasks converge on the same two hotspot files —
  `parrot/tools/manager.py` (shared with the FEAT-211 grant dispatch block) and
  `parrot/tools/decorators.py` — and they all depend on the `ConfirmationGuard` core
  (Module 1), which is a single dependency hub. Sequential execution keeps the
  `manager.py` dispatch edit coherent and prevents two worktrees from editing the
  same block.
- **Cross-feature dependencies**: Builds on FEAT-211 (Grant subsystem) which is
  already merged — no pending merge required. Reuses the HITL stack
  (`parrot/human/*`); avoid edits there to prevent collisions with `hitl_web` /
  FEAT-146 work. Coordinate around `parrot/tools/manager.py` if any other in-flight
  spec touches the dispatch path.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-12 | Jesus Lara | Initial draft from hitl-confirmation brainstorm (Option A) |
