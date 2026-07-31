---
type: Wiki Entity
title: UnicodeProcessor
id: class:parrot.voice.tts.supertonic_inference.UnicodeProcessor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Codepoint-based text tokeniser for Supertonic.
---

# UnicodeProcessor

Defined in [`parrot.voice.tts.supertonic_inference`](../summaries/mod:parrot.voice.tts.supertonic_inference.md).

```python
class UnicodeProcessor
```

Codepoint-based text tokeniser for Supertonic.

Normalises text, strips emojis, applies a small punctuation rewrite, wraps
it in ``<lang>…</lang>`` markers, then maps each character's Unicode
codepoint to a token id via ``unicode_indexer.json`` (a list indexed by
codepoint, or a ``{codepoint: id}`` dict).
