---
type: Wiki Entity
title: VoiceMode
id: class:parrot_formdesigner.audio.models.VoiceMode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: How a question participates in the audio form flow.
---

# VoiceMode

Defined in [`parrot_formdesigner.audio.models`](../summaries/mod:parrot_formdesigner.audio.models.md).

```python
class VoiceMode(str, Enum)
```

How a question participates in the audio form flow.

Introduced by FEAT-236 (Audio Renderer Form) to replace the prior
"silently drop non-voiceable fields" behavior with an explicit
voice-capability taxonomy so that no required field is ever lost.

Members:
    VOICE: Narrate the question and accept a spoken or typed answer.
    PROMPT_SELECT: Narrate the question; the answer comes from a UI
        selection (radio/selector), not free speech.
    VISUAL_FALLBACK: Too complex to voice; render a single-field
        visual fallback inline to complete the answer.
