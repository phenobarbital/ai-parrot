---
type: Wiki Summary
title: parrot.models.conference
id: mod:parrot.models.conference
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Data models for multi-party conferencing (FEAT-223).
relates_to:
- concept: class:parrot.models.conference.ConferenceResult
  rel: defines
- concept: class:parrot.models.conference.ConferenceRound
  rel: defines
- concept: class:parrot.models.conference.PeerVote
  rel: defines
---

# `parrot.models.conference`

Data models for multi-party conferencing (FEAT-223).

These Pydantic v2 models are the typed contract for the OrchestratorAgent's
deterministic conferencing mode:

- :class:`PeerVote` — a single agent's structured vote after seeing the
  anonymized answers of its peers.
- :class:`ConferenceRound` — the state of one cross-pollination + vote round.
- :class:`ConferenceResult` — the aggregated outcome of a conference.

The ``label_to_agent`` mapping on :class:`ConferenceRound` is an internal
bookkeeping structure: it correlates anonymous labels (``A``/``B``/``C``...)
back to the agent that produced each answer. It MUST NEVER be serialized into
a prompt shown to an LLM, to avoid reintroducing authority bias.

## Classes

- **`PeerVote(BaseModel)`** — Structured vote of an agent after seeing the anonymous peer answers.
- **`ConferenceRound(BaseModel)`** — State of one cross-pollination + vote round.
- **`ConferenceResult(BaseModel)`** — Aggregated outcome of a multi-party conference.
