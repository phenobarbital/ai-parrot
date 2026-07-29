---
type: Wiki Overview
title: 'TASK-1653: Credential Context Bridge — PermissionContext + RequestContext
  in _handle_message'
id: doc:sdd-tasks-completed-task-1653-msagentsdk-credential-context-bridge-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **4**. After identity extraction (TASK-1651), the
  bridge
relates_to:
- concept: mod:parrot.auth.context
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1653: Credential Context Bridge — PermissionContext + RequestContext in _handle_message

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1652
**Assigned-to**: unassigned

---

## Context

Implements spec Module **4**. After identity extraction (TASK-1651), the bridge
needs to propagate the user identity into the parrot permission/request context
mechanism so downstream tools can access it. This task updates `_handle_message()`
to set `_pctx_var` and pass `ctx=RequestContext(...)` to `ask()`.

## Scope

Modify `ParrotM365Agent._handle_message()` to:
1. Extract `aad_object_id` as canonical user identity via `_extract_user_id()`.
2. Build `UserSession` → `PermissionContext` with `channel="msagentsdk"`.
3. Set `_pctx_var` with the `PermissionContext` token.
4. Build `RequestContext` with `user_id`, `session_id`.
5. Pass `ctx=request_context` to `agent.ask()`.
6. Reset the `_pctx_var` token after the call.

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` — MODIFY

## Implementation Notes

```python
async def _handle_message(self, context) -> None:
    activity = context.activity
    text: Optional[str] = activity.text
    if not text or not text.strip():
        self.logger.debug("Received empty message — skipping ask()")
        return

    user_id: str = self._extract_user_id(activity)
    session_id: Optional[str] = (
        activity.conversation.id if activity.conversation else None
    )
    self.logger.info("Message from user=%s session=%s", user_id, session_id)

    # Build permission context and set ContextVar
    from parrot.auth.permission import UserSession, PermissionContext
    from parrot.auth.context import _pctx_var
    from parrot.utils.helpers import RequestContext

    user_session = UserSession(
        user_id=user_id,
        tenant_id="msagentsdk",
        roles=frozenset(),
    )
    pctx = PermissionContext(
        session=user_session,
        channel="msagentsdk",
    )
    token = _pctx_var.set(pctx)
    request_ctx = RequestContext(user_id=user_id, session_id=session_id)

    try:
        response = await self.parrot_agent.ask(
            question=text.strip(),
            session_id=session_id,
            user_id=user_id,
            ctx=request_ctx,
        )
        await self._send_text(context, str(response.content))
    except Exception as exc:
        self.logger.error(
            "Error processing message from user=%s: %s", user_id, exc, exc_info=True
        )
        await self._send_text(context, "Sorry, I encountered an error. Please try again.")
    finally:
        _pctx_var.reset(token)
```

Note: The `CredentialRequired` exception catch for OAuthCard emission is
intentionally deferred to TASK-1656 (Module 7). This task only wires up
the permission/request context.

## Codebase Contract

### Verified Imports
```python
from parrot.auth.permission import UserSession       # verified: permission.py:20
from parrot.auth.permission import PermissionContext  # verified: permission.py:80
from parrot.auth.context import _pctx_var            # verified: context.py:33
from parrot.utils.helpers import RequestContext       # verified: helpers.py:7
```

### Existing Signatures
```python
@dataclass(frozen=True)
class UserSession:                        # permission.py:20
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    metadata: dict = field(default_factory=dict)

@dataclass
class PermissionContext:                  # permission.py:80
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: Optional[TraceContext] = None
    extra: dict = field(default_factory=dict)

class RequestContext:                     # helpers.py:7
    def __init__(self, request=None, app=None, llm=None,
                 user_id=None, session_id=None, **kwargs): ...

_pctx_var: ContextVar["PermissionContext | None"]  # context.py:33

class AbstractBot:                        # abstract.py:156
    async def ask(self, question, session_id=None, user_id=None,
                  ..., ctx=None, ..., trace_context=None, **kwargs): ...
```

### Does NOT Exist
- `CredentialRequired` exception — does not exist yet; added in TASK-1656/auth.py

## Acceptance Criteria

- [ ] `_handle_message()` sets `_pctx_var` with `PermissionContext` having
      `channel="msagentsdk"` and `user_id=aad_object_id`.
- [ ] `ask()` receives `ctx=RequestContext(user_id=..., session_id=...)`.
- [ ] `_pctx_var` token is reset in `finally` block.
- [ ] Empty/whitespace messages still return early without context setup.
- [ ] No regressions for bots without OAuth connections.

## Test Specification

```python
def test_message_sets_pctx_var():
    # _handle_message sets _pctx_var with correct PermissionContext
    ...

def test_message_passes_ctx_to_ask():
    # ask() receives ctx=RequestContext(...)
    ...
```

### Completion Note

Updated `_handle_message()` to use `_extract_user_id()` for canonical identity,
build `UserSession(user_id=..., tenant_id="msagentsdk", roles=frozenset())`,
wrap in `PermissionContext(session=..., channel="msagentsdk")`, set `_pctx_var`
token before `ask()` and reset in `finally`. Passes `ctx=RequestContext(
user_id=..., session_id=...)` to `ask()`. All imports are lazy inside the method.
