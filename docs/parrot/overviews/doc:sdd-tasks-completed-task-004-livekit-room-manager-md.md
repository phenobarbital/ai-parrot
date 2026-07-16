---
type: Wiki Overview
title: 'TASK-004: LiveKit room manager — BYO Cloud tokens (M3)'
id: doc:sdd-tasks-completed-task-004-livekit-room-manager-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 3** (spec §3): mint a LiveKit Cloud room plus client/agent'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
---

# TASK-004: LiveKit room manager — BYO Cloud tokens (M3)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** (spec §3): mint a LiveKit Cloud room plus client/agent
tokens via `livekit-api` (BYO transport). **Shared with Phase C (FEAT-243)** — keep
the interface clean and provider-agnostic. Capability: `livekit-room-manager`.

---

## Scope

- Implement `LiveKitRoomManager` in `room_manager.py` with
  `mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens`.
- Read `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` from env (caller
  may inject; default to `os.environ`).
- Mint two tokens: a `client_token` (browser viewer, subscribe-only grants) and
  an `agent_token` (avatar participant, publish grants). Return a populated
  `LiveKitRoomTokens`.

**NOT in scope**: actually creating the room server-side beyond token grants if
the SDK auto-creates on join, opening WS, orchestration (TASK-006), endpoint
wiring (TASK-007).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py` | CREATE | `LiveKitRoomManager` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export `LiveKitRoomManager` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_manager.py` | CREATE | Token-minting tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
import os
import logging
from typing import Optional
from livekit import api as livekit_api            # provided by the `liveavatar` extra (TASK-001)
from parrot.integrations.liveavatar.models import LiveKitRoomTokens   # from TASK-001
```

### Existing Signatures to Use
```python
# Public interface to implement (spec §2):
class LiveKitRoomManager:
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens: ...

# livekit-api token minting (confirm exact API at impl — version pinned in TASK-001):
#   token = livekit_api.AccessToken(api_key, api_secret) \
#       .with_identity(identity).with_grants(livekit_api.VideoGrants(room_join=True, room=room))
#   jwt = token.to_jwt()
```

### Does NOT Exist (do NOT reference)
- ~~a self-hosted LiveKit SFU / `aiortc`~~ — out of scope; managed LiveKit Cloud only.
- ~~`livekit-api` installed by default~~ — it is an **optional extra** added in TASK-001;
  import lazily and raise a clear error if missing.
- ~~hardcoded LiveKit credentials~~ — env only.

---

## Implementation Notes

### Pattern to Follow
```python
class LiveKitRoomManager:
    def __init__(self, *, url: str | None = None, api_key: str | None = None,
                 api_secret: str | None = None):
        self.url = url or os.environ["LIVEKIT_URL"]
        self._key = api_key or os.environ["LIVEKIT_API_KEY"]
        self._secret = api_secret or os.environ["LIVEKIT_API_SECRET"]
        self.logger = logging.getLogger(__name__)
```

### Key Constraints
- Secrets via env only; never log token secrets.
- Client token = subscribe/viewer grants; agent token = publish grants.
- Confirm the exact `livekit-api` token-builder API against the pinned version
  before use (the snippet above is illustrative).

### References in Codebase
- None (clean slate). Use the official `livekit-api` docs for the pinned version.

---

## Acceptance Criteria

- [ ] `from parrot.integrations.liveavatar import LiveKitRoomManager` works
- [ ] `test_room_manager_mints_tokens`: returns a `LiveKitRoomTokens` with non-empty `client_token` and `agent_token` for a given room (env-driven, monkeypatched creds)
- [ ] Client and agent tokens carry distinct grants (viewer vs publisher)
- [ ] Missing `LIVEKIT_*` env raises a clear error
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_manager.py -v`
- [ ] No lint errors: `ruff check .../liveavatar/room_manager.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_manager.py
import pytest
from parrot.integrations.liveavatar import LiveKitRoomManager
from parrot.integrations.liveavatar.models import LiveKitRoomTokens


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")
    return LiveKitRoomManager()


def test_room_manager_mints_tokens(mgr):
    tokens = mgr.mint_room_tokens(room="r1", identity="viewer-1")
    assert isinstance(tokens, LiveKitRoomTokens)
    assert tokens.client_token and tokens.agent_token
    assert tokens.client_token != tokens.agent_token
```

---

## Agent Instructions

1. Read spec §3 Module 3.
2. Verify the Codebase Contract and the pinned `livekit-api` token API.
3. Implement `LiveKitRoomManager`.
4. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 7 unit tests pass, lint clean. Uses livekit-api 1.1.0.
``client_token`` has ``can_publish=False`` (subscribe-only). ``agent_token``
has ``can_publish=True``. ``livekit-api`` imported lazily with clear error on
missing. Secrets from env only.
**Deviations from spec**: None.
