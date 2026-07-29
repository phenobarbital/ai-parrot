---
type: Wiki Overview
title: 'TASK-1134: Teach `PromptLibraryManagement` GET to filter by `chatbot_id` OR
  `agent_id`'
id: doc:sdd-tasks-completed-task-1134-prompt-library-management-filter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module A2. After TASK-1133 the `PromptLibrary` row can be owned
---

# TASK-1134: Teach `PromptLibraryManagement` GET to filter by `chatbot_id` OR `agent_id`

**Feature**: FEAT-167 — Prompt Library: agent_id support + new UserPrompts model
**Spec**: `sdd/specs/promptlibrary-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1133
**Assigned-to**: unassigned

---

## Context

Spec §3 Module A2. After TASK-1133 the `PromptLibrary` row can be owned
by either a UUID chatbot or a string agent. The GET endpoint must let
clients fetch the prompts for a single bot/agent instance by either
identifier. If a client supplies both, return HTTP 400 — the row layout
is XOR.

The handler currently inherits `ModelView`'s generic filter machinery
(`handlers/bots.py:96-110`); the only customisation is `_set_created_by`.
This task adds explicit handling for `?chatbot_id=` and `?agent_id=`.

---

## Scope

- Add an overridden `get` (or pre-dispatch filter hook) on
  `PromptLibraryManagement` that:
  - parses both `chatbot_id` and `agent_id` from the request query string;
  - if **both** are present, returns HTTP 400 with a clear error body;
  - if **only `agent_id`** is present, filters the query by
    `agent_id == <slug>`;
  - if **only `chatbot_id`** is present, filters the query by
    `chatbot_id == <uuid>` (existing behaviour);
  - if **neither** is present, delegates to the inherited `ModelView`
    behaviour (i.e. lookup by `prompt_id` PK or full list).
- Preserve all other verbs (POST / PUT / DELETE / PATCH) unchanged.
- Add basic input validation: a `chatbot_id` value must parse as a UUID
  (return 400 otherwise); an `agent_id` value must be a non-empty
  string with only `[a-z0-9_-]` characters (return 400 otherwise).

**NOT in scope**:
- Changing the model (done in TASK-1133).
- Tests (TASK-1138).
- `UserPromptsManagement` (TASK-1137).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/bots.py` | not modified | (model already updated in TASK-1133) |
| `packages/ai-parrot/src/parrot/handlers/bots.py` | MODIFY | Override `get` (or add a filter hook) on `PromptLibraryManagement`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present near the top of handlers/bots.py
from navigator.views import ModelView                 # verified: handlers/bots.py:16
from .models import PromptLibrary                     # verified: handlers/bots.py:27-33
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/bots.py
class PromptLibraryManagement(ModelView):              # line 96
    model = PromptLibrary                              # line 102
    name: str = "Prompt Library Management"            # line 103
    path: str = '/api/v1/prompt_library'               # line 104 (class default)
    pk: str = 'prompt_id'                              # line 105

    async def _set_created_by(self, value, column, data):   # line 107
        if not value:
            return await self.get_userid(session=self._session)
        return value
```

```python
# Available on every ModelView subclass via aiohttp/navigator.views machinery:
self.request               # aiohttp.web.Request
self.request.rel_url.query # MultiDictProxy[str]  ← parse query string here
self.json_response(...)    # response helper
self.error(response=..., status=400)  # documented at handlers/bots.py:147-152
```

### Does NOT Exist
- ~~`PromptLibraryManagement.get_by_agent_id()`~~ — not a real method.
  Do NOT add it as a separate method; the override goes into `get` or
  into a pre-filter that ModelView already supports.
- ~~`ModelView.add_filter()`~~ — not a public helper; rely on overriding
  `get`.
- ~~`self.request.query_params`~~ — aiohttp uses
  `self.request.rel_url.query` (a `MultiDictProxy[str]`), not the
  FastAPI-style `query_params`.
- ~~`PromptLibrary.target_id`~~ — there is no unified `target_id`
  column; the schema is dual-column with a CHECK.

---

## Implementation Notes

### Pattern to Follow

The error-response pattern used elsewhere in this file is:
```python
# handlers/bots.py:147-152 (inside ChatbotUsageHandler.post)
return self.error(
    response={"message": "Error on Chatbot Usage payload"},
    status=400,
)
```

Re-use it for the both-supplied case.

### Suggested override skeleton

```python
import re
import uuid as _uuid

_AGENT_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

class PromptLibraryManagement(ModelView):
    model = PromptLibrary
    name: str = "Prompt Library Management"
    path: str = '/api/v1/prompt_library'
    pk: str = 'prompt_id'

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value

    async def get(self):
        q = self.request.rel_url.query
        chatbot_id = q.get("chatbot_id")
        agent_id   = q.get("agent_id")

        if chatbot_id and agent_id:
            return self.error(
                response={
                    "message": (
                        "Provide exactly one of chatbot_id or agent_id, not both."
                    ),
                },
                status=400,
            )

        if chatbot_id:
            try:
                _uuid.UUID(chatbot_id)
            except (ValueError, TypeError):
                return self.error(
                    response={"message": "chatbot_id must be a valid UUID."},
                    status=400,
                )
            return await super().get()  # inherited filter handles the param

        if agent_id:
            if not _AGENT_SLUG_RE.match(agent_id):
                return self.error(
                    response={
                        "message": (
                            "agent_id must match [a-z0-9_-]+ "
                            "(registry slug format)."
                        ),
                    },
                    status=400,
                )
            return await super().get()  # inherited filter handles the param

        return await super().get()
```

> If `ModelView.get` does NOT automatically filter on arbitrary query
> params, replace `return await super().get()` in the matched branches
> with an explicit query that uses `self.handler` / the active connection
> in the same style `ChatbotUsageHandler.post` uses
> (`handlers/bots.py:163-196`). Confirm `super().get` behaviour by
> `grep -n "async def get" packages/ai-parrot/src/parrot/handlers/bots.py`
> for live examples in this file.

### Key Constraints

- Do NOT remove `_set_created_by` — POST/PUT still rely on it.
- Do NOT change `pk = 'prompt_id'`. PK-based lookups must still work.
- Keep the `path` class attribute as `'/api/v1/prompt_library'`; the
  live route is set in `app.py:135` and is independent of this attribute.

### References in Codebase
- `handlers/bots.py:96-110` — handler under modification.
- `handlers/bots.py:147-152` — error-response pattern.
- `handlers/bots.py:163-196` — manual query pattern (fallback).
- `app.py:135` — route wiring (do NOT change here; that's a different task).

---

## Acceptance Criteria

- [ ] GET `?chatbot_id=<uuid>` returns only rows whose `chatbot_id` matches.
- [ ] GET `?agent_id=<slug>` returns only rows whose `agent_id` matches.
- [ ] GET with **both** `chatbot_id` and `agent_id` returns HTTP 400.
- [ ] GET with `chatbot_id` that is not a UUID returns HTTP 400.
- [ ] GET with `agent_id` that does not match `[a-z0-9_-]+` returns HTTP 400.
- [ ] GET with neither parameter still works exactly as before (PK lookup or list).
- [ ] `_set_created_by` is unchanged and still runs on POST/PUT.
- [ ] `ruff check packages/ai-parrot/src/parrot/handlers/bots.py` — no new errors.

---

## Test Specification

> Full pytest scaffolding lives in TASK-1138. The implementing agent
> may run a manual smoke test with `aiohttp.test_utils` if helpful.

---

## Agent Instructions

1. Read the spec at `sdd/specs/promptlibrary-changes.spec.md` §2 and §6.
2. Verify `PromptLibraryManagement` is still at `handlers/bots.py:96-110`
   and that TASK-1133 has landed (the `agent_id` field exists on the model).
3. Apply the `get` override per *Implementation Notes*.
4. Confirm `super().get()` honours the query-string filter for both
   `chatbot_id` and `agent_id`; if it does not, fall back to the manual
   query pattern from `handlers/bots.py:163-196`.
5. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-13
**Notes**: Added `import re` and `import uuid as _uuid` at top of handlers/bots.py. Added `_AGENT_SLUG_RE` module-level constant. Overrode `get()` on `PromptLibraryManagement` to validate and route on `chatbot_id` and `agent_id` query params. Returns HTTP 400 for both-supplied, invalid UUID, and invalid slug cases. Falls through to `super().get()` in all valid cases. `_set_created_by` left unchanged. Ruff passes.

**Deviations from spec**: none
