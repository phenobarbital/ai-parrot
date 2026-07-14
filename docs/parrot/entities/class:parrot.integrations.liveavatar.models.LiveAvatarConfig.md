---
type: Wiki Entity
title: LiveAvatarConfig
id: class:parrot.integrations.liveavatar.models.LiveAvatarConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for the LiveAvatar LITE API.
---

# LiveAvatarConfig

Defined in [`parrot.integrations.liveavatar.models`](../summaries/mod:parrot.integrations.liveavatar.models.md).

```python
class LiveAvatarConfig(BaseModel)
```

Configuration for the LiveAvatar LITE API.

Attributes:
    api_key: LiveAvatar API key (env: LIVEAVATAR_API_KEY).
    avatar_id: Avatar identifier (env: LIVEAVATAR_AVATAR_ID).
    base_url: Base URL for the LiveAvatar REST API.
    is_sandbox: Use the sandbox environment (default True).
    max_session_duration: Optional maximum session duration in seconds,
        sent to ``create_session_token`` as a safety net.
    quality: LITE video_settings.quality enum value.  # TODO Q-video-settings
    encoding: LITE video_settings.encoding enum value.  # TODO Q-video-settings
