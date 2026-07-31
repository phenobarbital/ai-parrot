---
type: Concept
title: chunk_text()
id: func:parrot.voice.tts.supertonic_inference.chunk_text
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Split text into synthesis-sized chunks by paragraph then sentence.
---

# chunk_text

```python
def chunk_text(text: str, max_len: int=300) -> list[str]
```

Split text into synthesis-sized chunks by paragraph then sentence.

Long agent answers are split so each chunk stays within the model's
comfortable context; chunks are re-joined (with short silences) by the
caller.

Args:
    text: Input text.
    max_len: Maximum characters per chunk.

Returns:
    Ordered list of non-empty chunk strings (at least one).
