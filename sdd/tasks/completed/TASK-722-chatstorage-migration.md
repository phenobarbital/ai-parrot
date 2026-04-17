# TASK-722: ChatStorage Migration — DocumentDB to DynamoDB

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-717, TASK-718, TASK-721
**Assigned-to**: unassigned

---

## Context

Implements spec Module 5. This is the core migration: replace `DocumentDb` backend inside `ChatStorage` with `ConversationDynamoDB`. All existing ChatStorage methods (`save_turn`, `load_conversation`, `list_user_conversations`, `delete_conversation`, `delete_turn`, `create_conversation`, `update_conversation_title`) must work against DynamoDB instead of DocumentDB.

The Redis hot-cache path remains completely unchanged.

---

## Scope

- Modify `ChatStorage.__init__()` to accept `ConversationDynamoDB` instead of `DocumentDb`
- Modify `ChatStorage.initialize()` to create/connect `ConversationDynamoDB` instead of `DocumentDb`
- Replace `_save_to_documentdb()` with `_save_to_dynamodb()` using `ConversationDynamoDB.put_turn()` + `update_thread()`
- Modify `load_conversation()` to query DynamoDB conversations table
- Modify `list_user_conversations()` to query DynamoDB for thread metadata only
- Modify `create_conversation()` to use `ConversationDynamoDB.put_thread()`
- Modify `update_conversation_title()` to use `ConversationDynamoDB.update_thread()`
- Modify `delete_conversation()` to cascade-delete from BOTH tables (conversations + artifacts)
- Modify `delete_turn()` to use DynamoDB
- Keep `get_context_for_agent()` unchanged (it delegates to Redis or load_conversation)
- Write unit tests for the migrated methods

**NOT in scope**: API endpoints, handler integration, artifact CRUD (that's ArtifactStore).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/chat.py` | MODIFY | Replace DocumentDb with ConversationDynamoDB |
| `tests/storage/test_chat_storage_dynamodb.py` | CREATE | Unit tests for migrated ChatStorage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.dynamodb import ConversationDynamoDB  # after TASK-718
from parrot.storage.models import ChatMessage, Conversation, MessageRole, ToolCall, Source
from parrot.memory.abstract import ConversationTurn
from parrot.memory import RedisConversation
from navconfig.logging import logging
```

### Existing Signatures to Use
```python
# parrot/storage/chat.py:27 — CURRENT implementation to modify:
class ChatStorage:
    def __init__(self, redis_conversation=None, document_db=None):  # line 30
        self._redis = redis_conversation          # line 35
        self._docdb = document_db                 # line 36 — THIS GETS REPLACED

    async def initialize(self) -> None:           # line 44
        # Currently creates DocumentDb() — change to ConversationDynamoDB

    async def save_turn(self, *, turn_id, user_id, session_id, agent_id,
                        user_message, assistant_response, ...):  # line 126
        # Redis path (lines 202-231) — DO NOT CHANGE
        # DocumentDB path (lines 233-241) — REPLACE with DynamoDB

    async def _save_to_documentdb(self, user_msg, assistant_msg,
                                  agent_id, now):  # line 243
        # REPLACE entirely with _save_to_dynamodb

    async def load_conversation(self, user_id, session_id,
                                agent_id=None, limit=50):  # line 323
        # Redis path — DO NOT CHANGE
        # DocumentDB fallback path — REPLACE with DynamoDB

    async def list_user_conversations(self, user_id, agent_id=None,
                                      limit=50, since=None):  # line 479
        # DocumentDB query — REPLACE with DynamoDB

    async def delete_conversation(self, user_id, session_id,
                                  agent_id=None):  # line 572
        # Redis delete — DO NOT CHANGE
        # DocumentDB delete — REPLACE with DynamoDB cascade
```

### Does NOT Exist
- ~~`ConversationDynamoDB.save_turn()`~~ — the method is `put_turn()`, not `save_turn()`
- ~~`ConversationDynamoDB.load_conversation()`~~ — use `query_turns()` and `query_threads()`
- ~~`ChatStorage._artifact_store`~~ — does not exist on ChatStorage; ArtifactStore is separate

---

## Implementation Notes

### Key Constraints
- The `__init__` signature changes: `document_db` parameter becomes `dynamodb: ConversationDynamoDB = None`
- `self._docdb` becomes `self._dynamo` (or similar)
- The Redis hot-cache path in every method MUST remain unchanged
- The fire-and-forget pattern (`asyncio.create_task()`) for DynamoDB writes should be preserved
- `load_conversation` DynamoDB fallback returns the same format as before (list of message dicts)
- `delete_conversation` must call `delete_thread_cascade()` on conversations table AND `delete_session_artifacts()` on artifacts table (parallel with `asyncio.gather`)
- Remove all diagnostic/DIAG logging from `load_conversation` (lines 375-418) — that was for DocumentDB debugging

---

## Acceptance Criteria

- [ ] `ChatStorage` uses `ConversationDynamoDB` instead of `DocumentDb`
- [ ] `save_turn()` writes to DynamoDB (fire-and-forget async)
- [ ] `load_conversation()` reads from DynamoDB (with Redis fallback first)
- [ ] `list_user_conversations()` returns thread metadata from DynamoDB
- [ ] `delete_conversation()` cascade-deletes from both tables
- [ ] Redis hot-cache path is completely unchanged
- [ ] All existing tests still pass
- [ ] New unit tests pass: `pytest tests/storage/test_chat_storage_dynamodb.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — Section 2 (Access Patterns) and Section 6 (ChatStorage signatures)
2. **Read** `parrot/storage/chat.py` in full — understand every method before modifying
3. **Check dependencies** — TASK-717, TASK-718, TASK-721 must be completed
4. **Update status** → `"in-progress"`
5. **Implement** the migration carefully — preserve Redis path, replace DocumentDB path
6. **Run tests**: `pytest tests/storage/ -v`
7. **Move + update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
