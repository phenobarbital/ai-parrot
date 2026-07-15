---
type: Wiki Entity
title: AudioSessionConfig
id: class:parrot_formdesigner.audio.models.AudioSessionConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for an audio form session.
---

# AudioSessionConfig

Defined in [`parrot_formdesigner.audio.models`](../summaries/mod:parrot_formdesigner.audio.models.md).

```python
class AudioSessionConfig(BaseModel)
```

Configuration for an audio form session.

Attributes:
    form_id: Unique identifier of the form to render in audio mode.
    locale: BCP 47 language tag for TTS and label resolution.
    tts_backend: Preferred TTS backend. Defaults to "supertonic" (a
        sub-second ONNX backend) with a graceful fallback to "google"
        at synthesis time (FEAT-236).
    tts_voice: Optional voice name to pass to the TTS backend.
    tts_mime_format: MIME type of the TTS audio output. Defaults to
        "audio/wav" since the SuperTonic backend emits WAV.
    auto_advance: When True, advance to the next question immediately
        after a valid answer without waiting for explicit confirmation.
    enumerate_options: When True, read the option labels aloud for
        PROMPT_SELECT questions (e.g. "Choose one: red, green, blue").
    stt_confirm_threshold: STT confidence below which a speech answer
        triggers a read-back confirmation turn before being stored.
