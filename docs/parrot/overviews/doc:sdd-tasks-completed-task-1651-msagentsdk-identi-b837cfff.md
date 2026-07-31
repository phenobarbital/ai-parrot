---
type: Wiki Overview
title: 'TASK-1651: Identity Extraction — aad_object_id from Activity'
id: doc:sdd-tasks-completed-task-1651-msagentsdk-identity-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **2**. `ParrotM365Agent` currently extracts
relates_to:
- concept: mod:parrot.auth.context
  rel: mentions
---

# TASK-1651: Identity Extraction — aad_object_id from Activity

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-1650
**Assigned-to**: unassigned

---

## Context

Implements spec Module **2**. `ParrotM365Agent` currently extracts
`from_property.id` as user identity. For Teams/Copilot Studio, the Entra
`aad_object_id` is the canonical identity needed to key the BF Token Service.
This task extracts `aad_object_id` first, falling back to `from_property.id`.

## Scope

Add `_extract_user_id(activity) -> str` helper to `ParrotM365Agent` that
returns `aad_object_id` from `activity.from_property` if present, otherwise
falls back to `activity.from_property.id`. Build and return a `UserContext`
from this identity.

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` — MODIFY

## Implementation Notes

- Add a private method `_extract_user_id(self, activity) -> str` that checks
  `activity.from_property` for an `aad_object_id` attribute (or `aadObjectId`
  key — Activity can be a dict-like object). Fall back to `activity.from_property.id`.
- Add a `_build_user_context(self, activity) -> UserContext` method using
  `_extract_user_id()`. Set `channel="msagentsdk"`.
- Add lazy import of `UserContext` inside the method to keep module importable
  without parrot installed.
- Keep the existing `_handle_message()` using `user_id` from `from_property.id`
  for now — it will be updated in TASK-1653.

### Identity extraction logic:
```python
def _extract_user_id(self, activity) -> str:
    """Extract canonical user identity, preferring aad_object_id."""
    from_prop = getattr(activity, "from_property", None)
    if from_prop is None:
        return "anonymous"
    # Try aad_object_id (Entra identity, preferred)
    aad_id = getattr(from_prop, "aad_object_id", None)
    if not aad_id:
        # Activity might expose it as a dict-like property
        aad_id = getattr(from_prop, "aadObjectId", None)
    if aad_id:
        return str(aad_id)
    # Fall back to channel-level user id
    return getattr(from_prop, "id", None) or "anonymous"
```

## Codebase Contract

### Verified Imports
```python
from parrot.auth.context import UserContext   # verified: context.py:38
```

### Existing Signatures
```python
class ParrotM365Agent:                       # agent.py:14
    def __init__(self, parrot_agent, welcome_message=None): ...  # agent.py:33
    async def on_turn(self, context) -> None: ...                # agent.py:52
    async def _handle_message(self, context) -> None: ...        # agent.py:76
    async def _handle_conversation_update(self, context): ...    # agent.py:116
    @staticmethod
    async def _send_text(context, text: str) -> None: ...        # agent.py:136
```

### Does NOT Exist
- `ParrotM365Agent._extract_user_id` — does not exist yet; being added
- `ParrotM365Agent._build_user_context` — does not exist yet; being added

## Acceptance Criteria

- [ ] `_extract_user_id(activity)` returns `aad_object_id` when present on
      `activity.from_property`.
- [ ] `_extract_user_id(activity)` falls back to `activity.from_property.id`
      when `aad_object_id` is absent.
- [ ] `_build_user_context(activity)` returns `UserContext` with `channel=
      "msagentsdk"` and `user_id` from `_extract_user_id()`.
- [ ] All existing behavior (message routing, conversation update) unaffected.

## Test Specification

```python
def test_identity_aad_object_id():
    # Activity with aad_object_id on from_property
    ...

def test_identity_fallback_channel_id():
    # Activity without aad_object_id — falls back to from_property.id
    ...
```

### Completion Note

Implemented `_extract_user_id(activity)` that checks `from_property.aad_object_id`
then `from_property.aadObjectId` (camelCase fallback for SDK version differences),
then `from_property.id`, then "anonymous". Added `_build_user_context(activity)`
that returns `UserContext(channel="msagentsdk", user_id=..., display_name=...,
session_id=...)` using lazy import. Updated `__init__` to accept `resolver` and
`audit_ledger` optional params.
