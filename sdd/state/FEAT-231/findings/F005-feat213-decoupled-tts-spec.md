---
id: F005
query_id: Q008
type: read
intent: Read FEAT-213 telegram-voice-reply-tts — closest TTS-reply prior art + provider choice
executed_at: 2026-06-08T23:36:00Z
depth: 0
---

# F005 — FEAT-213 established a decoupled TTS layer and explicitly deferred native voice↔voice

## Summary

FEAT-213 ("Telegram Voice Reply (TTS Output)", status: approved) built the
decoupled TTS layer this feature should reuse: `AbstractTTSBackend.synthesize(text)
-> bytes` + `VoiceSynthesizer` with lazy backend selection, default backend
reusing `GoogleGenAIClient.generate_speech`, and structure "ready for
elevenlabs/openai" backends. Critically, it records that **STT input already
works end-to-end** and **TTS generation already exists** — the only gap was
output wiring. It **explicitly postponed the native voice↔voice channel (Gemini
Live / VoiceBot)**, scoping itself to: voice in → transcribe → text agent
answers → synthesize → send back. That is exactly the shape of this request,
generalized from Telegram to a WebSocket/AgentTalk transport.

## Citations

- path: `sdd/specs/FEAT-213-telegram-voice-reply-tts.spec.md`
  lines: 20-66
  excerpt: |
    - Entrada (STT) ya hecha: VoiceTranscriber ...
    - Generación TTS ya existe: GoogleGenAIClient.generate_speech ...
    G1: Capa TTS desacoplada: AbstractTTSBackend.synthesize(text)->bytes + VoiceSynthesizer
    G2: Backend por defecto reutilizando la TTS ya existente; listo para elevenlabs/openai
    G5: Degradación elegante: si TTS falla, responder solo texto
    > el usuario pospuso el canal voz↔voz nativo (Gemini Live, VoiceBot).

## Notes

Direct architectural precedent. The Supertonic backend slots in as another
`AbstractTTSBackend` next to the reserved elevenlabs/openai slots.
