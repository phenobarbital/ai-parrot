---
type: Wiki Entity
title: AudioAttachment
id: class:parrot.integrations.msteams.voice.models.AudioAttachment
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parsed audio attachment from MS Teams.
---

# AudioAttachment

Defined in [`parrot.integrations.msteams.voice.models`](../summaries/mod:parrot.integrations.msteams.voice.models.md).

```python
class AudioAttachment(BaseModel)
```

Parsed audio attachment from MS Teams.

Represents an audio file attachment that can be downloaded
and transcribed.

## Methods

- `def is_voice_note(self) -> bool` — Check if this is a supported audio format for voice notes.
- `def file_extension(self) -> str` — Get file extension from content type.
