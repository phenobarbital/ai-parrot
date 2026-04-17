# TASK-725: Handler Integration — Auto-Save Artifacts

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-720, TASK-722
**Assigned-to**: unassigned

---

## Context

Implements spec Module 9. Wires automatic artifact saving into existing handler flows: when `get_infographic()` returns an `InfographicResponse`, save it as an infographic artifact. When `ask()` returns data, the turn data is already saved via ChatStorage — this task ensures artifact creation for chart-worthy responses.

---

## Scope

- Modify `parrot/handlers/infographic.py` (`InfographicTalk._generate_infographic()`):
  - After `get_infographic()` returns, create an `Artifact` of type `infographic` with the `InfographicResponse` as definition
  - Call `ArtifactStore.save_artifact()` as fire-and-forget (`asyncio.create_task`)
- Modify `parrot/handlers/agent.py` (`AgentTalk`):
  - After successful `ask()` response flow, if the response includes structured data (output/data), optionally create a data artifact reference
  - Fire-and-forget pattern (same as existing DocumentDB writes)
- Ensure `ArtifactStore` is accessible from request app context (register during app startup)
- Write integration tests

**NOT in scope**: API endpoints, ChatStorage migration, model definitions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/infographic.py` | MODIFY | Add auto-save after get_infographic() |
| `parrot/handlers/agent.py` | MODIFY | Add auto-save for data artifacts |
| `tests/handlers/test_auto_save.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.artifacts import ArtifactStore        # after TASK-720
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator  # after TASK-717
from parrot.models.infographic import InfographicResponse  # parrot/models/infographic.py:580
```

### Existing Signatures to Use
```python
# parrot/handlers/infographic.py:54
class InfographicTalk:  # inherits from AgentTalk
    # _generate_infographic() — line 132
    # Calls agent.get_infographic() → returns AIMessage with structured_output

# parrot/handlers/agent.py:47
class AgentTalk:
    # chat_storage = self.request.app.get('chat_storage')  — line 1775
    # Uses asyncio.get_running_loop().create_task() for fire-and-forget

# parrot/models/infographic.py:580
class InfographicResponse(BaseModel):
    template: Optional[str]
    theme: Optional[str]
    blocks: List[...]
    metadata: Optional[Dict[str, Any]]
```

### Does NOT Exist
- ~~`self.request.app.get('artifact_store')`~~ — must be registered during app startup
- ~~`AgentTalk._save_artifact()`~~ — does not exist; this task adds the integration

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing fire-and-forget pattern in ChatStorage.save_turn():
if artifact_store:
    asyncio.get_running_loop().create_task(
        artifact_store.save_artifact(user_id, agent_id, session_id, artifact)
    )
```

### Key Constraints
- NEVER block the request path — artifact saves are fire-and-forget
- The `ArtifactStore` instance must be available via `self.request.app.get('artifact_store')`
- Register `artifact_store` during app startup (same place `chat_storage` is registered)
- `InfographicResponse` serialization: use `.model_dump()` as the artifact definition
- Generate artifact_id: use `f"infog-{turn_id}"` or `f"infog-{uuid.uuid4().hex[:8]}"`

---

## Acceptance Criteria

- [ ] `get_infographic()` auto-saves infographic artifact
- [ ] Artifact save is fire-and-forget (no blocking)
- [ ] `ArtifactStore` registered in app context
- [ ] Existing handler behavior unchanged
- [ ] Tests pass

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/handlers/infographic.py` and `parrot/handlers/agent.py` in full
2. **Check dependencies** — TASK-720 and TASK-722 must be completed
3. **Find** where `chat_storage` is registered in app startup — register `artifact_store` similarly
4. **Implement** fire-and-forget artifact saves
5. **Run tests**

---

## Completion Note

*(Agent fills this in when done)*
