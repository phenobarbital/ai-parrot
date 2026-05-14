---
id: F005
query_id: Q011+Q013+Q014
type: grep
intent: Confirm user identity accessor + lack of test coverage + str-chatbot_id precedent
confidence: high
---

# F005 — User identity, test coverage, and str-typed `chatbot_id` precedent

## User identity in handlers
- `self.get_userid(session=self._session)` is the standard async accessor inside `ModelView`/`BaseView` subclasses for fetching the authenticated integer `user_id`.
- Used at `packages/ai-parrot/src/parrot/handlers/bots.py:109` (PromptLibraryManagement's own `_set_created_by`), :182 (`ChatbotUsageHandler.post`), and :790 (BotModel POST setting `created_by`).
- Same pattern can be reused for `UserPrompts` to populate `user_id` and `created_by`.

## Test coverage for PromptLibrary
- `grep -rn "PromptLibrary" packages/ai-parrot/tests/ tests/` → **0 hits**.
- No existing test fixtures or unit tests for the model or its handler.
- This is a gap; FEAT-167 should ship at least a minimal smoke test for the new model + handler.

## Precedent for str-typed `chatbot_id`
- `packages/ai-parrot/src/parrot/handlers/database/helpers.py:77-93` defines `agent_id: Optional[str] = None` in a helper signature that resolves either by `agent_id` slug or first available, indicating multi-key resolution already exists in the codebase. (No analogous `chatbot_id_str` precedent inside the model layer, but the proposed VARCHAR column is consistent with the registry-name pattern from F003.)
- In `users_bots_creation.sql:18`, `name VARCHAR NOT NULL` and `llm VARCHAR NOT NULL DEFAULT 'google'` are precedents for using `VARCHAR` for human-readable identifiers in this schema.

## Citations
- `packages/ai-parrot/src/parrot/handlers/bots.py:109, 182, 790`
- `packages/ai-parrot/src/parrot/handlers/database/helpers.py:77-93`
- `packages/ai-parrot/src/parrot/handlers/models/users_bots_creation.sql:18,38`
- `packages/ai-parrot/tests/` and `tests/` → no matches for "PromptLibrary"
