---
type: Wiki Overview
title: 'TASK-1043: Frontend integration handoff document'
id: doc:sdd-tasks-completed-task-1043-frontend-handoff-doc-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. **Context** — what an ephemeral agent is, user-perspective description.
---

# TASK-1043: Frontend integration handoff document

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1040, TASK-1041, TASK-1039
**Assigned-to**: unassigned

---

## Context

> The final deliverable of FEAT-149 is a handoff document for the `navigator-frontend-next`
> team (spec §3 Module 10, §7 Frontend Handoff Document). This Markdown document fully
> describes the HTTP surface so the frontend team can run `/sdd-proposal` without reading
> this repo.

---

## Scope

- Create `docs/api/feat-149-ephemeral-agents-api.md` containing ALL 10 sections listed in spec §7:
  1. **Context** — what an ephemeral agent is, user-perspective description.
  2. **End-to-end UI flow** — numbered screen walkthrough.
  3. **HTTP endpoints** — full request/response shapes for all 5 routes + cross-reference existing routes.
  4. **Polling guidance** — recommended intervals, phase meanings.
  5. **File upload protocol** — multipart layout, max size, MIME types.
  6. **Tool catalog payload** — exact JSON shape.
  7. **MCP server config payload** — JSON shape, handshake error surfacing.
  8. **Saving / promoting** — identity changes on promote.
  9. **Open questions for frontend team** — product decisions for frontend.
  10. **Out-of-scope reminders** — what FEAT-149 does NOT ship.
- The document must be self-contained — a reader with no access to this repo can run `/sdd-proposal` using only this document.

**NOT in scope**: Implementing any code. This is documentation only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/api/feat-149-ephemeral-agents-api.md` | CREATE | Frontend handoff document |

---

## Codebase Contract (Anti-Hallucination)

### Verified References
```
# Routes (from TASK-1040 + TASK-1041):
POST   /api/v1/agents/user/
GET    /api/v1/agents/user/{chatbot_id}/status
PUT    /api/v1/agents/user/{chatbot_id}
DELETE /api/v1/agents/user/{chatbot_id}
GET    /api/v1/tools/catalog

# Existing routes (cross-reference only):
PUT    /api/v1/user_agents
PATCH  /api/v1/user_agents/{chatbot_id}
GET    /api/v1/user_agents/{chatbot_id}
DELETE /api/v1/user_agents/{chatbot_id}
```

### Does NOT Exist
- ~~`POST /api/v1/user_agents`~~ — only PUT/PATCH/GET/DELETE exist there.
- ~~Sharing endpoints~~ — deferred to follow-up FEAT.
- ~~stdio MCP support~~ — HTTP-only for ephemeral creation.

---

## Implementation Notes

### Key Constraints
- The document is plain Markdown, written so it can be pasted as the `Problem Statement` and `Constraints & Requirements` body of a `/sdd-proposal` run in `navigator-frontend-next`.
- Must include concrete JSON examples for every request/response.
- Must include all status codes and error shapes.
- Must describe the multipart upload format precisely (field names, content types).
- Do NOT include backend implementation details (no mention of BotManager internals, DB schemas, etc.).

### References in Codebase
- `sdd/specs/ephemeral-agents.spec.md` §7 — exhaustive list of required sections.
- `parrot/handlers/agents/ephemeral.py` (TASK-1040) — actual handler for request/response shapes.
- `parrot/handlers/tools_catalog.py` (TASK-1039) — tool catalog response shape.

---

## Acceptance Criteria

- [ ] `docs/api/feat-149-ephemeral-agents-api.md` exists and is committed on `dev`.
- [ ] Contains ALL 10 sections listed in spec §7 "Frontend Handoff Document".
- [ ] Every HTTP endpoint includes: method+path, auth, content-type, request payload, response payload, status codes, example.
- [ ] Self-contained: a reader who has never seen this repo can run `/sdd-proposal` using only this document.
- [ ] No backend internals exposed (no BotManager, DB schema, or internal class names).
- [ ] Markdown renders cleanly (no broken links or formatting).

---

## Test Specification

No automated tests — this is a documentation deliverable. Manual review checklist:
- [ ] All 10 sections present.
- [ ] JSON examples are valid JSON.
- [ ] All 5 routes documented with full request/response shapes.
- [ ] Cross-references to existing routes are accurate.
- [ ] Polling guidance includes intervals and phase meanings.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §7 in full.
2. **Check dependencies** — TASK-1040, TASK-1041, TASK-1039 must be in `sdd/tasks/completed/`.
3. **Read the handler implementations** to extract accurate request/response shapes.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Write** the handoff document.
6. **Verify** all sections are present and accurate.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**: Created `docs/api/feat-149-ephemeral-agents-api.md` with all 10 sections
from spec §7. Document is 699 lines and includes full request/response examples,
field tables, polling guidance, MCP config, file upload protocol, tool catalog
payload description, promote identity notes, 8 open questions for the frontend
team, and an out-of-scope reminders section.

**Deviations from spec**: none
