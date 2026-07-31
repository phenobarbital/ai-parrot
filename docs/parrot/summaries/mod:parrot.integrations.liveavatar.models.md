---
type: Wiki Summary
title: parrot.integrations.liveavatar.models
id: mod:parrot.integrations.liveavatar.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic data models for the LiveAvatar integration (FEAT-242, Phase A).
relates_to:
- concept: class:parrot.integrations.liveavatar.models.AvatarSessionHandle
  rel: defines
- concept: class:parrot.integrations.liveavatar.models.FullModeConfig
  rel: defines
- concept: class:parrot.integrations.liveavatar.models.FullModeSessionHandle
  rel: defines
- concept: class:parrot.integrations.liveavatar.models.LiveAvatarConfig
  rel: defines
- concept: class:parrot.integrations.liveavatar.models.LiveKitRoomTokens
  rel: defines
- concept: class:parrot.integrations.liveavatar.models.StructuredOutputMessage
  rel: defines
---

# `parrot.integrations.liveavatar.models`

Pydantic data models for the LiveAvatar integration (FEAT-242, Phase A).

All secrets (``api_key``, ``avatar_id``) are required fields that the caller
injects from env vars — they are never defaulted in code.

Open questions deferred to owners:
  Q-video-settings: ``quality``/``encoding`` enum values are unconfirmed for
  LITE mode; kept as ``Optional[str] = None`` until the API reference is
  reviewed.

## Classes

- **`LiveAvatarConfig(BaseModel)`** — Configuration for the LiveAvatar LITE API.
- **`LiveKitRoomTokens(BaseModel)`** — Viewer and agent JWT tokens for a LiveKit Cloud room.
- **`AvatarSessionHandle(BaseModel)`** — Runtime handle for a LiveAvatar LITE session.
- **`FullModeConfig(LiveAvatarConfig)`** — FULL mode configuration (extends LITE config with voice/language fields).
- **`FullModeSessionHandle(AvatarSessionHandle)`** — Runtime handle for a LiveAvatar FULL mode session.
- **`StructuredOutputMessage(BaseModel)`** — Output-bridge contract for structured ai-parrot outputs (FEAT-249, relocated).
