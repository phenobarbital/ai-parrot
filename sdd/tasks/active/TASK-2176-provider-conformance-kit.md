# TASK-2176: Provider conformance kit — parametrized drop-in parity suite

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2168, TASK-2170, TASK-2172
**Assigned-to**: unassigned
**Parallel-safe**: no — Needs both provider lanes and the session layer complete before it can assert parity.

---

## Context

This is the task that makes the feature durable. FEAT-416 shipped the
abstractions and the divergences accumulated anyway, inside a feature whose
stated goal was a shared voice contract. Prose parity demonstrably does not hold
in this codebase.

The kit turns "drop-in" into a test that fails when it regresses, and gives the
already-declared-but-unimplemented providers (`OPENAI_REALTIME`, `WHISPER_TTS`
at `models/voice.py:41-42`) a ready-made acceptance checklist.

Implements: **Spec §3 Module 9**.

---

## Scope

- Create a parametrized suite over every declared `VoiceCapable`
  implementation, with the parametrization as the single extension point
  (adding a provider costs one entry).
- Assert, per provider: the projected options are honored; `role` is canonical;
  the reconnect signal is `reconnect_required`; the `VoiceSession` frame
  sequence is structurally identical across providers for the same input.
- Assert descriptor-vs-behavior consistency: every `True` in
  `VoiceCapabilities` is demonstrated, every `False` is demonstrated absent.
- Add the drop-in test from spec §4: same mocked audio + same `VoiceConfig`
  (provider aside) → structurally identical frame sequences.
- All tests run against mocked provider streams — no live AWS/Google calls.

**NOT in scope**: changing client behavior. If a provider fails the kit, that is
a bug for its lane's task, not something to paper over with a skip.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/voice/test_provider_conformance.py` | CREATE | The parametrized kit |
| `packages/ai-parrot/tests/voice/conftest.py` | CREATE/MODIFY | Shared provider doubles |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.protocols import VoiceCapable             # clients/protocols.py:16
from parrot.clients.live import GeminiLiveClient, LiveVoiceResponse
from parrot.clients.nova import NovaClient
from parrot.voice.session import VoiceSession                 # voice/session.py:36
from parrot.models.voice import (
    AudioFormat, VoiceCapabilities, VoiceConfig, VoiceProvider, VoiceStreamOptions,
)
```

### Existing Signatures to Use

```python
# Existing mocks to extend — packages/ai-parrot/tests/voice/test_voice_session.py
class MockVoiceClient:                                        # line 9
    async def stream_voice(self, audio_iterator, system_prompt=None,   # line 11
                           session_id=None, user_id=None, **kwargs): ...

@pytest.fixture
def mock_send_fn():                                           # line 20 — collects frames
    async def send(payload): ...                              # line 24

# packages/ai-parrot/tests/voice/test_voice_reconnection.py
class ReconnectingMockClient:                                 # line 11
    async def stream_voice(self, audio_iterator, **kwargs):   # line 16
class AlwaysReconnectMockClient:                              # line 28

# packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py
class TestVoiceConfigProviderSwitch:                          # line 100
```

### Does NOT Exist

- ~~`tests/voice/conftest.py`~~ — the core `tests/voice/` directory has only `__init__.py`, `test_voice_session.py` and `test_voice_reconnection.py`. A conftest may need creating.
- ~~A live-provider integration harness~~ — none exists and none should be added; CI must never call AWS or Google (spec §5).
- ~~`OPENAI_REALTIME` / `WHISPER_TTS` clients~~ — the enum variants exist (`models/voice.py:41-42`) but there is no implementation. Parametrize over the two real clients only.
- ~~A shared `VoiceCapable` registry~~ — there is no registry of voice clients; `resolve_voice_client_class()` (`handler.py:79`) is the closest thing and it is integrations-side.

---

## Implementation Notes

### Pattern to Follow
Build on the existing doubles rather than inventing new ones:
`MockVoiceClient` (`tests/voice/test_voice_session.py:9`) for happy-path turns,
`ReconnectingMockClient` (`test_voice_reconnection.py:11`) for the reconnect
path, and the frame-collecting `mock_send_fn` fixture (`:20-27`).

### Key Constraints
- The parametrization is the contract. Resist per-provider `if` branches inside
  test bodies — a difference that needs branching is either a real divergence
  (fix the client) or a genuine capability difference (assert it via the
  descriptor instead).
- "Structurally identical" means frame types and ordering, not payload bytes:
  audio content and token counts legitimately differ between providers.
- Mock at the provider-SDK boundary so the clients' own translation logic is
  exercised — mocking `stream_voice()` itself would test nothing.

---

## Acceptance Criteria

- [ ] `test_provider_conformance.py` is parametrized over both real providers
- [ ] Options-honored, canonical-role, and reconnect-signal assertions pass for both
- [ ] Descriptor-vs-behavior consistency asserted in both directions
- [ ] The drop-in test compares frame sequences across providers
- [ ] Adding a provider requires exactly one parametrization entry
- [ ] No live AWS/Google calls; suite runs offline
- [ ] Tests pass: `pytest packages/ai-parrot/tests/voice/test_provider_conformance.py -v`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/voice/test_provider_conformance.py
import pytest
from parrot.models.voice import VoiceConfig, VoiceProvider, VoiceStreamOptions

PROVIDERS = [
    pytest.param("google_live", id="gemini"),
    pytest.param("nova", id="nova"),
    # Adding a provider costs exactly one line here.
]


@pytest.fixture(params=PROVIDERS)
def provider(request):
    return request.param


class TestOptionsHonored:
    async def test_inference_params_reach_provider(self, provider, mocked_sdk):
        ...

class TestCanonicalEnvelope:
    async def test_roles_are_canonical(self, provider, mocked_sdk):
        assert {r.role for r in responses if r.role} <= {"user", "assistant"}

    async def test_no_legacy_metadata_key(self, provider, mocked_sdk):
        assert all("user_transcription" not in r.metadata for r in responses)

class TestReconnectSignal:
    async def test_limit_emits_reconnect_required(self, provider, mocked_limit):
        assert any(r.metadata.get("reconnect_required") for r in responses)

class TestDescriptorHonesty:
    def test_every_true_is_demonstrated(self, provider):
        """A descriptor that lies is worse than no descriptor."""

    def test_every_false_is_absent(self, provider):
        ...

class TestDropInEquivalence:
    async def test_frame_sequences_structurally_identical(self, mocked_sdk):
        """Same audio + same VoiceConfig (provider aside) -> same frame types
        in the same order. Payloads may differ; structure may not."""
        assert [f["type"] for f in gemini_frames] == [f["type"] for f in nova_frames]
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
