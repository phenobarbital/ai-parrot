---
type: Wiki Overview
title: 'TASK-005: Speakable-text flattener & sentence segmenter (M4)'
id: doc:sdd-tasks-completed-task-005-speakable-flattener-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 4** (spec §3): convert markdown chunks streamed from
  the'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
---

# TASK-005: Speakable-text flattener & sentence segmenter (M4)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** (spec §3): convert markdown chunks streamed from the
agent into speakable plaintext and segment them into complete sentences for
per-sentence streaming TTS. **Shared with Phase C (FEAT-243).** No avatar code is
referenced here — this is a pure, dependency-free text utility. Capability:
`speakable-text-flattener`.

---

## Scope

- Implement `SpeakableFlattener` in `speakable.py` with:
  - `feed(self, chunk: str) -> list[str]` — accumulate partial chunks, return
    any newly-completed sentences (incremental).
  - `flush(self) -> list[str]` — return any remaining buffered text as a final
    sentence.
- Flattening strips markdown that should not be read aloud: code fences,
  inline code, tables, links (keep link text, drop URL), headings markers,
  list bullets, emphasis markers (`*`, `_`, `#`, backticks, pipes).
- Sentence segmentation accumulates across chunk boundaries (a sentence split
  across two `feed()` calls is emitted once complete).

**NOT in scope**: TTS synthesis (TASK-006), avatar WS (TASK-003), any markdown→HTML
rendering. Pure text in / sentences out.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speakable.py` | CREATE | `SpeakableFlattener` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export `SpeakableFlattener` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_speakable.py` | CREATE | Flatten + segment tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
import re
from typing import List
```

### Existing Signatures to Use
```python
# Public interface to implement (spec §2):
class SpeakableFlattener:
    def feed(self, chunk: str) -> list[str]: ...   # incremental → complete sentences
    def flush(self) -> list[str]: ...
```

### Does NOT Exist (do NOT reference)
- ~~an existing markdown→speakable flattener~~ — confirmed NONE (spec §6). Only
  `_flatten_adf` (Atlassian ADF, `bots/github_reviewer.py`) and `strip_html_text`
  (`utils/jsonld_extractors.py`) exist — DIFFERENT purposes, do NOT import them.
- ~~a third-party markdown lib dependency~~ — keep it stdlib-only (`re`); do NOT add deps.

---

## Implementation Notes

### Pattern to Follow
```python
class SpeakableFlattener:
    _SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: str) -> List[str]:
        self._buffer += chunk
        cleaned = self._strip_markdown(self._buffer)
        # split off complete sentences, retain the trailing partial
        ...
```

### Key Constraints
- Stateful buffer survives across `feed()` calls.
- Be conservative: do NOT emit a sentence until terminal punctuation is seen
  (or `flush()` is called) so the TTS never speaks half a word.
- Strip but do not crash on malformed/partial markdown (e.g. an unclosed code fence).

### References in Codebase
- `packages/ai-parrot/src/parrot/utils/jsonld_extractors.py` (`strip_html_text`) — style reference only

---

## Acceptance Criteria

- [ ] `from parrot.integrations.liveavatar import SpeakableFlattener` works
- [ ] `test_flattener_strips_markdown`: code fences, tables, inline code, md syntax removed
- [ ] `test_sentence_segmenter_incremental`: a sentence split across two `feed()` calls is emitted once, complete
- [ ] `flush()` returns trailing buffered text without terminal punctuation
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_speakable.py -v`
- [ ] No lint errors: `ruff check .../liveavatar/speakable.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_speakable.py
import pytest
from parrot.integrations.liveavatar import SpeakableFlattener


def test_flattener_strips_markdown():
    f = SpeakableFlattener()
    out = f.feed("Here is code:\n```python\nprint(1)\n```\nDone.") + f.flush()
    text = " ".join(out)
    assert "print(1)" not in text
    assert "```" not in text
    assert "Done" in text


def test_sentence_segmenter_incremental():
    f = SpeakableFlattener()
    s1 = f.feed("Hello wor")
    s2 = f.feed("ld. How are you?")
    assert s1 == []
    assert "Hello world." in s2[0]
    assert any("How are you?" in s for s in s2)
```

---

## Agent Instructions

1. Read spec §3 Module 4 and §6 "Does NOT Exist" (P2).
2. Verify the Codebase Contract.
3. Implement `SpeakableFlattener` (stdlib-only).
4. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 15 unit tests pass, lint clean. Stdlib-only (re + typing).
``feed()`` accumulates across calls; sentences emitted on terminal punct
followed by whitespace or EOS. ``flush()`` drains any remainder. Code fences,
inline code, tables, headings, bold/italic, links, list bullets all stripped.
**Deviations from spec**: None. ``_RE_SENTENCE_SPLIT`` pattern used for
splitting (terminal punct + whitespace); EOS sentence detected separately
via trailing [.!?] check.
