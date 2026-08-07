# TASK-2165: Extend VoiceCapable with options + voice_capabilities (both clients)

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2164
**Assigned-to**: unassigned
**Parallel-safe**: no — Touches the Protocol AND both clients atomically — cannot overlap with the provider lanes.

---

## Context

`VoiceCapable` is `@runtime_checkable`, and `VoiceBot._create_llm_client()`
gates on `isinstance(client, VoiceCapable)` at `bots/voice.py:273`. A
`runtime_checkable` Protocol checks member **presence**: the moment
`voice_capabilities` joins the Protocol, any client lacking it fails that gate.

This task therefore lands the Protocol change AND both clients' descriptor
properties together, so the tree is never in a state where the gate is broken.
The descriptors declare the providers' behavior **as it is today** — later tasks
flip individual flags to `True` as they implement the capability.

Implements: **Spec §3 Module 2**.

---

## Scope

- Add `options: Optional[VoiceStreamOptions] = None` to the Protocol's
  `stream_voice()` signature and a `voice_capabilities` property returning
  `VoiceCapabilities`.
- Add a `voice_capabilities` property to `GeminiLiveClient` describing today's
  truth: `native_stt_only=True`, `supports_top_p=False`,
  `supports_per_call_voice=False`, `supports_per_call_inference=False`,
  `emits_reconnect_signal=False`, `supports_session_resumption=False`,
  PCM 16k in / 24k out, Gemini prebuilt voice catalog, `default_voice="Puck"`.
- Add the same property to `NovaClient` describing today's truth:
  `native_stt_only=False`, `supports_top_p=True`, `supports_per_call_voice=True`,
  `supports_per_call_inference=True`, `emits_reconnect_signal=True`,
  `max_session_seconds=NovaAudio._CONNECTION_LIMIT_SECONDS`,
  PCM 16k in / 24k out, Nova voice catalog, `default_voice="matthew"`.
- Tests: both clients still satisfy `isinstance(..., VoiceCapable)`; a stub with
  `stream_voice()` but no `voice_capabilities` does NOT.

**NOT in scope**: changing any streaming behavior. Flags that are `False` here
stay `False` until the task that implements them flips them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/protocols.py` | MODIFY | Add `options` param + `voice_capabilities` property |
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | Add `voice_capabilities` property only |
| `packages/ai-parrot/src/parrot/clients/nova/client.py` | MODIFY | Add `voice_capabilities` property only |
| `packages/ai-parrot/tests/clients/test_voice_protocol.py` | CREATE | Protocol conformance tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.protocols import VoiceCapable                       # clients/protocols.py:16
from parrot.clients.live import GeminiLiveClient, LiveVoiceResponse     # clients/live.py
from parrot.clients.nova import NovaClient                              # clients/nova/client.py
from parrot.models.voice import (                                       # models/voice.py
    AudioFormat, VoiceCapabilities, VoiceProvider, VoiceStreamOptions,  # last two added by TASK-2164
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/protocols.py
@runtime_checkable                                            # line 15
class VoiceCapable(Protocol):                                 # line 16
    async def stream_voice(                                   # line 29
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...

# packages/ai-parrot/src/parrot/clients/nova/audio.py
_CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15                # line 271 (465 s)

# packages/ai-parrot/src/parrot/clients/nova/client.py
def __init__(self, ..., voice_id: str = "matthew", ...):      # line 75
    self.voice_id = voice_id                                  # line 109

# packages/ai-parrot/src/parrot/bots/voice.py
if not isinstance(client, VoiceCapable):                      # line 273 — the gate this must not break
    raise TypeError(...)                                      # line 274
```

### Does NOT Exist

- ~~`AbstractClient.voice_capabilities`~~ — do NOT add anything to `parrot/clients/base.py`; voice stays a Protocol-level capability (spec §7, CLAUDE.md).
- ~~An enumerated Gemini voice catalog in the repo~~ — **CORRECTED during implementation (2026-08-07)**: this claim was stale. `parrot/models/google.py:398` DOES define a full enumerated catalog, `ALL_VOICE_PROFILES: List[VoiceProfile]` (30 entries, including `"Puck"`, `"Charon"`, `"Kore"`, etc.), used verbatim here via `frozenset(p.voice_name for p in ALL_VOICE_PROFILES)`. Spec §8 catalog-completeness question is resolved by using this real source of truth instead of a hand-picked subset.
- ~~A Nova voice catalog constant~~ — the only list is prose in a docstring at `clients/nova/audio.py:737` (`matthew`, `tiffany`, `amy`). TASK-2169 turns it into a constant; here just reference those three.
- ~~`VoiceCapable` as an ABC~~ — it is a `typing.Protocol`; do not convert it or make clients inherit from it.

---

## Implementation Notes

### Key Constraints
- Keep `@runtime_checkable`. Removing it silently disables the `bots/voice.py:273`
  gate rather than fixing it.
- Land all three files in ONE commit. A commit where the Protocol requires
  `voice_capabilities` but a client lacks it breaks `VoiceBot` at runtime.
- The descriptors describe *current* behavior. Do not optimistically set flags
  that later tasks implement — the conformance kit (TASK-2176) asserts
  descriptor-vs-behavior consistency and will fail on a lie.
- `voice_capabilities` is a plain `@property` (sync), not a coroutine — it must
  be cheap to call from a preflight check.

---

## Acceptance Criteria

- [ ] `VoiceCapable.stream_voice()` accepts `options`; `voice_capabilities` is on the Protocol
- [ ] `isinstance(GeminiLiveClient(...), VoiceCapable)` is `True`
- [ ] `isinstance(NovaClient(...), VoiceCapable)` is `True`
- [ ] A stub with `stream_voice()` but no `voice_capabilities` is NOT an instance
- [ ] Descriptors reflect today's real behavior (no optimistic flags)
- [ ] `parrot/clients/base.py` unmodified
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_voice_protocol.py -v`
- [ ] `VoiceBot` gate still works: `pytest packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py -v`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/clients/test_voice_protocol.py
from typing import AsyncIterator
import pytest
from parrot.clients.protocols import VoiceCapable
from parrot.models.voice import VoiceProvider


class _NoCapabilities:
    async def stream_voice(self, audio_iterator, system_prompt=None,
                           session_id=None, user_id=None, **kwargs):
        yield None


def test_stub_without_capabilities_is_not_voice_capable():
    assert not isinstance(_NoCapabilities(), VoiceCapable)


def test_gemini_satisfies_protocol():
    from parrot.clients.live import GeminiLiveClient
    assert isinstance(GeminiLiveClient(), VoiceCapable)


def test_nova_satisfies_protocol():
    from parrot.clients.nova import NovaClient
    assert isinstance(NovaClient(), VoiceCapable)


def test_descriptors_tell_current_truth():
    from parrot.clients.live import GeminiLiveClient
    from parrot.clients.nova import NovaClient
    gemini = GeminiLiveClient().voice_capabilities
    nova = NovaClient().voice_capabilities
    assert gemini.provider is VoiceProvider.GOOGLE_LIVE
    assert gemini.native_stt_only is True
    assert gemini.supports_top_p is False          # flipped by TASK-2166
    assert nova.native_stt_only is False           # Nova always generates
    assert nova.emits_reconnect_signal is True     # 465 s limit
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
**Notes**: Added `options: Optional[VoiceStreamOptions] = None` and the
`voice_capabilities` property to `VoiceCapable` in `protocols.py`; added
`voice_capabilities` properties describing today's real behavior to both
`GeminiLiveClient` (`clients/live.py`) and `NovaClient`
(`clients/nova/client.py`), landed in the same commit as the Protocol
change per the task's own warning about the `@runtime_checkable` gate.
Corrected a stale "Does NOT Exist" contract claim: `parrot/models/google.py`
DOES define a full 30-voice enumerated Gemini catalog
(`ALL_VOICE_PROFILES`) — used it directly for `voice_catalog` instead of
hand-picking a subset (see contract correction above, dated 2026-08-07).
Nova's `voice_catalog` uses the three documented voices
(`matthew`/`tiffany`/`amy`) per the task's instruction, pending TASK-2169's
promotion to a shared constant. `max_output_tokens=1024` for Nova's
descriptor reflects today's real hardcoded fallback (`nova/audio.py:790`),
not the post-TASK-2170 value of 4096 — documented inline. Wrote 14 new
tests in `tests/clients/test_voice_protocol.py`; all pass, plus the
existing `test_voicebot_provider_switch.py` gate suite (24 tests) still
passes unmodified.

**Deviations from spec**: One unplanned file touched outside the task's
table: `packages/ai-parrot/tests/bots/test_voice_capable_protocol.py`
(pre-existing FEAT-416 test). Adding a non-method member
(`voice_capabilities`, a `@property`) to a `@runtime_checkable` Protocol
makes Python's `typing` module raise `TypeError: Protocols with
non-method members don't support issubclass()` — an unavoidable language
constraint of the exact Protocol shape this task's spec mandates, not a
design choice made here. That pre-existing test used
`issubclass(SomeClass, VoiceCapable)`; the actual runtime gate this task
protects (`bots/voice.py:273`) already used `isinstance()`, not
`issubclass()`. Converted the three assertions in that file from
`issubclass(Class, ...)` to `isinstance(Class(), ...)` (and replaced the
uninstantiable-abstract-class negative case with an equivalent minimal
stub) — no behavioral coverage lost, and it now passes. Flagging this
explicitly per Cardinal Rule 2 (file fidelity) since it was not in the
task's Files table, but leaving it broken was not an option (STOP-worthy
regression this task itself introduced).
