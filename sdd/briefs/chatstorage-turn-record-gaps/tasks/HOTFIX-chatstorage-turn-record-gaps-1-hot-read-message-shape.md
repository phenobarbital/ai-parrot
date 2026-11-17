# HOTFIX-chatstorage-turn-record-gaps-1: Hot-tier reads return the same message shape as cold reads

**Feature**: chatstorage-turn-record-gaps — close the turn-record gaps between conversation history and ChatStorage
**Spec**: `sdd/briefs/chatstorage-turn-record-gaps.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`ChatStorage.load_conversation` reads Redis first. On that path it builds the user and assistant
message dicts by hand with a reduced key set, while the cold path returns
`ChatStorageTurn.to_messages()`. A caller therefore loses the tool invocations, usage, cost, model
and timing fields whenever the hot tier answers (brief, Problem 1).

## Scope

In `packages/ai-parrot/src/parrot/storage/chat.py`:

- Replace the hand-built dicts in the hot branch of `load_conversation` with one helper,
  `_hot_turn_messages(turn: ConversationTurn) -> List[Dict[str, Any]]` (a `@staticmethod` on
  `ChatStorage`), that returns the user and assistant dicts with **the same keys**
  `ChatStorageTurn.to_messages()` returns.
- Source of each assistant field on the hot path:
  - `tool_invocations`: `[inv.to_dict() for inv in turn.tool_invocations]`
  - `tool_calls`: the legacy projection `{name, status, output, arguments}` built from those dicts,
    exactly as `to_messages()` does
  - `tools_used`, `error`, `sequence`: from the turn (`sequence` is `turn.sequence or 0`)
  - `model`, `provider`, `response_time_ms`, `usage`, `cost_usd`, `tenant`, `output_mode`: from
    `turn.metadata` (written there by `ChatStorage._hot_tier_turn`); absent key → `None`
  - `output`, `data`, `code`: `None`; `sources`: `[]` (the hot tier does not hold them)
  - `schema_version`: `turn.schema_version`
  - `metadata`: `dict(turn.metadata)`
- The user dict keeps `role`, `content`, `timestamp`, `turn_id`. It no longer carries `metadata`
  (the cold path does not return it on the user message).
- Timestamps stay ISO-8601 strings, as today.

**NOT in scope**: `_load_cold`, `ChatStorageTurn`, the hot-tier write path, widening what the hot
tier stores, any handler that consumes these messages.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `_hot_turn_messages` helper; hot branch of `load_conversation` uses it |
| `packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py` | MODIFY | Tests for the hot-read message shape |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 80cc849fac, 2026-11-17)

- `packages/ai-parrot/src/parrot/storage/chat.py:378` — `async def load_conversation(`
- `packages/ai-parrot/src/parrot/storage/chat.py:432` — `"tools_used": turn.tools_used,` (inside the hand-built assistant dict)
- `packages/ai-parrot/src/parrot/storage/chat.py:475` — `messages.extend(stored.to_messages())` (cold path)
- `ChatStorage._hot_tier_turn(turn: ChatStorageTurn) -> ConversationTurn` (same file) merges
  `output_mode`, `model`, `provider`, `response_time_ms` and, when not `None`, `usage`, `tenant`,
  `cost_usd` into `ConversationTurn.metadata`.
- `ChatStorageTurn.to_messages()` in `packages/ai-parrot/src/parrot/storage/models.py` — assistant
  keys: `role`, `content`, `timestamp`, `turn_id`, `output`, `output_mode`, `data`, `code`, `model`,
  `provider`, `response_time_ms`, `tool_calls`, `sources`, `metadata`, `tools_used`,
  `tool_invocations`, `usage`, `cost_usd`, `tenant`, `error`, `sequence`, `schema_version`.
- `ConversationTurn` (`packages/ai-parrot/src/parrot/memory/abstract.py`) fields used here:
  `tool_invocations: List[ToolInvocation]`, `tools_used`, `error`, `sequence: Optional[int]`,
  `schema_version: int`, `metadata: Dict[str, Any]`.
- `ToolInvocation.to_dict()` exists (`packages/ai-parrot/src/parrot/memory/compaction/models.py:49`).

### Does NOT Exist

- No `ConversationTurn.to_messages()` and no `ChatStorageTurn.from_conversation_turn()`.
- The hot tier does not store `output`, `data`, `code` or `sources`.

## Acceptance Criteria

- [ ] **AC-1**: For one turn with a tool invocation stored through `ChatStorage.store_turn`, the
      assistant message returned by a hot-tier `load_conversation` has exactly the same key set as
      the one returned by the cold path for the same turn.
- [ ] **AC-2**: On the hot path `tool_invocations`, `tool_calls`, `usage`, `model`, `provider` and
      `response_time_ms` equal the cold-path values for that turn.
- [ ] **AC-3**: A hot turn whose metadata lacks `usage` / `cost_usd` / `tenant` yields `None` for
      those keys, not a `KeyError`.
- [ ] **AC-4**: Existing tests in `test_chat_hot_tier_metadata.py` and
      `test_chat_storage_hot_tier_seed.py` still pass.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/storage/test_chat_storage_hot_tier_seed.py -q`

## Agent Instructions

1. Work in this worktree only; verify every anchor above before editing.
2. `ruff check --fix` and `black -l 120` on the two files; run the validation commands.
3. Commit only the two listed files: `fix(chatstorage-turn-record-gaps): HOTFIX-chatstorage-turn-record-gaps-1 — hot-read message shape`.

## Completion Note

Pending.
