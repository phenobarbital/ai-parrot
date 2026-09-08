---
id: F004
query_id: Q001
type: read
intent: Comparar contratos y localizar brechas de paridad de voz
executed_at: 2026-09-07T05:33:34.494414+00:00
parent_id: null
depth: 1
---

# F004 — El consumidor WebSocket y el tee hacia LiveAvatar ya están implementados.

## Summary

_HandlerVoiceSession.build_frames convierte metadata.display_data en frames display_data. _relay entrega audio al navegador y al avatar, con interrupción y cierre de turno. VoiceAvatarSession.speak transmite PCM de 24 kHz sin remuestreo; Nova declara salida de 24 kHz. Se requiere validar el recorrido con Nova y herramientas reales sobre SDK simulado.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 437-458
  symbol: `_HandlerVoiceSession.build_frames`
  excerpt:

```python

            if resp.metadata.get("display_data"):
                frames.append(
                    {
                        "type": "display_data",
                        "data": resp.metadata["display_data"],
                    }
                )

```

- path: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
  lines: 511-545
  symbol: `_HandlerVoiceSession._relay`
  excerpt:

```python
        """Send build_frames()'s output, then run the LiveAvatar audio tee.

        The tee is async (awaits connection.avatar_session.speak()/
        interrupt()/finish_turn()) so it cannot live in the sync
        build_frames() — kept here, cooperating with the base class via
        super()._relay() rather than re-implementing frame sending.
        """
        await super()._relay(resp, turn_no)

```

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py`
  lines: 1-7
  symbol: `VoiceAvatarSession`
  excerpt:

```python
"""VoiceAvatarSession — drive a LiveAvatar mouth from a realtime PCM stream (FEAT-245).

Thin session-lifecycle wrapper that connects a realtime PCM source (e.g. Gemini
Live's 24 kHz output) to the LiveAvatar LITE "mouth" (``AvatarWebSocket``).
No TTS, no resampling — the caller supplies ready-to-send 24 kHz mono 16-bit PCM.

Lifecycle::
```

- path: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py`
  lines: 223-233
  symbol: `VoiceAvatarSession.speak`
  excerpt:

```python
    async def speak(self, pcm: bytes) -> None:
        """Push one PCM chunk into the avatar's mouth.

        The bytes are forwarded as-is to :meth:`AvatarWebSocket.send_audio_frame`
        — no resampling, no buffering.  Input must be 24 kHz mono 16-bit LE,
        which matches Gemini Live's output format exactly.

        Args:
```

- path: `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`
  lines: 303-305
  symbol: `NovaAudio`
  excerpt:

```python
    # PCM format constants (spec §2/§7).
    INPUT_SAMPLE_RATE_HZ: int = 16000
    OUTPUT_SAMPLE_RATE_HZ: int = 24000
```
