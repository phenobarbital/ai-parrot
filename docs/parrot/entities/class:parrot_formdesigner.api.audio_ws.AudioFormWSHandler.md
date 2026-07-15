---
type: Wiki Entity
title: AudioFormWSHandler
id: class:parrot_formdesigner.api.audio_ws.AudioFormWSHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: WebSocket handler for interactive audio form sessions.
---

# AudioFormWSHandler

Defined in [`parrot_formdesigner.api.audio_ws`](../summaries/mod:parrot_formdesigner.api.audio_ws.md).

```python
class AudioFormWSHandler
```

WebSocket handler for interactive audio form sessions.

Manages one stateful audio session per WebSocket connection:
- JWT authentication via Sec-WebSocket-Protocol header or first message.
- start_session: loads FormSchema, builds AudioFormManifest, sends Q1.
- answer_text: validates text answer, stores it, advances to next question.
- answer_audio: binary frame → temp file → STT transcription → validate.
- skip_question, go_back, repeat_question, end_session navigation.
- After last answer: submits form data, sends form_complete.

Args:
    registry: FormRegistry to look up forms by ID.
    synthesizer: VoiceSynthesizer for TTS question audio.
    transcriber: FasterWhisperBackend for STT transcription.
    validator: FormValidator for answer validation.
    token_validator: TokenValidator for JWT authentication.
    submission_storage: Optional storage backend for form submissions.
    auto_synthesize: When True and no explicit ``synthesizer`` is injected,
        the handler synthesizes TTS via the SuperTonic-first fallback helper
        (SuperTonic → Google → text-only). Defaults to False so callers that
        pass no synthesizer get a silent (text-only) session unless they
        opt in. Wired on by ``setup_form_api`` when audio is intended
        (FEAT-236 TASK-1542).

Example::

    handler = AudioFormWSHandler(
        registry=registry,
        synthesizer=synthesizer,
        transcriber=transcriber,
        validator=FormValidator(),
        token_validator=TokenValidator(secret_key=SECRET),
    )
    # Register route: app.router.add_get(
    #   "/api/v1/forms/{form_id}/audio/ws",
    #   handler.handle_websocket
    # )

## Methods

- `async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse` — Handle an incoming WebSocket connection for an audio form session.
