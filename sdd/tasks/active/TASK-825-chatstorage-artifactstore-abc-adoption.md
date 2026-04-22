# TASK-825: ChatStorage and ArtifactStore Consume the ABC

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-822, TASK-823, TASK-824
**Assigned-to**: unassigned

---

## Context

Completes Phase A of the worktree strategy (spec §"Worktree Strategy"). After
this task, `ChatStorage` and `ArtifactStore` are fully decoupled from the
concrete `ConversationDynamoDB` — they compose against the ABC and the
generalized `OverflowStore`. Three leaky abstractions are repaired (spec §7
"Leaky Abstractions to Repair"):

1. `ArtifactStore` no longer calls `ConversationDynamoDB._build_pk` directly.
2. `ChatStorage.delete_turn` no longer reaches into `_dynamo._conv_table.delete_item`.
3. `chat.py`'s inline import of `botocore.exceptions` at line 574 is removed.

AWS behavior must remain functionally identical — this is a pure decoupling refactor.

---

## Scope

### `packages/ai-parrot/src/parrot/storage/artifacts.py`
- Change the type annotation on `__init__`: `dynamodb: ConversationDynamoDB` → `dynamodb: ConversationBackend`; `s3_overflow: S3OverflowManager` → `s3_overflow: OverflowStore`. (Keep parameter names for back-compat; `OverflowStore` is the parent of `S3OverflowManager` so existing callers still work.)
- Replace both uses of `ConversationDynamoDB._build_pk` at lines 65 and 177 with `self._db.build_overflow_prefix(user_id, agent_id, session_id, artifact_id)`. The resulting `key_prefix` is the full prefix (no more manual concatenation), so `_overflow.maybe_offload(definition, key_prefix)` takes it as-is.
- Remove the module-level import of `ConversationDynamoDB` from `artifacts.py` — it is no longer referenced.

### `packages/ai-parrot/src/parrot/storage/chat.py`
- Change attribute types: `self._dynamo` is now `Optional[ConversationBackend]`.
- Remove the inline `from botocore.exceptions import ClientError, BotoCoreError` at line 574.
- Replace the body of the `delete_turn` method (around line 560-600) to call `self._dynamo.delete_turn(user_id, agent_id, session_id, turn_id)` on the ABC instead of reaching into `_conv_table.delete_item`. Preserve the surrounding guards (early return when `user_id` or `agent_id` is falsy) and the subsequent `update_thread` turn-count update.
- Do NOT yet change how `self._dynamo` is constructed in `initialize()` — that is TASK-829's concern (factory wiring). For now, `initialize()` still instantiates `ConversationDynamoDB` directly; the change here is only about the *call-sites*.

### Tests
- New test file `packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py`:
  - `parrot/storage/artifacts.py` source contains NO reference to `_build_pk`.
  - `parrot/storage/chat.py` source contains NO inline import of `botocore.exceptions`.
  - `ArtifactStore` instantiates cleanly when given any `ConversationBackend` subclass (use a stub).
  - `ArtifactStore.save_artifact` calls `backend.build_overflow_prefix(...)` exactly once per save.

**NOT in scope**: Changing `ChatStorage.__init__` signature. Adding the factory call in `initialize()` (that's TASK-829). Moving the `sdd/specs/agent-artifact-persistency.spec.md` tests. Introducing any new backend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/artifacts.py` | MODIFY | Type annotations + remove `_build_pk` calls |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | Type annotation + replace `delete_turn` body |
| `packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py` | CREATE | Regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/storage/artifacts.py — NEW import set:
from datetime import datetime
from typing import Dict, Any, List, Optional

from navconfig.logging import logging

from parrot.storage.backends.base import ConversationBackend   # from TASK-822
from parrot.storage.overflow import OverflowStore              # from TASK-823
from parrot.storage.models import Artifact, ArtifactSummary, ArtifactType

# REMOVE (no longer needed after refactor):
# from .dynamodb import ConversationDynamoDB
# from .s3_overflow import S3OverflowManager   # replaced by OverflowStore


# parrot/storage/chat.py — retain existing imports EXCEPT:
# REMOVE the inline import block at line 574:
#     from botocore.exceptions import ClientError, BotoCoreError
```

### Existing Signatures to Use

```python
# parrot/storage/backends/base.py (from TASK-822)
class ConversationBackend(ABC):
    async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool: ...
    def build_overflow_prefix(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> str: ...
    # ...plus all other abstract methods already in use.

# parrot/storage/overflow.py (from TASK-823)
class OverflowStore:
    INLINE_THRESHOLD: int = 200 * 1024
    def __init__(self, file_manager: FileManagerInterface) -> None: ...
    async def maybe_offload(self, data, key_prefix: str) -> Tuple[Optional[Dict], Optional[str]]: ...
    async def resolve(self, inline, ref) -> Optional[Dict]: ...
    async def delete(self, ref: str) -> bool: ...

# parrot/storage/artifacts.py — current (BEFORE refactor) lines to replace:
# Line 65-66:
#   pk = ConversationDynamoDB._build_pk(user_id, agent_id)
#   key_prefix = f"artifacts/{pk}/THREAD#{session_id}/{artifact.artifact_id}"
# Line 177-179:
#   pk = ConversationDynamoDB._build_pk(user_id, agent_id)
#   key_prefix = f"artifacts/{pk}/THREAD#{session_id}/{artifact_id}"

# parrot/storage/chat.py — current (BEFORE refactor) `delete_turn` body approximately at line 560-600.
# Find by: grep -n "def delete_turn" packages/ai-parrot/src/parrot/storage/chat.py
```

### Does NOT Exist

- ~~A parameter rename `dynamodb=` to `backend=` on `ArtifactStore.__init__`~~ — keep `dynamodb` as the param name to avoid call-site churn (types are still narrowed via the annotation). Same for `s3_overflow`.
- ~~`ChatStorage.__init__` parameter renamed `dynamodb=` to `backend=`~~ — out of scope. TASK-829 handles construction; this task only changes types.
- ~~A new method `ArtifactStore.with_backend(...)`~~ — no such helper.
- ~~`backend.build_overflow_prefix` returning a `Path`~~ — returns `str` (per spec §2 and TASK-822).

---

## Implementation Notes

### Pattern — ArtifactStore

Before:
```python
# artifacts.py:44-80 (save_artifact, abbreviated)
from .dynamodb import ConversationDynamoDB
from .s3_overflow import S3OverflowManager

class ArtifactStore:
    def __init__(self, dynamodb: ConversationDynamoDB, s3_overflow: S3OverflowManager) -> None:
        self._db = dynamodb
        self._overflow = s3_overflow

    async def save_artifact(self, user_id, agent_id, session_id, artifact):
        data = artifact.model_dump(mode="json")
        definition = data.pop("definition", None)
        definition_ref = data.pop("definition_ref", None)
        if definition is not None:
            pk = ConversationDynamoDB._build_pk(user_id, agent_id)
            key_prefix = f"artifacts/{pk}/THREAD#{session_id}/{artifact.artifact_id}"
            inline, ref = await self._overflow.maybe_offload(definition, key_prefix)
            ...
```

After:
```python
# artifacts.py
from parrot.storage.backends.base import ConversationBackend
from parrot.storage.overflow import OverflowStore

class ArtifactStore:
    def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None:
        self._db = dynamodb
        self._overflow = s3_overflow

    async def save_artifact(self, user_id, agent_id, session_id, artifact):
        data = artifact.model_dump(mode="json")
        definition = data.pop("definition", None)
        definition_ref = data.pop("definition_ref", None)
        if definition is not None:
            key_prefix = self._db.build_overflow_prefix(
                user_id, agent_id, session_id, artifact.artifact_id,
            )
            inline, ref = await self._overflow.maybe_offload(definition, key_prefix)
            ...
```

Apply the same pattern to `update_artifact` (line 177-179).

### Pattern — ChatStorage.delete_turn

Before (approximate):
```python
async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool:
    if not self._dynamo or not user_id or not agent_id:
        return False
    try:
        pk = self._dynamo._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#TURN#{turn_id}"
        from botocore.exceptions import ClientError, BotoCoreError
        try:
            await self._dynamo._conv_table.delete_item(Key={"PK": pk, "SK": sk})
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning("DynamoDB delete_turn failed for %s: %s", turn_id, exc)
            return False
        # ... update_thread turn count ...
```

After:
```python
async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool:
    if not self._dynamo or not user_id or not agent_id:
        return False
    ok = await self._dynamo.delete_turn(user_id, agent_id, session_id, turn_id)
    if not ok:
        return False
    # ... unchanged update_thread turn count ...
```

### Key Constraints

- Do NOT change the `__init__` parameter names on either class — only their type annotations. This keeps every caller's keyword-argument form working.
- Do NOT import `botocore.exceptions` anywhere in `chat.py` or `artifacts.py` after this task (grep verification in the test suite).
- The `S3OverflowManager` is a subclass of `OverflowStore` (from TASK-823), so passing an `S3OverflowManager` to `ArtifactStore(s3_overflow=...)` still type-checks.

### References in Codebase

- `parrot/storage/backends/base.py` (from TASK-822) — ABC surface.
- `parrot/storage/backends/dynamodb.py` (from TASK-824) — provides `delete_turn` and `build_overflow_prefix`.
- `parrot/storage/overflow.py` (from TASK-823) — the typed overflow store.
- Existing integration tests at `tests/storage/test_integration_artifact_persistence.py` exercise the end-to-end flow — they must keep passing.

---

## Acceptance Criteria

- [ ] `parrot/storage/artifacts.py` has no references to `ConversationDynamoDB` or `_build_pk` (`grep -n "_build_pk" packages/ai-parrot/src/parrot/storage/artifacts.py` returns nothing).
- [ ] `parrot/storage/chat.py` has no inline `from botocore.exceptions import` (`grep -n "from botocore" packages/ai-parrot/src/parrot/storage/chat.py` returns nothing).
- [ ] `ArtifactStore.__init__` type annotations are `ConversationBackend` and `OverflowStore`.
- [ ] `ArtifactStore.save_artifact` and `update_artifact` both call `self._db.build_overflow_prefix(...)`.
- [ ] `ChatStorage.delete_turn` calls `self._dynamo.delete_turn(...)` on the ABC.
- [ ] All pre-existing storage tests still pass:
  ```bash
  source .venv/bin/activate
  pytest packages/ai-parrot/tests/storage/ -v
  pytest packages/ai-parrot/tests/handlers/test_auto_save.py -v
  ```
- [ ] New regression tests pass: `pytest packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.overflow import OverflowStore
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator
from datetime import datetime


STORAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot" / "storage"


def test_artifacts_py_has_no_build_pk_reference():
    src = (STORAGE_DIR / "artifacts.py").read_text()
    assert "_build_pk" not in src


def test_chat_py_has_no_botocore_import():
    src = (STORAGE_DIR / "chat.py").read_text()
    assert "from botocore" not in src
    assert "import botocore" not in src


class _StubBackend(ConversationBackend):
    async def initialize(self): ...
    async def close(self): ...
    @property
    def is_connected(self): return True
    async def put_thread(self, *a, **kw): ...
    async def update_thread(self, *a, **kw): ...
    async def query_threads(self, *a, **kw): return []
    async def put_turn(self, *a, **kw): ...
    async def query_turns(self, *a, **kw): return []
    async def delete_turn(self, *a, **kw): return True
    async def delete_thread_cascade(self, *a, **kw): return 0
    async def put_artifact(self, *a, **kw): ...
    async def get_artifact(self, *a, **kw): return None
    async def query_artifacts(self, *a, **kw): return []
    async def delete_artifact(self, *a, **kw): ...
    async def delete_session_artifacts(self, *a, **kw): return 0


@pytest.mark.asyncio
async def test_artifact_store_uses_backend_overflow_prefix():
    backend = _StubBackend()
    backend.put_artifact = AsyncMock()
    backend.build_overflow_prefix = MagicMock(return_value="artifacts/USER#u#AGENT#a/THREAD#s/a1")

    overflow = MagicMock(spec=OverflowStore)
    overflow.maybe_offload = AsyncMock(return_value=({"k": "v"}, None))

    store = ArtifactStore(dynamodb=backend, s3_overflow=overflow)
    artifact = Artifact(
        artifact_id="a1",
        artifact_type=ArtifactType.CHART,
        title="t",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        created_by=ArtifactCreator.USER,
        definition={"k": "v"},
    )
    await store.save_artifact("u", "a", "s", artifact)

    backend.build_overflow_prefix.assert_called_once_with("u", "a", "s", "a1")
    overflow.maybe_offload.assert_awaited_once_with({"k": "v"}, "artifacts/USER#u#AGENT#a/THREAD#s/a1")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §7 "Leaky Abstractions to Repair".
2. **Check dependencies** — TASK-822, TASK-823, TASK-824 all in `sdd/tasks/completed/`.
3. **Re-read the current state** of `artifacts.py` and `chat.py` — line numbers in this task may have drifted one or two lines since the spec was written.
4. **Verify the Codebase Contract** — confirm `backend.delete_turn` and `backend.build_overflow_prefix` are present on `ConversationBackend` (they should be, from TASK-822 and TASK-824).
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
6. **Implement** artifacts.py first, then chat.py. Run tests after each file.
7. **Run the full sweep**:
   ```bash
   source .venv/bin/activate
   pytest packages/ai-parrot/tests/storage/ -v
   pytest packages/ai-parrot/tests/handlers/test_auto_save.py -v
   ```
8. **Move** this file to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
