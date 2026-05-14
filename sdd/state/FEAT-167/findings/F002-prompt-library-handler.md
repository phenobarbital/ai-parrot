---
id: F002
query_id: Q003+Q004+Q006
type: read
intent: PromptLibraryManagement handler shape + route wiring
confidence: high
---

# F002 — `PromptLibraryManagement` handler

## Location
- File: `packages/ai-parrot/src/parrot/handlers/bots.py`
- Lines: 96-110

## Current shape
```python
class PromptLibraryManagement(ModelView):
    """
    PromptLibraryManagement.
    description: PromptLibraryManagement for Parrot Application.
    """

    model = PromptLibrary
    name: str = "Prompt Library Management"
    path: str = '/api/v1/prompt_library'      # ← default path (overridden at wire-up)
    pk: str = 'prompt_id'

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value
```

## Route wiring (NOT the class default)
- `app.py:135`:
  ```python
  PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')
  ```
  So the canonical URL today is **`/api/v1/chatbots/prompt_library`**, not
  `/api/v1/prompt_library`. The `path` attribute on the class is a fallback.

## Inheritance behaviour
- `ModelView` (from `navigator.views`) provides the default REST verbs (GET/POST/PUT/DELETE) and PK-based filtering. The handler only overrides `_set_created_by`.
- No custom GET filter currently exists for `chatbot_id` or `agent_id`. Queries via REST hit ModelView's generic filter machinery (URL/query-string).

## User identity pattern used elsewhere in this file
- `self.get_userid(session=self._session)` is the canonical async accessor (lines 109, 182, 790). Returns the integer `user_id` from the authenticated session.

## Citations
- `packages/ai-parrot/src/parrot/handlers/bots.py:96-110` (handler)
- `packages/ai-parrot/src/parrot/handlers/bots.py:27-33` (imports `PromptLibrary` from `.models`)
- `app.py:135` (route wiring) — searched via `grep -n PromptLibraryManagement app.py`
