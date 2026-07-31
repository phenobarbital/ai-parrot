---
type: Wiki Summary
title: parrot.human.escalation_intent
id: mod:parrot.human.escalation_intent
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Escalation intent detector for HITL multi-tier escalation.
relates_to:
- concept: class:parrot.human.escalation_intent.RejectIntentDetector
  rel: defines
---

# `parrot.human.escalation_intent`

Escalation intent detector for HITL multi-tier escalation.

Detects when a user's free-text response is a request to be escalated
to a human operator (e.g. "I need a human", "pasame con un humano").

Strategy (§3 C5 of the FEAT-194 spec):
1. Regex match against a seed phrase list.
2. Optional LLM confirmation via Groq Haiku when regex is ambiguous and
   ``llm_client`` is provided (inline await, ``llm_timeout_seconds``
   default = 1.5 s; any failure → return False).

Pure helper module — no side effects, no global state.

FEAT-194 — TASK-1278

## Classes

- **`RejectIntentDetector`** — Detects escalation intent from free-text user responses.
