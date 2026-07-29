---
type: Wiki Overview
title: 'TASK-1220: AbstractBot prompt_caching kwarg + auto-injection'
id: doc:sdd-tasks-completed-task-1220-abstractbot-prompt-caching-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires the prompt caching plumbing into `AbstractBot` (spec Module
  4,
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.agent_context
  rel: mentions
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
---

# TASK-1220: AbstractBot prompt_caching kwarg + auto-injection

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1218, TASK-1219
**Assigned-to**: unassigned

---

## Context

This task wires the prompt caching plumbing into `AbstractBot` (spec Module 4,
§3). It adds the `prompt_caching: bool = False` kwarg, auto-injects
`AGENT_CONTEXT_LAYER` when the flag is on and a `PromptBuilder` is in use, and
threads segments through to the client at call time by calling
`build_segments()` instead of `build()`.

---

## Scope

- Add `prompt_caching: bool = False` kwarg to `AbstractBot.__init__()`.
- When `prompt_caching=True` and a `PromptBuilder` is in use:
  - Auto-inject `AGENT_CONTEXT_LAYER` into the builder.
  - Call `load_agent_context(self.name)` during `configure()` and put the
    result into the context dict as `agent_context_content`.
  - At call time (in the method that calls `self._prompt_builder.build()`),
    call `build_segments()` instead and pass the resulting segments as
    `system_prompt` to the client.
- When `prompt_caching=False` or no builder: zero behavior change. Existing
  `build()` path is untouched.
- Write unit tests.

**NOT in scope**: Client-side `_apply_cache_hints()` (TASK-1221–1224),
lifecycle events (TASK-1225), GitHubReviewer opt-in (TASK-1226).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add `prompt_caching` kwarg, auto-inject layer, thread segments |
| `packages/ai-parrot/tests/test_abstractbot_prompt_caching.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.builder import PromptBuilder  # builder.py:20
from parrot.bots.prompts.agent_context import load_agent_context, AGENT_CONTEXT_LAYER  # TASK-1219
from parrot.bots.prompts.segments import CacheableSegment  # TASK-1217
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py
class AbstractBot:
    _prompt_builder: Optional[PromptBuilder] = None  # line 186

    def __init__(
        self,
        name: str = 'Nav',                          # line 248-249
        system_prompt: str = None,                   # line 250
        llm: Union[...] = None,                      # line 251
        # ...
        prompt_builder: PromptBuilder = None,        # line 265
        prompt_preset: str = None,                   # line 266
        event_bus: Optional[Any] = None,             # line 267
        **kwargs                                     # line 268
    ):
        # ... (line 464-468)
        if prompt_builder is not None:
            self._prompt_builder = prompt_builder
        elif prompt_preset:
            from .prompts.presets import get_preset
            self._prompt_builder = get_preset(prompt_preset)

# PromptBuilder API (TASK-1217 + TASK-1218)
class PromptBuilder:
    def __init__(self, layers=None, *, prompt_caching: bool = False): ...
    def add(self, layer: PromptLayer) -> PromptBuilder: ...    # line 116
    def build(self, context: Dict[str, Any]) -> str: ...       # line 204
    def build_segments(self, context: Dict[str, Any]) -> List[CacheableSegment]: ...  # TASK-1218
    @property
    def is_configured(self) -> bool: ...                       # line 233
```

### Does NOT Exist
- ~~`AbstractBot.prompt_caching`~~ — no such attribute; this task adds it
- ~~`AbstractBot._prompt_caching`~~ — no such attribute; this task adds it
- ~~`AbstractBot._agent_context_content`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow

In `__init__`, after the existing builder setup (lines 464-468):
```python
self._prompt_caching: bool = kwargs.get('prompt_caching', False)
if self._prompt_caching and self._prompt_builder is not None:
    from .prompts.agent_context import AGENT_CONTEXT_LAYER
    self._prompt_builder.add(AGENT_CONTEXT_LAYER)
```

In the `configure()` method, when building the context dict for the builder:
```python
if self._prompt_caching:
    from .prompts.agent_context import load_agent_context
    agent_ctx = load_agent_context(self.name)
    if not agent_ctx:
        self.logger.info(
            "prompt_caching is on but no context file found for agent '%s'",
            self.name
        )
    context["agent_context_content"] = agent_ctx
```

In the call path (where `self._prompt_builder.build(ctx)` is called to produce
`system_prompt`), add a branch:
```python
if self._prompt_caching and self._prompt_builder:
    system_prompt = self._prompt_builder.build_segments(ctx)
else:
    system_prompt = self._prompt_builder.build(ctx) if self._prompt_builder else self._system_prompt
```

### Key Constraints
- `AbstractBot.__init__` uses `**kwargs` — extract `prompt_caching` via
  `kwargs.get('prompt_caching', False)` or add it as an explicit parameter.
  Using `kwargs.get` is safer to avoid breaking subclass signatures.
- When `prompt_caching=False` (default), behavior is identical to today.
- The `load_agent_context()` call is sync — safe to call inline since it's
  just a file read cached by lru_cache.
- Be careful to find ALL sites where the builder's `build()` is called and
  add the conditional branch. Search for `_prompt_builder.build(` in the file.

### References in Codebase
- `parrot/bots/abstract.py` — target file
- `parrot/bots/prompts/agent_context.py` — TASK-1219
- `parrot/bots/prompts/builder.py` — `build()` and `build_segments()`

---

## Acceptance Criteria

- [ ] `AbstractBot(prompt_caching=True)` creates successfully with a builder
- [ ] `AGENT_CONTEXT_LAYER` is auto-injected when `prompt_caching=True` + builder present
- [ ] `AGENT_CONTEXT_LAYER` is NOT injected when `prompt_caching=False`
- [ ] `load_agent_context()` is called during `configure()` when flag is on
- [ ] Missing context file logs at INFO level, does not raise
- [ ] When flag is on, `build_segments()` is called instead of `build()`
- [ ] When flag is off, `build()` is called (zero behavior change)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_abstractbot_prompt_caching.py -v`
- [ ] Existing bot tests still pass (no regression)

---

## Test Specification

```python
# packages/ai-parrot/tests/test_abstractbot_prompt_caching.py
import pytest
from unittest.mock import patch, MagicMock
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.segments import CacheableSegment


class TestAbstractBotPromptCaching:
    def test_flag_off_no_layer_injection(self):
        """When prompt_caching=False, no AGENT_CONTEXT_LAYER is injected."""
        builder = PromptBuilder.default()
        original_names = set(builder.layer_names)
        # Create bot with flag off — agent_context should NOT be in layers
        # (Test via direct builder inspection, not full bot init)
        assert "agent_context" not in original_names

    def test_flag_on_injects_layer(self):
        """When prompt_caching=True and builder is set, AGENT_CONTEXT_LAYER is added."""
        builder = PromptBuilder.default()
        from parrot.bots.prompts.agent_context import AGENT_CONTEXT_LAYER
        builder.add(AGENT_CONTEXT_LAYER)
        assert "agent_context" in builder.layer_names

    def test_segments_type(self):
        """build_segments returns List[CacheableSegment]."""
        builder = PromptBuilder.default()
        builder.configure({"name": "T", "role": "r", "goal": "", "backstory": "", "rationale": ""})
        segments = builder.build_segments({"knowledge_content": "", "user_context": "", "chat_history": ""})
        assert all(isinstance(s, CacheableSegment) for s in segments)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1218 and TASK-1219 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — search `abstract.py` for all sites where
   `_prompt_builder.build(` is called
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1220-abstractbot-prompt-caching-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
