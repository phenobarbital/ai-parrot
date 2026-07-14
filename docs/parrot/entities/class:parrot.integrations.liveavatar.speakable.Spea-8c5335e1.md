---
type: Wiki Entity
title: SpeakableFlattener
id: class:parrot.integrations.liveavatar.speakable.SpeakableFlattener
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Incremental markdown→speakable-text flattener with sentence segmentation.
---

# SpeakableFlattener

Defined in [`parrot.integrations.liveavatar.speakable`](../summaries/mod:parrot.integrations.liveavatar.speakable.md).

```python
class SpeakableFlattener
```

Incremental markdown→speakable-text flattener with sentence segmentation.

Maintains an internal buffer that accumulates across ``feed()`` calls.
A sentence is only emitted once terminal punctuation is detected.

Example::

    f = SpeakableFlattener()
    sentences = f.feed("Hello wor") + f.feed("ld. How are you?")
    # sentences == ["Hello world.", "How are you?"]
    rest = f.flush()   # any trailing content

Note:
    This class is NOT thread-safe.  Create one instance per conversation
    turn and discard it afterwards.

## Methods

- `def feed(self, chunk: str) -> List[str]` — Accumulate ``chunk`` and return any newly completed sentences.
- `def flush(self) -> List[str]` — Return all remaining buffered text as a final sentence.
