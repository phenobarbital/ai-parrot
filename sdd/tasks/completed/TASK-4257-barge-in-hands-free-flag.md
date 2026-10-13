# TASK-4257: `HandsFreeConfig.barge_in` flag + server barge-in regression test

**Feature**: FEAT-654 — Voice Form hands-free barge-in and per-option narration segments
**Spec**: `sdd/specs/voice-form-barge-in.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (G1, G5; AC1, AC2). Barge-in is a **client policy**: the server already
accepts a recording while the engine is in `ASKING` right after a `question`
(`audio/engine.py:334`). What is missing is the contract flag `hands_free.barge_in` (default
`True`) that reaches the client in v2 `session_started`, plus a regression test pinning the
server premise that barge-in relies on.

`SessionStarted.hands_free` embeds `HandsFreeConfig` directly (`audio/events.py:293`), so
adding the field is enough to put it on the wire — no engine change.

Per spec §8 Q-B, `barge_in` is a **ceiling** honoured by the client (documented in TASK-4261).
There is NO server-side per-session override: do not add anything to `StartSession` or
`AudioSessionConfig`.

---

## Scope

- Add `barge_in: bool = True` to `HandsFreeConfig` and update its docstring.
- Add unit tests: default + round-trip, and the v2 `session_started` wire carrying the key
  (v1 `hands_free=None` omits it).
- Add the engine regression test `test_engine_accepts_audio_right_after_question`.

**NOT in scope**: `option_pause_ms` (TASK-4258), narration segments (TASK-4259), wire glue
(TASK-4260), docs (TASK-4261), any `StartSession` / `resolve_voice_config` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` | MODIFY | `HandsFreeConfig.barge_in` |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py` | MODIFY | flag default / wire tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py` | MODIFY | barge-in server regression test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.voice import HandsFreeConfig, VoiceFormConfig  # core/voice.py:19,50
from parrot_formdesigner.audio.events import SessionStarted, AudioReceived, Transcribe  # audio/events.py:287 (+ already imported in test_audio_engine_turns.py:20)
```

### Existing Signatures to Use
```python
# core/voice.py:19-23
class HandsFreeConfig(BaseModel):
    """Client hands-free behaviour: auto-open mic after TTS, end-of-speech silence."""
    auto_record: bool = True
    silence_ms: int = Field(default=1200, ge=0)

# audio/events.py:287-295
class SessionStarted(_Wire):
    type: Literal["session_started"] = "session_started"
    session_id: str
    total_questions: int
    title: str
    protocol_version: int = 1
    hands_free: HandsFreeConfig | None = None
    max_recording_seconds: int | None = None
    prefetch_count: int | None = None
# _Wire.to_wire() -> model_dump(mode="json", exclude_none=True)   # audio/events.py:~283

# tests/formdesigner/test_audio_engine_turns.py
def _build(extra_meta=None, cfg=None, protocol=1) -> AudioFormSession   # :70
def _advance(session) -> list                                          # :123 (PlanReady → session_started, prefetch, first question)
@pytest.fixture def started(session) -> (session, out)                # :153
# existing usage :245-247:
#   out = s.handle(AudioReceived(type="_audio", audio=b"abc", mime="audio/webm"))
#   assert isinstance(out[0], Transcribe) and out[0].field_id == "name"
```

### Does NOT Exist
- ~~`HandsFreeConfig.barge_in`~~ — created by this task.
- ~~`StartSession.barge_in`~~ / ~~`StartSession.hands_free`~~ — never added (spec §8 Q-B: no server override).
- ~~`Phase.NARRATING`~~ / ~~`Phase.PLAYING`~~ — the engine is in `ASKING` while the client plays.
- ~~`PlaybackInterrupted`~~ wire message — out of scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#HandsFreeConfig",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#SessionStarted"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default MUST be `True` (spec §2 item 1, AC1). The client downgrades it; the server never upgrades or overrides it.
- v1 sessions must keep omitting `hands_free` entirely (existing behaviour of `hands_free=None` + `exclude_none`).
- No production code besides the one field + docstring.

---

## Implementation Blueprint

### Steps (in order)
1. Add the field to `HandsFreeConfig` — *why*: `SessionStarted` embeds the model, so this alone carries it on the v2 wire.
2. Add the two schema tests — *why*: AC1 (default, round-trip, v1 omission).
3. Add the engine regression test — *why*: AC2 pins that a recording right after `question` is transcribed for the cursor field.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    silence_ms: int = Field(default=1200, ge=0)' core/voice.py)
# REPLACE the class body at core/voice.py:19-23 with:
class HandsFreeConfig(BaseModel):
    """Client hands-free behaviour: auto-open mic after TTS, end-of-speech silence, barge-in.

    ``barge_in`` (default True) tells the client it MAY keep the microphone armed with VAD while
    narration segments play and cancel playback on speech onset. It is a client policy and a
    ceiling: the client must still disable it when echo cancellation is not effective or the
    user opts out, and never enables it when the form says False. The server already accepts a
    recording at any time during ASKING/CONFIRMING and never learns playback was interrupted.
    """

    auto_record: bool = True
    silence_ms: int = Field(default=1200, ge=0)
    barge_in: bool = True
```
**Why**: spec §3 M1 skeleton; the docstring carries the ceiling rule (§8 Q-B) so it is visible to anyone reading the model.

### `packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py` (MODIFY — append at end of file)
```python
def test_hands_free_config_barge_in_default():
    from parrot_formdesigner.core.voice import HandsFreeConfig

    assert HandsFreeConfig().barge_in is True
    # FILL IN: HandsFreeConfig(barge_in=False).model_dump() round-trips (barge_in False, other defaults intact) — AC1


def test_session_started_wire_carries_barge_in():
    from parrot_formdesigner.audio.events import SessionStarted
    from parrot_formdesigner.core.voice import HandsFreeConfig

    v2 = SessionStarted(session_id="s", total_questions=1, title="T", protocol_version=2,
                        hands_free=HandsFreeConfig()).to_wire()
    assert v2["hands_free"] == {"auto_record": True, "silence_ms": 1200, "barge_in": True}
    # FILL IN: v1 (hands_free=None) to_wire() has no "hands_free" key — AC1
```
**Why**: AC1. Imports are local to keep the existing module imports untouched.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py` (MODIFY — add inside `class TestEngineTurns`)
```python
# occurrences: 1 (verified: grep -c '^class TestEngineTurns' test_audio_engine_turns.py)
    def test_engine_accepts_audio_right_after_question(self, started) -> None:
        """Barge-in premise (AC2): a recording arriving right after `question` — before any
        client playback could have ended — is transcribed against the cursor field."""
        s, out = started
        assert s.state.phase == Phase.ASKING
        # FILL IN: assert the last item of `out` is the first Question and capture its field_id — bounded by AC2
        out = s.handle(AudioReceived(type="_audio", audio=b"abc", mime="audio/webm"))
        assert isinstance(out[0], Transcribe)
        # FILL IN: out[0].field_id equals the cursor field id captured above; s._last_audio is set — AC2
```
**Why**: spec §4 `test_engine_accepts_audio_right_after_question`; reuses the `started` fixture (`:153`). `Phase` is imported in this module — verify with `grep -n 'Phase' test_audio_engine_turns.py`; if not, add it from `parrot_formdesigner.audio.models`.

### FILL IN checklist
- [ ] round-trip assertion — AC1
- [ ] v1 omission assertion — AC1
- [ ] cursor field id + `_last_audio` assertions — AC2 (verify `_last_audio` attr name with `grep -n '_last_audio' audio/engine.py`)

---

## Acceptance Criteria

- [ ] `HandsFreeConfig().barge_in is True`; v2 `session_started.hands_free` carries `auto_record`, `silence_ms`, `barge_in`; v1 omits `hands_free` (AC1)
- [ ] `test_engine_accepts_audio_right_after_question` passes (AC2)
- [ ] Existing tests in the two touched test files still pass
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`

---

## Test Specification

See the blueprint test blocks above (`test_hands_free_config_barge_in_default`,
`test_session_started_wire_carries_barge_in`, `test_engine_accepts_audio_right_after_question`).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug voice-form-barge-in --feature-id FEAT-654 --spec sdd/specs/voice-form-barge-in.spec.md --index sdd/tasks/index/voice-form-barge-in.json`)
2. **Read the spec** (§2 Overview item 1, §3 Module 1, §5 AC1–AC2, §8 Q-B)
3. **Check dependencies** in `sdd/tasks/index/voice-form-barge-in.json`
4. **Verify the Codebase Contract** — re-run every `grep -c`; a changed count means re-locate; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands one file at a time (`-p no:xdist`)
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4257 voice-form-barge-in verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (sequential, no MCP coder seats)
**Date**: 2026-10-12
**Notes**: Added `HandsFreeConfig.barge_in` (default True) + docstring; schema/wire tests and `test_engine_accepts_audio_right_after_question`. Mutation checks: `barge_in` default→False turns 2 schema tests red; removing `_last_audio` assignment in engine turns the new engine test red. ruff not installed in the worktree venv (not run).

**Deviations from spec**: none
