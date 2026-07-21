---
type: Wiki Summary
title: parrot.handlers.agents.sharing
id: mod:parrot.handlers.agents.sharing
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent sharing scaffold — deferred to a follow-up FEAT.
relates_to:
- concept: class:parrot.handlers.agents.sharing.AgentSharingHandler
  rel: defines
---

# `parrot.handlers.agents.sharing`

Agent sharing scaffold — deferred to a follow-up FEAT.

Design decision (FEAT-149 §8 Open Questions):
    Sharing will be implemented as a per-user permission list stored in the
    ``permissions`` JSONB column of ``navigator.users_bots``.  The exact
    scheme (read-only share links, per-user ACL, org-level visibility) is
    still being finalised and is intentionally out of scope for FEAT-149.

Intended interface (subject to change)::

    POST /api/v1/user_agents/{chatbot_id}/share
        {
          "target_user_id": 42,
          "permission": "read"  # or "write" | "none"
        }

    GET /api/v1/user_agents/{chatbot_id}/share
        → list of {user_id, permission, granted_at}

    DELETE /api/v1/user_agents/{chatbot_id}/share/{target_user_id}

References:
    - FEAT-149 spec §3 Module 9
    - FEAT-149 spec §8 Open Questions (sharing / multi-user)

TODO(FEAT-XXX): Implement agent sharing when the design is finalised.

## Classes

- **`AgentSharingHandler`** — Stub handler for ephemeral agent sharing.
