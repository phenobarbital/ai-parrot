# TASK-4551: ChatStorage Redis hot tier keeps caller metadata

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 / design research S12. `ChatStorage.save_turn` stores caller `metadata` in the cold tier but builds the Redis `ConversationTurn` with a fixed dict, so `usage`/`cost_usd`/`tenant`/`agent` are lost on hot-tier reads.

---

## Scope

- Merge the caller `metadata` into the hot-tier `ConversationTurn.metadata`, fixed keys win: `{**(metadata or {}), "output_mode": ..., ...}`.
- Write tests.

**NOT in scope**: AgentTalk passing metadata (TASK-4552).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | Merge caller metadata into the Redis ConversationTurn |
| `packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.storage.chat import ChatStorage  # verified: storage/chat.py (save_turn at :106)
from parrot.memory.abstract import ConversationTurn  # verified: lazy import in storage/chat.py:183
```

### Existing Signatures to Use
```python
# storage/chat.py
async def save_turn(self, *, turn_id=None, user_id, session_id, agent_id, user_message, assistant_response, ...,
                    metadata: Optional[Dict[str, Any]] = None) -> str     # :106-125
turn = ConversationTurn(..., metadata={"output_mode": output_mode, "model": model, "provider": provider,
                                       "response_time_ms": response_time_ms})   # :187-199
```

### Does NOT Exist
- ~~`ChatStorage.save_turn_metadata`~~ — no such method

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/chat.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.save_turn"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Change the hot-tier metadata literal to a merge — *why*: caller keys survive, and the fixed keys keep their current meaning.
2. Write the test with a fake Redis/memory backend.

### `packages/ai-parrot/src/parrot/storage/chat.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"response_time_ms": response_time_ms,' packages/ai-parrot/src/parrot/storage/chat.py)
# REPLACE the `metadata={...}` argument of `turn = ConversationTurn(` (:193-198) with:
                    metadata={
                        **(metadata or {}),
                        "output_mode": output_mode,
                        "model": model,
                        "provider": provider,
                        "response_time_ms": response_time_ms,
                    },
```

### `packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py` (CREATE)
```python
"""FEAT-710 TASK-4551 — hot tier keeps caller metadata."""
import pytest


@pytest.mark.asyncio
async def test_hot_tier_turn_contains_usage_and_tenant() -> None:
    # FILL IN: ChatStorage with a stubbed Redis conversation memory (pattern: packages/ai-parrot/tests/test_chat_storage.py);
    #          save_turn(metadata={"usage": {"total_tokens": 3}, "tenant": "t1"}); assert the stored ConversationTurn.metadata has both
    #          plus output_mode — AC-1
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Test body — AC-1

---

## Acceptance Criteria

- [ ] The Redis `ConversationTurn.metadata` contains caller keys and the four fixed keys (fixed keys win on conflict).
- [ ] Existing chat storage tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py -q`
- `pytest packages/ai-parrot/tests/test_chat_storage.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4551 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note



**Completed by**: sdd-worker orchestrator (coder: nova/zai.glm-4.7-flash)
**Date**: 2026-10-22
**Notes**: Delivered, merged and merge-tier validated green (no review fixes needed).

**Deviations from spec**: none
