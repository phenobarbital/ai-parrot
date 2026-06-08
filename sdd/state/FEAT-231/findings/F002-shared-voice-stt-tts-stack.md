---
id: F002
query_id: Q002
type: grep
intent: Find existing TTS/STT clients and providers to reuse instead of building from scratch
executed_at: 2026-06-08T23:33:00Z
depth: 0
---

# F002 — A shared, decoupled STT+TTS stack already exists in `parrot.voice`

## Summary

There is a dedicated `parrot.voice` package (shipped from ai-parrot-integrations)
with **both** halves already built and symmetric:
- **STT**: `parrot.voice.transcriber` — `VoiceTranscriber`,
  `AbstractTranscriberBackend`, `FasterWhisperBackend` (FEAT-039).
- **TTS**: `parrot.voice.tts` — `VoiceSynthesizer`, `AbstractTTSBackend`,
  `GoogleTTSBackend` (FEAT-213).

This means STT-in and TTS-out are solved primitives; the requested feature is a
**wiring + transport** task, plus adding one new TTS backend (Supertonic).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/voice/__init__.py`
  lines: 1-16
  excerpt: |
    Submodules:
    - ``parrot.voice.transcriber`` — STT backends + VoiceTranscriber
    - ``parrot.voice.tts`` — TTS backends + VoiceSynthesizer

- path: `packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py`
  symbol: `VoiceTranscriber` (`transcribe_url`, `transcribe`)

- path: `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py`
  symbol: `VoiceSynthesizer`

- path: `packages/ai-parrot/src/parrot/clients/google/generation.py`
  lines: 411
  symbol: `GoogleGenAIClient.generate_speech`
  excerpt: |
    # Existing concrete TTS producer reused by GoogleTTSBackend.

## Notes

`parrot.voice` lives in the **integrations** distribution, not core. A generic
AgentTalk web endpoint that imports it creates a core→integrations dependency to
account for (see synthesis constraints).
