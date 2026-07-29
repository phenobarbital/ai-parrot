---
type: Wiki Entity
title: VoiceBot
id: class:parrot.bots.voice.VoiceBot
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bot with native voice interaction capabilities.
relates_to:
- concept: class:parrot.a2a.server.A2AEnabledMixin
  rel: extends
- concept: class:parrot.bots.base.BaseBot
  rel: extends
---

# VoiceBot

Defined in [`parrot.bots.voice`](../summaries/mod:parrot.bots.voice.md).

```python
class VoiceBot(A2AEnabledMixin, BaseBot)
```

Bot with native voice interaction capabilities.

Uses GeminiLiveClient internally for:
- Bidirectional audio processing
- Tool execution during conversation
- Usage tracking (tokens, timing, etc.)

Usage:
    bot = VoiceBot(
        name="Assistant",
        system_prompt="You are helpful...",
        tools=[MyTool()],
        voice_config=VoiceConfig(voice_name="Puck")
    )

    async for response in bot.ask_stream(audio_iterator):
        if response.audio_data:
            play_audio(response.audio_data)
        if response.usage:
            print(f"Tokens: {response.usage.total_tokens}")

## Methods

- `async def configure(self, app=None) -> None` — Configure the bot.
- `async def ask_text(self, prompt: str, **kwargs) -> str` — Text-based ask using GoogleGenAIClient (for non-voice operations).
- `def get_tool_definitions(self) -> List[Dict[str, Any]]` — Get tool definitions in API format.
- `async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any` — Execute a tool by name.
- `async def setup_mcp_servers(self, configurations: Optional[List[MCPServerConfig]]=None) -> None` — Setup multiple MCP servers during initialization.
- `async def ask_stream(self, audio_input: Union[bytes, AsyncIterator[bytes]], session_id: Optional[str]=None, user_id: Optional[str]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]` — Voice interaction stream.
- `async def ask_voice(self, audio_input: bytes, session_id: Optional[str]=None, user_id: Optional[str]=None, **kwargs) -> LiveVoiceResponse` — Process voice input and return complete response.
- `async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]` — Send text and receive voice response.
- `async def close(self)` — Close any resources if needed.
