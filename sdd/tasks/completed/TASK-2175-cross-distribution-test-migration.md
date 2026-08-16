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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-07
**Notes**: `test_handler_refactor.py`'s `test_user_transcription_still_forwarded`
was already migrated to `role="user"` in TASK-2174 (it's the same
`_HandlerVoiceSession._relay` test the handler-migration task itself
needed to fix as part of that task's own scope) — no further change
needed here for that file. Migrated `test_agent_voice_stt_only.py`'s
`_transcription_response()` and `test_voice_ws_stt_only_integration.py`'s
`_make_transcription_response()` fixtures from
`metadata={"user_transcription": text}` to `LiveVoiceResponse(text=text,
role="user")`. Updated the stale docstring on
`test_stt_only_emits_user_transcription` (mentioned the old metadata key)
— left the test's NAME unchanged since its body only ever asserted the
output WIRE frame shape (`{"type": "transcription", "is_user": True}`),
which is unaffected by the envelope change; only the docstring described
the old internal representation. Final repo-wide grep (both a loose
substring pass and a stricter functional-access-pattern pass for
`metadata.get("user_transcription")`/`metadata["user_transcription"]`)
confirms zero remaining functional reads outside `sdd/` — every surviving
hit is a comment/docstring/identifier documenting the migration, or a
historical `sdd/` artifact (including two unrelated older spec files,
`nova-sonic-protocol-fidelity.spec.md` and
`livekit-gemini-voice-input.spec.md`, from earlier features — untouched,
out of this feature's scope).

**Two collateral bugs found and fixed while running these test files**
(both squarely inside the two files this task explicitly authorizes):
1. `test_agent_voice_stt_only.py`'s two `_build_live_config()` unit tests
   construct a `GeminiLiveClient.__new__(GeminiLiveClient)` bypassing
   `__init__`, then manually set a handful of attributes. TASK-2166 added
   a `self.top_p` fallback read and TASK-2168 added a
   `self._resumption_handle` read inside `_build_live_config()` —  neither
   attribute existed on these bypassed-`__init__` test doubles, causing
   `AttributeError`. Added `client.top_p = None` and
   `client._resumption_handle = None` to both tests' manual setup.
2. Also added `"SessionResumptionConfig"` to this file's local
   `google.genai.types` stub (TASK-2168 added
   `types.SessionResumptionConfig(...)` to `_build_live_config()`'s
   `LiveConnectConfig` construction; the stub previously lacked it).

**Pre-existing, unrelated failure — confirmed NOT caused by this feature**:
`test_voice_ws_stt_only_integration.py::test_voice_ws_stt_only_session`
and `::test_voice_ws_full_duplex_session` fail both before and after this
feature's changes (reproduced by checking out `handler.py` from the
commit immediately preceding TASK-2174, `6f0f5bb5d`, and re-running —
identical 2 failures). Root cause: the test only calls
`_handle_start_session()` and then waits for `connection.voice_task` to
finish — it never calls `start_turn()`/`push_audio()`/`end_turn()` (or
equivalent), which has been required to drive a turn since TASK-2152's
`VoiceSession`-based refactor (a prior, unrelated feature). The mocked
`bot.ask_stream` is therefore never invoked at all, so no
`response_chunk`/`transcription` frame is ever produced —
architecturally unrelated to the envelope/role migration. Per Cardinal
Rule 5 (no scope creep) and this task's own explicit scope (migrate the
ONE fixture line, not the test's turn-lifecycle-driving logic), I did not
attempt to rewrite this test's flow. Flagging explicitly rather than
silently leaving it red or silently "fixing" architecture this task
doesn't own.

---

## Follow-up (2026-08-07) — the pre-existing failure is now FIXED

The two `test_voice_ws_stt_only_integration.py` failures documented above
are resolved; the file's `[done-with-issues]` state is cleared.

**Root cause** (exactly as triaged above): since FEAT-416 (TASK-2152),
`_run_voice_session()` no longer drives turns — it constructs
`connection.voice_session` and idles until shutdown. The turn lifecycle is
driven by the client frames `start_recording` → `audio_data` →
`stop_recording`, which map onto `VoiceSession.start_turn()` /
`push_audio()` / `end_turn()`. Both tests called only
`_handle_start_session()`, so `bot.ask_stream` was never invoked and no
frame was ever produced.

**Fix** (test-only — no production code changed): added
`_drive_one_turn()`, which sends the real client frame sequence, plus
`_await_voice_session()` (waits for the voice task to construct the
session) and `_await_voice_task()`. `_handle_stop_recording`'s 500 ms
`MIN_DURATION_MS` guard is cleared by backdating
`connection.recording_start_time` rather than sleeping. Both mocks now
consume the audio iterator until the `None` end-of-turn sentinel, so they
reply only after `end_turn()` — as a real provider does.

**Assertions strengthened** (from an adversarial Codex review, which
warned the repaired tests could still pass over real bugs). They now also
assert that the mic audio actually reached the provider's iterator, that
`stt_only` propagates through `_AskStreamVoiceClient.stream_voice()` into
`ask_stream()`, that the voice task exits on its own rather than being
cancelled, and that STT-only suppresses *every* model-output branch
(assistant transcription / `display_data` / `tool_call` /
`response_complete`), not just `response_chunk`.

**Verified by mutation testing** — each of these breaks the suite:
not driving the turn (the original bug), dropping the `push_audio()` call,
and dropping `stt_only` propagation.

Suite status: `ai-parrot-server/tests/handlers/` 227 passed,
`ai-parrot-integrations/tests/voice/` 136 passed.

**Two unrelated pre-existing failures found while verifying** (NOT caused
by and NOT in scope for FEAT-418; both confirmed identical before the
feature merge `8bc3a8fa4`):
1. `ai-parrot-server/tests/handlers/test_mode_a_e2e.py::test_mode_a_start_chat_stop`
   — **FIXED on 2026-08-07 at the user's request.** Its module-level env
   gate ("skip unless LiveAvatar/LiveKit credentials are set") was
   defeated on a developer machine because navconfig loads `env/.env`,
   which supplies all five credentials plus `LIVEAVATAR_SANDBOX=False`, as
   soon as any `parrot.handlers.*` module is imported. The gate then
   passed and the test tried to reach a live server at `localhost:8080`.
   It skipped correctly standalone and on CI, which made it look like a
   test-ordering bug rather than config injection.

   Fix: credential presence is not a statement of intent, so the module is
   now gated on an explicit `RUN_MODE_A_E2E=1` opt-in evaluated *before*
   the credential check, and carries `pytestmark = pytest.mark.live`
   (marker registered in `ai-parrot-server`'s `pyproject.toml` and
   `tests/conftest.py`, matching the repo's existing `@pytest.mark.live`
   convention) so `-m "not live"` deselects it. Verified: full handlers
   suite 227 passed + 1 skipped; standalone skips citing the opt-in;
   `RUN_MODE_A_E2E=1` standalone skips citing missing credentials;
   `RUN_MODE_A_E2E=1` on the full dir reaches the test (fails on connect,
   correctly, with no server running); `-m "not live"` deselects it.
2. `ai-parrot/tests/voice/test_voice_session.py::TestVoiceSession::test_no_aiohttp_import`
   — asserts the literal string `aiohttp` is absent from `session.py`'s
   source, but it appears in the class *docstring* added by FEAT-416
   TASK-2149 (`git log -S` confirms; the mention count is 2 both at
   `8bc3a8fa4^1` and `8bc3a8fa4`). The test should check imports, not grep
   raw source.

---

**Deviations from spec**: none for the two fixture migrations that are
this task's actual scope. The two collateral `_build_live_config()`
attribute/stub fixes above were necessary to make
`test_agent_voice_stt_only.py` (a file this task explicitly modifies)
pass at all — not a scope violation, but flagged per the file-fidelity
principle. The pre-existing integration-test failure above was
NOT fixed at the time — explicitly out of scope, explicitly documented,
confirmed pre-existing via git history rather than assumed. It has since
been fixed; see the Follow-up section above.
