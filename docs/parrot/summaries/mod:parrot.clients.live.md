---
type: Wiki Summary
title: parrot.clients.live
id: mod:parrot.clients.live
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GeminiLiveClient - Live/Realtime API Client for AI-Parrot
relates_to:
- concept: class:parrot.clients.live.GeminiLiveClient
  rel: defines
- concept: class:parrot.clients.live.LiveCompletionUsage
  rel: defines
- concept: class:parrot.clients.live.LiveToolAdapter
  rel: defines
- concept: class:parrot.clients.live.LiveToolCall
  rel: defines
- concept: class:parrot.clients.live.LiveVoiceResponse
  rel: defines
- concept: class:parrot.clients.live.VoiceTurnMetadata
  rel: defines
- concept: func:parrot.clients.live.create_live_client
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.clients.live`

GeminiLiveClient - Live/Realtime API Client for AI-Parrot

Inherits from AbstractClient to maintain consistency with the AI-Parrot
ecosystem while supporting the unique requirements of voice streaming.

Key Features:
- Inherits from AbstractClient (same as GoogleGenAIClient, AnthropicClient, etc.)
- Reuses tool_manager, conversation_memory, preset system
- Uses same credential pattern as GoogleGenAIClient
- Supports AbstractTool integration via LiveToolAdapter
- Returns LiveVoiceResponse with CompletionUsage metadata

Usage:
    client = GeminiLiveClient(
        model=GoogleVoiceModel.DEFAULT,
        voice_name="Puck",
        tools=[my_tool],  # AbstractTool instances
    )

    async with client:
        async for response in client.stream_voice(audio_iterator):
            print(response.text, response.usage)

Location: parrot/clients/live.py

## Classes

- **`LiveCompletionUsage`** — Usage tracking for Gemini Live API responses.
- **`LiveToolCall`** — Represents a tool call from Gemini Live API.
- **`VoiceTurnMetadata`** — Metadata for a single voice turn/response.
- **`LiveVoiceResponse`** — Response from GeminiLiveClient voice interaction.
- **`LiveToolAdapter`** — Adapter to convert AI-Parrot AbstractTool instances to Gemini Live API
- **`GeminiLiveClient(AbstractClient)`** — Client for Gemini Live API voice interactions.

## Functions

- `def create_live_client(model: Optional[Union[str, GoogleVoiceModel]]=None, voice_name: str='Puck', tools: Optional[List[AbstractTool]]=None, use_tools: bool=True, **kwargs) -> GeminiLiveClient` — Factory function to create a GeminiLiveClient.
