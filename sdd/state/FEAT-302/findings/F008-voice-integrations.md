---
id: F008
slug: voice-integrations
query: List integrations directory, read voice-related files
type: read
---

## Finding: Existing Voice Integrations

**Path**: `packages/ai-parrot-integrations/src/parrot/integrations/`

Integration packages: a2a, liveavatar, matrix, mcp, msagentsdk, msteams, slack, telegram, whatsapp.

Voice-related:
- `liveavatar/`: voice_provider.py, voice_session.py, speaker.py, speakable.py, room_audio_publisher.py (LiveKit-based)
- `msteams/voice/`: backend.py, faster_whisper_backend.py, openai_backend.py, transcriber.py

No Nova Sonic or Bedrock voice integration exists. Nova Sonic would be a new integration
in `ai-parrot-integrations[voice]` or a new package, using the experimental SDK.

Nova Sonic requires: bidirectional HTTP/2, PCM 16kHz input / 24kHz output, base64 encoding,
the `aws_sdk_bedrock_runtime` SDK (Pre-Alpha v0.7.0, Python >= 3.12).
