---
type: Concept
title: synthesize_with_fallback()
id: func:parrot_formdesigner.renderers.audio.synthesize_with_fallback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Synthesize ``text`` to audio bytes, SuperTonic→Google→text-only.
---

# synthesize_with_fallback

```python
async def synthesize_with_fallback(text: str, *, config: AudioSessionConfig | None=None, language: str | None=None) -> bytes | None
```

Synthesize ``text`` to audio bytes, SuperTonic→Google→text-only.

The single reusable place for the FEAT-236 graceful-degradation contract
(shared by the renderer and the WebSocket handler). Tries the preferred
backend first (default SuperTonic), then Google. Any
``ImportError``/``ValueError``/``RuntimeError`` raised by a backend (missing
extra, unconfigured weights, no ``inference_fn``) is caught and the next
backend is tried. Returns ``None`` when no backend is usable — the caller
delivers the question text-only. NEVER raises for a missing/misconfigured
backend (FEAT-231 contract).

Args:
    text: The text to synthesize.
    config: Optional session config (preferred backend, voice, mime).
    language: Optional BCP 47 language hint for the backend.

Returns:
    Raw audio bytes, or ``None`` for a text-only fallback.
