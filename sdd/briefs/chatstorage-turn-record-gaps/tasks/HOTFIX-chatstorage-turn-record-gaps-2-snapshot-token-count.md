# HOTFIX-chatstorage-turn-record-gaps-2: The turn event snapshot carries a token count

**Feature**: chatstorage-turn-record-gaps — close the turn-record gaps between conversation history and ChatStorage
**Spec**: `sdd/briefs/chatstorage-turn-record-gaps.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`AbstractBot.save_conversation_turn` snapshots the turn raw, before `ConversationMemory.add_turn`
normalizes and counts it. The cold ChatStorage row is written from that snapshot, so it has
`token_count: null` while history and the hot tier carry a count (brief, Problem 2). Decision 1 of
the brief: count the raw snapshot.

## Scope

In `packages/ai-parrot/src/parrot/bots/abstract.py`, inside `save_conversation_turn`:

- Right after the snapshot is taken, when `snapshot is not None` and `snapshot["token_count"]` is
  `None`, set `snapshot["token_count"] = count_turn(turn, self.conversation_memory.token_counter).to_dict()`.
- Write the count into the **snapshot dict only**. Do not assign `turn.token_count`: `add_turn`
  must keep counting the normalized turn exactly as it does today.
- A counting failure must not lose the turn: catch `Exception`, log at WARNING with the turn id, and
  leave `snapshot["token_count"]` as `None`.
- Keep the snapshot before `add_turn` (the existing comment on that line still holds).

**NOT in scope**: `ConversationMemory.add_turn`, `count_turn`, `ChatStorageTurn`, the hot tier, any
change when no `turn_publisher` is set.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Stamp a token count on the raw event snapshot |
| `packages/ai-parrot/tests/unit/bots/test_turn_snapshot_token_count.py` | CREATE | Regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 80cc849fac, 2026-11-17)

- `packages/ai-parrot/src/parrot/bots/abstract.py:3003` — `# Raw, pre-normalization snapshot: MUST precede add_turn (spec §7 "Raw turn snapshot").`
- `packages/ai-parrot/src/parrot/bots/abstract.py:3004` — `snapshot = copy.deepcopy(turn.to_dict()) if self.turn_publisher is not None else None`
- `packages/ai-parrot/src/parrot/memory/compaction/tokens.py:119` — `def count_turn(turn: ConversationTurn, counter: TokenCounter) -> TokenCount:`
- `ConversationMemory.token_counter` is a property (`packages/ai-parrot/src/parrot/memory/abstract.py:425`).
- `TokenCount.to_dict()` exists; `ConversationTurn.to_dict()` emits `"token_count"` (`None` when unset).
- `ChatStorageTurn.from_event_payload` reads `turn.get("token_count")` (`packages/ai-parrot/src/parrot/storage/models.py`).
- Existing pattern for bot-level turn tests: `packages/ai-parrot/tests/unit/bots/test_memory_key_id.py`.

### Does NOT Exist

- No `AbstractBot._count_turn` helper and no token-count field on `TurnPresentation`.

## Acceptance Criteria

- [ ] **AC-1**: With a `turn_publisher` set, the published event's `turn["token_count"]` is a dict
      with `user`, `assistant`, `tools`, `total` and `tokenizer`, and `total > 0`.
- [ ] **AC-2**: The count stored in conversation history for the same turn is identical to the count
      stored when no `turn_publisher` is set (the working-memory write is unchanged).
- [ ] **AC-3**: With no `turn_publisher`, no counting happens before `add_turn` (no snapshot, no event).
- [ ] **AC-4**: If the counter raises, the turn is still published and saved, with `token_count: None`.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/bots/test_turn_snapshot_token_count.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/bots/test_memory_key_id.py -q`

## Agent Instructions

1. Work in this worktree only; verify every anchor above before editing.
2. `ruff check --fix` and `black -l 120` on the two files; run the validation commands.
3. Commit only the two listed files: `fix(chatstorage-turn-record-gaps): HOTFIX-chatstorage-turn-record-gaps-2 — snapshot token count`.

## Completion Note

Pending.
