---
type: Wiki Entity
title: FullModeConfig
id: class:parrot.integrations.liveavatar.models.FullModeConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: FULL mode configuration (extends LITE config with voice/language fields).
relates_to:
- concept: class:parrot.integrations.liveavatar.models.LiveAvatarConfig
  rel: extends
---

# FullModeConfig

Defined in [`parrot.integrations.liveavatar.models`](../summaries/mod:parrot.integrations.liveavatar.models.md).

```python
class FullModeConfig(LiveAvatarConfig)
```

FULL mode configuration (extends LITE config with voice/language fields).

LiveAvatar FULL mode lets the avatar manage its own STT, TTS, and lip-sync.
The ai-parrot backend only mints the session (restricted mode — no
``llm_configuration_id``, no ``context_id``) and calls ``avatar.speak_text``.

Attributes:
    voice_id: Optional voice ID for the avatar persona.  When ``None`` the
        avatar uses its default voice.
    language: BCP-47 language tag for the avatar (default ``"en"``).
    interactivity_type: Session interactivity mode — either
        ``"CONVERSATIONAL"`` (default) or ``"PUSH_TO_TALK"``.
