---
type: Wiki Summary
title: parrot.integrations.matrix.crew.session
id: mod:parrot.integrations.matrix.crew.session
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Collaborative session orchestrator for Matrix multi-agent investigation.
relates_to:
- concept: class:parrot.integrations.matrix.crew.session.MatrixCollaborativeSession
  rel: defines
- concept: mod:parrot.integrations.matrix.appservice
  rel: references
- concept: mod:parrot.integrations.matrix.crew.config
  rel: references
- concept: mod:parrot.integrations.matrix.crew.crew_wrapper
  rel: references
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: references
- concept: mod:parrot.integrations.matrix.crew.registry
  rel: references
- concept: mod:parrot.integrations.matrix.crew.session_models
  rel: references
- concept: mod:parrot.manager
  rel: references
---

# `parrot.integrations.matrix.crew.session`

Collaborative session orchestrator for Matrix multi-agent investigation.

``MatrixCollaborativeSession`` manages the full lifecycle of a phased
collaborative investigation triggered by ``!investigate`` in a Matrix room:

1. **INVESTIGATING** — All registered agents investigate the question in parallel.
2. **CROSS_POLLINATING** (1-N configurable rounds) — Agents see each other's
   results injected as enriched context and refine their analysis.
3. **SYNTHESIZING** — A dedicated summarizer agent (or raw results fallback)
   produces the final answer.
4. **COMPLETED** (or **FAILED** on error) — Session archived, transport
   returns to normal routing.

## Classes

- **`MatrixCollaborativeSession`** — Stateful session managing one collaborative investigation in a Matrix room.
