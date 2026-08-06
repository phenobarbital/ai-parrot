# TASK-2166: Gemini: per-call temperature/max_tokens/top_p + real transcription params

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2164
**Assigned-to**: unassigned
**Parallel-safe**: yes — Gemini lane — touches only clients/live.py and its tests; disjoint from the Nova lane (TASK-2169/2170).

---

## Context

`_build_live_config()` reads `self.temperature`/`self.max_tokens` from the
constructor (`live.py:692-693`), so the per-call values Nova already honors are
silently ignored by Gemini. `top_p` does not reach the Live config at all.

There is also a latent crash: `stream_voice()` forwards
`enable_input_transcription`/`enable_output_transcription` to
`_build_live_config()` (`live.py:777-780`), but that method's signature
(`live.py:652-656`) does not accept them — the moment anyone threads those two
`VoiceConfig` fields, Gemini raises `TypeError`. TASK-2171 will thread exactly
those fields, so this task must close the hole first.

Implements: **Spec §3 Module 3 (inference half)**.

---

## Scope

- Give `_build_live_config()` optional `temperature`, `max_tokens`, `top_p`
  parameters that fall back to the constructor values when not supplied.
- Place `top_p` into the `types.LiveConnectConfig` (it is absent today).
- Add **real** `enable_input_transcription` / `enable_output_transcription`
  parameters to `_build_live_config()` and honor them, replacing today's
  unconditional `input_audio_transcription` (`live.py:709`) and the
  `stt_only`-only gate on output (`live.py:711`).
- Accept `options: Optional[VoiceStreamOptions] = None` in `stream_voice()` and
  derive the above from it; explicit `**kwargs` keep winning over `options`.
- Flip `supports_top_p` and `supports_per_call_inference` to `True` in Gemini's
  descriptor.
- Tests per spec §4 for each of the above, including a regression test that
  passing the two transcription flags does not raise `TypeError`.

**NOT in scope**: canonical `role`, voice override, session resumption
(TASK-2167/2168). Do not touch Nova.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | `_build_live_config()` params + `top_p` + `options` |
| `packages/ai-parrot/tests/clients/test_live_inference_params.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.live import GeminiLiveClient          # clients/live.py
from parrot.models.voice import VoiceStreamOptions        # models/voice.py (TASK-2164)
from google.genai import types                            # google-genai 2.17.0
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
def _build_live_config(                                       # line 652
    self,
    system_prompt: Optional[str] = None,
    response_modalities: Optional[List[str]] = None,
    stt_only: bool = False,                                   # line 656
) -> types.LiveConnectConfig:
    ...
    live_config = types.LiveConnectConfig(                    # line 689
        response_modalities=modalities,                       # line 690
        speech_config=speech_config,                          # line 691
        temperature=self.temperature,                         # line 692 — constructor, NOT per-call
        max_output_tokens=self.max_tokens,                    # line 693 — constructor, NOT per-call
        context_window_compression=...,                       # line 694
        realtime_input_config=...,                            # line 697
        input_audio_transcription=types.AudioTranscriptionConfig(),          # line 709 — unconditional
        output_audio_transcription=None if stt_only else types.AudioTranscriptionConfig(),  # line 711
        media_resolution=...,                                 # line 712
    )

async def stream_voice(                                       # line 729
    self, audio_iterator, system_prompt=None, session_id=None,
    user_id=None, stt_only: bool = False, **kwargs,           # stt_only at line 735
) -> AsyncIterator[LiveVoiceResponse]:
    parallel_tool_execution = kwargs.get("parallel_tool_execution", False)   # line 772
    live_config = self._build_live_config(                                   # line 774
        system_prompt=system_prompt,
        stt_only=stt_only,
        **{k: v for k, v in kwargs.items() if k in (                         # lines 777-780
            'response_modalities',
            'enable_input_transcription',      # ← NOT a param → TypeError
            'enable_output_transcription',     # ← NOT a param → TypeError
        )}
    )
```

### Does NOT Exist

- ~~`GeminiLiveClient.top_p`~~ — `top_p` appears ONLY in a `**kwargs` docstring at `clients/live.py:574`. There is no attribute and no config field today.
- ~~`_build_live_config(enable_input_transcription=…)`~~ / ~~`enable_output_transcription=…`~~ — not parameters today (`live.py:652-656`); this task adds them.
- ~~`types.LiveConnectConfig(top_p=…)`~~ — **verify the exact field name against the installed `google-genai` 2.17.0 `types.py` before using it.** Do not assume; `grep` for `top_p` in `.venv/lib/python3.11/site-packages/google/genai/types.py`.
- ~~A `VoiceConfig` reference inside `live.py`~~ — the client does not import `VoiceConfig` today and must not start; it receives `VoiceStreamOptions` only.

---

## Implementation Notes

### Pattern to Follow
Nova already does exactly this correctly — mirror the shape at
`clients/nova/audio.py:789-796`:
```python
temperature = kwargs.get("temperature", <fallback>)
max_tokens = kwargs.get("max_tokens", <fallback>)
top_p = kwargs.get("top_p", <fallback>)
```
Here the fallback chain is: explicit kwarg → `options` field → constructor value.

### Key Constraints
- Backwards compatible: a caller passing nothing must get today's behavior
  (constructor values), so existing tests keep passing.
- STT-only still wins over the transcription flags: in `stt_only` mode output
  transcription stays `None` regardless of `enable_output_transcription`
  (`live.py:711` semantics preserved).
- Verify the `LiveConnectConfig` field name for top-p in the installed SDK
  before wiring it — if the field does not exist in 2.17.0, leave
  `supports_top_p=False` and record the finding in the Completion Note rather
  than inventing a field.

---

## Acceptance Criteria

- [ ] `_build_live_config()` accepts and honors `temperature`, `max_tokens`, `top_p`
- [ ] `top_p` reaches the Live config (or, if the SDK has no such field, `supports_top_p` stays `False` and the Completion Note explains why)
- [ ] `enable_input_transcription`/`enable_output_transcription` are real parameters and are honored
- [ ] Passing those two flags through `stream_voice()` does NOT raise `TypeError`
- [ ] `stream_voice()` accepts `options: VoiceStreamOptions`; explicit kwargs still win
- [ ] Omitting everything reproduces today's behavior exactly
- [ ] Gemini descriptor flags updated to match what was actually implemented
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_live_inference_params.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/live.py`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/clients/test_live_inference_params.py
import pytest
from parrot.clients.live import GeminiLiveClient
from parrot.models.voice import VoiceStreamOptions


@pytest.fixture
def client():
    return GeminiLiveClient(temperature=0.7, max_tokens=1000)


class TestPerCallInference:
    def test_per_call_temperature_wins(self, client):
        cfg = client._build_live_config(temperature=0.1)
        assert cfg.temperature == 0.1

    def test_per_call_max_tokens_wins(self, client):
        cfg = client._build_live_config(max_tokens=8192)
        assert cfg.max_output_tokens == 8192

    def test_falls_back_to_constructor(self, client):
        cfg = client._build_live_config()
        assert cfg.temperature == 0.7 and cfg.max_output_tokens == 1000


class TestTranscriptionFlags:
    def test_flags_do_not_raise(self, client):
        """Regression: live.py:777-780 forwarded params the signature lacked."""
        client._build_live_config(
            enable_input_transcription=True, enable_output_transcription=False)

    def test_output_transcription_disabled(self, client):
        cfg = client._build_live_config(enable_output_transcription=False)
        assert cfg.output_audio_transcription is None

    def test_stt_only_still_wins(self, client):
        cfg = client._build_live_config(stt_only=True, enable_output_transcription=True)
        assert cfg.output_audio_transcription is None


class TestOptionsObject:
    def test_options_applied(self, client):
        opts = VoiceStreamOptions(temperature=0.3, max_tokens=2048)
        cfg = client._build_live_config(
            temperature=opts.temperature, max_tokens=opts.max_tokens)
        assert (cfg.temperature, cfg.max_output_tokens) == (0.3, 2048)
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
