# TASK-2100: Add additive `role` field to LiveVoiceResponse

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 1. Nova Sonic reports the speaker on its `contentStart`
frames, but `LiveVoiceResponse` has nowhere to carry it, so every downstream
consumer sees the user's transcription and the assistant's reply on the same
`text` channel with no way to tell them apart.

This task only creates the carrier. TASK-2102 populates it. Doing it first keeps
that task from having to touch two packages at once.

---

## Scope

- Add `role: Optional[str] = None` to the `LiveVoiceResponse` dataclass.
- Emit `"role"` from `LiveVoiceResponse.to_websocket_message()`.
- Write tests proving the field is **additive**: existing construction without
  `role` still works and defaults to `None`.

**NOT in scope**: populating `role` from Nova frames (TASK-2102); changing
`GeminiLiveClient` to set it (it separates transcripts via its own
`input_audio_transcription`/`output_audio_transcription` config — leave alone);
surfacing `role` in `VoiceBot` or `VoiceChatHandler` public protocols (spec §8
open question, deliberately deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | Add the field + serialize it |
| `packages/ai-parrot/tests/clients/test_live_voice_response_role.py` | CREATE | Additive-change tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.

### Verified Imports

```python
from parrot.clients.live import LiveVoiceResponse   # verified: clients/live.py:156
from parrot.clients.live import LiveCompletionUsage # verified: clients/live.py:60
from parrot.clients.live import LiveToolCall        # verified: clients/live.py:128
from parrot.clients.live import VoiceTurnMetadata   # verified: clients/live.py:140
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                              # line 156
    text: str = ""                                    # line 164
    audio_data: Optional[bytes] = None                # line 165
    audio_format: str = "audio/pcm;rate=24000"        # line 166
    is_complete: bool = False                         # line 169
    is_interrupted: bool = False                      # line 170
    tool_calls: List[LiveToolCall] = field(default_factory=list)   # line 173
    usage: Optional[LiveCompletionUsage] = None       # line 176
    turn_metadata: Optional[VoiceTurnMetadata] = None # line 179
    session_id: Optional[str] = None                  # line 182
    turn_id: Optional[str] = None                     # line 183
    user_id: Optional[str] = None                     # line 184
    metadata: Dict[str, Any] = field(default_factory=dict)         # line 187
    def to_websocket_message(self) -> Dict[str, Any]: ...          # line 189
```

### Does NOT Exist

- ~~`LiveVoiceResponse.role`~~ — **this task creates it**. Do not assume any
  existing role/speaker attribute.
- ~~`LiveVoiceResponse.speaker`~~ / ~~`.who`~~ / ~~`.source`~~ — none exist; do
  not invent an alternative name. The spec fixes the name as `role`.
- ~~a Pydantic `BaseModel` base~~ — `LiveVoiceResponse` is a stdlib
  `@dataclass`, not Pydantic. Use `field(default_factory=...)` conventions, not
  `Field(...)`.

---

## Implementation Notes

### Pattern to Follow

Every field on this dataclass has a default, so the new one must too — it is
appended with `= None` and therefore cannot break positional construction of
existing fields.

```python
    # Session info
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    user_id: Optional[str] = None

    # Speaker attribution (FEAT-408)
    role: Optional[str] = None
    """Speaker this frame is attributed to: "USER", "ASSISTANT", "TOOL", or
    None when the provider does not report one (e.g. GeminiLiveClient)."""
```

In `to_websocket_message()` (line 189) add `"role": self.role` alongside the
existing keys. Do not reorder or rename existing keys — `VoiceChatHandler` and
the frontend guides consume them.

### Key Constraints

- **Additive only.** No existing field may be renamed, reordered ahead of an
  existing field, or given a new default.
- `Optional[str]`, not an Enum — Nova may introduce roles beyond
  USER/ASSISTANT/TOOL and an Enum would raise on an unknown value mid-turn.
  Matches the file's existing `Optional[str]` idiom.
- Google-style docstring on the new field.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/live.py:189` — `to_websocket_message()`
- `packages/ai-parrot-integrations/src/parrot/voice/models.py:137` — a parallel
  `to_websocket_message()` in the integrations package; **do not** change it in
  this task, but be aware it exists so you don't edit the wrong file.

---

## Acceptance Criteria

- [ ] `LiveVoiceResponse(role="USER")` works; `LiveVoiceResponse()` gives
      `role is None`.
- [ ] `to_websocket_message()` output contains a `"role"` key.
- [ ] Every pre-existing key of `to_websocket_message()` is still present and
      unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/clients/test_live_voice_response_role.py -v`
- [ ] No regressions: `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
      and `pytest packages/ai-parrot-integrations/tests/voice/ -q`
- [ ] No new lint errors: `ruff check packages/ai-parrot/src/parrot/clients/live.py`
      (compare against the pre-change baseline; this file has pre-existing findings)

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_live_voice_response_role.py
import pytest

from parrot.clients.live import LiveVoiceResponse


class TestLiveVoiceResponseRole:
    def test_role_defaults_to_none(self):
        """Additive change: existing construction is unaffected."""
        assert LiveVoiceResponse().role is None

    def test_role_can_be_set(self):
        assert LiveVoiceResponse(role="ASSISTANT").role == "ASSISTANT"

    def test_to_websocket_message_includes_role(self):
        msg = LiveVoiceResponse(text="hi", role="ASSISTANT").to_websocket_message()
        assert msg["role"] == "ASSISTANT"

    def test_to_websocket_message_role_is_none_by_default(self):
        assert LiveVoiceResponse(text="hi").to_websocket_message()["role"] is None

    def test_existing_websocket_keys_unchanged(self):
        """Regression guard: consumers depend on these exact keys."""
        msg = LiveVoiceResponse(text="hi").to_websocket_message()
        for key in (
            "type", "text", "audio_base64", "audio_format", "is_complete",
            "is_interrupted", "tool_calls", "usage", "metadata",
            "session_id", "turn_id",
        ):
            assert key in msg
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2100-live-voice-response-role-field.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
