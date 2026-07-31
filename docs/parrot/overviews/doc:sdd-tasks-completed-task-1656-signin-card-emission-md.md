---
type: Wiki Overview
title: 'TASK-1656: Sign-in Card Emission — OAuthCard on CredentialRequired'
id: doc:sdd-tasks-completed-task-1656-signin-card-emission-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **7**. When a tool raises `CredentialRequired`, the
relates_to:
- concept: mod:parrot.auth.context
  rel: mentions
---

# TASK-1656: Sign-in Card Emission — OAuthCard on CredentialRequired

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1653, TASK-1654
**Assigned-to**: unassigned

---

## Context

Implements spec Module **7**. When a tool raises `CredentialRequired`, the
bridge must emit a native OAuthCard activity instead of an error. The OAuthCard
triggers the BF Token Service's hosted OAuth flow. The raw token must never
appear in the transcript or model context.

## Scope

Modify `ParrotM365Agent._handle_message()` to:
1. Import and catch `CredentialRequired` from `msagentsdk.auth`.
2. On `CredentialRequired`, emit a native OAuthCard sign-in activity.
3. Never fall back to service identity for a per-user tool.
4. Never include a secret in the transcript.

Add `_emit_oauth_card(context, connection_name: str, tool: str)` helper.

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` — MODIFY

## Implementation Notes

### CredentialRequired catch in _handle_message():

```python
    try:
        response = await self.parrot_agent.ask(
            question=text.strip(),
            session_id=session_id,
            user_id=user_id,
            ctx=request_ctx,
        )
        await self._send_text(context, str(response.content))
    except Exception as exc:  # noqa: BLE001
        # Check for CredentialRequired (lazy import to avoid hard dependency)
        try:
            from .auth import CredentialRequired
        except ImportError:
            CredentialRequired = None  # type: ignore[assignment,misc]

        if CredentialRequired is not None and isinstance(exc, CredentialRequired):
            self.logger.info(
                "CredentialRequired for tool=%s connection=%s — emitting OAuthCard",
                exc.tool,
                exc.connection_name,
            )
            await self._emit_oauth_card(context, exc.connection_name, exc.tool)
        else:
            self.logger.error(
                "Error processing message from user=%s: %s", user_id, exc, exc_info=True
            )
            await self._send_text(context, "Sorry, I encountered an error. Please try again.")
    finally:
        _pctx_var.reset(token)
```

### _emit_oauth_card() helper:

```python
async def _emit_oauth_card(
    self, context, connection_name: str, tool: str
) -> None:
    """Emit a native OAuthCard sign-in activity.

    The OAuthCard triggers the Bot Framework Token Service's hosted OAuth
    flow. The token is NEVER included in the card — the token service
    handles credential exchange server-side.

    Args:
        context: TurnContext to send the reply through.
        connection_name: Azure Bot OAuth connection name (e.g. "graph_sso").
        tool: Tool name requesting credentials (used in card text only).
    """
    from microsoft_agents.activity import Activity, ActivityTypes, Attachment

    signin_text = f"Please sign in to authorize access for {tool}."
    oauth_card = {
        "contentType": "application/vnd.microsoft.card.oauth",
        "content": {
            "text": signin_text,
            "connectionName": connection_name,
        },
    }
    reply = Activity(
        type=ActivityTypes.message,
        attachments=[oauth_card],
    )
    await context.send_activity(reply)
    self.logger.info(
        "OAuthCard emitted for tool=%s connection=%s", tool, connection_name
    )
```

Note on SDK API: The exact class for OAuth cards may differ in the Python SDK.
If `Attachment` is not importable, construct the dict directly as shown.
`application/vnd.microsoft.card.oauth` is the standard content type for
OAuthCard in Bot Framework.

## Codebase Contract

### Verified Imports
```python
from microsoft_agents.activity import Activity, ActivityTypes    # verified: agent.py:153 (lazy)
from parrot.auth.context import _pctx_var                       # verified: context.py:33
```

### Existing Signatures
```python
class ParrotM365Agent:
    async def _handle_message(self, context) -> None:  # agent.py:76
```

### Does NOT Exist
- `CredentialRequired` — created in TASK-1654 (auth.py); imported lazily here
- OAuthCard SDK class — may not exist; use dict construction per Bot Framework spec

## Acceptance Criteria

- [ ] `_handle_message()` catches `CredentialRequired` and calls
      `_emit_oauth_card()`.
- [ ] `_emit_oauth_card()` sends an activity with OAuthCard attachment (no
      raw token, no secret).
- [ ] The `CredentialRequired` exception is imported lazily (no hard dep).
- [ ] On any other exception, the existing error path is unchanged.
- [ ] `_emit_oauth_card()` never falls back to service identity.
- [ ] The card's `connectionName` matches the connection from `CredentialRequired`.

## Test Specification

```python
def test_credential_required_emits_card():
    # CredentialRequired exception → OAuthCard activity sent
    ...

def test_no_service_fallback():
    # CredentialRequired never falls back to a service-identity answer
    ...
```

### Completion Note

Added `CredentialRequired` catch block in `_handle_message()` using lazy import
(`from .auth import CredentialRequired`). On `CredentialRequired`, calls
`_emit_oauth_card(context, exc.connection_name, exc.tool)`. Added
`_emit_oauth_card()` that sends an `ActivityTypes.message` with an OAuthCard
attachment (contentType `application/vnd.microsoft.card.oauth`, content with
`text` and `connectionName`). No raw token in the card. Other exceptions use
the existing error path unchanged.
