---
type: Wiki Summary
title: parrot.integrations.liveavatar.speakable
id: mod:parrot.integrations.liveavatar.speakable
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Speakable-text flattener and sentence segmenter (FEAT-242 Phase A — Module
  4).
relates_to:
- concept: class:parrot.integrations.liveavatar.speakable.SpeakableFlattener
  rel: defines
---

# `parrot.integrations.liveavatar.speakable`

Speakable-text flattener and sentence segmenter (FEAT-242 Phase A — Module 4).

Converts markdown chunks streamed from the agent into speakable plaintext and
segments them into complete sentences for per-sentence streaming TTS.

**Shared with Phase C (FEAT-243).**

No avatar or TTS imports — this is a pure text utility (stdlib only).

Flattening strips:
- Code fences (``` ... ```)
- Inline code (` ... `)
- Tables (| col | ... |)
- Markdown headings (#, ##, …)
- Emphasis markers (*, **, _, __)
- List bullets (-, *, +, 1.)
- Links — keeps link text, drops URL (``[text](url)`` → ``text``)
- HTML tags (basic strip)
- Horizontal rules (---, ***, ___)

Sentence segmentation:
- Accumulates chunks across ``feed()`` calls.
- Emits a sentence only when terminal punctuation (.!?) is seen followed by
  whitespace or the end of the buffer.
- ``flush()`` emits any remaining buffered content as a final sentence.

## Classes

- **`SpeakableFlattener`** — Incremental markdown→speakable-text flattener with sentence segmentation.
