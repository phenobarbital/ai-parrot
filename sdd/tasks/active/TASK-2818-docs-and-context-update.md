# TASK-2818: Documentation — ownership guide, CONTEXT.md, proposal pointer

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2816
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. The new ownership model must be discoverable by the next
agent or human: a short guide in `docs/`, the architecture context updated
(its `AbstractClient` entry still points at a file that does not exist), and
the compaction proposal told where its extension point now lives.

---

## Scope

- CREATE `docs/memory/conversation-history-ownership.md`: the three-layer
  model (store+render / orchestrate+record / format+call), `memory_key_id`
  rule and the storage key `(chatbot, user, session)`, lazy legacy re-key,
  how to call a client standalone (memory-less, pass `history=` if you have
  one), how a bot persists a turn, the `render_history` guarantees, and a
  "breaking changes in 0.29.0" list (removed client ctor kwarg, removed
  `user_id`/`session_id`, removed `*_conversation()` helpers, removed
  `get_messages_for_api`, removed `build_conversation_context`).
- MODIFY `.agent/CONTEXT.md`: `AbstractClient` section — fix the path
  (`parrot/clients/base.py`, not `abstract_client.py`), add "memory-less;
  receives `history: Sequence[HistoryMessage]`"; add a one-paragraph
  "Conversation memory" entry pointing at the new doc.
- MODIFY `sdd/proposals/per-turn-conversation-compactation.proposal.md`
  (**only if it is tracked by git at task time** — on 2026-09-04 it was
  untracked in the author's working copy; if still untracked, skip and say
  so): add a one-line note that the render extension point is
  `parrot.memory.render.render_history`, not `get_messages_for_api(budget=)`.
- Release notes: add the breaking-change entry wherever the repo keeps them
  (`grep -ril "changelog\|release notes" docs/ *.md | head`); if there is no
  changelog file, put the list in the new doc only and say so.

**NOT in scope**: code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/memory/conversation-history-ownership.md` | CREATE | guide |
| `.agent/CONTEXT.md` | MODIFY | AbstractClient path + memory entry |
| `sdd/proposals/per-turn-conversation-compactation.proposal.md` | MODIFY (conditional) | pointer to `render_history` |
| changelog (if any) | MODIFY | 0.29.0 breaking changes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory import HistoryMessage, render_history   # TASK-2809
```

### Existing Signatures to Use
```
.agent/CONTEXT.md — "### AbstractClient" block says: Location: `parrot/clients/abstract_client.py`  ← wrong; real: packages/ai-parrot/src/parrot/clients/base.py:230
.agent/CONTEXT.md — "What Lives Where" tree lists `memory/  # Conversation memory (Redis-backed)`
docs/ — check for an existing memory/ or architecture section before creating a new folder (`ls docs`)
```

### Does NOT Exist
- ~~`parrot/clients/abstract_client.py`~~ — the doc must stop claiming it.
- ~~`docs/memory/`~~ — may not exist yet; create it or place the file under the closest existing docs section and note the choice.

---

## Implementation Notes

- Keep the guide under ~150 lines; link to the spec for rationale.
- Write for the implementing agent of the compaction feature: they need `render_history`'s signature and guarantees verbatim.

---

## Acceptance Criteria

- [ ] Guide exists and matches the shipped code (signatures copied from the source, not from the spec).
- [ ] `.agent/CONTEXT.md` no longer mentions `abstract_client.py`; describes clients as memory-less.
- [ ] Proposal pointer added, or skipped with reason in the note.
- [ ] Breaking-change list present.

---

## Test Specification

Docs task — no tests. Optional: `python -c "import parrot.memory.render as r; help(r.render_history)"` to copy the docstring.

---

## Agent Instructions

1. Read spec §2 Overview + §8. 2. Read the shipped code (post-TASK-2816) before writing. 3. Commit only the listed files.
4. Move to `completed/`, update index (this may be the last task — set the index header `completed_at` only if `/sdd-done` policy says so; otherwise leave it to `/sdd-done`), fill note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
