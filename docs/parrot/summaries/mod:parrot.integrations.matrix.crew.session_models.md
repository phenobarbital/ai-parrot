---
type: Wiki Summary
title: parrot.integrations.matrix.crew.session_models
id: mod:parrot.integrations.matrix.crew.session_models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Session state data models for collaborative multi-agent investigation sessions.
relates_to:
- concept: class:parrot.integrations.matrix.crew.session_models.AgentRoundResult
  rel: defines
- concept: class:parrot.integrations.matrix.crew.session_models.CollaborativeSessionState
  rel: defines
- concept: class:parrot.integrations.matrix.crew.session_models.SessionPhase
  rel: defines
---

# `parrot.integrations.matrix.crew.session_models`

Session state data models for collaborative multi-agent investigation sessions.

Pydantic v2 models for tracking the lifecycle, per-agent round results, and
overall state of a ``MatrixCollaborativeSession``. These are pure data models
with no Matrix I/O.

## Classes

- **`SessionPhase(str, Enum)`** — Phase in the collaborative session lifecycle.
- **`AgentRoundResult(BaseModel)`** — Result from one agent for one investigation round.
- **`CollaborativeSessionState(BaseModel)`** — Full state of a collaborative investigation session.
