# TASK-2175: Migrate envelope fixtures in ai-parrot-integrations and ai-parrot-server tests

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-2174
**Assigned-to**: unassigned
**Parallel-safe**: no — Must follow the handler migration; touches two other distributions' test suites.

---

## Context

The envelope break lands with no deprecation window (spec §5), so every test
that constructs `metadata={"user_transcription": …}` fixtures fails the moment
TASK-2167 removes the producer. Those tests live in two distributions other than
the one the change "belongs" to — leaving them red would make the feature look
like it broke unrelated packages.

Note that `ai-parrot-server` has no voice handler in its source: it only mounts
`VoiceChatHandler` (`parrot/manager/manager.py:1528-1550`). Only its *tests*
touch the envelope.

Implements: **Spec §3 Module 10**.

---

## Scope

- Migrate `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py:156-169`
  (`test_user_transcription_still_forwarded`) to the canonical envelope.
- Migrate `packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py`
  (`:200`, `:242-245`) to construct `role="user"` responses.
- Migrate `packages/ai-parrot-server/tests/handlers/test_voice_ws_stt_only_integration.py:207`
  likewise.
- Grep the whole repository afterwards and confirm zero remaining
  `user_transcription` references outside historical SDD artifacts.

**NOT in scope**: production code — all of it is migrated by TASK-2167/2173/2174.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py` | MODIFY | Canonical-role fixture |
| `packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py` | MODIFY | Canonical-role fixtures |
| `packages/ai-parrot-server/tests/handlers/test_voice_ws_stt_only_integration.py` | MODIFY | Canonical-role fixture |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.live import LiveVoiceResponse      # clients/live.py
from parrot.voice.handler import VoiceChatHandler      # handler.py:388
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py
async def test_user_transcription_still_forwarded(self, handler, connection):   # line 156
    """...preserved."""                                                        # line 158
    ... metadata={"user_transcription": "what's the weather"},                   # line 169

# packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py
    metadata={"user_transcription": text},                                       # line 200
async def test_stt_only_emits_user_transcription():                              # line 242

# packages/ai-parrot-server/tests/handlers/test_voice_ws_stt_only_integration.py
    metadata={"user_transcription": text},                                       # line 207

# packages/ai-parrot-server/src/parrot/manager/manager.py
    from parrot.voice.handler import VoiceChatHandler                            # line 1539
    handler = VoiceChatHandler()                                                 # line 1548
    # "VoiceChatHandler registered at /ws/voice (Mode D)."                       # line 1550
```

### Does NOT Exist

- ~~A voice handler class in `ai-parrot-server`~~ — it only mounts the integrations one (`manager.py:1528-1550`). Do not create or migrate server-side handler code.
- ~~Other `user_transcription` sites~~ — the complete set is 8: `clients/live.py:875`, `bots/voice.py:583-584`, `handler.py:1481`/`:1614`, `chat.html:1096`, and these three test files. Verify with a repo-wide grep; do not assume more exist.
- ~~A compatibility shim to keep old tests green~~ — explicitly rejected: no deprecation window (spec §5).

---

## Implementation Notes

### Key Constraints
- Rename tests whose names assert the old behavior (e.g.
  `test_user_transcription_still_forwarded`) so the suite does not document a
  contract that no longer exists.
- Run all three distributions' suites, not just the one you edited.
- The final grep is part of the deliverable: `user_transcription` must survive
  only in `sdd/` historical artifacts.

---

## Acceptance Criteria

- [ ] All three test files construct canonical-envelope fixtures
- [ ] Tests asserting the old contract are renamed to describe the new one
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/ -v` passes
- [ ] `pytest packages/ai-parrot-server/tests/handlers/ -v` passes
- [ ] `pytest packages/ai-parrot/tests/ -v` passes
- [ ] `grep -rn "user_transcription" --include=*.py --include=*.html --include=*.md .` returns hits only under `sdd/`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py (migrated shape)

def _stt_response(text: str):
    """Canonical envelope: the user's transcription is a role='user' response,
    not a metadata key (FEAT-418)."""
    return LiveVoiceResponse(text=text, role="user")


async def test_stt_only_emits_user_transcription():
    """A role='user' response is forwarded as a transcription frame."""
    ...
    assert frame == {"type": "transcription", "text": text, "is_user": True}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/googlelive-nova2-audiobot-homologation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
