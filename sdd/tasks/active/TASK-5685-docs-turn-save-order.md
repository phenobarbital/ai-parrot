# TASK-5685: Documentation — turn-save order and failure rules

**Feature**: FEAT-895 — Turn save — outbox first, one save at a time per session
**Spec**: `sdd/specs/bots-abstract-tech-debt-2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5684
**Assigned-to**: unassigned

---

## Context

The FEAT-886 pages state the old write path: `durable-conversation-memory.md` draws `add_turn` before
`TurnPublisher.publish`, says the turn is handed to the publisher "after `add_turn` succeeds", and says "A publish
failure inside the bot is logged at ERROR and never fails the round". `conversation-history-ownership.md` says
`save_conversation_turn` "publishes the raw turn after `add_turn`". TASK-5684 reverses the order, makes a rejected
append fail the round, adds best-effort invalidation and a per-session save lock. This task updates both pages and
pins the new text with a content test.

---

## Scope

- `wiki/memory/durable-conversation-memory.md`, `## Event flow`: swap the two `save_conversation_turn` branches in
  the diagram (publish first, then `add_turn`); rewrite the "After `add_turn` succeeds…" paragraph (outbox append
  first, the raw snapshot still precedes `add_turn`); replace the "never fails the round" sentence with the new
  failure rules: a rejected append fails the round with working memory untouched; a working-memory failure after
  the append fails the round and, with a hydration source, drops the session's working memory so the next request
  rehydrates it. Add one paragraph on the per-session save lock (in-process, shared by bot instances with one
  `memory_key_id`; answers still run concurrently; other pods rely on the sequence allocator). State that
  `ChatStorage`'s hot tier is its own `chat:` store, not the bot's working memory.
- `wiki/memory/conversation-history-ownership.md`, the "Emitter-owned ordering" bullet (`:202`): "publishes the raw
  turn to the outbox before `add_turn`, one save at a time per session".
- `packages/ai-parrot/tests/docs/test_durable_memory_docs.py`: add `test_turn_save_order_is_documented`.

**NOT in scope**: any code; other wiki pages; headings of the main page (the existing test pins them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/memory/durable-conversation-memory.md` | MODIFY | diagram order, two paragraphs, lock paragraph |
| `wiki/memory/conversation-history-ownership.md` | MODIFY | one bullet |
| `packages/ai-parrot/tests/docs/test_durable_memory_docs.py` | MODIFY | one content test appended |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test_durable_memory_docs.py already defines (verified: test_durable_memory_docs.py:10-19 at 098e0b08e3)
ROOT, WIKI, MAIN, PAGES  # MAIN = wiki/memory/durable-conversation-memory.md; PAGES includes
                         # wiki/memory/conversation-history-ownership.md
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/docs/test_durable_memory_docs.py
def test_page_exists_and_is_clean(page)  # forbids "TODO", "TASK-" and "worktree" in every page
def test_main_page_has_every_mandatory_heading()  # pins the eleven "## " headings — do not rename any
def test_documented_methods_and_settings_exist()  # every listed method/setting must stay named in the pages
```
- `wiki/memory/durable-conversation-memory.md:39` — `        +--> ConversationMemory.add_turn      (awaited)`
- `wiki/memory/durable-conversation-memory.md:41` — `        +--> TurnPublisher.publish            (optional)`
- `wiki/memory/durable-conversation-memory.md:50` — ``After `add_turn` succeeds, `AbstractBot.save_conversation_turn` hands the **raw, pre-normalization** turn, wrapped in a``
- `wiki/memory/durable-conversation-memory.md:60` — `never retried. A publish failure inside the bot is logged at ERROR and never fails the round.`
- `wiki/memory/conversation-history-ownership.md:202` — ``  `ConversationTurn.sequence`, and publishes the raw turn after `add_turn`. `ask`, `ask_stream`, `conversation` ``

### Does NOT Exist
- ~~a "Turn save" heading on the main page~~ — keep the new text inside `## Event flow`; adding a heading is
  allowed but the eleven pinned headings must stay.
- ~~a bus subscriber that writes the bot's working memory~~ — do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/memory/durable-conversation-memory.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/memory/conversation-history-ownership.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_durable_memory_docs.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- No "TODO", "TASK-" or "worktree" in either page (`test_page_exists_and_is_clean`).
- Plain sentences, present tense; no version claims of the form "shipped in **x**".

### References in Codebase
- Spec §1 Goals and §7 Known Risks — the exact rules the prose must state.

---

## Implementation Blueprint

### Steps (in order)
1. Append the content test and run it on the unmodified pages: it must FAIL — *why*: it pins the change.
2. Edit the diagram, the two paragraphs and the bullet — *why*: they state the old order and the old failure rule.
3. Run the Validation Commands and `parrot sdd techwiki check --spec sdd/specs/bots-abstract-tech-debt-2.spec.md --root .`.

### `wiki/memory/durable-conversation-memory.md` (MODIFY — `## Event flow`)
```text
# REPLACE the two diagram lines (verified: :39 and :41; occurrences: 1 each) so TurnPublisher.publish comes first:
        +--> TurnPublisher.publish            (optional, first: the outbox append)
        |                                      |  SqliteOutbox -> Redis Streams   (keep the existing relay lines)
        +--> ConversationMemory.add_turn      (awaited, after the append)
# FILL IN: the diagram's connector lines between them — keep column alignment, bounded by the existing drawing
# REPLACE the paragraph starting at :50 and the sentence at :60 — bounded by spec §1 Goals
```

### `wiki/memory/conversation-history-ownership.md` (MODIFY — :202)
```text
  `ConversationTurn.sequence`, and appends the raw turn to the outbox before `add_turn`, one save at a time per
  session. `ask`, `ask_stream`, `conversation`
```

### `packages/ai-parrot/tests/docs/test_durable_memory_docs.py` (MODIFY — append)
```python
def test_turn_save_order_is_documented():
    """FEAT-895: the outbox append precedes the working-memory write, and its failure fails the round."""
    main = MAIN.read_text(encoding="utf-8")
    ownership = (WIKI / "memory" / "conversation-history-ownership.md").read_text(encoding="utf-8")
    # FILL IN: assert the main page names the outbox append before add_turn, the failing round on a rejected
    #          append, the hydration-only invalidation and the per-session lock; assert neither page still says
    #          "publishes the raw turn after `add_turn`" nor "never fails the round" — bounded by spec §4 row
```

### FILL IN checklist
- [ ] Diagram connectors.
- [ ] The two rewritten paragraphs and the lock paragraph.
- [ ] Test assertions.

---

## Acceptance Criteria

- [ ] Both pages state the outbox-first order, the failure rules and the per-session lock.
- [ ] `test_turn_save_order_is_documented` fails on the unmodified pages and passes after the edit.
- [ ] `parrot sdd techwiki check --spec sdd/specs/bots-abstract-tech-debt-2.spec.md --root .` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/docs/test_durable_memory_docs.py -q`

> Also run (not a test-runner command, so not listed above): `parrot sdd techwiki check --spec sdd/specs/bots-abstract-tech-debt-2.spec.md --root .`

---

## Test Specification

See spec §4 Unit Tests (row for M2).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug bots-abstract-tech-debt-2 --feature-id FEAT-895`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5684 must be `done`
4. **Verify the Codebase Contract** before writing anything
5. **Update status** in `sdd/tasks/index/bots-abstract-tech-debt-2.json` → `"in-progress"` (set `started_at`) and
   commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit** — stage only the files listed above
9. **Close the task** with `parrot sdd task close TASK-5685 bots-abstract-tech-debt-2 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*
