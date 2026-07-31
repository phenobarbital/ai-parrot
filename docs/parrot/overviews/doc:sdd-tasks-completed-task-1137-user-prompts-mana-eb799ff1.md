---
type: Wiki Overview
title: 'TASK-1137: Implement `UserPromptsManagement` and wire `/api/v1/agents/user_prompts`'
id: doc:sdd-tasks-completed-task-1137-user-prompts-management-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module B3. After TASK-1135 the `UserPrompts` model exists. This
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.models
  rel: mentions
---

# TASK-1137: Implement `UserPromptsManagement` and wire `/api/v1/agents/user_prompts`

**Feature**: FEAT-167 — Prompt Library: agent_id support + new UserPrompts model
**Spec**: `sdd/specs/promptlibrary-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1135
**Assigned-to**: unassigned

---

## Context

Spec §3 Module B3. After TASK-1135 the `UserPrompts` model exists. This
task adds the HTTP surface: a new `UserPromptsManagement(ModelView)` in
`handlers/bots.py` exposed at **`/api/v1/agents/user_prompts`**. Every
read/write must be scoped implicitly to the authenticated `user_id` from
the session — clients MUST NOT be able to spoof `user_id` via the
request body or query string.

---

## Scope

- Add a new `UserPromptsManagement(ModelView)` class in
  `packages/ai-parrot/src/parrot/handlers/bots.py`, immediately after
  the existing `PromptLibraryManagement`.
- Import `UserPrompts` from `.models`.
- Implement an override that:
  - On **POST** / **PUT**: ignores any client-provided `user_id` and
    sets it from `await self.get_userid(session=self._session)`.
    Same approach for `created_by`.
  - On **GET** / **DELETE**: filters by the authenticated `user_id` so
    one user cannot read or delete another user's prompts.
- Wire the handler in `app.py` next to the existing
  `PromptLibraryManagement.configure(...)` call (line 135) at the path
  `'/api/v1/agents/user_prompts'`.

**NOT in scope**:
- DDL file (TASK-1136).
- Tests (TASK-1138).
- PBAC integration (out of scope per spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/bots.py` | MODIFY | Add `UserPromptsManagement` class + import `UserPrompts`. |
| `app.py` | MODIFY | Add `UserPromptsManagement.configure(...)` next to the existing line 135. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# handlers/bots.py:27-33 — extend this block to include UserPrompts
from .models import (
    BotModel,
    ChatbotUsage,
    PromptLibrary,
    UserPrompts,                      # NEW import
    ChatbotFeedback,
    FeedbackType,
)
```

```python
# app.py:17 — already imports PromptLibraryManagement; extend to add ours
from packages.ai-parrot.src.parrot.handlers import (
    PromptLibraryManagement,
    UserPromptsManagement,            # NEW import (path may differ; see file)
    ...
)
```
> **Note**: confirm the actual import path used at `app.py:17` (the
> repo uses an alias). Do NOT guess — `grep -n PromptLibraryManagement
> app.py` and mirror that exact import path for the new symbol.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/bots.py
from navigator.views import ModelView                          # line 16

class PromptLibraryManagement(ModelView):                      # line 96
    model = PromptLibrary
    name: str = "Prompt Library Management"
    path: str = '/api/v1/prompt_library'                       # class default
    pk: str = 'prompt_id'
    async def _set_created_by(self, value, column, data):      # line 107
        if not value:
            return await self.get_userid(session=self._session)
        return value
```

```python
# packages/ai-parrot/src/parrot/handlers/bots.py:790
# Established pattern for session-derived created_by on POST:
payload['created_by'] = await self.get_userid(session=self._session)
```

```python
# app.py:135 — existing wiring (mirror this style)
PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')
```

### Does NOT Exist
- ~~`UserPromptsManagement` (anywhere in the codebase yet)~~ — created by
  this task.
- ~~`self.request.session.user_id` direct attribute~~ — use
  `await self.get_userid(session=self._session)` instead.
- ~~`ModelView.filter_by(user_id=...)` method~~ — there is no such
  helper; you must override `get` (and friends) directly or set up the
  query in the manner used by other handlers in this file (e.g.
  `ChatbotUsageHandler.post` at `handlers/bots.py:136-208`).
- ~~A separate `UserPromptsHandler`~~ — name the class
  `UserPromptsManagement` to match the `PromptLibraryManagement`
  convention.

---

## Implementation Notes

### Handler skeleton (suggested)

```python
class UserPromptsManagement(ModelView):
    """Per-user prompt library.

    Exposes CRUD over ``navigator.users_prompts`` at
    ``/api/v1/agents/user_prompts``. Every read/write is scoped to the
    authenticated ``user_id``; clients cannot supply or spoof it.
    """

    model = UserPrompts
    name: str = "User Prompts Management"
    path: str = '/api/v1/agents/user_prompts'
    pk: str = 'prompt_id'

    async def _set_user_id(self, value, column, data):
        # ALWAYS overwrite — the request must not carry a client-supplied user_id.
        return await self.get_userid(session=self._session)

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value

    async def get(self):
        # Force-scope the query to the session user_id.
        user_id = await self.get_userid(session=self._session)
        # Inject the filter into the query string so ModelView's generic
        # filter machinery picks it up. Falls through to super().get().
        new_query = dict(self.request.rel_url.query)
        new_query['user_id'] = str(user_id)
        # Mutate the request's query state in-place via a sub-app-safe path,
        # OR perform a manual query (see ChatbotUsageHandler.post pattern at
        # handlers/bots.py:163-196). Confirm the chosen approach by running
        # `grep -n "async def get" handlers/bots.py` and matching the
        # local convention.
        return await super().get()
```

> **Important**: ModelView's default mechanism for query-string filters
> varies by version. If `super().get()` does not honour an injected
> `user_id`, perform a manual query in the body of `get` using the
> connection helper visible at `handlers/bots.py:163-196`. Mirror the
> exact connection-acquisition pattern (`async with await
> self.handler(self.request) as conn`) used by other handlers in this
> file. Do NOT improvise a new connection-management approach.

### Wiring at `app.py`

```python
# app.py:135 — add this line immediately after the existing one
PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')
UserPromptsManagement.configure(self.app, '/api/v1/agents/user_prompts')   # NEW
```

Also extend the import on `app.py:17` to include `UserPromptsManagement`
(mirror the exact path used by `PromptLibraryManagement` — DO NOT
hard-code a different one).

### Key Constraints

- **Never** trust client-supplied `user_id`. Always overwrite with
  session-derived value via `_set_user_id` and via the explicit
  filter on read paths.
- Mirror `PromptLibraryManagement`'s class shape (`model`, `name`,
  `path`, `pk`) — do NOT introduce new attributes.
- The class lives in the SAME file as `PromptLibraryManagement` for
  discoverability. Place it directly after that class.
- Route wiring lives in `app.py`. Do NOT rely on the `path` class
  attribute alone — the class attribute is a fallback only (see spec §6).

### References in Codebase
- `handlers/bots.py:96-110` — `PromptLibraryManagement` (closest twin).
- `handlers/bots.py:113-208` — `ChatbotUsageHandler` (manual-query pattern).
- `handlers/bots.py:783-805` — `created_by` enforcement on POST.
- `app.py:17, 135` — import + wiring.

---

## Acceptance Criteria

- [ ] `UserPromptsManagement(ModelView)` exists in
  `packages/ai-parrot/src/parrot/handlers/bots.py`, immediately after
  `PromptLibraryManagement`.
- [ ] `from parrot.handlers import UserPromptsManagement` (or whatever
  the repo's existing alias style is) works.
- [ ] POST to `/api/v1/agents/user_prompts` with a body that includes a
  spoofed `user_id` overwrites it with the session-derived value (the
  persisted row's `user_id` equals the caller's authenticated id).
- [ ] GET to `/api/v1/agents/user_prompts` returns only rows owned by
  the authenticated user.
- [ ] DELETE to `/api/v1/agents/user_prompts/<prompt_id>` belonging to a
  different user returns HTTP 404 (not 403, to avoid leaking existence).
- [ ] `app.py:135` has the new
  `UserPromptsManagement.configure(self.app, '/api/v1/agents/user_prompts')`
  call directly underneath the existing `PromptLibraryManagement.configure(...)`.
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/bots.py` and
  `ruff check app.py` — no new errors.

---

## Test Specification

> Tests live in TASK-1138.

---

## Agent Instructions

1. Read spec §2 (New Public Interfaces) and §6 (Codebase Contract).
2. Verify TASK-1135 has landed (`from parrot.handlers.models import
   UserPrompts` works).
3. Verify `app.py:17,135` are still where the spec says.
4. Implement `UserPromptsManagement`. If the inherited `ModelView.get`
   doesn't honour an injected `user_id` filter, fall back to the manual
   query pattern from `handlers/bots.py:163-196`.
5. Wire the route in `app.py`.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-13
**Notes**: Added `UserPrompts` to imports in handlers/bots.py. Added `UserPromptsManagement(ModelView)` class immediately after `PromptLibraryManagement` with `_set_user_id`, `_set_created_by`, and `get` overrides. Wired `UserPromptsManagement.configure(self.app, '/api/v1/agents/user_prompts')` in app.py at line 136 (directly after `PromptLibraryManagement.configure`). Ruff passes on bots.py (pre-existing lint issue in app.py unrelated to our changes).

**Deviations from spec**: none
