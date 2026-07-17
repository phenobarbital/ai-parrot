# TASK-1807: NovaAudio mixin — port Nova Sonic voice streaming to nova/audio.py

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1806
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. The bidirectional speech-to-speech code in
`nova_sonic.py` (FEAT-302) moves into a capability mixin `NovaAudio` at
`packages/ai-parrot/src/parrot/clients/nova/audio.py`, mirroring how
`GoogleGeneration` is a mixin composed into `GoogleGenAIClient`. Behavior is a
**port, not a redesign** — the wire protocol, sender/receiver architecture,
and `LiveVoiceResponse` yield shape are contractual for `VoiceChatHandler`.

Two deliberate changes vs. the source module:
1. The Pre-Alpha SDK guard moves from `__init__` to first `stream_voice()`
   call (text/generation use of NovaClient must not require the SDK).
2. `_apply_pii_guardrail` calls `self.apply_guardrail_text(...)` directly
   (inherited from `BedrockConverseBase`, TASK-1806) — the `_get_text_client`
   delegate no longer exists.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/nova/` package directory
  (a minimal placeholder `__init__.py` is acceptable; the real exports land
  in TASK-1809).
- Create `nova/audio.py` with `class NovaAudio` (plain mixin, NO base class),
  porting from `nova_sonic.py` verbatim in behavior:
  - constants `_CONNECTION_LIMIT_SECONDS`, `INPUT_SAMPLE_RATE_HZ`,
    `OUTPUT_SAMPLE_RATE_HZ`
  - `_open_stream`, `_send_event`, `_iter_events` (thin Pre-Alpha wrappers)
  - `stream_voice(...)` (full event protocol incl. barge-in, toolUse loop,
    8-minute `reconnect_required`, base64 decode of `audioOutput`)
  - `_audio_sender(...)` (base64-encode PCM chunks; `None` sentinel → `contentEnd`)
  - `_apply_pii_guardrail` → `await self.apply_guardrail_text(text, source="INPUT")`
- Lazy SDK guard: `_require_voice_sdk()` helper raising an actionable
  ImportError naming `aws_sdk_bedrock_runtime==0.7.0` / Python ≥ 3.12,
  invoked at the top of `stream_voice()` (NOT at import, NOT in `__init__`).

**NOT in scope**: deleting `nova_sonic.py` (TASK-1811), `NovaClient` itself
(TASK-1809), generation (TASK-1808), tests migration (TASK-1812 — but a small
smoke test for the lazy guard belongs here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/__init__.py` | CREATE | placeholder (finalized in TASK-1809) |
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | CREATE | `NovaAudio` mixin |
| `packages/ai-parrot/tests/clients/test_nova_audio_guard.py` | CREATE | lazy-SDK-guard smoke test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.live import (        # clients/live.py:61,117,138,156
    LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata,
)
from parrot.conf import AWS_REGION_NAME, BEDROCK_AWS_REGION
from parrot.models.bedrock_models import translate as translate_bedrock_model  # models/bedrock_models.py:100
from parrot.models.responses import AIMessage
# Pre-Alpha SDK — import ONLY inside methods, never at module scope:
# from aws_sdk_bedrock_runtime import BedrockAgentRuntimeClient           (nova_sonic.py:142)
# from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamOperationInput  (nova_sonic.py:183-185)
```

### Existing Signatures to Use (source of the port)
```python
# packages/ai-parrot/src/parrot/clients/nova_sonic.py — PORT SOURCE (read it in full)
class NovaSonicClient(AbstractClient):                       # line 42
    _CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15           # line 63
    INPUT_SAMPLE_RATE_HZ: int = 16000                        # line 66
    OUTPUT_SAMPLE_RATE_HZ: int = 24000                       # line 67
    async def _open_stream(self, model_id: str) -> Any: ...  # line 174
    async def _send_event(self, stream, event: Dict[str, Any]) -> None: ...  # line 191
    def _iter_events(self, stream) -> AsyncIterator[Dict[str, Any]]: ...     # line 195
    async def _apply_pii_guardrail(self, text: str) -> str: ...              # line 203
    async def stream_voice(self, audio_iterator, system_prompt=None,
        session_id=None, user_id=None, **kwargs
    ) -> AsyncIterator[LiveVoiceResponse]: ...               # line 216
    async def _audio_sender(self, stream, audio_iterator,
        prompt_name, content_name) -> None: ...              # line 445
# Attributes the mixin READS from the composed client (set by TASK-1809 / base):
#   self.voice_id (constructor kwarg), self._region_prefix, self.model,
#   self.default_model, self.logger, self._execute_tool(name, input)  (AbstractClient)
#   self._ensure_client() — NOT used for voice; voice builds its own SDK client (line 142)

# packages/ai-parrot/src/parrot/clients/bedrock.py (post TASK-1806)
class BedrockConverseBase(AbstractClient):
    async def apply_guardrail_text(self, text: str, source: str = "OUTPUT") -> str:  # was line 400
```

### Does NOT Exist
- ~~`self._get_text_client()`~~ — the delegate pattern dies with this feature;
  guardrails go through `self.apply_guardrail_text` (inherited).
- ~~`NovaAudio.__init__`~~ — the mixin must NOT define `__init__` (MRO
  constraint, spec §7).
- ~~boto3/aioboto3 support for `invoke_model_with_bidirectional_stream`~~ —
  only the Pre-Alpha `aws_sdk_bedrock_runtime` SDK supports it.
- ~~`parrot/clients/nova/`~~ — does not exist until this task creates it.
- Base64 note: `audioOutput.content` arrives as base64 TEXT (decode before
  yielding `audio_data: bytes`); `audioInput.content` must be base64-encoded
  text — both are code-review fixes already in the source (lines 360-369, 466-476).

---

## Implementation Notes

### Pattern to Follow
Mixin shape: `GoogleGeneration` (`clients/google/generation.py`) — a plain
class with async methods that assume composition into an `AbstractClient`
subclass. Module docstring should carry over the EXPERIMENTAL warning from
`nova_sonic.py:15-22`.

### Key Constraints
- Event protocol frames must stay byte-identical (sessionStart → promptStart →
  optional SYSTEM contentStart/textInput/contentEnd → AUDIO contentStart →
  audioInput* → toolResult* → completionEnd), including
  `audioOutputConfiguration` with `voiceId: self.voice_id` and
  `encoding: "base64"`.
- `stream_voice` must resolve the model via
  `translate_bedrock_model(self.model or self.default_model, self._region_prefix)`
  the way `_translate_model` does (nova_sonic.py:145-148) — note the composed
  client's default model is `nova-2-lite`, so voice callers pass
  `model="nova-2-sonic"` or the bot layer configures it (TASK-1811 handles wiring).
- Sender task must be cancelled + awaited in `finally` (nova_sonic.py:440-443).

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/nova_sonic.py` — the port source (519 lines)
- `packages/ai-parrot/src/parrot/clients/live.py` — `GeminiLiveClient.stream_voice` (architecture precedent) + response dataclasses
- `packages/ai-parrot/tests/clients/test_nova_sonic.py` — existing protocol tests (migrated in TASK-1812)

---

## Acceptance Criteria

- [ ] `from parrot.clients.nova.audio import NovaAudio` works without `aws_sdk_bedrock_runtime` installed
- [ ] `stream_voice()` raises actionable ImportError when the SDK is missing (test with import-blocking fixture)
- [ ] Ported methods match the source protocol (verified fully in TASK-1812's migrated suite)
- [ ] `NovaAudio` defines no `__init__` and no class-level SDK import
- [ ] `pytest packages/ai-parrot/tests/clients/test_nova_audio_guard.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/nova/` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_audio_guard.py
import sys
import pytest
from parrot.clients.nova.audio import NovaAudio


def test_module_imports_without_sdk(monkeypatch):
    """Importing the mixin never requires the Pre-Alpha SDK."""
    assert NovaAudio is not None


async def test_stream_voice_raises_actionable_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "aws_sdk_bedrock_runtime", None)

    class Host(NovaAudio):
        voice_id = "matthew"; _region_prefix = "us"
        model = None; default_model = "nova-2-sonic"

    async def gen():
        yield b"\x00\x00"

    with pytest.raises(ImportError, match="aws_sdk_bedrock_runtime"):
        async for _ in Host().stream_voice(gen()):
            pass


def test_no_init_defined():
    assert "__init__" not in NovaAudio.__dict__
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§2, §3 Module 3, §6, §7)
2. **Check dependencies** — TASK-1806 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `nova_sonic.py` in full before porting
4. **Update status** in `sdd/tasks/index/novaclient-amazon-aws.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-17
**Notes**: Created `parrot/clients/nova/` (placeholder `__init__.py`,
finalized in TASK-1809) and `nova/audio.py` with `class NovaAudio` (plain
mixin, no `__init__`), porting `stream_voice`/`_audio_sender`/
`_open_stream`/`_send_event`/`_iter_events`/`_apply_pii_guardrail` from
`nova_sonic.py` verbatim in behavior. `_apply_pii_guardrail` now calls
`self.apply_guardrail_text` directly (inherited from `BedrockConverseBase`,
TASK-1806) instead of the removed `_get_text_client()` delegate. Added
`_require_voice_sdk()` lazy guard invoked at the top of `stream_voice()`
(not at import/`__init__`) raising an actionable `ImportError` naming
`aws_sdk_bedrock_runtime==0.7.0`/Python>=3.12. `_open_stream` builds its
own `BedrockAgentRuntimeClient` directly rather than via
`self._ensure_client()` (that seam is reserved for the aioboto3 text
engine). Resolved spec §8 open question: `voice_id` is now also readable
per-call via `stream_voice(**kwargs)` (`kwargs.get("voice_id")`), falling
back to `self.voice_id`, while keeping the contracted signature intact.
Added `tests/clients/test_nova_audio_guard.py` (3 tests, all passing).
`ruff check` clean.

**Deviations from spec**: none
