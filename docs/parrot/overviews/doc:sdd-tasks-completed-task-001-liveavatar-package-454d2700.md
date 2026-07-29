---
type: Wiki Overview
title: 'TASK-001: LiveAvatar package skeleton, Pydantic models & `livekit-api` extra'
id: doc:sdd-tasks-completed-task-001-liveavatar-package-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task for FEAT-242. Every other module (M1–M7) imports the Pydantic
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
---

# TASK-001: LiveAvatar package skeleton, Pydantic models & `livekit-api` extra

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-242. Every other module (M1–M7) imports the Pydantic
data models defined here and lives inside the `parrot.integrations.liveavatar`
package created here. This task implements the **Data Models** block of spec §2
and registers the new `livekit-api` optional dependency (spec §7 External
Dependencies). No business logic — just the package skeleton, models, and
packaging wiring.

---

## Scope

- Create the package `parrot/integrations/liveavatar/` (under
  `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/`) with an
  `__init__.py` that re-exports the public models.
- Implement `models.py` with the four Pydantic v2 models from spec §2:
  `LiveAvatarConfig`, `LiveKitRoomTokens`, `AvatarSessionHandle`.
- Add a `liveavatar` optional extra to
  `packages/ai-parrot-integrations/pyproject.toml` declaring `livekit-api`.
- Write unit tests for model construction / defaults / required fields.

**NOT in scope**: HTTP client (TASK-002), WS bridge (TASK-003), room manager
logic (TASK-004), flattener (TASK-005), orchestrator (TASK-006). Do NOT add
business methods to the models.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | CREATE | Package init; re-export models |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` | CREATE | Pydantic models |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | Add `liveavatar` extra with `livekit-api` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_models.py` | CREATE | Model unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18 against the source.

### Verified Imports
```python
from pydantic import BaseModel, Field            # Pydantic v2 (project standard)
from typing import Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/pyproject.toml
# [project.optional-dependencies] block starts at line 33.
# Existing extras follow this exact shape (verified):
#   voice-supertonic = ["onnxruntime>=1.17"]
#   matrix = ["mautrix>=0.20", "python-olm>=3.2.16"]
# Add a new sibling entry; optionally fold it into the "all" aggregate (line ~85).

# packages/ai-parrot-integrations/src/parrot/integrations/  (verified to exist)
#   core/  manager.py  matrix/  models.py  msteams/  parser.py  slack/
#   telegram/  whatsapp/  — add a NEW sibling subpackage `liveavatar/`.
```

### Data Models to Implement (from spec §2, illustrative — finalize types here)
```python
class LiveAvatarConfig(BaseModel):
    api_key: str                      # LIVEAVATAR_API_KEY (env, injected by caller)
    avatar_id: str                    # LIVEAVATAR_AVATAR_ID (env)
    base_url: str = "https://api.liveavatar.com"
    is_sandbox: bool = True
    max_session_duration: Optional[int] = None
    quality: Optional[str] = None     # video_settings.quality — Q-video-settings (see Notes)
    encoding: Optional[str] = None    # video_settings.encoding — Q-video-settings (see Notes)

class LiveKitRoomTokens(BaseModel):
    livekit_url: str                  # wss://<project>.livekit.cloud
    room: str
    client_token: str                 # browser viewer
    agent_token: str                  # avatar participant (server-side only)

class AvatarSessionHandle(BaseModel):
    session_id: str                   # ai-parrot session_id (shared with AgentChat)
    liveavatar_session_id: str
    session_token: str                # Bearer for start_session
    ws_url: str                       # avatar media-server WS
    tenant_id: Optional[str] = None
    agent_name: str
```

### Does NOT Exist (do NOT reference)
- ~~any existing `parrot.integrations.liveavatar` / `livekit` / `webrtc` / `aiortc` module~~ — ZERO matches in `packages/*/src` (confirmed 2026-06-18). Clean slate.
- ~~a `liveavatar` extra in any pyproject~~ — does not exist yet; this task creates it.

---

## Implementation Notes

### Pattern to Follow
Mirror the existing models file style in
`packages/ai-parrot-integrations/src/parrot/integrations/models.py` (Pydantic v2,
`Field(..., description=...)`). Keep models pure data — no methods, no I/O.

### Key Constraints
- Pydantic v2 only. Use `Field(..., description="...")` for every field.
- Secrets are NOT defaulted in code — `api_key`/`avatar_id` are required fields
  the caller fills from env (`LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`).
- `agent_token` lives only on the server-side `LiveKitRoomTokens`; never expose it
  to clients (enforced downstream in TASK-007, but document the intent here).

### Open Question to surface (do NOT guess)
- **Q-video-settings**: the LITE `video_settings.quality` / `encoding` enum values
  are unconfirmed. Keep both as `Optional[str] = None` for now and add a `# TODO
  Q-video-settings` comment. Do NOT invent an enum.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/models.py` — model style
- `packages/ai-parrot-integrations/pyproject.toml:33` — extras block

---

## Acceptance Criteria

- [ ] Package imports: `from parrot.integrations.liveavatar import LiveAvatarConfig, LiveKitRoomTokens, AvatarSessionHandle`
- [ ] `LiveAvatarConfig(api_key="x", avatar_id="y")` constructs with `is_sandbox=True`, `base_url="https://api.liveavatar.com"` defaults
- [ ] Missing required field raises `pydantic.ValidationError`
- [ ] `pyproject.toml` declares `liveavatar = ["livekit-api>=0.x"]` (pin at impl)
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_models.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_models.py
import pytest
from pydantic import ValidationError
from parrot.integrations.liveavatar import (
    LiveAvatarConfig, LiveKitRoomTokens, AvatarSessionHandle,
)


def test_config_defaults():
    cfg = LiveAvatarConfig(api_key="k", avatar_id="a")
    assert cfg.is_sandbox is True
    assert cfg.base_url == "https://api.liveavatar.com"
    assert cfg.max_session_duration is None


def test_config_requires_keys():
    with pytest.raises(ValidationError):
        LiveAvatarConfig()


def test_room_tokens_roundtrip():
    t = LiveKitRoomTokens(livekit_url="wss://x.livekit.cloud", room="r",
                          client_token="c", agent_token="a")
    assert t.room == "r"


def test_session_handle():
    h = AvatarSessionHandle(session_id="s", liveavatar_session_id="ls",
                            session_token="st", ws_url="wss://ws", agent_name="bot")
    assert h.tenant_id is None
```

---

## Agent Instructions

1. Read the spec §2 (Data Models) for full context.
2. Verify the Codebase Contract before writing code.
3. Implement models + package skeleton + pyproject extra.
4. Run tests + ruff.
5. Move this file to `sdd/tasks/completed/` and update the per-spec index.
6. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 8 unit tests pass, lint clean. `livekit-api>=1.0` added as the
`liveavatar` extra in `pyproject.toml`. Both `quality` and `encoding` fields
kept as `Optional[str] = None` with `# TODO Q-video-settings` comments per
task instructions — enum values not guessed.
**Deviations from spec**: None. `quality`/`encoding` defaults match task
spec (Optional[str] = None) since Q-video-settings is unresolved.
