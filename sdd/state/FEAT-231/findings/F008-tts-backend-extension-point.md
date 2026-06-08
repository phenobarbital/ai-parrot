---
id: F008
query_id: Q002
type: read
intent: Read the TTS backend/synthesizer/config to find the Supertonic extension point
executed_at: 2026-06-08T23:39:00Z
depth: 0
---

# F008 — Adding Supertonic = one new `AbstractTTSBackend` + one `Literal`/dispatch entry

## Summary

`VoiceSynthesizer._get_backend()` is an explicit if/elif dispatch on
`config.backend`; `"google"` is implemented, `"elevenlabs"`/`"openai"` raise
`ValueError` (reserved). `AbstractTTSBackend.synthesize(text, *, voice=None,
mime_format=...) -> SynthesisResult` is the single method to implement.
`TTSConfig.backend` is `Literal["google","elevenlabs","openai"]`. To add
Supertonic: extend the Literal to include `"supertonic"`, add
`tts/supertonic_backend.py::SupertonicTTSBackend(AbstractTTSBackend)`, and add
the dispatch branch. The sub-second claim fits here because Supertonic is an
on-device ONNX model — but it adds a heavyweight optional dependency + model
weights (extras-gated, mirroring how faster-whisper is optional for STT).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py`
  lines: 71-91
  symbol: `VoiceSynthesizer._get_backend`
  excerpt: |
    if backend_name == "google":
        from .google_backend import GoogleTTSBackend
        self._backend = GoogleTTSBackend(voice=self.config.voice)
    elif backend_name in ("elevenlabs", "openai"):
        raise ValueError(f"TTS backend not implemented: '{backend_name}'. ")

- path: `packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py`
  lines: 17-80
  symbol: `AbstractTTSBackend.synthesize`
  excerpt: |
    async def synthesize(self, text, *, voice=None, mime_format="audio/ogg") -> SynthesisResult: ...

- path: `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py`
  lines: 42-56
  symbol: `TTSConfig.backend`
  excerpt: |
    backend: Literal["google", "elevenlabs", "openai"] = Field(default="google", ...)
    mime_format: str = Field(default="audio/ogg", ...)

## Notes

Supertonic outputs raw PCM/WAV; browsers want WAV/Opus — `mime_format` already
parameterizes this. Sub-second latency is a backend property, not an API change.
