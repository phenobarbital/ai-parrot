---
type: Concept
title: resolve_voice_client_class()
id: func:parrot.voice.handler.resolve_voice_client_class
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve the ``AbstractClient`` subclass for a given ``VoiceProvider``.
---

# resolve_voice_client_class

```python
def resolve_voice_client_class(provider: 'VoiceProvider')
```

Resolve the ``AbstractClient`` subclass for a given ``VoiceProvider``.

Recognizes ``VoiceProvider.NOVA_SONIC`` and returns
:class:`~parrot.clients.nova_sonic.NovaSonicClient` (lazily imported —
the Pre-Alpha ``aws_sdk_bedrock_runtime`` extra is optional). Every
other currently-declared provider resolves to
:class:`~parrot.clients.live.GeminiLiveClient`, the only fully-wired
voice client at this time (``OPENAI_REALTIME`` / ``WHISPER_TTS`` are
declared in the enum but not yet backed by dedicated client classes).

Args:
    provider: The ``VoiceProvider`` enum member to resolve.

Returns:
    The ``AbstractClient`` subclass to instantiate for *provider*.

Raises:
    ImportError: When ``NOVA_SONIC`` is requested but
        ``aws_sdk_bedrock_runtime`` (Pre-Alpha, Python >= 3.12 only) is
        not installed.
