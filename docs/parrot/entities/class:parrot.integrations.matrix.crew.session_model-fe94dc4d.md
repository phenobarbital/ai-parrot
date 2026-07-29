---
type: Wiki Entity
title: CollaborativeSessionState
id: class:parrot.integrations.matrix.crew.session_models.CollaborativeSessionState
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Full state of a collaborative investigation session.
---

# CollaborativeSessionState

Defined in [`parrot.integrations.matrix.crew.session_models`](../summaries/mod:parrot.integrations.matrix.crew.session_models.md).

```python
class CollaborativeSessionState(BaseModel)
```

Full state of a collaborative investigation session.

Tracks all phase transitions, per-agent results across rounds, and
the final synthesized answer. Serializable for archiving.

Attributes:
    session_id: Unique session identifier (UUID).
    room_id: Matrix room where the session takes place.
    question: The original question from the ``!investigate`` command.
    phase: Current lifecycle phase.
    current_round: Current cross-pollination round (0 = investigation).
    max_rounds: Configured maximum cross-pollination rounds.
    agent_results: Per-agent results keyed by agent_name, list by round.
    started_at: When the session started (None if not yet started).
    completed_at: When the session ended (None if not yet ended).
    final_synthesis: Summarizer's final answer text (None until synthesized).
