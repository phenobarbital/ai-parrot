# TASK-2173: VoiceBot: use the projection, pass native voice, persist memory from role

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2164, TASK-2167, TASK-2170
**Assigned-to**: unassigned
**Parallel-safe**: no — Depends on both provider lanes having landed the canonical envelope.

---

## Context

Three `VoiceBot` sites need to follow the new contract:

1. `ask_stream()` builds an ad-hoc kwargs dict (`bots/voice.py:539-545`) that
   must become `voice_config.to_stream_options(**kwargs)`.
2. `_resolve_llm_config()` maps `voice_config.voice_name` — default `"Puck"` —
   into Nova's `voice_id` (`bots/voice.py:198`), which is how a Gemini voice
   reaches a Nova session in the first place.
3. **The riskiest one**: conversation memory builds the user transcript from
   `metadata["user_transcription"]` (`bots/voice.py:583-584`). TASK-2167 removes
   that key. If this line is not migrated, `VoiceBot` silently persists empty
   user turns — a data bug with no crash and no error log.

Implements: **Spec §3 Module 7**.

---

## Scope

- Replace the `voice_stream_kwargs` dict (`:539-545`) with
  `self.voice_config.to_stream_options(**kwargs)`, preserving today's precedence
  (explicit kwargs win).
- Stop forcing `voice_config.voice_name` into Nova's `voice_id` (`:198`); pass
  the native voice through the options object and let the client validate it
  (TASK-2169).
- Migrate the memory path (`:583-584`) to accumulate the user transcript from
  responses with `role == "user"` and the assistant transcript from
  `role == "assistant"`.
- Keep `stt_only` flowing from `ask_stream()` into the options object.
- Tests per spec §4, with an explicit regression test for memory persistence.

**NOT in scope**: `VoiceSession` (TASK-2171/2172), the handler (TASK-2174).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | Projection, voice passthrough, memory-from-role |
| `packages/ai-parrot/tests/bots/test_voicebot_contract.py` | CREATE | Projection + memory regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.bots import VoiceBot                              # bots/__init__.py:12, __all__ :21
from parrot.models.voice import VoiceConfig, VoiceProvider, VoiceStreamOptions
from parrot.clients.protocols import VoiceCapable             # bots/voice.py imports it for the gate
from parrot.memory import ConversationTurn                    # bots/voice.py:~40
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/voice.py
def _resolve_llm_config(self, llm=None, model=None, preset=None,      # line 158
                        model_config=None, **kwargs):
    provider = getattr(self.voice_config, 'provider', 'google_live')  # line 175
    if provider == 'nova':                                            # line 177
        resolved_model = model or self.voice_config.model or "nova-2-sonic"  # line 190
        extra={'voice_id': kwargs.get('voice_id',
                                      self.voice_config.voice_name), …}     # line 198 ← FIX

def _create_llm_client(self, config, conversation_memory=None) -> VoiceCapable:   # line 220
    if config.provider == 'nova':                                     # line 245
        client = NovaClient(..., voice_id=config.extra.get('voice_id', 'matthew'), …)  # line 249
    if not isinstance(client, VoiceCapable):                          # line 273
        raise TypeError(...)                                          # line 274

async def ask_stream(self, audio_input, session_id=None, user_id=None,   # line 419
                     stt_only: bool = False, **kwargs):                  # line 424
    voice_stream_kwargs = {                                              # line 539 ← REPLACE
        'temperature': self.voice_config.temperature,
        'max_tokens': self.voice_config.max_tokens,
        'top_p': self.voice_config.top_p,
        'parallel_tool_execution': self.voice_config.parallel_tool_execution,
        **kwargs,
    }                                                                    # line 545
    async with self._llm as client:                                      # line 547
        async for response in client.stream_voice(                       # line 548
                audio_iterator=..., system_prompt=..., session_id=...,
                user_id=..., stt_only=stt_only, **voice_stream_kwargs):  # line 554
            if "user_transcription" in response.metadata:                # line 583 ← MIGRATE
                user_transcript += " " + response.metadata["user_transcription"]  # line 584
```

### Does NOT Exist

- ~~`metadata["user_transcription"]`~~ — removed from the producer by TASK-2167. Reading it here after that lands yields nothing; this is the silent-data-loss risk in spec §7.
- ~~`VoiceBot.voice_capabilities`~~ — the descriptor lives on the client, reachable via `self._llm.voice_capabilities`. Do not add a duplicate on the bot.
- ~~A `voice_id` concept in core `VoiceConfig`~~ — the field is `voice_name` (`models/voice.py:73`). `voice_id` is Nova's wire-level name only.
- ~~`AbstractBot.ask_stream`~~ overriding concerns — `VoiceBot.ask_stream()` (`bots/voice.py:419`) is the voice entry point; do not touch the text paths (`ask_text` at `:~300`).

---

## Implementation Notes

### Key Constraints
- **The memory migration is the whole risk of this task.** Removing the metadata
  read without adding the role-based accumulation produces empty user turns with
  no error. `test_voicebot_memory_from_role` is mandatory, not optional.
- Preserve today's precedence exactly: explicit `**kwargs` beat
  `VoiceConfig`-derived values (`bots/voice.py:539-545` semantics).
- Keep the `isinstance(client, VoiceCapable)` gate at `:273` intact.
- Turn-boundary handling around `response.turn_id` (`bots/voice.py:559+`) stays
  as-is; only the source of the transcript text changes.

---

## Acceptance Criteria

- [ ] `ask_stream()` builds options via `to_stream_options()`; explicit kwargs still win
- [ ] Nova no longer receives `"Puck"`; the native voice flows through the options object
- [ ] User turns persist to memory via `role == "user"` (regression test required)
- [ ] Assistant turns persist via `role == "assistant"`
- [ ] `stt_only` still reaches the client
- [ ] `isinstance(..., VoiceCapable)` gate intact
- [ ] Tests pass: `pytest packages/ai-parrot/tests/bots/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/voice.py`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/bots/test_voicebot_contract.py
import pytest
from parrot.models.voice import VoiceConfig


class TestProjection:
    async def test_uses_to_stream_options(self, bot_with_recording_client):
        await drain(bot_with_recording_client.ask_stream(b""))
        assert bot_with_recording_client._llm.calls[0].max_tokens == 4096

    async def test_explicit_kwargs_win(self, bot_with_recording_client):
        await drain(bot_with_recording_client.ask_stream(b"", temperature=0.1))
        assert bot_with_recording_client._llm.calls[0].temperature == 0.1


class TestVoicePassthrough:
    def test_nova_does_not_receive_puck(self):
        """Regression for bots/voice.py:198."""
        bot = VoiceBot(voice_config=VoiceConfig(provider="nova"))
        cfg = bot._resolve_llm_config()
        assert cfg.extra.get("voice_id") != "Puck"


class TestMemoryFromRole:
    async def test_user_turn_persisted_from_role(self, bot_with_memory):
        """CRITICAL regression: bots/voice.py:583-584 read a key that no
        longer exists. Without this migration, user turns persist EMPTY —
        silent data loss, no crash, no error log."""
        await drain(bot_with_memory.ask_stream(b""))
        turn = await bot_with_memory.conversation_memory.last_turn()
        assert turn.user_message == "what's the weather"

    async def test_assistant_turn_persisted_from_role(self, bot_with_memory):
        turn = await bot_with_memory.conversation_memory.last_turn()
        assert turn.assistant_response
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
**Notes**: Removed `'voice_id': kwargs.get('voice_id', self.voice_config.voice_name)`
from `_resolve_llm_config()`'s Nova branch `extra` dict — this was the
constructor-time path that bypassed `NovaAudio._resolve_voice()`'s
catalog validation entirely (only per-call overrides get validated;
`_resolve_voice(None)` returns `self.voice_id` unfiltered). An explicit
`voice_id` kwarg to `_resolve_llm_config()` still flows through via the
existing `**kwargs` spread. `ask_stream()` now builds
`options = self.voice_config.to_stream_options(**option_overrides)`
where `option_overrides` is `kwargs` filtered to just the field names
`dataclasses.fields(VoiceStreamOptions)` declares (introspected, not
hardcoded, so it can't silently drift) — arbitrary extra kwargs already
consumed earlier in `ask_stream()` (`initial_context`/`use_vectors`/`ctx`)
must NOT reach `to_stream_options()`, which raises `TypeError` on an
unrecognized field name; the full original `**kwargs` is still forwarded
to `stream_voice()` alongside `options=options`, since both clients
already implement "explicit kwarg > options field" precedence
internally (TASK-2166/2170) — preserves "explicit kwargs win" exactly.
Migrated the memory-accumulation block from
`"user_transcription"/"assistant_transcription" in response.metadata` to
`response.role == "user"`/`"assistant"` with `response.text` — this ALSO
fixes a latent divergence found while reading the code: the OLD
`assistant_transcription` read only ever populated from Gemini's
separate output-transcription frames (never from Nova, which has no such
key, and duplicated Gemini's own `role="assistant"` text chunks) — Nova
conversations were silently never persisting assistant turns before this
change. 13 new tests in `tests/bots/test_voicebot_contract.py`, using
real `VoiceBot()` construction (the Cython `parrot.utils.types` extension
IS built in this worktree, built manually for TASK-2164 — confirmed live
imports work, unlike the "blocked by Cython" caveat some pre-existing
test files in this directory document for a fresh/unbuilt environment).
The one-time ~8s HuggingFace guardrail-model load happens once per pytest
process, not per test. All 56 bots/ voice-domain tests pass, including
one pre-existing test
(`test_voicebot_refinements.py::test_inference_params_threaded_from_voice_config`)
updated in a preceding commit — it asserted the literal old
`voice_stream_kwargs` dict pattern this task replaces.

**Deviations from spec**: none for the module's own scope. Extended the
memory migration slightly beyond the literal `:583-584` anchor to also
migrate the adjacent `:585-586` `assistant_transcription` read (not
explicitly named in the codebase contract, but covered by the acceptance
criterion "Assistant turns persist via `role == \"assistant\"`" and the
scope bullet "accumulate ... the assistant transcript from
`role == \"assistant\"`") — leaving it on the old key would have left
Nova's assistant turns silently unpersisted, the exact class of bug this
task exists to close.
