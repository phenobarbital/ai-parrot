---
type: Wiki Overview
title: 'TASK-1224: Google/Gemini client cache translator'
id: doc:sdd-tasks-completed-task-1224-gemini-client-cache-translator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the Gemini-specific cache translator (spec Module 8,
  §3).
relates_to:
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.clients.google
  rel: mentions
- concept: mod:parrot.clients.google.client
  rel: mentions
---

# TASK-1224: Google/Gemini client cache translator

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1221
**Assigned-to**: unassigned

---

## Context

This task implements the Gemini-specific cache translator (spec Module 8, §3).
Gemini uses an explicit `CachedContent` resource created via a separate API call
before `generate_content`, with a minimum token threshold of ≥4096 tokens
(≥32k for some Flash variants). The translator must be conditional: estimate
token count and skip with a debug log when the threshold is not met.

This is the most complex translator due to Gemini's asymmetric caching model
(separate resource creation + reference) and the multiple call sites spread
across `client.py`, `analysis.py`, and `generation.py`.

---

## Scope

- Override `_apply_cache_hints()` in `GoogleGenAIClient`.
- Set `_min_cache_tokens = 4096` on `GoogleGenAIClient`.
- Implement conditional caching:
  - Estimate token count of cacheable segments.
  - If ≥ threshold: call `client.caches.create(...)` and add
    `cached_content=<name>` to the `generate_content` payload.
  - If < threshold: skip with debug log and emit
    `PromptCacheSkippedEvent(reason="below_threshold")` (event from TASK-1225,
    use conditional import).
- Create a shared helper that the call sites in `client.py`, `analysis.py`,
  and `generation.py` can use.
- Write unit tests.

**NOT in scope**: Claude translator (TASK-1222), OpenAI translator (TASK-1223).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Override `_apply_cache_hints()`, set `_min_cache_tokens`, shared helper |
| `packages/ai-parrot/src/parrot/clients/google/analysis.py` | MODIFY | Route through shared helper (if needed) |
| `packages/ai-parrot/src/parrot/clients/google/generation.py` | MODIFY | Route through shared helper (if needed) |
| `packages/ai-parrot/tests/test_prompt_caching_gemini.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # base.py:242
from parrot.bots.prompts.segments import CacheableSegment  # TASK-1217
```

### Existing Signatures to Use
```python
# parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):  # line 96

# Key call sites in google/ files:
# client.py: self.client.aio.models.generate_content  # lines 2273, 2890, 3453, 3713, 3739, 3770
# analysis.py: generate_content wrappers               # lines 96, 173, 411, 580, 764, 773, 958, 1018, 1076, 1145
# generation.py: generate_content partials              # lines 362, 506, 1592, 1798, 2104

# parrot/clients/base.py (TASK-1221)
class AbstractClient:
    _min_cache_tokens: int = 0
    def _apply_cache_hints(self, payload, segments) -> Dict: ...
```

### Does NOT Exist
- ~~`GoogleGenAIClient._apply_cache_hints()`~~ — does not exist; this task creates it
- ~~`GoogleGenAIClient._min_cache_tokens`~~ — does not exist; this task sets it
- ~~`GoogleGenAIClient._cached_content`~~ — no such attribute
- ~~`parrot.clients.google.cache`~~ — no such module
- ~~`google.genai.caching`~~ — verify the actual `google-genai` SDK caching API before implementing

---

## Implementation Notes

### Pattern to Follow

The Gemini caching API uses a separate `caches.create()` call:
```python
# Pseudocode — verify against actual google-genai SDK docs
cached = client.caches.create(
    model=model_name,
    contents=[...],  # the cacheable content
    display_name="parrot-prompt-cache",
    ttl="300s",
)
# Then reference in generate_content:
response = await client.aio.models.generate_content(
    model=model_name,
    cached_content=cached.name,
    contents=[user_prompt],
)
```

**IMPORTANT**: The google-genai SDK caching API may differ from the pseudocode
above. The implementing agent MUST verify the exact SDK interface by reading:
1. The installed `google-genai` package's caching module
2. Google's official documentation for `CachedContent`

### Token Estimation

Use a rough estimate of 4 chars ≈ 1 token for the threshold check. This is
intentionally conservative — it's better to skip caching than to fail with an
API error for being below the threshold.

```python
def _estimate_tokens(self, text: str) -> int:
    return len(text) // 4
```

### Key Constraints
- **MUST be conditional**: never raise because of provider limitations. If
  caching fails or threshold not met, log at debug and proceed without caching.
- `_min_cache_tokens = 4096` for the base `GoogleGenAIClient`. Flash variants
  may need 32768 — this can be handled via a model-specific lookup table.
- The `CachedContent` resource has a TTL. For v1, use a reasonable default
  (e.g., 5 minutes / 300s).
- Multiple call sites exist across 3 files. Consider a shared helper method
  on `GoogleGenAIClient` that all generate_content paths can call.

### References in Codebase
- `parrot/clients/google/client.py` — main client
- `parrot/clients/google/analysis.py` — analysis call sites
- `parrot/clients/google/generation.py` — generation call sites

---

## Acceptance Criteria

- [ ] `GoogleGenAIClient._min_cache_tokens == 4096`
- [ ] Above-threshold segments create a `CachedContent` resource
- [ ] Below-threshold segments skip with debug log, no error raised
- [ ] String `system_prompt` still works unchanged (regression guard)
- [ ] Cache creation errors are caught and logged, never raised
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_prompt_caching_gemini.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_prompt_caching_gemini.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from parrot.bots.prompts.segments import CacheableSegment


class TestGeminiCacheTranslator:
    def test_min_cache_tokens(self):
        from parrot.clients.google.client import GoogleGenAIClient
        assert GoogleGenAIClient._min_cache_tokens == 4096

    def test_below_threshold_skips(self):
        """Short segments skip caching without error."""
        segments = [CacheableSegment(text="short", cacheable=True)]
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        # Should not have cached_content in payload
        assert "cached_content" not in result

    def test_above_threshold_caches(self):
        """Long segments trigger CachedContent creation."""
        long_text = "x" * 20000  # ~5000 tokens, above 4096 threshold
        segments = [CacheableSegment(text=long_text, cacheable=True)]
        # Test with mocked SDK — verify caches.create is called
        pass  # Implement with proper mocks

    def test_empty_segments_noop(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        payload = {"system_prompt": "original"}
        result = client._apply_cache_hints(payload, [])
        assert result == payload
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1221 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read the google-genai SDK's caching API
   before implementing. Check `pip show google-genai` for the installed version.
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1224-gemini-client-cache-translator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
