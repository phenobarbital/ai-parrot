# TASK-4837: Capture the per-turn rendered system prompt and pass it to OUTPUT guardrails

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4825, TASK-4834
**Assigned-to**: unassigned

---

## Context

Spec §2 item 6 + §3 Module 7 (design-research S5): leakage detection must compare
against the exact prompt the LLM saw this turn — never a re-render at OUTPUT time
(resolved user decision: per-turn rendered prompt, cached).

Task-time design decisions (verified in code, implement exactly):
1. **Request-local, not an instance attribute.** One bot instance serves concurrent
   requests; `self._last_rendered_system_prompt` would race between turns and could
   compare turn A's output against turn B's prompt. Use a module-level
   `ContextVar[str | None]`. `await`ed coroutines and async-generator bodies share the
   caller's context, so a value set during prompt creation is visible to the later
   `_run_output_pipeline` call in the same request.
2. **Capture at the call sites in `bots/base.py`, not inside `create_system_prompt`.**
   Four subclasses override `create_system_prompt` without guaranteed `super()` calls
   (`bots/agent.py:1496`, `bots/data.py:806`, `bots/database/agent.py:372`,
   `bots/voice.py:209`); capturing at the call site sees whatever the dispatch produced,
   *including* `system_prompt_addition`. Sites (verified):
   - `conversation`: before `self._debug_prompt_dump(` followed by `method="conversation",` (`base.py:468`)
   - `ask`: before `self._debug_prompt_dump(` followed by `method="ask",` (`base.py:1404`)
   - `ask_stream`: before `self._debug_prompt_dump(` followed by `method="ask_stream",` (`base.py:2061`)
   - `invoke` (no vector context): after the one-liner
     `system_prompt = await self.create_system_prompt(user_id=user_id, session_id=session_id, **kwargs)` (`base.py:778`)
   (`execute_llm_call` is not a complete funnel — streaming calls the client directly.)
3. **Zero overhead**: `_run_output_pipeline` adds `extras["system_prompt"]` only when a
   registered OUTPUT guardrail has `requires_system_prompt` (TASK-4825).
4. Prompt may be `List[CacheableSegment]` when prompt caching is on (`abstract.py:3730-3736`):
   flatten to `"".join(seg.text ...)`.

Depends on TASK-4834 only because both modify `bots/abstract.py` (serialize).

---

## Scope

- `abstract.py`: module-level `_RENDERED_SYSTEM_PROMPT` ContextVar; `_capture_rendered_prompt(prompt)`
  method; OUTPUT extras gated by `requires_system_prompt`.
- `base.py`: one capture call at each of the four sites.
- Tests.

**NOT in scope**: changing `create_system_prompt` or its overrides; INPUT ctx; streaming withholding.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | ContextVar, capture helper, OUTPUT extras |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | 4 capture calls |
| `packages/ai-parrot/tests/unit/test_guardrails_rendered_prompt.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from contextvars import ContextVar        # stdlib — NOT imported in bots/abstract.py today; add it
from parrot.bots.prompts.segments import CacheableSegment   # segments.py:19 (has .text, .cacheable)
# already in bots/abstract.py:
from .guardrails.streaming import StreamingGuardrail        # abstract.py:121 (import-block anchor)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage:   # :2758
    pipeline = self._guardrail_pipelines[GuardrailStage.OUTPUT]                         # :2781
    ctx = GuardrailContext(... extras={"chatbot_id": str(self.chatbot_id), "ai_message": response})  # :2785-2799
async def create_system_prompt(...) -> "Union[str, List]"                               # :3679 (do not modify)

# packages/ai-parrot/src/parrot/bots/base.py — call sites (verified counts):
#   '            self._debug_prompt_dump(' occurs 3x: :468 (method="conversation"), :1404 (method="ask"), :2061 (method="ask_stream")
#   '            system_prompt = await self.create_system_prompt(user_id=user_id, session_id=session_id, **kwargs)' 1x :778
# OUTPUT pipeline callers: base.py:1735 (ask), base.py:2273 (ask_stream), abstract.py:4326 (get_response)
```

### Does NOT Exist
- ~~`_RENDERED_SYSTEM_PROMPT`, `AbstractBot._capture_rendered_prompt`~~ — created here.
- ~~`self._last_rendered_system_prompt`~~ — rejected design (races); do not create it.
- ~~`extras["system_prompt"]` today~~ — only `chatbot_id` + `ai_message`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_rendered_prompt.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._run_output_pipeline",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.create_system_prompt"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the ContextVar + helper in `abstract.py` — *why*: request-local capture.
2. Gate and add `system_prompt` in `_run_output_pipeline` extras — *why*: zero overhead when unused.
3. Insert the four capture calls in `base.py` — *why*: every entrypoint, overrides included.
4. Tests, including two interleaved concurrent "turns" proving no cross-talk.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .guardrails.streaming import StreamingGuardrail' abstract.py)
# AFTER — insert below `from .guardrails.streaming import StreamingGuardrail` (verified: abstract.py:121)
from contextvars import ContextVar

#: FEAT-761 — the system prompt actually sent to the LLM for the CURRENT
#: request. Request-local on purpose: one bot instance serves concurrent
#: turns, so an instance attribute would compare one turn's output with
#: another turn's prompt. Set by `_capture_rendered_prompt` at the
#: `bots/base.py` call sites; read by `_run_output_pipeline`.
_RENDERED_SYSTEM_PROMPT: ContextVar[Optional[str]] = ContextVar("parrot_rendered_system_prompt", default=None)
```
```python
# occurrences: 1 (verified: grep -c '    async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage:' abstract.py)
# BEFORE — insert above that line (verified: abstract.py:2758)
    def _capture_rendered_prompt(self, prompt: Any) -> None:
        """Record this request's rendered system prompt for OUTPUT guardrails (FEAT-761).

        Accepts ``str`` or ``List[CacheableSegment]`` (prompt caching); stores
        a flat string in the request-local ContextVar. Never raises.
        """
        # FILL IN: str -> set; list -> "".join(getattr(s, "text", str(s)) for s in prompt); else str(prompt) if prompt else None
```
```python
# occurrences: 1 (verified: grep -c '            extras={"chatbot_id": str(self.chatbot_id), "ai_message": response},' abstract.py)
# REPLACE that line (verified: abstract.py:2798) with:
            extras=self._output_extras(response, pipeline),
# and add, next to _capture_rendered_prompt:
    def _output_extras(self, response: AIMessage, pipeline: GuardrailPipeline) -> Dict[str, Any]:
        """OUTPUT ctx extras; ``system_prompt`` only when a registered guardrail requires it."""
        extras: Dict[str, Any] = {"chatbot_id": str(self.chatbot_id), "ai_message": response}
        # FILL IN: if any(getattr(g, "requires_system_prompt", False) for g in pipeline.guardrails):
        #   extras["system_prompt"] = _RENDERED_SYSTEM_PROMPT.get()  — bounded by "zero overhead when unused"
        return extras
```
Keep the existing FEAT-398 comment block above the `extras=` line intact.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)
```python
# occurrences: 3 (verified: grep -c '            self._debug_prompt_dump(' base.py) — ambiguous, use 2-line context:
# BEFORE each of these 2-line anchors, insert `            self._capture_rendered_prompt(system_prompt)`:
#   `            self._debug_prompt_dump(` + next line `                method="conversation",`   (verified: base.py:468-469)
#   `            self._debug_prompt_dump(` + next line `                method="ask",`            (verified: base.py:1404-1405)
#   `            self._debug_prompt_dump(` + next line `                method="ask_stream",`     (verified: base.py:2061-2062)
```
```python
# occurrences: 1 (verified: grep -c '            system_prompt = await self.create_system_prompt(user_id=user_id, session_id=session_id, **kwargs)' base.py)
# AFTER — insert below that line (verified: base.py:778)
            self._capture_rendered_prompt(system_prompt)
```
**Why**: placed after `system_prompt_addition` is appended (the three multi-line sites
append it in the same statement), so the captured string is what the client receives.

### `packages/ai-parrot/tests/unit/test_guardrails_rendered_prompt.py` (CREATE)
```python
"""FEAT-761 TASK-4837 — rendered system prompt capture for OUTPUT guardrails."""
import asyncio

import pytest

from parrot.bots import abstract as abstract_mod
from parrot.bots.abstract import AbstractBot

# FILL IN: stub bot via AbstractBot.__new__ + minimal attrs; tests:
#  - _capture_rendered_prompt(str) / (list of CacheableSegment) / (None)
#  - _output_extras without a requires_system_prompt guardrail has NO "system_prompt" key
#  - with one -> extras["system_prompt"] equals the captured value
#  - two concurrent asyncio tasks capturing different prompts, then reading after an await, each see their own
#  - the four base.py sites: grep-style source assertion (inspect.getsource) that each capture call follows the render
```

### FILL IN checklist
- [ ] `_capture_rendered_prompt`
- [ ] `_output_extras` gate
- [ ] four base.py insertions
- [ ] tests incl. concurrency

---

## Acceptance Criteria

- [ ] OUTPUT ctx carries `system_prompt` only when a registered OUTPUT guardrail requires it.
- [ ] Captured value equals what the client received (incl. `system_prompt_addition`, flattened segments).
- [ ] Concurrent turns never see each other's prompt.
- [ ] No change to `create_system_prompt` or its overrides; existing output-guardrail tests green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_rendered_prompt.py -q`
- `pytest packages/ai-parrot/tests/integration/test_guardrails_output.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4825 and TASK-4834 are `done`; re-verify anchors (counts above).
3. Mark `in-progress`; implement; complete `# FILL IN:`. Never mutate `_llm_kwargs` in these methods.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4837 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: sonnet · Backend: native · Attempts: 1)
**Date**: 2026-10-27
**Notes**: Rendered-prompt ContextVar capture + _output_extras added; 7 tests; merge-tier validation green. Engine-reported lint residuals in abstract.py/base.py (E402/F841) are pre-existing style debt, left to /sdd-done. Closed via close_task.sh (no durable review-evidence artifact writable).

**Deviations from spec**: tests use a concrete _StubBot subclass (AbstractBot is abstract).
