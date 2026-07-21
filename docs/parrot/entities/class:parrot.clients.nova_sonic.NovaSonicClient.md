---
type: Wiki Entity
title: NovaSonicClient
id: class:parrot.clients.nova_sonic.NovaSonicClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Experimental Amazon Nova 2 Sonic bidirectional speech-to-speech client.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# NovaSonicClient

Defined in [`parrot.clients.nova_sonic`](../summaries/mod:parrot.clients.nova_sonic.md).

```python
class NovaSonicClient(AbstractClient)
```

Experimental Amazon Nova 2 Sonic bidirectional speech-to-speech client.

Handles PCM 16kHz mono audio input and PCM 24kHz mono audio output over
an ``aws_sdk_bedrock_runtime`` bidirectional stream. Text-only
``ask()``/``ask_stream()`` calls delegate to an internally-managed
:class:`~parrot.clients.bedrock.BedrockConverseClient` (lazily
constructed) rather than reimplementing text completion here.

Connections are limited to ~8 minutes by the Nova Sonic service;
:meth:`stream_voice` proactively yields a ``reconnect_required`` signal
frame and closes the stream shortly before the limit so callers can
open a new session and replay recent context.

## Methods

- `async def get_client(self) -> Any` — Build the Nova Sonic bidirectional-stream SDK client.
- `async def stream_voice(self, audio_iterator: AsyncIterator[bytes], system_prompt: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]` — Stream bidirectional voice interaction via Nova Sonic.
- `async def ask(self, prompt: str, **kwargs) -> AIMessage` — Text-only fallback — delegates to an internal
- `async def ask_stream(self, prompt: str, **kwargs) -> AsyncIterator[Union[str, AIMessage]]` — Text-only streaming fallback — delegates to the internal
- `async def invoke(self, prompt: str, **kwargs)` — Text-only lightweight fallback — delegates to the internal
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any])` — Not supported: NovaSonicClient has no suspend/resume concept for
