# TASK-1754: Card action round-trip invoke shim

**Feature**: FEAT-303 — UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)
**Spec**: `sdd/specs/ux-custom-engine-copilot.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1753
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-303 (spec §3). The primary action round-trip
needs NO code: card actions are `Action.Submit` with `msteams.messageBack`
payloads (built in TASK-1752), which Teams/Copilot deliver as ordinary
`message` activities that re-enter `_handle_message()`. This task adds the
compatibility shim for surfaces that instead deliver the click as an
`adaptiveCard/action` **invoke** (Universal-Action style): acknowledge the
invoke and route the embedded prompt through the same message path.

---

## Scope

- Modify `ParrotM365Agent.on_turn()` (agent.py:117): extend the invoke-name
  dispatch (currently `signin/verifyState` / `signin/tokenExchange`,
  lines 140-147) with an `elif name == "adaptiveCard/action":` branch calling
  a new handler `_handle_adaptive_card_action(context)`.
- Implement `async def _handle_adaptive_card_action(self, context) -> None`:
  1. Acknowledge the invoke first:
     `await self._send_invoke_response(context, status_code=200)`
     (pattern: `_handle_signin_verify`, agent.py:359-389).
  2. Extract the prompt: the invoke `activity.value` carries the Action.Submit
     `data` under `value["action"]["data"]` (dict access with `.get()` chains
     and a `getattr` fallback for object-shaped values, mirroring the
     defensive style at agent.py:374-380). Read `data["feat303_prompt"]`
     (set by TASK-1752's action builder); fall back to
     `data["msteams"]["text"]` if absent.
  3. If no prompt found → log at WARNING and return (never raise).
  4. Otherwise feed it through the message path: set `context.activity.text`
     to the prompt and `await self._handle_message(context)` — this reuses
     identity extraction, permission context, broker, and the card seam
     wholesale.
- Write unit tests in
  `packages/ai-parrot-integrations/tests/unit/test_msagent_invoke_shim.py`.

**NOT in scope**: building action payloads (TASK-1752), the card seam
(TASK-1753), messageBack click handling (zero code — it's a normal message),
`Action.Execute` card refresh semantics (out of spec; cards use Action.Submit).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` | MODIFY | `on_turn()` route + `_handle_adaptive_card_action()` |
| `packages/ai-parrot-integrations/tests/unit/test_msagent_invoke_shim.py` | CREATE | Unit tests for the shim |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Do NOT invent, guess, or assume anything not listed here. Verified 2026-07-14
> against `dev` @ 16b30ee1a. NOTE: line numbers below predate TASK-1753's
> edits to the same file — RE-VERIFY with `grep -n` before editing.

### Verified Imports
```python
# SDK imports stay lazy INSIDE methods (existing pattern, agent.py:131):
from microsoft_agents.activity import ActivityTypes
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py
class ParrotM365Agent:                                     # line 21
    async def on_turn(self, context) -> None:              # line 117
        # Invoke dispatch to EXTEND (lines 140-147):
        #   elif activity_type in ("invoke",):
        #       name = getattr(activity, "name", None) or ""
        #       if name == "signin/verifyState": ...
        #       elif name == "signin/tokenExchange": ...
        #       else: self.logger.debug("Ignoring invoke type: %s", name)
        # Insert the adaptiveCard/action elif BEFORE the else.
    async def _handle_message(self, context) -> None:      # line 214
        # Reads context.activity.text (line 233) — the shim sets this then delegates.
    @staticmethod
    async def _send_invoke_response(context, status_code: int = 200) -> None:  # line 618

# Defensive value extraction pattern to mirror (agent.py:374-380):
value = getattr(activity, "value", None) or {}
state = value.get("state") if isinstance(value, dict) else getattr(value, "state", None)

# Action payload shape produced by TASK-1752 (cards.py action builder):
# Action.Submit "data" dict:
#   {"msteams": {"type": "messageBack", "text": <filled prompt>, ...},
#    "feat303_prompt": <filled prompt>}
# In an adaptiveCard/action invoke, this arrives at activity.value["action"]["data"].
```

### Does NOT Exist
- ~~`adaptiveCard/action` handling anywhere in the package~~ — YOU add the
  only occurrence.
- ~~`ActivityTypes.adaptive_card_action` or an SDK helper for card
  invokes~~ — route on the raw invoke `name` string, exactly like the
  `signin/*` names.
- ~~`AdaptiveCardInvokeValue` typed model imports~~ — do not import SDK invoke
  value types; use the defensive dict/getattr extraction pattern above (SDK
  version variance is why `_send_invoke_response` itself has a fallback,
  agent.py:628-633).
- ~~A separate dispatch API on the bot for actions~~ — resolved in
  brainstorm: actions are natural-language prompts through the normal
  `_handle_message()`/`ask()` path.

---

## Implementation Notes

### Pattern to Follow
```python
# on_turn() extension (mirror the existing elif chain):
elif name == "adaptiveCard/action":
    await self._handle_adaptive_card_action(context)

# Handler skeleton:
async def _handle_adaptive_card_action(self, context) -> None:
    """Handle an ``adaptiveCard/action`` invoke (Universal-Action shim). ..."""
    await self._send_invoke_response(context, status_code=200)
    activity = context.activity
    value = getattr(activity, "value", None) or {}
    action = value.get("action") if isinstance(value, dict) else getattr(value, "action", None)
    ...
    prompt = data.get("feat303_prompt") or (data.get("msteams") or {}).get("text")
    if not prompt: self.logger.warning(...); return
    activity.text = prompt
    await self._handle_message(context)
```

### Key Constraints
- Acknowledge (200) BEFORE processing — Bot Framework requires a timely
  invoke response; `ask()` can take many seconds.
- Never raise out of the handler: any extraction failure logs WARNING and
  returns (a broken click must not surface an error activity storm).
- Google-style docstring on the new handler, matching the tone/detail of
  `_handle_signin_verify` (agent.py:359-373).
- Do not modify `_handle_signin_verify` / `_handle_signin_exchange`.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:359-420`
  — the two existing invoke handlers (ack + act pattern).
- `packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py:43-66` —
  `FakeTurnContext` double to extend with an invoke-shaped activity.

---

## Acceptance Criteria

- [ ] `adaptiveCard/action` invoke → invoke response 200 sent + prompt routed
  into `_handle_message()` (asserted via a stubbed bot receiving `ask()` with
  the prompt text)
- [ ] Missing/garbled payload → 200 ack + WARNING log + no exception, no ask()
- [ ] `signin/*` invokes and unknown invoke names behave exactly as before
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/unit/test_msagent_invoke_shim.py -v`
- [ ] Existing unit suite green: `pytest packages/ai-parrot-integrations/tests/unit/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/unit/test_msagent_invoke_shim.py
# Reuse FakeTurnContext / _make_agent patterns from test_msagent_cards.py,
# extended so the fake activity has type="invoke", name="adaptiveCard/action",
# and value={"action": {"data": {...}}}.

class TestAdaptiveCardActionShim:
    async def test_invoke_acked_and_prompt_routed(self):
        # value.action.data.feat303_prompt = "Show details for order 42"
        # → invokeResponse activity sent with {"status": 200}
        # → bot.ask called once with question="Show details for order 42"
        ...

    async def test_msteams_text_fallback_used(self):
        # no feat303_prompt, msteams.text present → that text is routed
        ...

    async def test_missing_prompt_warns_and_returns(self):
        # value.action.data = {} → 200 ack, no ask() call, no exception
        ...

    async def test_unknown_invoke_still_ignored(self):
        # name="config/fetch" → debug-ignored, no invoke response change
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1753 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - `grep -n "signin/tokenExchange\|_send_invoke_response" agent.py` to
     re-locate the dispatch and ack helper (line numbers shifted after
     TASK-1753)
   - Confirm the `feat303_prompt` key name in `cards.py` (TASK-1752 output)
4. **Update status** in `sdd/tasks/index/ux-custom-engine-copilot.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1754-card-action-invoke-shim.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added an `elif name == "adaptiveCard/action":` branch to
`on_turn()`'s invoke dispatch (before the `else`), calling the new
`_handle_adaptive_card_action()` handler. The handler acknowledges first
via `_send_invoke_response(context, status_code=200)`, then extracts the
prompt from `activity.value["action"]["data"]` using the same
dict-or-getattr defensive pattern as `_handle_signin_verify`, preferring
`feat303_prompt` and falling back to `data["msteams"]["text"]`. Missing
prompt → WARNING log + return (no `ask()` call, no exception). On a
found prompt, sets `activity.text` and delegates to `_handle_message()`
wholesale. `_handle_signin_verify`/`_handle_signin_exchange` untouched
(verified via diff). 4/4 new shim tests pass; full package suite green
(59/59); ruff clean.

**Deviations from spec**: none
