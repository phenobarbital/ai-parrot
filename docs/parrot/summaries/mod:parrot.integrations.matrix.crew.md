---
type: Wiki Summary
title: parrot.integrations.matrix.crew
id: mod:parrot.integrations.matrix.crew
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix multi-agent crew integration package.
relates_to:
- concept: mod:parrot.integrations.matrix
  rel: references
---

# `parrot.integrations.matrix.crew`

Matrix multi-agent crew integration package.

Provides all components needed to run a crew of AI agents on a Matrix
homeserver via the Application Service protocol.

Public API::

    from parrot.integrations.matrix.crew import (
        MatrixCrewConfig,
        MatrixCrewAgentEntry,
        MatrixCrewRegistry,
        MatrixAgentCard,
        MatrixCoordinator,
        MatrixCrewAgentWrapper,
        MatrixCrewTransport,
        parse_mention,
        format_reply,
        build_pill,
    )
