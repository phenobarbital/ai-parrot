# TASK-5553: Realign test_live_envelope TestCanonicalRole with the AUDIO-mode role contract

**Feature**: FEAT-883 — Gemini Live envelope tests — match the AUDIO-mode role contract
**Spec**: `sdd/specs/fixgroup-f545489af365.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:33b76e470d2b`

---

## Context

Ledger `issue:33b76e470d2b`: `TestCanonicalRole::test_model_text_is_assistant` and
`::test_mixed_turn_both_roles_present` in `packages/ai-parrot/tests/clients/test_live_envelope.py` fail on
`dev`. The tests feed a `model_turn` text frame to `GeminiLiveClient.stream_voice` without
`response_modalities`, so the client runs in its default AUDIO mode, where `model_turn` text is the
model's internal "thinking": it is yielded with `text=""` and `metadata={"thinking": ...}` (live.py:866).
Spoken assistant words arrive as `output_transcription` frames (live.py:929). The tests are stale;
`live.py` is correct and stays unchanged. Implements spec §3 Module 1.

---

## Scope

- Rename `_text_response` to `_model_turn_text_response` and give it a docstring.
- Add `_output_transcription_response(text)` building a `server_content.output_transcription` frame.
- Rewire `test_model_text_is_assistant` to the AUDIO-mode path (output transcription) and assert the exact text.
- Add `test_text_mode_model_turn_is_assistant` (TEXT mode via `response_modalities=["TEXT"]`).
- Add `test_audio_mode_model_turn_is_thinking_only` (AUDIO mode: empty `text`, `metadata["thinking"]`).
- Rewire `test_mixed_turn_both_roles_present` to use `_output_transcription_response`.

**NOT in scope**: any change to `packages/ai-parrot-client-google/src/parrot/clients/google/live.py`,
to `TestVoiceOverride`, `TestGeminiCapabilitiesVoiceFlip`, the two user-transcription tests, or the fake
session helpers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/clients/test_live_envelope.py` | MODIFY | Frame helpers + `TestCanonicalRole` realignment |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google.live import GeminiLiveClient  # verified: test_live_envelope.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/live.py
class GeminiLiveClient(...):  # line 328
    def _build_live_config(self, system_prompt=None, response_modalities: Optional[List[str]] = None, ...)  # line 572
        # line 643: modalities = response_modalities or ["AUDIO"]
    async def stream_voice(self, audio_iterator, system_prompt=None, session_id=None, user_id=None,
                           stt_only: bool = False, options=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]:  # line 693
        # line 773: response_modalities=kwargs.get("response_modalities"),
        # line 783: is_audio_mode = not stt_only and "AUDIO" in (live_config.response_modalities or [])
        # line 866: AUDIO-mode model_turn text -> LiveVoiceResponse(text="", metadata={"thinking": part.text}, role="assistant")
        # line 913: input_transcription -> role="user" text
        # line 929: output_transcription -> role="assistant" text

# packages/ai-parrot/src/parrot/models/voice.py
class LiveVoiceResponse:  # line 398
    text: str = ""
    role: Optional[str] = None  # line 430
    metadata: Dict[str, Any] = field(default_factory=dict)  # line 438

# packages/ai-parrot/tests/clients/test_live_envelope.py (existing helpers, reused unchanged)
def _mock_client(monkeypatch, client, responses): ...      # line 66
def _user_transcription_response(text: str): ...           # line 85
async def _empty_audio_iterator(): ...                      # line 61
```

### Does NOT Exist
- ~~`GeminiLiveClient(response_modalities=...)` constructor argument~~ — modality is per call, via the `stream_voice` kwarg.
- ~~`LiveVoiceResponse.thinking`~~ — thinking text lives in `metadata["thinking"]`.
- ~~an existing `_output_transcription_response` helper~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/clients/test_live_envelope.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/live.py#GeminiLiveClient.stream_voice",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/live.py#GeminiLiveClient._build_live_config",
    "sym:packages/ai-parrot/src/parrot/models/voice.py#LiveVoiceResponse"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Test-only change: `git diff --name-only origin/dev...HEAD` must list only the test file (plus SDD state).
- Keep the `SimpleNamespace` frame style and `@pytest.mark.asyncio` markers.
- Format with `black` (line length 120, root `pyproject.toml`); lint with `ruff check`.

### References in Codebase
- `packages/ai-parrot-client-google/src/parrot/clients/google/live.py:777` — comment documenting the AUDIO-mode thinking contract.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `_text_response` helper with `_model_turn_text_response` and add `_output_transcription_response` below it — *why*: the helper names must say which server frame they build, because the same `model_turn` text means different things in AUDIO and TEXT mode.
2. Rewrite `test_model_text_is_assistant` and insert the two new tests right after it — *why*: the default AUDIO path asserts through the transcript; the `model_turn` path keeps coverage in both modes.
3. Swap the second frame of `test_mixed_turn_both_roles_present` to `_output_transcription_response` — *why*: in AUDIO mode only the transcript carries assistant text.
4. Run `black` and `ruff check` on the file, then the Validation Command — *why*: black collapses the TEXT-mode list comprehension onto one line (it fits in 120 columns).

### `packages/ai-parrot/tests/clients/test_live_envelope.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c 'def _text_response(text: str):' packages/ai-parrot/tests/clients/test_live_envelope.py)
# REPLACE the whole `_text_response` function (verified: test_live_envelope.py:74-82) with:
def _model_turn_text_response(text: str):
    """A ``model_turn`` text part.

    It is the model's reply in TEXT mode but its internal reasoning
    ("thinking") in the default AUDIO mode.
    """
    return SimpleNamespace(
        server_content=SimpleNamespace(
            model_turn=SimpleNamespace(parts=[SimpleNamespace(text=text, inline_data=None)]),
        ),
        tool_call=None,
        usage_metadata=None,
        go_away=None,
    )


def _output_transcription_response(text: str):
    """An ``output_transcription`` frame: the model's spoken words in AUDIO mode."""
    return SimpleNamespace(
        server_content=SimpleNamespace(
            output_transcription=SimpleNamespace(text=text),
        ),
        tool_call=None,
        usage_metadata=None,
        go_away=None,
    )
```
**Why this shape**: identical frame layout to the existing helpers so the fake session needs no change;
`stream_voice` reads `server_content.output_transcription.text` (live.py:929-930).

### `packages/ai-parrot/tests/clients/test_live_envelope.py` (MODIFY — TestCanonicalRole)
```python
# occurrences: 1 (verified: grep -c 'async def test_model_text_is_assistant(self, monkeypatch, client):' packages/ai-parrot/tests/clients/test_live_envelope.py)
# REPLACE the body of test_model_text_is_assistant (verified: test_live_envelope.py:103-106) and append two tests:
    async def test_model_text_is_assistant(self, monkeypatch, client):
        """AUDIO mode (default): the spoken transcript is the assistant's text."""
        _mock_client(monkeypatch, client, [_output_transcription_response("Hello there")])
        responses = [r async for r in client.stream_voice(_empty_audio_iterator())]
        assert any(r.role == "assistant" and r.text == "Hello there" for r in responses)

    @pytest.mark.asyncio
    async def test_text_mode_model_turn_is_assistant(self, monkeypatch, client):
        """TEXT mode: ``model_turn`` text is the reply and carries role="assistant"."""
        _mock_client(monkeypatch, client, [_model_turn_text_response("Hello there")])
        responses = [r async for r in client.stream_voice(_empty_audio_iterator(), response_modalities=["TEXT"])]
        assert any(r.role == "assistant" and r.text == "Hello there" for r in responses)

    @pytest.mark.asyncio
    async def test_audio_mode_model_turn_is_thinking_only(self, monkeypatch, client):
        """AUDIO mode: ``model_turn`` text is thinking — metadata only, never response text."""
        _mock_client(monkeypatch, client, [_model_turn_text_response("planning the answer")])
        responses = [r async for r in client.stream_voice(_empty_audio_iterator())]
        assert all(not r.text for r in responses)
        assert any(r.role == "assistant" and r.metadata.get("thinking") == "planning the answer" for r in responses)
```
**Why**: keeps the existing test name (history) while asserting the exact text; the two new tests pin both
sides of the modality branch (live.py:851-885).

### `packages/ai-parrot/tests/clients/test_live_envelope.py` (MODIFY — mixed turn)
```python
# occurrences: 1 (verified: grep -c "_text_response(\"It's sunny\")," packages/ai-parrot/tests/clients/test_live_envelope.py)
# REPLACE line test_live_envelope.py:127 with:
                _output_transcription_response("It's sunny"),
```
**Why**: the turn runs in AUDIO mode, where only the transcript yields assistant text.

### FILL IN checklist
- [ ] Confirm no reference to the old helper remains: `grep -nE '\b_text_response\(' <file>` returns nothing — bounded by spec §5 AC-2 (note: `_model_turn_text_response(` contains the old name as a substring, so use the word boundary).
- [ ] Confirm `live.py` is absent from `git diff --name-only origin/dev...HEAD` — bounded by spec §5 AC-3.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/clients/test_live_envelope.py` passes: 13 tests (11 existing + 2 new), run from the worktree with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src`.
- [ ] `_text_response` no longer exists in the file; `_model_turn_text_response` and `_output_transcription_response` do.
- [ ] `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` is unchanged.
- [ ] `ruff check` and `black --check` pass on the changed file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/clients/test_live_envelope.py -q`

---

## Test Specification

The tests ARE the deliverable — see the Implementation Blueprint. Expected result: `13 passed`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug fixgroup-f545489af365 --feature-id FEAT-883`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-f545489af365.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the test file
9. **Close the task** with `parrot sdd task close TASK-5553 fixgroup-f545489af365 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
