---
type: Wiki Summary
title: parrot.integrations.msteams.voice.models
id: mod:parrot.integrations.msteams.voice.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MS Teams Voice Data Models.
relates_to:
- concept: class:parrot.integrations.msteams.voice.models.AudioAttachment
  rel: defines
- concept: mod:parrot.voice.transcriber.models
  rel: references
---

# `parrot.integrations.msteams.voice.models`

MS Teams Voice Data Models.

MS Teams-specific audio attachment model. Shared transcription models
(VoiceTranscriberConfig, TranscriptionResult, TranscriberBackend) have been
moved to `parrot.voice.transcriber.models` and are re-exported here
for backward compatibility.

Part of FEAT-008: MS Teams Voice Note Support.

## Classes

- **`AudioAttachment(BaseModel)`** — Parsed audio attachment from MS Teams.
