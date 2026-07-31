---
type: Wiki Overview
title: 'TASK-009: Frontend LiveKit viewer (Svelte 5) (M8)'
id: doc:sdd-tasks-completed-task-009-frontend-livekit-viewer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 8** (spec §3): embed a `livekit-client` viewer in the'
---

# TASK-009: Frontend LiveKit viewer (Svelte 5) (M8)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-007
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** (spec §3): embed a `livekit-client` viewer in the
AgentChat frontend so the browser joins the same room (with the `client_token`
returned by TASK-007) and renders the avatar `<video>`/`<audio>`. Opt-in aware;
shares the AgentChat `session_id`. Structured outputs keep rendering as today.
Capability: `avatar-viewer-frontend`.

---

## ⚠️ Cross-Repo Notice

**This module lives in the AgentChat frontend (separate Svelte 5 repo/package),
NOT in this Python monorepo.** It CANNOT be implemented inside the
`feat-242-...` Python worktree. The SDD worker running in the Python repo MUST
NOT create files here and should mark this task `done-with-issues` (reason:
"frontend lives in the AgentChat repo — tracked here for feature completeness,
implemented in that repo") unless the frontend repo is explicitly mounted into
the worktree. This task exists to keep the feature's acceptance criteria
traceable and to define the contract the frontend must satisfy.

---

## Scope (in the AgentChat frontend repo)

- Add a LiveKit viewer component using `livekit-client` (JS) that:
  - Joins the room using `{ livekit_url, client_token }` from the TASK-007 start
    endpoint, keyed by the shared `session_id`.
  - Renders the avatar's video + audio tracks.
  - Is opt-in aware: hidden / not initialized when the tenant has avatar mode off.
- Structured outputs (charts/data/canvas) continue to render via the existing
  AgentChat WS — do NOT route them through LiveKit.

**NOT in scope**: backend endpoint (TASK-007), token minting (TASK-004), any
Python changes.

---

## Codebase Contract (Anti-Hallucination)

### Backend contract this frontend consumes (from TASK-007)
```jsonc
// POST /api/v1/agents/avatar/<agent_id>/start  → response
{
  "livekit_url": "wss://<project>.livekit.cloud",
  "client_token": "<viewer JWT>",   // subscribe-only
  "session_id": "<shared AgentChat session id>"
  // NOTE: agent_token / ws_url are NEVER present — do not expect them
}
```

### Does NOT Exist (do NOT reference)
- ~~an agent token in the client response~~ — the viewer receives `client_token` only.
- ~~LiveKit handling of structured outputs~~ — those stay on the existing AgentChat WS.

### External Dependency
| Package | Version | Reason |
|---|---|---|
| `livekit-client` (JS) | pin at impl | Browser viewer joins the LiveKit Cloud room |

---

## Acceptance Criteria

- [ ] Viewer joins the room with `client_token` and renders avatar `<video>`/`<audio>`
- [ ] Viewer is opt-in aware (absent for disabled tenants)
- [ ] Shares the AgentChat `session_id`; structured outputs still render via the existing WS
- [ ] Never references an agent token

> NOTE for the Python-repo SDD worker: if you cannot reach the frontend repo,
> mark this `done-with-issues` per the Cross-Repo Notice above rather than
> creating frontend files in the Python worktree.

---

## Agent Instructions

1. Read spec §3 Module 8 and the TASK-007 response contract.
2. If the AgentChat frontend repo is NOT available in this worktree, STOP and mark
   `done-with-issues` (coordinate with Jesús). Do NOT scaffold Svelte files in the
   Python monorepo.
3. Otherwise implement the viewer component in the frontend repo per scope.
4. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Status**: done-with-issues
**Notes**: The AgentChat Svelte frontend repo is NOT present in this Python monorepo worktree.
Per the task's own Agent Instructions (step 2): "If the AgentChat frontend repo is NOT
available in this worktree, STOP and mark done-with-issues (coordinate with Jesus). Do NOT
scaffold Svelte/JS files in the Python monorepo." This task is tracked here for completeness;
the LiveKit viewer Svelte component must be implemented in the AgentChat repo. Coordinate
with Jesus to implement TASK-009 there using the response contract from TASK-007:
``{ livekit_url, client_token, session_id }`` returned by
``POST /api/v1/agents/avatar/{agent_id}/start``.
**Deviations from spec**: No code produced. Frontend implementation deferred to AgentChat repo.
