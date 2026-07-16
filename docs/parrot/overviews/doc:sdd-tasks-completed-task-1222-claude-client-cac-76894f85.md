---
type: Wiki Overview
title: 'TASK-1222: ClaudeClient (AnthropicClient) cache translator'
id: doc:sdd-tasks-completed-task-1222-claude-client-cache-translator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the Anthropic-specific cache translator (spec Module
  6, §3).
relates_to:
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.clients.claude
  rel: mentions
---

# TASK-1222: ClaudeClient (AnthropicClient) cache translator

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1221
**Assigned-to**: unassigned

---

## Context

This task implements the Anthropic-specific cache translator (spec Module 6, §3).
Anthropic requires the `system` field to be a list of content blocks (not a
string) to attach `cache_control`. There is a hard limit of 4 `cache_control`
blocks per request. The translator converts cacheable segments into this
list-of-blocks form.

---

## Scope

- Override `_apply_cache_hints()` in `AnthropicClient` (class name in codebase
  is `AnthropicClient`, file is `claude.py`).
- Set `_min_cache_tokens = 1024` on `AnthropicClient`.
- When segments are present: convert `payload["system"]` from a string to a
  list of `{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}`
  blocks for cacheable segments, plain `{"type": "text", "text": ...}` for non-cacheable.
- Aggregate cacheable segments into ≤4 blocks (Anthropic limit). If more
  cacheable segments exist, merge excess into the last cacheable block.
- When no segments (string system_prompt): produce today's payload exactly.
- Handle the 5 `payload["system"]` assignment sites (lines 193, 581, 982, 984, 986).
- Write unit tests.

**NOT in scope**: OpenAI translator (TASK-1223), Gemini translator (TASK-1224),
lifecycle events (TASK-1225).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | Override `_apply_cache_hints()`, set `_min_cache_tokens`, update system prompt handling |
| `packages/ai-parrot/tests/test_prompt_caching_claude.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # base.py:242
from parrot.bots.prompts.segments import CacheableSegment  # TASK-1217
```

### Existing Signatures to Use
```python
# parrot/clients/claude.py
class AnthropicClient(AbstractClient):   # line 46

    # System prompt assignment sites:
    # line 193: payload["system"] = system_prompt       (ask() main)
    # line 581: payload["system"] = system_prompt       (ask_stream() main)
    # line 982: payload["system"] = f"{system_prompt}\n\n{structured_system_prompt}"
    # line 984: payload["system"] = structured_system_prompt
    # line 986: payload["system"] = system_prompt       (ask() structured output)

    async def ask(self, ...): ...          # line 95
    async def ask_stream(self, ...): ...   # line 492

# parrot/clients/base.py (TASK-1221 additions)
class AbstractClient:
    _min_cache_tokens: int = 0
    def _apply_cache_hints(self, payload, segments) -> Dict: ...
```

### Does NOT Exist
- ~~`AnthropicClient._apply_cache_hints()`~~ — does not exist; this task creates it
- ~~`AnthropicClient._min_cache_tokens`~~ — does not exist; this task sets it
- ~~`AnthropicClient._build_system_blocks()`~~ — no such method; create a private helper if needed
- ~~`parrot.clients.claude.cache_control`~~ — no such module/function

---

## Implementation Notes

### Pattern to Follow

Create a private helper method for translating segments to Anthropic blocks:
```python
def _segments_to_anthropic_blocks(
    self, segments: "List[CacheableSegment]"
) -> list:
    """Convert CacheableSegments to Anthropic system content blocks.
    
    Aggregates cacheable segments into ≤4 cache_control blocks.
    """
    MAX_CACHE_BLOCKS = 4
    blocks = []
    cacheable_count = 0
    for seg in segments:
        block = {"type": "text", "text": seg.text}
        if seg.cacheable and cacheable_count < MAX_CACHE_BLOCKS:
            block["cache_control"] = {"type": "ephemeral"}
            cacheable_count += 1
        blocks.append(block)
    return blocks
```

Override `_apply_cache_hints`:
```python
def _apply_cache_hints(self, payload, segments):
    if not segments:
        return payload
    payload["system"] = self._segments_to_anthropic_blocks(segments)
    return payload
```

At each `payload["system"] = system_prompt` site, add a check:
```python
if isinstance(system_prompt, list):
    payload = self._apply_cache_hints(payload, system_prompt)
else:
    payload["system"] = system_prompt
```

### Key Constraints
- Anthropic SDK accepts `system` as either a string or a list of content blocks.
  The list form is required for `cache_control`.
- Hard limit: **4 `cache_control` blocks per request.** v1 marks at most 1–2.
  If more cacheable segments exist, drop the `cache_control` on excess (log at debug).
- When `system_prompt` is a plain string, behavior MUST be identical to today.
- The structured output path (lines 982-986) combines `system_prompt` with
  `structured_system_prompt`. Handle the case where `system_prompt` is segments
  but `structured_system_prompt` is a string — append it as a non-cacheable block.

### References in Codebase
- `parrot/clients/claude.py` — target file
- `parrot/clients/base.py` — base `_apply_cache_hints()` (TASK-1221)

---

## Acceptance Criteria

- [ ] `AnthropicClient._min_cache_tokens == 1024`
- [ ] Cacheable segments produce `cache_control: {type: "ephemeral"}` blocks
- [ ] Non-cacheable segments produce plain text blocks (no `cache_control`)
- [ ] At most 4 blocks have `cache_control` — excess segments get plain blocks
- [ ] String `system_prompt` produces today's payload exactly (regression guard)
- [ ] Structured output path handles mixed segment + string input
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_prompt_caching_claude.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/claude.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_prompt_caching_claude.py
import pytest
from parrot.bots.prompts.segments import CacheableSegment


class TestAnthropicCacheTranslator:
    def test_string_system_prompt_unchanged(self):
        """String system_prompt produces identical payload to today."""
        # When system_prompt is a string, payload["system"] should be that string
        pass  # Implement with actual AnthropicClient instance or mock

    def test_segments_produce_blocks(self):
        segments = [
            CacheableSegment(text="identity", cacheable=True),
            CacheableSegment(text="user data", cacheable=False),
        ]
        # Expected: list of blocks, first with cache_control, second without
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        blocks = client._segments_to_anthropic_blocks(segments)
        assert len(blocks) == 2
        assert "cache_control" in blocks[0]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[1]

    def test_max_4_cache_control_blocks(self):
        segments = [CacheableSegment(text=f"s{i}", cacheable=True) for i in range(6)]
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        blocks = client._segments_to_anthropic_blocks(segments)
        cache_count = sum(1 for b in blocks if "cache_control" in b)
        assert cache_count <= 4

    def test_min_cache_tokens(self):
        from parrot.clients.claude import AnthropicClient
        assert AnthropicClient._min_cache_tokens == 1024
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1221 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the 5 `payload["system"]` sites still
   exist at the listed line numbers
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1222-claude-client-cache-translator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
