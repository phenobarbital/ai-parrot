---
type: Wiki Entity
title: GeminiLiveClient
id: class:parrot.clients.live.GeminiLiveClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for Gemini Live API voice interactions.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# GeminiLiveClient

Defined in [`parrot.clients.live`](../summaries/mod:parrot.clients.live.md).

```python
class GeminiLiveClient(AbstractClient)
```

Client for Gemini Live API voice interactions.

Inherits from AbstractClient to maintain consistency with the AI-Parrot
ecosystem. Reuses tool_manager, conversation_memory, and credential
patterns from GoogleGenAIClient.

Key features:
- Inherits tool_manager and conversation_memory from AbstractClient
- Uses same credential system (api_key, vertexai, credentials_file)
- Integrates AbstractTool via LiveToolAdapter
- Returns LiveVoiceResponse with usage metadata

Cross-loop reuse:
    The base per-loop cache (``AbstractClient._ensure_client``) transparently
    builds a new ``genai.Client`` for each event loop this wrapper is used
    from. That cache is safe for the setup client.

    The LiveConnect WebSocket session, however, is created inside the
    ``async with`` body of a specific call and **cannot be migrated to a
    different loop**. Always open LiveConnect (and consume its stream) on
    a single loop. Do not attempt to resume a Live session from a
    background task running on a fresh loop — use a new session instead.

    ``close()`` is inherited from ``AbstractClient`` and tears down every
    cached ``genai.Client``. Entries whose owning loop is no longer
    running are dropped without awaiting.

Usage:
    client = GeminiLiveClient(
        model=GoogleVoiceModel.DEFAULT,
        voice_name="Puck",
        tools=[my_tool],
        use_tools=True,
    )

    async with client:
        async for response in client.stream_voice(audio_iterator):
            print(response.text, response.usage)

## Methods

- `async def get_client(self) -> genai.Client` — Return the underlying genai.Client instance.
- `async def stream_voice(self, audio_iterator: AsyncIterator[bytes], system_prompt: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, stt_only: bool=False, **kwargs) -> AsyncIterator[LiveVoiceResponse]` — Stream bidirectional voice interaction.
- `async def ask(self, question: str, system_prompt: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]` — Send text input and receive voice response.
- `async def close(self) -> None` — Close the client and clean up resources.
- `async def ask_stream(self, *args, **kwargs)` — Deprecated alias for stream_voice.
- `async def batch_ask(self, *args, **kwargs)` — Deprecated alias for send_text.
- `async def invoke(self, *args, **kwargs)` — Not supported: GeminiLiveClient is a realtime voice client.
- `async def resume(self, *args, **kwargs)` — Not supported: GeminiLiveClient does not implement suspend/resume.
