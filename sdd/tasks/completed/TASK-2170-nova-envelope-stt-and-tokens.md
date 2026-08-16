# TASK-2170: Nova: canonical role, stt_only acceptance, max_tokens default, options

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2169
**Assigned-to**: unassigned
**Parallel-safe**: yes — Nova lane — same files as TASK-2169; disjoint from the Gemini lane.

---

## Context

Three Nova-side divergences remain after TASK-2169:

1. `role` is uppercase `"USER"`/`"ASSISTANT"` from `contentStart`
   (`nova/audio.py:897`, emitted `:940`); the canonical form is lowercase.
2. `stt_only` is absorbed by `**kwargs` and silently ignored. Nova always
   returns voice **and** text and generation cannot be turned off, so the
   resolved decision (spec §8) is: accept the flag, do **not** raise, do **not**
   filter the response, and declare `native_stt_only=False`.
3. `max_tokens` falls back to a hardcoded `1024` (`nova/audio.py:790`) instead of
   the shared `VoiceConfig` default of `4096`.

Implements: **Spec §3 Module 4 (envelope + inference half)**.

---

## Scope

- Normalize `role` to lowercase `"user"`/`"assistant"` on every yielded
  `LiveVoiceResponse`.
- Add an explicit `stt_only: bool = False` parameter to `stream_voice()`. When
  `True`: log once at `info` that Nova has no native STT-only mode and that the
  model response is still generated and still billed. Do NOT suppress or filter
  any frame.
- Replace the hardcoded `max_tokens` fallback of `1024` with `4096`; accept
  `8192`. Confirm Nova 2 Sonic's real ceiling against the Bedrock docs
  (spec §8) and record it in `max_output_tokens` + the Completion Note.
- Accept `options: Optional[VoiceStreamOptions] = None` and derive
  `temperature`/`max_tokens`/`top_p`/`voice`/`parallel_tool_execution` from it;
  explicit `**kwargs` keep winning.
- Tests per spec §4.

**NOT in scope**: voice validation (TASK-2169), any Gemini file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | Role normalization, `stt_only`, `max_tokens`, `options` |
| `packages/ai-parrot/src/parrot/clients/nova/client.py` | MODIFY | Descriptor `max_output_tokens` |
| `packages/ai-parrot/tests/clients/test_nova_envelope.py` | CREATE | Envelope + stt_only + token tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.nova import NovaClient                 # clients/nova/client.py
from parrot.clients.live import LiveVoiceResponse          # clients/live.py — shared response type
from parrot.models.voice import VoiceStreamOptions         # models/voice.py (TASK-2164)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py
async def stream_voice(                                       # line 712
    self, audio_iterator, system_prompt=None, session_id=None,
    user_id=None, **kwargs,                                   # no stt_only param today
) -> AsyncIterator[LiveVoiceResponse]:
    parallel_tool_execution = kwargs.get("parallel_tool_execution", False)  # line 765
    temperature = kwargs.get("temperature", 0.7)              # line 789
    max_tokens = kwargs.get("max_tokens", 1024)               # line 790 — → 4096
    top_p = kwargs.get("top_p", 0.9)                          # line 791
    await self._send_event(stream, {"event": {"sessionStart": {
        "inferenceConfiguration": {
            "maxTokens": max_tokens, "topP": top_p, "temperature": temperature,
        }}}})                                                 # lines 793-798
    ...
    turn_state.role = content_start.get("role")               # line 897 — "USER"/"ASSISTANT"
    role = turn_state.role                                    # line 926
    if role == "ASSISTANT":                                   # line 936
        ...
        role=role,                                            # line 940 — uppercase leaks out

# Interruption handling (already correct — do not disturb):
def _is_interruption_payload(content: str) -> bool:           # line 173
    turn_metadata.was_interrupted = True                      # line 912
```

### Does NOT Exist

- ~~`NovaAudio.stream_voice(stt_only=…)`~~ — not a parameter today; absorbed by `**kwargs` and ignored. This task adds it.
- ~~A way to disable Nova generation~~ — there is none. Do NOT implement client-side filtering to fake STT-only; the resolved decision (spec §8) is to accept the flag and let the response through.
- ~~Lowercase roles from Nova today~~ — `contentStart` yields `"USER"`/`"ASSISTANT"` (`nova/audio.py:897`).
- ~~`metadata["user_transcription"]` on the Nova side~~ — Nova never produced it; only Gemini did (`live.py:875`). Do not add it.

---

## Implementation Notes

### Key Constraints
- Normalize roles at the single emission point (`nova/audio.py:940`), not at
  every call site, so `turn_state.role` can keep the provider's raw value for
  protocol-level comparisons like `role == "ASSISTANT"` (`:936`).
- The `stt_only` log fires **once per session**, not per frame — a voice turn
  yields many responses and a per-frame log would flood.
- `4096` is the shared default (spec §8 resolved). Verify Nova's true ceiling
  before setting `max_output_tokens`; if it is lower than `8192`, record that in
  the descriptor and the Completion Note rather than silently letting Bedrock
  clamp.
- Do not disturb interruption handling (`nova/audio.py:173-196`, `:907-916`) —
  it is already at parity with Gemini.

---

## Acceptance Criteria

- [ ] Every yielded response carries lowercase `role` (`"user"`/`"assistant"`)
- [ ] `stt_only=True` does not raise and does not suppress the model response
- [ ] The STT-only notice is logged once per session, not per frame
- [ ] `max_tokens` defaults to `4096`; `8192` is accepted
- [ ] `options: VoiceStreamOptions` is honored; explicit kwargs still win
- [ ] Nova descriptor: `native_stt_only=False`, `max_output_tokens` set from verified docs
- [ ] Interruption behavior unchanged
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_nova_envelope.py -v`
- [ ] Existing Nova tests pass: `pytest packages/ai-parrot/tests/clients/test_nova.py -v`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/clients/test_nova_envelope.py
import pytest
from parrot.clients.nova import NovaClient


class TestCanonicalRole:
    async def test_roles_lowercased(self, mocked_nova_stream):
        responses = [r async for r in mocked_nova_stream.stream_voice(...)]
        assert {r.role for r in responses if r.role} <= {"user", "assistant"}


class TestSttOnly:
    async def test_accepted_without_raising(self, mocked_nova_stream):
        [r async for r in mocked_nova_stream.stream_voice(..., stt_only=True)]

    async def test_model_response_still_delivered(self, mocked_nova_stream):
        """Resolved decision: Nova cannot suppress generation; do not fake it."""
        responses = [r async for r in mocked_nova_stream.stream_voice(..., stt_only=True)]
        assert any(r.role == "assistant" for r in responses)

    def test_capabilities_declare_non_native(self):
        assert NovaClient().voice_capabilities.native_stt_only is False


class TestInferenceDefaults:
    async def test_max_tokens_defaults_to_4096(self, capture_session_start):
        [r async for r in capture_session_start.stream_voice(...)]
        cfg = capture_session_start.sent[0]["event"]["sessionStart"]["inferenceConfiguration"]
        assert cfg["maxTokens"] == 4096

    async def test_8192_accepted(self, capture_session_start):
        [r async for r in capture_session_start.stream_voice(..., max_tokens=8192)]
        cfg = capture_session_start.sent[0]["event"]["sessionStart"]["inferenceConfiguration"]
        assert cfg["maxTokens"] == 8192
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
**Notes**: Normalized `role` to lowercase at the single existing emission
point (`role=role.lower() if role else None`), leaving `turn_state.role`
and the local `role` variable holding Nova's raw uppercase value for the
existing protocol-level comparisons (`role == "ASSISTANT"`) untouched, per
the task's explicit key constraint. Added `stt_only: bool = False` as an
explicit `stream_voice()` parameter; when `True`, logs once (guarded by
the `if stt_only:` check running once per call, before the event loop)
that Nova has no native STT-only mode and the response is still generated
and billed — never filters or suppresses any frame. Replaced the
hardcoded `max_tokens` fallback of `1024` with `4096`; `8192` flows
through unchanged when explicitly requested. Added
`options: Optional[VoiceStreamOptions] = None`, deriving
`temperature`/`max_tokens`/`top_p`/`voice`/`parallel_tool_execution` from
it via the same `kwargs.get(name, options.field if options else default)`
precedence pattern already used inline in this file for temperature/
max_tokens/top_p — explicit kwargs always win. `voice` from `options`
feeds into the existing `_resolve_voice()` validation from TASK-2169 (no
new voice-handling logic duplicated). Updated `NovaClient.voice_capabilities`:
`max_output_tokens` is now `8192` (see below) with `native_stt_only`
staying `False` (already correct pre-task). Interruption handling
(`nova/audio.py` `_is_interruption_payload`/`was_interrupted`) untouched,
confirmed by re-reading it before and after. 15 new tests in
`tests/clients/test_nova_envelope.py`, following the exact
`sys.modules['aws_sdk_bedrock_runtime']`-stubbing mock pattern already
established in `test_nova.py` (discovered by reading that file's own
module docstring, which documents the pattern). All existing Nova tests
(`test_nova.py`, `test_nova_audio_guard.py`, `test_nova_voice_catalog.py`
— 35 tests) still pass unmodified. Full voice-domain regression
(167 tests) green except the one already-documented pre-existing
`test_no_aiohttp_import` failure.

**`max_output_tokens` source (spec §8 open question, same constraint as
TASK-2169)**: this sandboxed environment has no live network access to
re-verify Nova 2 Sonic's exact numeric ceiling against the current AWS
Bedrock documentation. Rather than inventing an unverified number, I used
`8192` — the value the spec ITSELF resolves as explicitly supported
(spec §3 Module 4: "`max_tokens` hardcoded fallback `1024` ... replaced by
the `VoiceConfig` default of `4096`" plus §8: "`8192` explicitly supported,
no voice-specific pin"). This is a verifiable-from-the-spec-document
value, not a guess. Flagging this explicitly, matching TASK-2169's
same-shaped open item, for a human with AWS docs access to confirm or
correct.

**Deviations from spec**: none — `max_output_tokens` sourced from the
spec's own resolved decision per the reasoning above, not a live docs
fetch (unavailable in this sandbox).
