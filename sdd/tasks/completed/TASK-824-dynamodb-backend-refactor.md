# TASK-824: Refactor ConversationDynamoDB to Implement ConversationBackend

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-822
**Assigned-to**: unassigned

---

## Context

Moves `ConversationDynamoDB` to `parrot/storage/backends/dynamodb.py`, makes it
a subclass of the new `ConversationBackend` ABC, adds the new `delete_turn()`
method (extracting logic that currently lives inline in `chat.py:572-582`),
and overrides `build_overflow_prefix` to keep the existing S3 key layout
byte-identical.

Implements **Module 3** of the spec (§3). AWS production behavior must remain
byte-identical — the only semantic change is the addition of `delete_turn` as a
public method.

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` by moving the full contents of `packages/ai-parrot/src/parrot/storage/dynamodb.py` there.
- Add `from parrot.storage.backends.base import ConversationBackend` and change the class declaration to `class ConversationDynamoDB(ConversationBackend):`.
- Add a new public `async def delete_turn(user_id, agent_id, session_id, turn_id) -> bool` method on the class. Its body is the DynamoDB-specific code currently inlined in `chat.py:572-582`.
- Override `build_overflow_prefix(user_id, agent_id, session_id, artifact_id) -> str` to return `f"artifacts/{self._build_pk(user_id, agent_id)}/THREAD#{session_id}/{artifact_id}"` — byte-identical to what `ArtifactStore` computes today at `artifacts.py:65-66`.
- Replace the contents of `packages/ai-parrot/src/parrot/storage/dynamodb.py` with a one-line shim: `from parrot.storage.backends.dynamodb import ConversationDynamoDB  # noqa: F401` plus `__all__ = ["ConversationDynamoDB"]`. This preserves backward-compatible imports.
- Add a new unit test file `packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py` covering:
  - `ConversationDynamoDB` is a subclass of `ConversationBackend`.
  - `delete_turn(...)` returns `True` on success and calls `_conv_table.delete_item` with the correct `Key={"PK": pk, "SK": "THREAD#<session>#TURN#<turn_id>"}`.
  - `delete_turn` returns `False` when not connected.
  - `build_overflow_prefix("u", "a", "s", "aid")` returns `"artifacts/USER#u#AGENT#a/THREAD#s/aid"` (matches the existing `ArtifactStore` layout).
  - Importing via the shim `from parrot.storage.dynamodb import ConversationDynamoDB` still works.
- All existing DynamoDB tests must continue to pass unchanged.

**NOT in scope**: Changes to `ChatStorage` or `ArtifactStore` (TASK-825). Factory wiring (TASK-829). New backends (TASKs 826–828). Observability (TASK-831).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` | CREATE | Moved + refactored class |
| `packages/ai-parrot/src/parrot/storage/dynamodb.py` | MODIFY | Becomes a re-export shim |
| `packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py` | CREATE | New unit tests for `delete_turn` + shim |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# For the refactored backend file — same as current dynamodb.py header:
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aioboto3
from botocore.exceptions import ClientError, BotoCoreError
from navconfig.logging import logging

from boto3.dynamodb.types import TypeSerializer, TypeDeserializer
from boto3.dynamodb.conditions import Key as DKey

# NEW:
from parrot.storage.backends.base import ConversationBackend   # from TASK-822
```

### Existing Signatures to Use

```python
# parrot/storage/dynamodb.py — the file being moved (study the full 600 lines)
class ConversationDynamoDB:                                                   # line 20
    DEFAULT_TTL_DAYS = 180                                                    # line 38

    @staticmethod
    def _build_pk(user_id: str, agent_id: str) -> str:                        # line 108
        return f"USER#{user_id}#AGENT#{agent_id}"

    # All 11 async public methods exist verbatim on lines 133-553.

# parrot/storage/chat.py — source of the delete_turn body to extract
# Lines 560-600 approximately:
# if not self._dynamo or not user_id or not agent_id:
#     return False
# pk = self._dynamo._build_pk(user_id, agent_id)
# sk = f"THREAD#{session_id}#TURN#{turn_id}"
# from botocore.exceptions import ClientError, BotoCoreError
# try:
#     await self._dynamo._conv_table.delete_item(Key={"PK": pk, "SK": sk})
# except (ClientError, BotoCoreError, Exception) as exc:
#     self.logger.warning("DynamoDB delete_turn failed for %s: %s", turn_id, exc)
#     return False
# ...

# parrot/storage/artifacts.py — shows the S3 key layout that must be preserved
# Line 65-66:
# pk = ConversationDynamoDB._build_pk(user_id, agent_id)
# key_prefix = f"artifacts/{pk}/THREAD#{session_id}/{artifact.artifact_id}"
```

### Does NOT Exist

- ~~`ConversationBackend.delete_turn` with a different signature~~ — it is `(user_id, agent_id, session_id, turn_id) -> bool`. Do NOT change.
- ~~A separate DynamoDB-specific exception class~~ — use `botocore.exceptions.ClientError` / `BotoCoreError` as today.
- ~~`ConversationBackend.__init__`~~ — there is no parent constructor; the subclass keeps its own `__init__(conversations_table, artifacts_table, dynamo_params)`.
- ~~A migration to `asyncdb[dynamodb]` driver~~ — explicitly deferred (spec §8 Q3, answered "keep aioboto3 in v1").

---

## Implementation Notes

### Pattern to Follow — Minimal-Diff Move

Step 1 — Create `parrot/storage/backends/dynamodb.py`:

```python
# parrot/storage/backends/dynamodb.py
# ... same imports as current parrot/storage/dynamodb.py plus:
from parrot.storage.backends.base import ConversationBackend


class ConversationDynamoDB(ConversationBackend):
    """(docstring unchanged from original)"""

    DEFAULT_TTL_DAYS = 180

    def __init__(self, conversations_table, artifacts_table, dynamo_params):
        # ... unchanged
        ...

    # ... ALL existing methods unchanged ...

    # NEW:
    async def delete_turn(
        self, user_id: str, agent_id: str, session_id: str, turn_id: str,
    ) -> bool:
        """Delete a single conversation turn."""
        if not self.is_connected:
            return False
        pk = self._build_pk(user_id, agent_id)
        sk = f"THREAD#{session_id}#TURN#{turn_id}"
        try:
            await self._conv_table.delete_item(Key={"PK": pk, "SK": sk})
            return True
        except (ClientError, BotoCoreError, Exception) as exc:
            self.logger.warning(
                "DynamoDB delete_turn failed for %s: %s", turn_id, exc,
            )
            return False

    # NEW — preserve byte-identical S3 key prefix layout:
    def build_overflow_prefix(
        self, user_id: str, agent_id: str, session_id: str, artifact_id: str,
    ) -> str:
        return (
            f"artifacts/{self._build_pk(user_id, agent_id)}"
            f"/THREAD#{session_id}/{artifact_id}"
        )
```

Step 2 — Replace `parrot/storage/dynamodb.py` with:

```python
"""Backward-compatible re-export shim for ConversationDynamoDB.

The class was moved to parrot.storage.backends.dynamodb in FEAT-116.
This shim is kept for one release cycle.
"""
from parrot.storage.backends.dynamodb import ConversationDynamoDB  # noqa: F401

__all__ = ["ConversationDynamoDB"]
```

### Key Constraints

- **Byte-identical behavior** on every existing method — do NOT refactor internals. `git diff` should only show: class declaration (add `(ConversationBackend)`), two new methods (`delete_turn`, `build_overflow_prefix`), and a new import.
- **`_build_pk` stays** — it is used by `artifacts.py` today (removed in TASK-825). Keep it as a staticmethod during this task.
- **Tests at `tests/storage/test_dynamodb_backend.py` and `tests/storage/test_chat_storage_dynamodb.py`** must pass unchanged (they import via `from parrot.storage.dynamodb import ConversationDynamoDB`, which still works via the shim).
- **Logger name unchanged** — `"parrot.storage.ConversationDynamoDB"` (`dynamodb.py:53`).

### References in Codebase

- `parrot/storage/dynamodb.py` — entire file (source of the move).
- `parrot/storage/chat.py:560-600` — source of the `delete_turn` body to extract.
- `parrot/storage/artifacts.py:65-66` and `:177-178` — the S3 key layout `build_overflow_prefix` must preserve.

---

## Acceptance Criteria

- [ ] `parrot/storage/backends/dynamodb.py` exists and `ConversationDynamoDB` there is a subclass of `ConversationBackend`.
- [ ] `ConversationDynamoDB.delete_turn(...)` exists, returns `bool`, and calls `_conv_table.delete_item` with the correct key.
- [ ] `ConversationDynamoDB.build_overflow_prefix("u", "a", "s", "aid") == "artifacts/USER#u#AGENT#a/THREAD#s/aid"`.
- [ ] `parrot/storage/dynamodb.py` is a one-line shim re-exporting `ConversationDynamoDB`.
- [ ] `from parrot.storage.dynamodb import ConversationDynamoDB` still works.
- [ ] `from parrot.storage.backends.dynamodb import ConversationDynamoDB` also works.
- [ ] All existing tests pass unchanged:
  ```bash
  source .venv/bin/activate
  pytest packages/ai-parrot/tests/storage/test_dynamodb_backend.py -v
  pytest packages/ai-parrot/tests/storage/test_chat_storage_dynamodb.py -v
  pytest packages/ai-parrot/tests/storage/test_artifact_store.py -v
  pytest packages/ai-parrot/tests/storage/test_integration_artifact_persistence.py -v
  pytest packages/ai-parrot/tests/handlers/test_auto_save.py -v
  ```
- [ ] New tests pass: `pytest packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.dynamodb import ConversationDynamoDB


def test_is_subclass_of_conversation_backend():
    assert issubclass(ConversationDynamoDB, ConversationBackend)


def test_shim_still_imports():
    from parrot.storage.dynamodb import ConversationDynamoDB as Shimmed
    assert Shimmed is ConversationDynamoDB


def test_build_overflow_prefix_matches_existing_s3_layout():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    assert (
        backend.build_overflow_prefix("u", "a", "s", "aid")
        == "artifacts/USER#u#AGENT#a/THREAD#s/aid"
    )


@pytest.mark.asyncio
async def test_delete_turn_not_connected_returns_false():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    # _conv_table is None by default → is_connected == False
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_turn_calls_delete_item():
    backend = ConversationDynamoDB("conv", "art", {"region_name": "us-east-1"})
    backend._conv_table = MagicMock()
    backend._art_table = MagicMock()
    backend._conv_table.delete_item = AsyncMock(return_value={})
    ok = await backend.delete_turn("u", "a", "s", "t1")
    assert ok is True
    backend._conv_table.delete_item.assert_awaited_once_with(
        Key={"PK": "USER#u#AGENT#a", "SK": "THREAD#s#TURN#t1"}
    )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §3 Module 3 and §7 "Known Risks — S3 key prefix back-compat".
2. **Read the full `parrot/storage/dynamodb.py`** — this is a move, behavior must be byte-identical.
3. **Read `chat.py` lines 560-600** to understand the `delete_turn` body you're extracting.
4. **Check dependencies** — TASK-822 must be in `sdd/tasks/completed/`.
5. **Verify the Codebase Contract**.
6. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
7. **Implement** — do the move first, commit, then add `delete_turn`, then `build_overflow_prefix`, then replace the old file with the shim.
8. **Run the full test sweep** listed in Acceptance Criteria.
9. **Move** this file to `sdd/tasks/completed/`.
10. **Update index** → `"done"`.
11. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
