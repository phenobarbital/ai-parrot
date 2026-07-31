---
type: Wiki Overview
title: 'TASK-1278: RejectIntentDetector (regex first, Groq Haiku confirmation on doubt)'
id: doc:sdd-tasks-completed-task-1278-reject-intent-detector-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C5**. Detects escalation intent in free-text
relates_to:
- concept: mod:parrot.clients.groq
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.escalation_intent
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1278: RejectIntentDetector (regex first, Groq Haiku confirmation on doubt)

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C5**. Detects escalation intent in free-text
responses so users on channels without the reject button (e.g. CLI) can
still escalate by saying "pasame con un humano" or "I need a human".

Per brainstorm Round 3: **regex first, Groq Haiku confirmation only when
regex is ambiguous, inline await (NOT callback) with short timeout**.

---

## Scope

- Create `parrot/human/escalation_intent.py` with `RejectIntentDetector`.
- Ship initial seed regex phrase list:
  - Spanish (≥ 8): "pasame con un humano", "necesito un humano",
    "quiero hablar con un humano", "no entiendo, pasame", "escalar",
    "esto no me sirve", "hablar con soporte", "ayuda humana", "atención humana".
  - English (≥ 8): "I need a human", "talk to a human", "speak with an agent",
    "escalate this", "please escalate", "this isn't helping", "let me talk to support",
    "human help", "live agent please".
- `is_escalation_intent(text: str) -> bool`:
  1. Lowercase + normalise (`unicodedata.normalize`) `text`.
  2. If any regex matches with high confidence → return `True`.
  3. If no match and `text` is short (< 80 chars) and an `llm_client`
     is configured → call it via `asyncio.wait_for(..., timeout=llm_timeout_seconds)`
     asking for a structured `{is_escalate: bool}`. On timeout or any
     exception → return `False`.
  4. Else → return `False`.
- Pure helper module — no side effects, no global state.

**NOT in scope**: Wiring this into `HumanInteractionManager.receive_response`
(part of TASK-1277 follow-up or a small follow-up task — see note below).
Calling this from channels.

> **Wiring note**: `receive_response` already exists at manager.py:368-441.
> The recommended call site is *after* type validation and *before*
> response accumulation: if `is_escalation_intent(response.value)` for
> a free-text response, call `advance_chain(interaction_id, cause="reject")`
> and return without accumulating. This wiring is part of TASK-1278's
> acceptance criteria — implement it as a 5-line addition to
> `receive_response` and cover with a manager integration test.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/escalation_intent.py` | CREATE | `RejectIntentDetector` |
| `packages/ai-parrot/src/parrot/human/manager.py` | MODIFY | In `receive_response`, call detector for free-text responses on policy-bound interactions and route to `advance_chain` if escalation detected |
| `packages/ai-parrot/tests/human/test_reject_intent_detector.py` | CREATE | Regex hit/miss + LLM-fallback + timeout |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing:
from parrot.human.models import InteractionType                       # for type matching
# Optional:
from parrot.clients.groq import GroqClient   # verify exact import path before use
# Stdlib:
import asyncio
import re
import unicodedata
```

### Existing Signatures to Use

```python
# parrot/human/manager.py:368-441 — receive_response (current shape)
async def receive_response(self, response: HumanResponse) -> None:
    interaction = await self._load_interaction(response.interaction_id)
    if interaction is None: return
    if not self._validate_response(interaction, response): return
    # ... accumulate + consensus + resolve ...

# This task adds, right after _validate_response and before accumulation:
#   if (response.response_type == InteractionType.FREE_TEXT
#       and interaction.policy is not None
#       and self._reject_detector is not None
#       and await self._reject_detector.is_escalation_intent(response.value)):
#       await self.advance_chain(response.interaction_id, cause="reject")
#       return
```

### Does NOT Exist

- ~~`parrot.human.RejectIntentDetector`~~ — to be created.
- ~~`InteractionStatus.REJECTED`~~ — reject is a cause, not a status.
- ~~Hard import of `parrot.clients.groq` at module top~~ — must be
  lazy / optional; detector accepts `llm_client=None`.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/human/escalation_intent.py
import asyncio, re, unicodedata
from typing import Any, List, Optional


class RejectIntentDetector:
    _DEFAULT_REGEX_PHRASES_ES = [
        r"\bpasame con (un )?humano\b",
        r"\bnecesito (un )?humano\b",
        r"\bquiero hablar con (un )?humano\b",
        r"\bescalar\b",
        r"\batenci[oó]n humana\b",
        r"\bayuda humana\b",
        r"\bhablar con soporte\b",
        r"\besto no me (sirve|ayuda)\b",
    ]
    _DEFAULT_REGEX_PHRASES_EN = [
        r"\b(i )?need (a )?human\b",
        r"\btalk to (a )?human\b",
        r"\bspeak (with|to) (a )?(human|agent)\b",
        r"\b(please )?escalate( this)?\b",
        r"\blet me talk to support\b",
        r"\bhuman help\b",
        r"\blive agent( please)?\b",
        r"\bthis isn'?t helping\b",
    ]

    def __init__(self, regex_phrases=None, llm_client=None, llm_timeout_seconds=1.5):
        phrases = regex_phrases or (
            self._DEFAULT_REGEX_PHRASES_ES + self._DEFAULT_REGEX_PHRASES_EN
        )
        self._pattern = re.compile("|".join(phrases), re.IGNORECASE)
        self._llm = llm_client
        self._llm_timeout = llm_timeout_seconds

    async def is_escalation_intent(self, text: Any) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False
        norm = unicodedata.normalize("NFKD", text).lower()
        if self._pattern.search(norm):
            return True
        if self._llm is None or len(norm) > 80:
            return False
        try:
            return await asyncio.wait_for(self._llm_classify(norm), self._llm_timeout)
        except (asyncio.TimeoutError, Exception):
            return False

    async def _llm_classify(self, text: str) -> bool:
        # Implement using parrot.clients.groq or generic AbstractClient
        # with a one-shot structured prompt: {"is_escalate": bool}
        ...
```

### Key Constraints

- Detector is **pure**: same input → same output (modulo LLM
  non-determinism, which is what `wait_for` + exception swallow guards
  against).
- Default phrase lists must be overrideable via constructor for
  per-deployment tuning.
- NO module-level import of Groq client; lazy if needed.
- LLM timeout default = 1.5s (per spec open question proposal).
- Manager integration adds at most ~6 lines to `receive_response`; if
  `self._reject_detector` is `None` (default), behaviour is unchanged.

### References in Codebase

- Spec §3 C5; §7 "Groq Haiku optional dependency" gotcha.

---

## Acceptance Criteria

- [ ] `RejectIntentDetector().is_escalation_intent("pasame con un humano")` → `True`.
- [ ] `RejectIntentDetector().is_escalation_intent("necesito un humano por favor")` → `True`.
- [ ] `RejectIntentDetector().is_escalation_intent("I need a human")` → `True`.
- [ ] `RejectIntentDetector().is_escalation_intent("please escalate")` → `True`.
- [ ] `RejectIntentDetector().is_escalation_intent("thanks!")` → `False`.
- [ ] `RejectIntentDetector().is_escalation_intent("ok")` → `False`.
- [ ] `RejectIntentDetector().is_escalation_intent("")` → `False`.
- [ ] With mocked LLM client returning `{is_escalate: True}` on ambiguous
  short input, detector returns `True`.
- [ ] When LLM takes longer than `llm_timeout_seconds`, detector returns
  `False` without raising.
- [ ] When LLM raises any exception, detector returns `False`.
- [ ] Manager has a constructor kwarg `reject_detector: Optional[RejectIntentDetector] = None`.
- [ ] When detector is configured and a free-text response on a
  policy-bound interaction matches escalation intent, `receive_response`
  calls `advance_chain(cause="reject")` and does NOT accumulate the response.
- [ ] All tests pass:
  `pytest packages/ai-parrot/tests/human/test_reject_intent_detector.py packages/ai-parrot/tests/test_human_manager.py -v`.

---

## Test Specification

```python
# tests/human/test_reject_intent_detector.py
import pytest, asyncio
from unittest.mock import AsyncMock
from parrot.human.escalation_intent import RejectIntentDetector

class TestRegex:
    @pytest.mark.parametrize("phrase", ["pasame con un humano", "I need a human", "please escalate"])
    async def test_positive(self, phrase):
        d = RejectIntentDetector()
        assert await d.is_escalation_intent(phrase) is True

    @pytest.mark.parametrize("phrase", ["thanks", "ok", ""])
    async def test_negative(self, phrase):
        d = RejectIntentDetector()
        assert await d.is_escalation_intent(phrase) is False

class TestLlmFallback:
    async def test_llm_called_when_regex_misses(self):
        llm = AsyncMock(return_value=True)
        d = RejectIntentDetector(llm_client=llm)
        ...

    async def test_llm_timeout_returns_false(self):
        async def slow(*a, **k):
            await asyncio.sleep(5)
            return True
        d = RejectIntentDetector(llm_client=AsyncMock(side_effect=slow), llm_timeout_seconds=0.1)
        ...
```

---

## Agent Instructions

1. Read spec §3 C5 + §7 gotchas.
2. Implement detector + manager integration.
3. Test, lint.
4. Move to completed.

---

## Completion Note

Implemented 2026-05-21 by sdd-worker (FEAT-194).

- Created `parrot/human/escalation_intent.py` with `RejectIntentDetector`.
- 17 Spanish + English regex phrases; custom phrase list overrides defaults.
- NFKD normalisation + combining-mark stripping ensures accented text matches.
- LLM fallback (llm_client kwarg) uses asyncio.wait_for; timeout/exceptions → False.
- Manager `receive_response` wired: if policy-bound interaction + detector configured + FREE_TEXT response matches intent → advance_chain(cause="reject") + return.
- `HumanInteractionManager.__init__` accepts `reject_detector: Optional[RejectIntentDetector] = None`.
- 44 detector tests + 3 manager integration tests; all 93 tests pass.
