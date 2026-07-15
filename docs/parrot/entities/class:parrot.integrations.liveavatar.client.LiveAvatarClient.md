---
type: Wiki Entity
title: LiveAvatarClient
id: class:parrot.integrations.liveavatar.client.LiveAvatarClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async HTTP client for the LiveAvatar LITE API.
---

# LiveAvatarClient

Defined in [`parrot.integrations.liveavatar.client`](../summaries/mod:parrot.integrations.liveavatar.client.md).

```python
class LiveAvatarClient
```

Async HTTP client for the LiveAvatar LITE API.

Manages session token creation, session start/stop, and periodic
keep-alive.  All auth is handled internally; callers receive an opaque
:class:`~parrot.integrations.liveavatar.models.AvatarSessionHandle`.

Usage (preferred — guarantees stop on exit)::

    async with LiveAvatarClient(cfg) as client:
        handle = await client.create_session_token(cfg)
        await client.start_session(handle)
        ...  # speak

Args:
    cfg: LiveAvatar configuration (read from env by the caller).
    session: Optional external ``aiohttp.ClientSession`` to reuse.
        When ``None`` (default) the client creates and owns one.

## Methods

- `async def aopen(self) -> 'LiveAvatarClient'` — Open the owned aiohttp session (idempotent).
- `async def aclose(self) -> None` — Cancel the keep-alive loop and close the owned aiohttp session.
- `async def create_session_token(self, cfg: LiveAvatarConfig, *, livekit_config: Optional[Dict[str, Any]]=None) -> AvatarSessionHandle` — Create a LiveAvatar LITE session token.
- `async def create_full_session_token(self, cfg: FullModeConfig) -> FullModeSessionHandle` — Create a LiveAvatar FULL mode session token (restricted — no LLM, no context).
- `async def start_session(self, handle: AvatarSessionHandle) -> Dict[str, Any]` — Start a previously created session.
- `async def stop_session(self, handle: AvatarSessionHandle) -> None` — Stop (close) an active session.
- `async def keep_alive(self, handle: AvatarSessionHandle) -> None` — Send a single HTTP keep-alive ping for the session.
- `async def list_avatars(self, cfg: LiveAvatarConfig) -> List[Dict[str, Any]]` — List available avatars (stock + user-uploaded).
- `async def list_voices(self, cfg: LiveAvatarConfig) -> List[Dict[str, Any]]` — List available voices.
- `async def get_session_transcript(self, cfg: LiveAvatarConfig, session_id: str) -> Dict[str, Any]` — Retrieve the server-side transcript for a completed session.
