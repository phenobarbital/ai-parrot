---
id: F001
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F001 — VoiceBot ya selecciona Nova y comparte el contrato de voz.

## Summary

VoiceBot selecciona nova-2-sonic para voz, entrega herramientas y ToolManager al cliente y consume stream_voice con VoiceStreamOptions. La propuesta amplía paridad existente, no implementa un proveedor nuevo.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 205-220
  symbol: `VoiceBot._resolve_llm_config`
  excerpt:

```python
        provider = getattr(self.voice_config, "provider", "google_live")

        if provider == "nova":
            from ..clients.amazon.nova import NovaClient

            # NovaClient's default model (nova-2-lite) is the TEXT model —
            # voice sessions need the Sonic model explicitly unless the
            # caller already configured one (spec §3 Module 6).
            # FEAT-416 (TASK-2151 code-review fix): the unified VoiceConfig
```

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 296-312
  symbol: `VoiceBot._create_llm_client`
  excerpt:

```python
        # Get all tools from tool_manager (includes dynamically registered tools)
        current_tools = []
        if self.tool_manager:
            current_tools = list(self.tool_manager.get_all_tools())
        use_tools = bool(current_tools or (self.tool_manager and self.tool_manager.tool_count() > 0))

        if config.provider == "nova":
            from ..clients.amazon.nova import NovaClient

```

- path: `packages/ai-parrot/src/parrot/bots/voice.py`
  lines: 600-616
  symbol: `VoiceBot.ask_stream`
  excerpt:

```python
            # exactly: explicit kwargs win over the VoiceConfig-derived
            # default.
            option_field_names = {f.name for f in fields(VoiceStreamOptions)}
            option_overrides = {k: v for k, v in kwargs.items() if k in option_field_names}
            options = self.voice_config.to_stream_options(**option_overrides)

            async with self._llm as client:
                async for response in client.stream_voice(
                    audio_iterator=audio_iterator,
```

- path: `packages/ai-parrot/src/parrot/clients/protocols.py`
  lines: 17-23
  symbol: `VoiceCapable`
  excerpt:

```python
class VoiceCapable(Protocol):
    """Protocol for clients that support bidirectional voice streaming.

    ``GeminiLiveClient`` and ``NovaClient`` (via the ``NovaAudio`` mixin)
    both implement ``stream_voice()`` with a compatible signature; this
    Protocol makes that compatibility explicit and type-checkable, and
    enables ``isinstance(client, VoiceCapable)`` runtime checks.
```

- path: `packages/ai-parrot/src/parrot/models/voice.py`
  lines: 175-183
  symbol: `VoiceStreamOptions`
  excerpt:

```python
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    voice: str | None = None
    language: str = "en-US"
    stt_only: bool = False
    parallel_tool_execution: bool = False
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True
```

- path: `packages/ai-parrot/src/parrot/models/voice.py`
  lines: 370-379
  symbol: `LiveVoiceResponse`
  excerpt:

```python
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_format: str = "audio/pcm;rate=24000"

    # State
    is_complete: bool = False
    is_interrupted: bool = False

    # Tool calls
```
