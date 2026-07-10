---
id: F011
slug: voice-architecture
query: Deep dive into voice/audio integration patterns
type: read
---

## Finding: Voice/Audio Architecture

### GeminiLiveClient (`parrot/clients/live.py`)
Only bidirectional voice-streaming client today. Key method: `stream_voice(audio_iterator, ...)`.
Pattern: sender task reads from AsyncIterator[bytes] PCM 16kHz, receiver iterates session responses.
Yields `LiveVoiceResponse` objects (text, audio_data bytes, is_complete, is_interrupted, tool_calls, usage).

### VoiceBot (`parrot/bots/voice.py`)
Wraps GeminiLiveClient. `_resolve_llm_config()` hardcodes GeminiLiveClient.
For Nova Sonic: either make VoiceBot provider-aware or create NovaSonicVoiceBot subclass.

### VoiceChatHandler (`parrot/voice/handler.py`)
aiohttp WebSocket handler. Two modes: "streaming" (real-time bidirectional) and "buffered" (PTT).
Protocol: audio_data/audio_chunk in, response_chunk/response_complete/transcription out.
Iterates `LiveVoiceResponse` from bot.ask_stream() — Nova Sonic must return compatible shape.

### Voice models (`parrot/voice/models.py`)
- VoiceProvider enum: GOOGLE_LIVE, OPENAI_REALTIME, WHISPER_TTS — needs BEDROCK_NOVA_SONIC
- AudioFormat enum: PCM_16K (input), PCM_24K (output), WAV, MP3, OGG_OPUS, WEBM_OPUS
- SessionState enum: lifecycle states

### Audio format constants
- Input: 16kHz 16-bit PCM mono (same as Nova Sonic requirement)
- Output: 24kHz 16-bit PCM mono (Nova Sonic configurable: 8k/16k/24kHz)

### LiveAvatar integration
- AvatarTurnSpeaker: buffers text, segments into sentences, synthesizes to PCM, pushes to avatar WS
- VoiceAvatarSession: drives avatar from Gemini Live 24kHz PCM stream directly
- RoomAudioPublisher: LiveKit room audio track publisher

### STT/TTS subsystem
- AbstractTranscriberBackend: file-based STT (FasterWhisper, OpenAIWhisper, Moonshine)
- AbstractTTSBackend: one-shot TTS (GoogleTTS, SupertonicTTS)
- Both file-based (not streaming) — Nova Sonic bypasses these (native bidirectional audio)

### Patterns for NovaSonicClient:
1. Follow GeminiLiveClient's `stream_voice()` pattern with sender/receiver tasks
2. Yield LiveVoiceResponse (or compatible) for VoiceChatHandler compatibility
3. Add BEDROCK_NOVA_SONIC to VoiceProvider enum
4. Use audio queue + None sentinel pattern for turn management
5. Handle barge-in natively (Nova Sonic supports it)
6. Implement tool_use mid-conversation via contentStart(TOOL)/toolResult/contentEnd
7. Apply ApplyGuardrail on textOutput/ASR transcriptions for PII
8. Handle 8-min connection limit with reconnect + history replay
