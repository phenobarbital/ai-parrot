---
type: Wiki Entity
title: AudioSessionState
id: class:parrot_formdesigner.audio.models.AudioSessionState
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Server-side state for an active audio form session.
---

# AudioSessionState

Defined in [`parrot_formdesigner.audio.models`](../summaries/mod:parrot_formdesigner.audio.models.md).

```python
class AudioSessionState(BaseModel)
```

Server-side state for an active audio form session.

One instance is created per WebSocket connection. Not persisted by
default; use Redis if resumable sessions are needed (spec open question).

Attributes:
    session_id: Unique identifier for this session.
    form_id: The form being filled in this session.
    user_id: Authenticated user ID from JWT.
    current_index: Zero-based index of the current question.
    answers: Map of field_id → AudioAnswer for completed questions.
    manifest: The session manifest (set after start_session).
    completed: True when all required questions have been answered
        and the form has been submitted.
    config: The resolved AudioSessionConfig for this session (FEAT-236),
        set at start_session. None until the session starts.
    pending: A low-confidence speech answer awaiting a confirm/repeat
        turn (FEAT-236). None when no answer is pending confirmation.
