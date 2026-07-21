---
type: Wiki Summary
title: parrot.handlers.threads
id: mod:parrot.handlers.threads
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST handler for thread management.
relates_to:
- concept: class:parrot.handlers.threads.ThreadDetailView
  rel: defines
- concept: class:parrot.handlers.threads.ThreadListView
  rel: defines
---

# `parrot.handlers.threads`

REST handler for thread management.

Provides endpoints for conversation thread CRUD operations with
DynamoDB backend support.  Uses ChatStorage (DynamoDB) for thread
and turn persistence, and ArtifactStore for cascade deletes.

FEAT-103: agent-artifact-persistency — Module 7.

Endpoints:
    GET    /api/v1/threads?agent_id=X           — list conversations (sidebar)
    POST   /api/v1/threads                      — create new thread
    GET    /api/v1/threads/{session_id}          — load thread turns (limit=10)
    PATCH  /api/v1/threads/{session_id}          — update metadata (title, pinned, tags)
    DELETE /api/v1/threads/{session_id}          — delete thread + cascade artifacts

## Classes

- **`ThreadListView(BaseView)`** — List and create conversation threads.
- **`ThreadDetailView(BaseView)`** — Detail operations on a single conversation thread.
