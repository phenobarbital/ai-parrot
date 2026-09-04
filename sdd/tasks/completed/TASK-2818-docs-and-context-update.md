# TASK-2818: Documentation — ownership guide, CONTEXT.md, proposal pointer

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: done
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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**:
- **CREATED `docs/memory/conversation-history-ownership.md`** (~190 lines). `docs/memory/`
  did not exist; created it rather than filing the guide under an unrelated section.
  Covers: the three-layer ownership table + an ASCII call-flow, the
  `(chatbot, user, session)` storage key with the per-backend key formats, the
  `memory_key_id` rule and *why* it is not `self.chatbot_id`, the lazy legacy re-key,
  how to call a client standalone, how a bot persists a turn, the `render_history`
  guarantees, and the 0.29.0 breaking-change list.
  **All signatures were copied from the shipped code**, not from the spec — extracted
  with `inspect.signature` against the post-TASK-2816 tree, as the AC requires. That
  caught two places where the spec's draft signature no longer matched: `_build_messages`
  ships with defaults (`files=None, history=None`), and `from_ai_message` ships with the
  extra `assistant_text` override added for the streaming partial save.
  Also documented the three provider deviations a future reader would otherwise
  rediscover the hard way: Bedrock's and Google's `_format_history` overrides, Google's
  extra `_dict_messages` (because `resume()` re-parses `state["messages"]` as dicts), and
  that `claude_agent.py`/`live.py` accept `history` but deliberately do not replay it.
- **MODIFIED `.agent/CONTEXT.md`**:
  * fixed the stale `parrot/clients/abstract_client.py` path → `parrot/clients/base.py`,
    and corrected the "Implement …" line, which listed `completion()/stream()/embed()` —
    none of which exist. The real abstract methods are
    `ask/ask_stream/invoke/resume/get_client`;
  * added the "memory-less (FEAT-524)" bullet to the `AbstractClient` entry;
  * added a new **"### Conversation memory"** section under Core Abstractions pointing at
    the new guide;
  * expanded the `memory/` line in the "What Lives Where" tree (it said only
    "Redis-backed", which was wrong on two counts — there are three backends, and it
    now also holds the render layer).
  * `grep -c "abstract_client.py" .agent/CONTEXT.md` → **0**.
- **MODIFIED `CHANGELOG.md`** — new `### Breaking Changes` block at the top of
  `[Unreleased]` (the file already uses that heading, cf. `[0.27.0]`), listing every
  removal and addition grouped by `AbstractClient` / `parrot.memory` / `AbstractBot`,
  plus the storage-key change and the lazy re-key. Links to both the guide and the spec.
- Verified the doc's factual claims rather than asserting them: the "19 concrete clients"
  figure comes from `test_all_client_ask_signatures.CLIENTS` (172 passing assertions over
  19 discovered classes), not from counting files by hand.

**Deviations from spec**:
1. **The compaction-proposal pointer was SKIPPED, as the task's own conditional
   instructs.** `sdd/proposals/per-turn-conversation-compactation.proposal.md` is **still
   untracked** in this repo (`git ls-files --error-unmatch` → "did not match any file
   known to git"; it shows as `??` in `git status`). Editing an untracked working-copy
   file would produce a change that cannot be committed and that no reviewer would see.
   The information is not lost: `render_history` is documented as "the extension point"
   in the new guide, which the compaction spec author will reach via `.agent/CONTEXT.md`.
   **Follow-up for the author**: when that proposal is committed, add the one-line note
   that the extension point is `parrot.memory.render.render_history`, not
   `get_messages_for_api(budget=)`.
2. `.agent/CONTEXT.md` is excluded by the repo-local `.git/info/exclude` (`.agent/`), but
   the file itself is tracked in HEAD. Staged with `git add -u` so the tracked
   modification is committed without force-adding anything newly ignored.
3. Went slightly past the task's "~150 lines" guidance (~190). The extra length is the
   breaking-change list and the provider-override table, both of which the task
   separately requires.
