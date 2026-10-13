# TASK-4260: Wire glue — `option` segment kind, v1 inline grouping, barge-in v2 integration test

**Feature**: FEAT-654 — Voice Form hands-free barge-in and per-option narration segments
**Spec**: `sdd/specs/voice-form-barge-in.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4257, TASK-4259
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, wire part (§2 Overview item 3; AC6, AC7, AC8). TASK-4259 makes the narrator
emit `q:<uid>:options_intro` and `q:<uid>:opt:<n>` keys. The WS adapter must:

- label them correctly in v2 `audio_segment` headers: intro → `kind: "options"`, items →
  `kind: "option"` (`_segment_kind`, `api/audio_ws.py:901`). Note `q:<uid>:opt:3` ends with a
  number, so a naive `endswith(":options")` misses it — match on the `:opt:` segment.
- keep protocol v1 / `prefetch: false` sessions receiving ONE `question.audio` with the whole
  narration in order: the inline grouping at `api/audio_ws.py:946` accepts only
  `label|hint|options` today and would silently DROP the options for v1 clients.
- document the new kind on `AudioSegment.kind` (`audio/events.py:302`).

Plus the end-to-end integration test `test_barge_in_flow_v2` (needs `barge_in` from TASK-4257
and the per-option keys from TASK-4259).

`AudioSegmentCache` (`audio/segments.py`) and `_SYNTH_LOCK` are NOT touched (AC8).

---

## Scope

- Extend `_segment_kind` for `options_intro` and `opt:<n>`.
- Extend the v1 inline grouping rule to accept `options_intro` and `opt:<n>` keys.
- Update the `AudioSegment.kind` comment to list `"option"`.
- Tests: `test_segment_kind_new_keys`, `test_do_synthesize_v2_emits_option_segments`,
  `test_do_synthesize_v1_inline_groups_option_keys` (adapter); `test_question_narration_v2_prefetch_includes_option_keys`
  and `test_barge_in_flow_v2` (v2 integration).

**NOT in scope**: `audio/segments.py`, `_SYNTH_LOCK`, any server-side VAD / streaming / `playback_interrupted` message, docs (TASK-4261).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `_segment_kind`, v1 grouping |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` | MODIFY | `AudioSegment.kind` comment |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` | MODIFY | adapter tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py` | MODIFY | v2 integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, _ConnCtx   # api/audio_ws.py:228 (imported in test_audio_ws_adapter.py:14)
from parrot_formdesigner.audio.events import AudioSegment                     # audio/events.py:298
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.options import FieldOption                      # test_audio_engine_turns.py:47
from parrot_formdesigner.core.types import FieldType
```

### Existing Signatures to Use
```python
# api/audio_ws.py:900-910
    @staticmethod
    def _segment_kind(key: str) -> str:
        """Header ``kind`` for a narration segment key."""
        if key.startswith("review:"):  return "review"
        if key.endswith(":hint"):      return "hint"
        if key.endswith(":options"):   return "options"
        if key.startswith("q:"):       return "question"
        return "system"

# api/audio_ws.py:938-955 (_do_synthesize, inline branch)
        if ctx.inline_audio:
            groups: dict[str, list[str]] = {}
            for key in item.keys:
                parts = key.split(":")
                if len(parts) == 3 and parts[0] == "q" and parts[2] in ("label", "hint", "options"):
                    groups.setdefault(parts[1], []).append(item.texts.get(key, ""))
            ...combined = {f"v1:{uid}": " ".join(t for t in texts if t.strip()) ...}

# audio/events.py:298-303
class AudioSegment(_Wire):
    type: Literal["audio_segment"] = "audio_segment"
    key: str
    mime: str
    kind: str  # "question" | "hint" | "options" | "system" | "review"
    text: str

# test_audio_ws_adapter.py helpers: _form(*ids, **kw) :27 (TEXT fields only), _ws() :44, _msgs(ws) :51,
#   _types(ws) :55, fixtures synth (returns MagicMock(audio=b"AUDIO")) :60 / stt :67,
#   _handler(form, synth, stt, **kw) :73, async _boot(handler, *, start=None) -> (ws, ctx) :79
# test_audio_ws_v2_integration.py helpers: _voice_form(**kw) :135 (has SELECT "color": Red/Green/Blue + disabled Teal),
#   voice_app fixture :252 (env.form, env.synth, env.transcripts), connect :295, start(ws, env, **extra) :299,
#   say(ws, env, text, conf, *stop) :304, until :270, types :281, jsons :285; class TestAudioWsV2Integration :348
```

### Does NOT Exist
- ~~`AudioSegment.kind == "option"`~~ — documented by this task (field stays `str`).
- ~~`PlaybackInterrupted`~~ / ~~`playback_interrupted`~~ — out of scope.
- ~~`StartSession.barge_in`~~ — no per-session override.
- ~~server-side VAD / chunked audio~~ — `_process_binary` takes one complete container per answer.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._segment_kind",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler._do_synthesize",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py#AudioSegment"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `pause:` keys never produce a segment (already skipped by `_synth_items`) — assert it (AC6).
- The v1 combined text must equal `label + hint + options_intro + opt:1 + opt:2` joined in key order — identical to the old concatenation (AC7).
- Don't grow `_do_synthesize`: put the key predicate in a small static helper (Rule 4).

---

## Implementation Blueprint

### Steps (in order)
1. Extend `_segment_kind` — *why*: AC6 header kinds.
2. Extract the v1 key predicate into `_v1_group_uid(key) -> str | None` and use it in `_do_synthesize` — *why*: AC7, keeps the method's complexity flat.
3. Update the `AudioSegment.kind` comment — *why*: the wire doc lives there.
4. Adapter tests, then the two v2 integration tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    def _segment_kind(key: str) -> str:' api/audio_ws.py)
# REPLACE the body of _segment_kind (:901-910) with:
    @staticmethod
    def _segment_kind(key: str) -> str:
        """Header ``kind`` for a narration segment key.

        ``review:*`` → review; ``*:hint`` → hint; ``*:options`` and ``*:options_intro`` → options;
        ``q:<uid>:opt:<n>`` → option; other ``q:*`` → question; else system.
        """
        if key.startswith("review:"):
            return "review"
        if key.endswith(":hint"):
            return "hint"
        if key.endswith((":options", ":options_intro")):
            return "options"
        parts = key.split(":")
        if len(parts) == 4 and parts[0] == "q" and parts[2] == "opt":
            return "option"
        if key.startswith("q:"):
            return "question"
        return "system"

    @staticmethod
    def _v1_group_uid(key: str) -> str | None:
        """Field uid a narration key belongs to for v1 inline audio, or None (pause/sys/review keys)."""
        parts = key.split(":")
        if parts[0] != "q":
            return None
        # FILL IN: return parts[1] when (len(parts) == 3 and parts[2] in ("label", "hint", "options", "options_intro"))
        # or (len(parts) == 4 and parts[2] == "opt"); else None — bounded by AC7 and spec §3 M2 skeleton comment.

# occurrences: 1 (verified: grep -cF '                if len(parts) == 3 and parts[0] == "q" and parts[2] in ("label", "hint", "options"):' api/audio_ws.py)
# REPLACE the 4-line loop body in _do_synthesize's inline branch:
            for key in item.keys:
                uid = self._v1_group_uid(key)
                if uid is not None:
                    groups.setdefault(uid, []).append(item.texts.get(key, ""))
```
**Why**: spec §2 item 3 + §3 M2 skeleton. `_v1_group_uid` is a private helper (not public API).

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    kind: str  # "question" | "hint" | "options" | "system" | "review"' audio/events.py)
# REPLACE that line with:
    kind: str  # "question" | "hint" | "options" | "option" | "system" | "review"
```

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` (MODIFY — append)
```python
def _select_form() -> FormSchema:
    from parrot_formdesigner.core.options import FieldOption

    return FormSchema(
        form_id="f",
        title="T",
        tenant=_TENANT,
        sections=[FormSection(section_id="s1", fields=[
            FormField(field_id="c", field_type=FieldType.SELECT, label="Color?", required=True,
                      options=[FieldOption(value="r", label="Red"), FieldOption(value="g", label="Green")]),
        ])],
    )


def test_segment_kind_new_keys() -> None:
    assert AudioFormWSHandler._segment_kind("q:u:options_intro") == "options"
    assert AudioFormWSHandler._segment_kind("q:u:opt:3") == "option"
    # FILL IN: existing mappings unchanged — "q:u:label"→question, "q:u:hint"→hint, "q:u:options"→options,
    # "review:1"→review, "sys:x"→system (AC6)


class TestOptionSegments:
    async def test_do_synthesize_v2_emits_option_segments(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_select_form(), synth, stt), start={"protocol_version": 2})
        segs = [m for m in _msgs(ws) if m["type"] == "audio_segment"]
        # FILL IN: one header with kind "option" per opt:<n> key (2), intro has kind "options",
        # no header key starts with "pause:"; send_bytes count == header count — AC6

    async def test_do_synthesize_v1_inline_groups_option_keys(self, synth, stt) -> None:
        ws, _ = await _boot(_handler(_select_form(), synth, stt))
        # FILL IN: the synthesizer was called with ONE text for the question that equals
        # label + options_intro + "1, Red." + "2, Green." joined by single spaces, and the v1
        # `question` carries base64 audio — AC7 (inspect synth.synthesize.call_args_list)
```
**Why**: spec §4 adapter tests; reuses `_boot`, `_handler`, fixtures. `_form()` only builds TEXT fields, hence `_select_form()`.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py` (MODIFY — add inside `class TestAudioWsV2Integration`)
```python
# occurrences: 1 (verified: grep -c '^class TestAudioWsV2Integration' test_audio_ws_v2_integration.py)
    async def test_question_narration_v2_prefetch_includes_option_keys(self, aiohttp_client, voice_app: _Env) -> None:
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        frames = await start(ws, env)
        # FILL IN: drive to the "color" question (answer "name" via say(...)); its narration.audio_keys
        # contains opt:1..opt:3 (Teal is disabled) and every opt key has a prefetched audio_segment header — AC6
        await ws.close()

    async def test_barge_in_flow_v2(self, aiohttp_client, voice_app: _Env) -> None:
        """Barge-in end to end: a recording sent before 'playing' anything is accepted for the cursor field."""
        env = voice_app
        client = await aiohttp_client(env.app)
        ws = await connect(client, env)
        frames = await start(ws, env)
        assert frames[0]["hands_free"]["barge_in"] is True
        # FILL IN: answer "name"; when the "color" question arrives, immediately say(ws, env, "Green")
        # (no wait for playback) → transcription + answer_accepted for "color", then the next question — spec §4
        await ws.close()
```
**Why**: spec §4 integration test. `_voice_form()` has `voice=VoiceFormConfig()`, so `hands_free` defaults are on the wire for v2.

### FILL IN checklist
- [ ] `_v1_group_uid` predicate — AC7
- [ ] existing `_segment_kind` mappings — AC6
- [ ] v2 option headers / no pause headers — AC6
- [ ] v1 single combined text — AC7
- [ ] v2 prefetch covers opt keys — AC6
- [ ] barge-in flow assertions — spec §4 integration

---

## Acceptance Criteria

- [ ] v2 headers: intro `kind: "options"`, items `kind: "option"`; `pause:` keys never produce a segment (AC6)
- [ ] v1 / `prefetch: false` sessions still get one `question.audio` with the full narration in order (AC7)
- [ ] `audio/segments.py` and `_SYNTH_LOCK` untouched; `repeat` still replays full `audio_keys` (AC8)
- [ ] All existing tests in `test_audio_ws_adapter.py`, `test_audio_ws_v2_integration.py` pass (AC12)
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`

---

## Test Specification

See the blueprint test blocks above.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug voice-form-barge-in --feature-id FEAT-654 --spec sdd/specs/voice-form-barge-in.spec.md --index sdd/tasks/index/voice-form-barge-in.json`)
2. **Read the spec** (§2 Overview item 3, §3 Module 2, §4, §5 AC6–AC8, AC12, §7 Known Risks)
3. **Check dependencies** — TASK-4257 and TASK-4259 must be `"done"`
4. **Verify the Codebase Contract** — re-run every `grep -c`; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — Validation Commands one file at a time (`-p no:xdist`)
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4260 voice-form-barge-in verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (sequential, no MCP coder seats)
**Date**: 2026-10-12
**Notes**: _segment_kind option/options_intro, _v1_group_uid helper for v1 inline grouping, AudioSegment.kind comment; adapter + v2 integration tests (prefetch option keys, barge-in flow). Mutations red: opt kind branch removed (adapter+integration), v1 opt grouping removed, options_intro kind removed. ruff unavailable in venv.

**Deviations from spec**: none
