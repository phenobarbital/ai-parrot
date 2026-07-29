---
type: Wiki Overview
title: 'TASK-1223: OpenAI client cache translator'
id: doc:sdd-tasks-completed-task-1223-openai-client-cache-translator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the OpenAI-specific cache translator (spec Module 7,
  §3).
relates_to:
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.clients.gpt
  rel: mentions
---

# TASK-1223: OpenAI client cache translator

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1221
**Assigned-to**: unassigned

---

## Context

This task implements the OpenAI-specific cache translator (spec Module 7, §3).
OpenAI caches prefixes ≥1024 tokens automatically — no API shape change is
needed. The translator is a pass-through that emits
`PromptCacheAppliedEvent` when segments are present and the concatenated text
exceeds `_min_cache_tokens`.

---

## Scope

- Override `_apply_cache_hints()` in `OpenAIClient`.
- Set `_min_cache_tokens = 1024` on `OpenAIClient`.
- The override concatenates segments back into a single string for the
  `system` message (OpenAI uses messages-array format, not a top-level `system`
  field like Anthropic). No payload shape change.
- Emit `PromptCacheAppliedEvent` when caching is active (TASK-1225 creates the
  event class — use a conditional import or emit only if the event class exists).
- Write unit tests.

**NOT in scope**: Claude translator (TASK-1222), Gemini translator (TASK-1224).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Override `_apply_cache_hints()`, set `_min_cache_tokens` |
| `packages/ai-parrot/tests/test_prompt_caching_openai.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # base.py:242
from parrot.bots.prompts.segments import CacheableSegment  # TASK-1217
```

### Existing Signatures to Use
```python
# parrot/clients/gpt.py
class OpenAIClient(AbstractClient):   # line 95

# parrot/clients/base.py (TASK-1221)
class AbstractClient:
    _min_cache_tokens: int = 0
    def _apply_cache_hints(self, payload, segments) -> Dict: ...
```

### Does NOT Exist
- ~~`OpenAIClient._apply_cache_hints()`~~ — does not exist; this task creates it
- ~~`OpenAIClient._min_cache_tokens`~~ — does not exist; this task sets it
- ~~`OpenAIClient.prompt_cache_key`~~ — no such attribute

---

## Implementation Notes

### Pattern to Follow

OpenAI's automatic prefix caching requires no API changes. The translator
simply reconstructs a string from the segments:

```python
_min_cache_tokens: int = 1024

def _apply_cache_hints(self, payload, segments):
    if not segments:
        return payload
    # OpenAI caches prefixes automatically — reconstruct string
    combined = "\n\n".join(s.text for s in segments)
    payload["system_prompt"] = combined
    return payload
```

### Key Constraints
- OpenAI prefix caching is automatic for prefixes ≥1024 tokens. No explicit
  API parameter is needed.
- The payload shape must be identical to today's string-based path.
- The `_min_cache_tokens = 1024` is informational — it signals to the
  AbstractBot that caching might be effective above this threshold.

### References in Codebase
- `parrot/clients/gpt.py` — target file
- `parrot/clients/base.py` — base `_apply_cache_hints()` (TASK-1221)

---

## Acceptance Criteria

- [ ] `OpenAIClient._min_cache_tokens == 1024`
- [ ] `_apply_cache_hints()` returns payload with string system prompt
- [ ] Payload shape is identical to today's string-based path
- [ ] String `system_prompt` still works unchanged
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_prompt_caching_openai.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/gpt.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_prompt_caching_openai.py
import pytest
from parrot.bots.prompts.segments import CacheableSegment


class TestOpenAICacheTranslator:
    def test_min_cache_tokens(self):
        from parrot.clients.gpt import OpenAIClient
        assert OpenAIClient._min_cache_tokens == 1024

    def test_segments_produce_string(self):
        segments = [
            CacheableSegment(text="identity text", cacheable=True),
            CacheableSegment(text="user data", cacheable=False),
        ]
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        payload = {"system_prompt": "old"}
        result = client._apply_cache_hints(payload, segments)
        assert isinstance(result.get("system_prompt", ""), str)

    def test_empty_segments_noop(self):
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        payload = {"system_prompt": "original"}
        result = client._apply_cache_hints(payload, [])
        assert result["system_prompt"] == "original"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1221 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `OpenAIClient` is at line 95 of `gpt.py`
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1223-openai-client-cache-translator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
