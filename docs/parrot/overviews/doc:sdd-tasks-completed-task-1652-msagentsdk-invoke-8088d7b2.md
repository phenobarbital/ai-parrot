---
type: Wiki Overview
title: 'TASK-1652: Invoke Routing — signin/verifyState and signin/tokenExchange'
id: doc:sdd-tasks-completed-task-1652-msagentsdk-invoke-routing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **3**. The Bot Framework sign-in flow completes when
  the
---

# TASK-1652: Invoke Routing — signin/verifyState and signin/tokenExchange

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1651
**Assigned-to**: unassigned

---

## Context

Implements spec Module **3**. The Bot Framework sign-in flow completes when the
token service sends an `invoke` activity back to the bot. Currently `on_turn()`
ignores `invoke` activities. This task adds routing for `signin/verifyState` and
`signin/tokenExchange` invoke types.

## Scope

Extend `ParrotM365Agent.on_turn()` to detect `activity_type == "invoke"` and
route to one of two new handlers:
- `_handle_signin_verify(context)` — handles `signin/verifyState` invoke
- `_handle_signin_exchange(context)` — handles `signin/tokenExchange` invoke

Other invoke types should be logged at DEBUG and ignored (no regression).

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` — MODIFY

## Implementation Notes

### on_turn() extension:
```python
elif activity_type in ("invoke",):
    name = getattr(activity, "name", None) or ""
    if name == "signin/verifyState":
        await self._handle_signin_verify(context)
    elif name == "signin/tokenExchange":
        await self._handle_signin_exchange(context)
    else:
        self.logger.debug("Ignoring invoke type: %s", name)
```

### _handle_signin_verify():
```python
async def _handle_signin_verify(self, context) -> None:
    """Handle signin/verifyState invoke — validate magic code."""
    from microsoft_agents.activity import Activity, ActivityTypes
    activity = context.activity
    value = getattr(activity, "value", None) or {}
    state = value.get("state") if isinstance(value, dict) else getattr(value, "state", None)
    self.logger.info(
        "signin/verifyState received: user=%s state_present=%s",
        self._extract_user_id(activity),
        bool(state),
    )
    # The token service already stores the token when it sends verifyState.
    # Just acknowledge with a 200 invoke response.
    await self._send_invoke_response(context, status_code=200)
```

### _handle_signin_exchange():
```python
async def _handle_signin_exchange(self, context) -> None:
    """Handle signin/tokenExchange invoke — exchange SSO token."""
    from microsoft_agents.activity import Activity, ActivityTypes
    activity = context.activity
    value = getattr(activity, "value", None) or {}
    connection_name = (
        value.get("connectionName")
        if isinstance(value, dict)
        else getattr(value, "connection_name", None)
    )
    self.logger.info(
        "signin/tokenExchange received: user=%s connection=%s",
        self._extract_user_id(activity),
        connection_name,
    )
    # SSO token exchange is handled by the token service; acknowledge.
    await self._send_invoke_response(context, status_code=200)
```

### _send_invoke_response():
```python
@staticmethod
async def _send_invoke_response(context, status_code: int = 200) -> None:
    """Send an invoke response activity."""
    from microsoft_agents.activity import Activity, ActivityTypes
    response = Activity(type=ActivityTypes.invoke_response)
    response.value = {"status": status_code}
    await context.send_activity(response)
```

Note: `ActivityTypes.invoke_response` may be spelled differently in the Python
SDK. If it doesn't exist, use the string `"invokeResponse"` directly.

## Codebase Contract

### Verified Imports
```python
from microsoft_agents.activity import ActivityTypes   # verified: agent.py:64 (lazy)
from microsoft_agents.activity import Activity        # verified: agent.py:153 (lazy)
```

### Existing Signatures
```python
class ParrotM365Agent:                    # agent.py:14
    async def on_turn(self, context) -> None:  # agent.py:52
        # Routes: message → _handle_message, conversationUpdate → _handle_conversation_update
```

### Does NOT Exist
- `ParrotM365Agent._handle_signin_verify` — does not exist yet; being added
- `ParrotM365Agent._handle_signin_exchange` — does not exist yet; being added
- `ParrotM365Agent._send_invoke_response` — does not exist yet; being added

## Acceptance Criteria

- [ ] `on_turn()` routes `invoke/signin/verifyState` → `_handle_signin_verify()`.
- [ ] `on_turn()` routes `invoke/signin/tokenExchange` → `_handle_signin_exchange()`.
- [ ] Unknown invoke types are logged at DEBUG and ignored.
- [ ] Both handlers send an invoke response with status 200.
- [ ] Existing message and conversationUpdate routing unchanged.

## Test Specification

```python
def test_invoke_signin_verify_state():
    # invoke activity with name="signin/verifyState" is routed correctly
    ...

def test_invoke_signin_token_exchange():
    # invoke activity with name="signin/tokenExchange" is routed correctly
    ...

def test_invoke_unknown_ignored():
    # invoke with unknown name is silently ignored (no error)
    ...
```

### Completion Note

Added `invoke` branch in `on_turn()` that reads `activity.name` and routes to
`_handle_signin_verify()` or `_handle_signin_exchange()`. Unknown invoke names
logged at DEBUG and ignored. Both handlers call `_send_invoke_response(context,
200)`. Added `_send_invoke_response()` static method that tries
`ActivityTypes.invoke_response` and falls back to the `"invokeResponse"` string
for SDK version compatibility.
