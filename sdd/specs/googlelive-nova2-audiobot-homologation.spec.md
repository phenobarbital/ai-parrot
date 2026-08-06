---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Google Gemini Live ↔ Nova 2 Sonic Homologation

**Feature ID**: FEAT-418
**Date**: 2026-08-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.26.0

> Input document: `sdd/proposals/googlelive-nova2-audiobot-homologation.brainstorm.md`
> (Recommended Option C — Versioned voice contract + provider conformance kit;
> all 13 open questions resolved before this spec was written).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-416 (voice-agent-framework, merged 2026-08-06) built the *scaffolding*
for provider-agnostic voice: `VoiceCapable` (a structural Protocol), a
unified `VoiceConfig`, a promoted `VoiceSession`, and parallel tool
execution on both clients. What it did **not** build is *behavioral
equivalence*. Today `GeminiLiveClient` and `NovaClient` satisfy the same
Protocol while behaving differently in at least seven observable ways, so
swapping `VoiceConfig.provider` between `google_live` and `nova` silently
changes what the application receives.

| # | Dimension | Gemini Live | Nova 2 Sonic |
|---|---|---|---|
| 1 | Per-call `temperature`/`max_tokens` | **ignored** — `_build_live_config` reads `self.temperature`/`self.max_tokens` (`live.py:692-693`) | honored from `stream_voice(**kwargs)` (`nova/audio.py:789-791`) |
| 2 | `top_p` | **does not exist** in the Live config | honored (`nova/audio.py:791`) |
| 3 | `stt_only` | native suppression via empty `response_modalities` (`live.py:678-684`) | swallowed by `**kwargs`, silent no-op |
| 4 | Reconnection signal | `metadata["go_away"]` only (`live.py:1077`, `1107`) — `VoiceSession`'s reconnect loop never fires | `metadata["reconnect_required"]` at 465 s (`nova/audio.py:271`, `860`) |
| 5 | Transcript envelope | `role` always `None`; user transcription in `metadata["user_transcription"]` (`live.py:875`) | `role="USER"`/`"ASSISTANT"` (`nova/audio.py:897`, `926-940`) |
| 6 | Voice selection | constructor-only `voice_name` | per-call `voice_id` kwarg + constructor default |
| 7 | Voice naming | `"Puck"`, `"Charon"`, `"Kore"`… | `"matthew"`, `"tiffany"`, `"amy"`… — and `VoiceBot` forwards `voice_config.voice_name` (default `"Puck"`) straight into Nova's `voice_id` (`bots/voice.py:198`) |

Two structural leaks compound this:

- **`VoiceSession` threads nothing.** `_run_turn()` passes only
  `system_prompt` and `session_id` to `stream_voice()`
  (`voice/session.py:182-186`). Every `VoiceConfig` knob FEAT-416 added is
  dropped for any consumer driving the session directly. Only the
  integrations handler escapes it, by re-implementing the entire turn loop
  on top of `bot.ask_stream()` (`handler.py:305-360`) — a ~60-line duplicate
  of the base class's reconnection logic kept in sync by hand.
- **A latent crash on the transcription path.** `stream_voice` forwards
  `enable_input_transcription` / `enable_output_transcription` to
  `_build_live_config` (`live.py:777-780`), whose signature is
  `(system_prompt, response_modalities, stt_only)` (`live.py:652-656`).
  Threading those two `VoiceConfig` fields — the obvious next step of this
  homologation — raises `TypeError`.

Finally, the artifact that would make all of this visible does not exist.
`examples/voice/README.md` documents `examples/voice/bot.py` ("Provider
Switch & Usage Tracking") — **that file is not in the repository**.
`examples/clients/nova/audio.py` is the only working browser demo, it is
Nova-only, it still carries its own pre-FEAT-416 `NovaVoiceSession`
(line 116), and its ~560-line browser UI (`INDEX_HTML`, line 459) is welded
into the Python file.

**Who is affected**: framework users choosing a provider (silent behavior
changes), `VoiceChatHandler` (carries the duplicated loop), `ai-parrot-server`
(mounts that handler at `/ws/voice`), and any frontend consuming the WS frame
protocol (Nova transcripts render, Gemini transcripts do not).

**Why now**: every additional provider multiplies the divergence.
`OPENAI_REALTIME` and `WHISPER_TTS` are already declared in `VoiceProvider`
(`models/voice.py:41-42`) with no implementation — the contract must be
pinned down and *tested* while there are only two implementations.

### Goals

- **G1** — Both clients honor the identical per-call option set:
  `temperature`, `max_tokens`, `top_p`, `stt_only`, `voice`, `language`,
  `parallel_tool_execution`, `enable_input_transcription`,
  `enable_output_transcription`.
- **G2** — A single canonical `LiveVoiceResponse` envelope: lowercase
  `role` (`"user"`/`"assistant"`) from both providers;
  `metadata["user_transcription"]` removed.
- **G3** — A single canonical reconnection signal: both providers emit
  `metadata["reconnect_required"]` at their session limit, and Gemini
  additionally resumes with a `SessionResumptionConfig` handle.
- **G4** — A runtime-inspectable `VoiceCapabilities` descriptor per provider
  covering behavioral knobs, voice catalog, session limits **and audio
  formats / sample rates**.
- **G5** — One reconnection loop in the codebase: `VoiceSession` gains a
  relay extension hook and `_HandlerVoiceSession._run_turn()` is deleted.
- **G6** — A parametrized conformance suite that every `VoiceCapable`
  implementation must pass, so parity is enforced rather than asserted.
- **G7** — `examples/clients/voice/` — one aiohttp server, two
  `VoiceChatHandler` instances (`/ws/gemini`, `/ws/nova`), one browser page
  with a provider switch, UI served from a shared extracted asset.

### Non-Goals (explicitly out of scope)

- **OpenAI Realtime / Whisper+TTS clients.** The enum variants exist; this
  spec makes the contract they will have to meet, it does not implement them.
- **Cross-provider conversation continuity.** Switching provider always
  starts a fresh session (resolved decision) — no memory replay, no
  transcript migration.
- **Abstract voice-name translation.** Rejected in brainstorm — `voice_name`
  stays the provider's native string
  (see `proposals/googlelive-nova2-audiobot-homologation.brainstorm.md`,
  Round 2 "Voice naming").
- **A `VoiceRouterClient` façade.** Rejected in brainstorm Option D — it
  would create a second provider-selection authority alongside
  `VoiceBot._resolve_llm_config()`.
- **Client-side emulation of STT-only on Nova.** Nova always generates;
  the response is *not* filtered away (resolved decision).
- **Deprecation window / dual-emission** of the old envelope. Clean break.
- **Avatar / LiveAvatar session management** and WebRTC/SIP transport —
  untouched, as in FEAT-416.

---

## 2. Architectural Design

### Overview

Promote "drop-in" from a claim to an executable contract, in three pieces,
plus the client work needed to satisfy it.

1. **`VoiceStreamOptions`** — a frozen dataclass carrying the per-call
   option set (G1). `VoiceCapable.stream_voice()` accepts it as an optional
   parameter; `**kwargs` remains for provider-specific extras.
   `VoiceConfig.to_stream_options()` is the single projection used by
   `VoiceBot`, `VoiceSession` and `VoiceChatHandler`, collapsing today's
   three divergent threading paths into one.
2. **`VoiceCapabilities`** — a frozen dataclass exposed as a
   `voice_capabilities` property on the Protocol, declaring per provider what
   is natively supported: behavioral knobs, `voice_catalog`,
   `max_session_seconds`, `max_output_tokens`, and the audio-format contract
   (`input_formats`/`output_formats` + sample rates). Requesting an
   unsupported knob logs once per session and emits a `capability_notice`
   frame — never a silent divergence, never a hard failure.
3. **A conformance kit** — a parametrized pytest suite driving *every*
   declared `VoiceCapable` implementation against mocked provider streams,
   asserting the canonical contract and that each declared capability matches
   observed behavior.

Client work to pass the kit: Gemini learns per-call inference params,
`top_p`, real transcription-flag parameters, per-call voice override,
`session_resumption`, `GoAway → reconnect_required`, and canonical `role`.
Nova learns voice-id validation, canonical lowercase `role`, and explicit
(non-native, unfiltered) `stt_only` acceptance.

Envelope migration is a clean break across all three distributions
(resolved decision, scope confirmed during codebase research): the producer,
`VoiceBot`'s memory path, both handler call sites, the shipped `chat.html`
legacy branch, the frontend guide, and the tests in `ai-parrot-integrations`
and `ai-parrot-server`.

### Component Diagram

```
                         VoiceConfig  (models/voice.py — single source of truth)
                              │
                              │  .to_stream_options()      ← NEW projection
                              ▼
                      VoiceStreamOptions  (frozen)         ← NEW
                              │
        ┌─────────────────────┼──────────────────────┐
        │                     │                      │
   VoiceBot.ask_stream   VoiceSession._run_turn   VoiceChatHandler
        │                     │  (+ relay hook)       │  (_HandlerVoiceSession:
        │                     │                       │   _relay override ONLY —
        │                     │                       │   _run_turn DELETED)
        └─────────────────────┴──────────────────────┘
                              │
                              ▼
                   VoiceCapable  (Protocol, runtime_checkable)
                   ├── async stream_voice(..., options=None, **kwargs)
                   └── property voice_capabilities -> VoiceCapabilities   ← NEW
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
     GeminiLiveClient                    NovaClient (NovaAudio)
     • per-call temp/max_tokens/top_p    • voice-id validation + fallback
     • transcription flags (real params) • canonical lowercase role
     • per-call voice override           • stt_only accepted, non-native
     • session_resumption handle         • max_tokens default → VoiceConfig
     • GoAway → reconnect_required       • (already) reconnect_required @465s
     • canonical lowercase role
             │                                 │
             └──────────────┬──────────────────┘
                            ▼
         canonical LiveVoiceResponse envelope
         role="user"|"assistant" · metadata["reconnect_required"]
         (metadata["user_transcription"] REMOVED)
                            │
                            ▼
              tests/voice/test_provider_conformance.py   ← NEW, parametrized
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/clients/base.py` (`AbstractClient`) | **unmodified** | Voice stays a Protocol-level capability (CLAUDE.md constraint) |
| `parrot/clients/protocols.py` | extends | `VoiceCapable` gains `options` param + `voice_capabilities`; stays `@runtime_checkable` |
| `parrot/models/voice.py` | extends | `VoiceStreamOptions`, `VoiceCapabilities`, `VoiceConfig.to_stream_options()` |
| `parrot/clients/live.py` | modifies | inference params, `top_p`, transcription params, per-call voice, resumption, `reconnect_required`, canonical `role` |
| `parrot/clients/nova/audio.py` | modifies | voice-id validation, canonical `role`, `stt_only` acceptance, `max_tokens` default |
| `parrot/clients/nova/client.py` | modifies | `voice_capabilities` + voice catalog |
| `parrot/voice/session.py` | modifies | options threading (incl. across reconnect), relay extension hook, capability preflight |
| `parrot/bots/voice.py` | modifies | uses the projection instead of the ad-hoc `voice_stream_kwargs` dict (`:539-545`); stops blind `voice_name`→`voice_id` mapping (`:198`); memory path migrates off `metadata["user_transcription"]` (`:583-584`) |
| `parrot/voice/handler.py` (integrations) | **breaking** | `_HandlerVoiceSession._run_turn()` deleted; two `user_transcription` call sites migrated |
| `parrot/voice/ui/chat.html` (integrations) | **breaking** | legacy `message.user_transcription` branch removed (`:1096-1097`) |
| `parrot/manager/manager.py` (ai-parrot-server) | **unmodified** | only mounts `VoiceChatHandler` at `/ws/voice` (`:1528-1550`); no envelope access |
| `ai-parrot-server` voice tests | **breaking** | two tests construct `metadata={"user_transcription": …}` fixtures |
| `docs/frontend/voicebot-realtime-frontend-guide.md` | **breaking** | frame-protocol doc updated for canonical `role` |
| `examples/clients/nova/audio.py` | modifies | migrate to core `VoiceSession`; UI extracted |
| `examples/clients/voice/` | **new** | dual-handler provider-switch demo + shared static UI |
| `examples/voice/README.md` | modifies | reconcile with reality (documents a non-existent `bot.py`) |

### Data Models

```python
# parrot/models/voice.py (NEW — alongside the existing VoiceConfig)

@dataclass(frozen=True)
class VoiceStreamOptions:
    """Per-call voice options, projected from VoiceConfig.

    Provider-specific extras continue to travel via **kwargs; anything in
    THIS object must be honored identically by every VoiceCapable client.
    """
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    voice: Optional[str] = None          # provider-native name; None = provider default
    language: str = "en-US"
    stt_only: bool = False
    parallel_tool_execution: bool = False
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True


@dataclass(frozen=True)
class VoiceCapabilities:
    """What a provider natively supports. Inspectable at runtime and
    asserted against observed behavior by the conformance suite."""
    provider: VoiceProvider

    # Behavioral knobs
    native_stt_only: bool                 # False for Nova: it always generates
    supports_top_p: bool
    supports_per_call_voice: bool
    supports_per_call_inference: bool
    parallel_tool_execution: bool

    # Session lifecycle
    emits_reconnect_signal: bool
    supports_session_resumption: bool
    max_session_seconds: Optional[float]  # None = no documented provider limit

    # Inference bounds
    max_output_tokens: int

    # Audio contract (G4) — descriptive today, load-bearing for a future
    # non-PCM provider (Opus, mu-law, other rates).
    input_formats: frozenset[AudioFormat]
    output_formats: frozenset[AudioFormat]
    input_sample_rates: frozenset[int]
    output_sample_rates: frozenset[int]

    # Synthesis
    voice_catalog: frozenset[str]
    default_voice: str


# parrot/models/voice.py (MODIFIED — VoiceConfig gains one method)
class VoiceConfig:
    def to_stream_options(self, **overrides) -> VoiceStreamOptions:
        """Project this config into the per-call option object.

        `overrides` win over config-derived values, preserving the
        precedence VoiceBot.ask_stream() implements today at
        bots/voice.py:539-545.
        """
```

### New Public Interfaces

```python
# parrot/clients/protocols.py (MODIFIED)

@runtime_checkable
class VoiceCapable(Protocol):
    @property
    def voice_capabilities(self) -> VoiceCapabilities: ...

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        options: Optional[VoiceStreamOptions] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...


# parrot/voice/session.py (MODIFIED)
class VoiceSession:
    async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None:
        """Unchanged default behavior; now delegates frame construction to
        the relay hook below so subclasses need not re-implement _run_turn."""

    def build_frames(self, resp: LiveVoiceResponse, turn_no: int) -> list[dict]:
        """Relay extension hook (G5). Subclasses override THIS to emit a
        richer frame protocol; the turn loop and reconnection stay inherited.
        """


# parrot/clients/live.py + parrot/clients/nova/client.py (MODIFIED)
#   both gain:  @property def voice_capabilities(self) -> VoiceCapabilities
```

---

## 3. Module Breakdown

### Module 1: Voice contract types
- **Path**: `packages/ai-parrot/src/parrot/models/voice.py`
- **Responsibility**: Add `VoiceStreamOptions` and `VoiceCapabilities`
  frozen dataclasses and `VoiceConfig.to_stream_options(**overrides)`.
  Export both from the module. No behavior change to existing fields.
- **Depends on**: nothing (leaf module — `AudioFormat`/`VoiceProvider` are
  already defined here at lines 24-46)

### Module 2: `VoiceCapable` Protocol extension
- **Path**: `packages/ai-parrot/src/parrot/clients/protocols.py`
- **Responsibility**: Add the `options` parameter to `stream_voice()` and the
  `voice_capabilities` property. Must remain `@runtime_checkable` so
  `VoiceBot._create_llm_client()`'s existing `isinstance` gate
  (`bots/voice.py:273`) keeps working.
- **Depends on**: Module 1
- **Gotcha**: `@runtime_checkable` `isinstance()` checks method **presence**
  only, not signatures — adding a property to the Protocol makes any client
  lacking `voice_capabilities` fail that gate. Both clients must gain the
  property in Modules 3/4 before this lands, or the gate breaks.

### Module 3: Gemini Live parity
- **Path**: `packages/ai-parrot/src/parrot/clients/live.py`
- **Responsibility**:
  - `_build_live_config()` accepts per-call `temperature`, `max_tokens`,
    `top_p` (falling back to the constructor values), plus **real**
    `enable_input_transcription` / `enable_output_transcription` parameters
    — fixing the latent `TypeError` at `live.py:777-780`.
  - Per-call voice override.
  - `stream_voice()` accepts `options: VoiceStreamOptions`.
  - Canonical lowercase `role` on every yielded `LiveVoiceResponse`;
    user transcription emitted as a text response with `role="user"`
    instead of `metadata["user_transcription"]`.
  - `voice_capabilities` property.
- **Depends on**: Module 1

### Module 4: Nova 2 Sonic parity
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`,
  `packages/ai-parrot/src/parrot/clients/nova/client.py`
- **Responsibility**:
  - Voice-id validation against the Nova catalog with a warned fallback to
    `"matthew"` (today `resolved_voice_id` is used unvalidated,
    `nova/audio.py:761`).
  - Canonical lowercase `role` (currently `"USER"`/`"ASSISTANT"` from
    `contentStart`, `nova/audio.py:897`).
  - `stt_only` accepted as an explicit parameter: **not** emulated, **not**
    raising; logged once and reported via `native_stt_only=False`.
  - `max_tokens` hardcoded fallback `1024` (`nova/audio.py:790`) replaced by
    the `VoiceConfig` default of `4096`.
  - `options: VoiceStreamOptions` support + `voice_capabilities` property.
- **Depends on**: Module 1
- **Note**: Nova's real `max_output_tokens` ceiling must be confirmed against
  the Bedrock docs so `8192` is validated rather than silently clamped.

### Module 5: Gemini session resumption
- **Path**: `packages/ai-parrot/src/parrot/clients/live.py`
- **Responsibility**: Enable `types.SessionResumptionConfig` on connect,
  retain the handle from `LiveServerSessionResumptionUpdate`, and on `GoAway`
  emit `metadata["reconnect_required"]=True` (keeping `go_away` as an extra
  informational flag) so `VoiceSession`'s existing loop reconnects — using
  the stored handle. Falls back to a cold reconnect when the handle is
  rejected or expired.
- **Depends on**: Module 3

### Module 6: `VoiceSession` threading + relay hook
- **Path**: `packages/ai-parrot/src/parrot/voice/session.py`
- **Responsibility**:
  - Accept/derive `VoiceStreamOptions` and forward it on every turn **and on
    every reconnect** (today `_run_turn()` forwards nothing,
    `voice/session.py:182-186`).
  - Add the `build_frames()` relay hook so subclasses reshape frames without
    re-implementing the turn loop.
  - Capability preflight: compare `VoiceConfig.input_format`/`output_format`
    against the client's declared formats and fail at construction on
    mismatch; emit `capability_notice` for requested-but-unsupported knobs.
- **Depends on**: Modules 1, 2

### Module 7: `VoiceBot` wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/voice.py`
- **Responsibility**: Replace the ad-hoc `voice_stream_kwargs` dict
  (`:539-545`) with `voice_config.to_stream_options(**kwargs)`; stop mapping
  `voice_config.voice_name` blindly into Nova's `voice_id` (`:198`) — pass
  the native name and let the client validate; migrate the conversation-memory
  path (`:583-584`) from `metadata["user_transcription"]` to `role == "user"`.
- **Depends on**: Modules 1, 3, 4

### Module 8: Handler de-duplication + envelope migration (integrations)
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`,
  `packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html`
- **Responsibility**: Delete `_HandlerVoiceSession._run_turn()` (`:305-360`)
  in favor of the inherited loop + `build_frames()` override; migrate both
  `user_transcription` call sites (`:1481-1484`, `:1614-1617`) to canonical
  `role`; remove the legacy `message.user_transcription` branch in
  `chat.html:1096-1097`.
- **Depends on**: Modules 6, 7

### Module 9: Provider conformance kit
- **Path**: `packages/ai-parrot/tests/voice/test_provider_conformance.py`
- **Responsibility**: One parametrized suite over every declared
  `VoiceCapable` implementation, asserting: options honored, canonical
  `role`, canonical reconnect signal, identical `VoiceSession` frame
  sequence, and descriptor-vs-behavior consistency. Adding a provider must
  cost one line in the parametrization.
- **Depends on**: Modules 3, 4, 6

### Module 10: Cross-distribution test migration
- **Path**: `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py`,
  `packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py`,
  `packages/ai-parrot-server/tests/handlers/test_voice_ws_stt_only_integration.py`
- **Responsibility**: Migrate the fixtures that construct
  `metadata={"user_transcription": …}` to the canonical envelope, so all
  three distributions stay green in the same change.
- **Depends on**: Module 8

### Module 11: Shared browser UI asset
- **Path**: `examples/clients/voice/static/` (new),
  `examples/clients/nova/audio.py`
- **Responsibility**: Extract `INDEX_HTML` (`examples/clients/nova/audio.py:459`,
  ~560 lines) into a standalone static asset; migrate the Nova example off its
  stale local `NovaVoiceSession` (`:116`) onto `parrot.voice.session.VoiceSession`.
- **Depends on**: Module 6

### Module 12: Provider-switch example
- **Path**: `examples/clients/voice/` (new), `examples/voice/README.md`
- **Responsibility**: One aiohttp server mounting two `VoiceChatHandler`
  instances (`/ws/gemini`, `/ws/nova`), each backed by a `VoiceBot` with the
  same name/prompt/tools and a different `VoiceConfig`. Browser page with a
  provider toggle (switch = fresh session, old socket closed), a live
  capability panel from `voice_capabilities`, and per-provider token/latency
  counters. Nova route reports unavailable on Python 3.11. Reconcile
  `examples/voice/README.md`, which documents a non-existent `bot.py`.
- **Depends on**: Modules 8, 11

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_stream_options_defaults` | 1 | All 9 fields exist with documented defaults; dataclass is frozen |
| `test_to_stream_options_projection` | 1 | `VoiceConfig` values map 1:1 onto `VoiceStreamOptions` |
| `test_to_stream_options_overrides_win` | 1 | Explicit overrides beat config values (preserves `bots/voice.py:539-545` precedence) |
| `test_capabilities_declares_audio_formats` | 1 | `input_formats`/`output_formats`/sample-rate sets are populated, not empty |
| `test_voice_capable_still_runtime_checkable` | 2 | `isinstance(GeminiLiveClient(...), VoiceCapable)` and same for `NovaClient` |
| `test_voice_capable_rejects_client_without_capabilities` | 2 | A client with `stream_voice()` but no `voice_capabilities` fails the gate |
| `test_gemini_honors_per_call_temperature` | 3 | `LiveConnectConfig.temperature` reflects the per-call value, not the constructor's |
| `test_gemini_honors_per_call_max_tokens` | 3 | Same for `max_output_tokens` |
| `test_gemini_applies_top_p` | 3 | `top_p` reaches the Live config (today it exists nowhere) |
| `test_gemini_transcription_flags_accepted` | 3 | Passing `enable_input_transcription`/`enable_output_transcription` does NOT raise `TypeError` (regression for `live.py:777-780`) |
| `test_gemini_per_call_voice_override` | 3 | Per-call voice beats the constructor's `voice_name` |
| `test_gemini_emits_canonical_role` | 3 | Model text yields `role="assistant"`; transcribed input yields `role="user"` |
| `test_gemini_no_user_transcription_metadata` | 3 | `metadata` no longer carries `user_transcription` |
| `test_nova_voice_id_validated` | 4 | A catalog voice passes through unchanged |
| `test_nova_invalid_voice_falls_back_warned` | 4 | `"Puck"` → `"matthew"` + warning, never an opaque provider error |
| `test_nova_emits_canonical_role` | 4 | `"ASSISTANT"`/`"USER"` normalized to lowercase |
| `test_nova_stt_only_accepted_not_raising` | 4 | `stt_only=True` does not raise and does not suppress the model response |
| `test_nova_capabilities_native_stt_only_false` | 4 | Descriptor tells the truth about STT-only |
| `test_nova_max_tokens_default_from_config` | 4 | Default is `4096`, not the old hardcoded `1024` |
| `test_gemini_goaway_sets_reconnect_required` | 5 | `GoAway` produces `metadata["reconnect_required"]=True` |
| `test_gemini_resumption_handle_retained` | 5 | Handle from `LiveServerSessionResumptionUpdate` is stored and reused on reconnect |
| `test_gemini_resumption_rejected_falls_back_cold` | 5 | Expired handle → cold reconnect, `resumed: false` marker |
| `test_session_forwards_options` | 6 | `stream_voice()` receives the projected options (regression for `voice/session.py:182-186`) |
| `test_session_forwards_options_on_reconnect` | 6 | Options survive the reconnect loop, not just the first turn |
| `test_build_frames_hook_used` | 6 | Overriding `build_frames()` changes emitted frames without touching `_run_turn` |
| `test_session_format_mismatch_fails_fast` | 6 | Unsupported `AudioFormat` raises at construction, not mid-stream |
| `test_capability_notice_emitted_once` | 6 | Unsupported knob logs/emits once per session, not per frame |
| `test_voicebot_uses_projection` | 7 | `ask_stream()` builds options via `to_stream_options()` |
| `test_voicebot_memory_from_role` | 7 | User turns persist via `role="user"`, not `metadata` (regression for `bots/voice.py:583-584`) |
| `test_voicebot_passes_native_voice_name` | 7 | No blind `voice_name`→`voice_id` mapping (regression for `bots/voice.py:198`) |
| `test_handler_run_turn_deleted` | 8 | `_HandlerVoiceSession` no longer defines `_run_turn` (inherits it) |
| `test_handler_transcription_frames_canonical` | 8 | Handler emits `transcription`/`is_user` frames from canonical `role` |

### Integration Tests

| Test | Description |
|---|---|
| `test_provider_conformance[gemini]` / `[nova]` | The Module 9 kit: same options in, same envelope out, same `VoiceSession` frame sequence, for each provider |
| `test_capabilities_match_behavior[gemini]` / `[nova]` | Every `True` in the descriptor is demonstrated; every `False` is demonstrated absent |
| `test_drop_in_swap_identical_frames` | Same mocked audio + same `VoiceConfig` (provider aside) produce structurally identical frame sequences from both providers |
| `test_reconnect_loop_parity` | Both providers' reconnect signals drive the same `VoiceSession` path to the same frames |
| `test_handler_end_to_end_after_dedup` | `VoiceChatHandler` full turn works with the inherited loop + `build_frames()` |
| `test_example_dual_handler_routes` | `/ws/gemini` and `/ws/nova` both accept a session and stream a mocked turn |
| `test_nova_route_unavailable_on_py311` | Missing `aws_sdk_bedrock_runtime` marks the Nova route unavailable rather than failing startup |

### Test Data / Fixtures

```python
# Extend the existing pattern in packages/ai-parrot/tests/voice/test_voice_session.py:9
# (MockVoiceClient) and test_voice_reconnection.py:11 (ReconnectingMockClient).

@pytest.fixture(params=["google_live", "nova"])
def conformance_client(request):
    """Parametrization seam for the conformance kit — adding a provider is
    one entry here."""

@pytest.fixture
def recording_client():
    """VoiceCapable double that records the exact `options` object and
    kwargs it received, so threading assertions are direct."""

@pytest.fixture
def mock_send_fn():
    """Collects relayed frames — reuse verbatim from
    tests/voice/test_voice_session.py:20-27."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

**Contract (G1, G4)**
- [ ] `VoiceStreamOptions` and `VoiceCapabilities` exist in `parrot.models.voice`, are frozen, and are exported.
- [ ] `VoiceConfig.to_stream_options(**overrides)` exists; overrides beat config values.
- [ ] `VoiceCapabilities` declares input/output `AudioFormat` sets and sample rates for both providers.
- [ ] `VoiceCapable` still satisfies `isinstance()` for both clients after gaining `voice_capabilities`.

**Parity (G1, G2, G3)**
- [ ] Gemini honors per-call `temperature`, `max_tokens` and `top_p`.
- [ ] Passing `enable_input_transcription`/`enable_output_transcription` to Gemini's `stream_voice()` does not raise (latent `TypeError` closed).
- [ ] Gemini supports a per-call voice override.
- [ ] Both providers emit lowercase `role` (`"user"`/`"assistant"`) on every response.
- [ ] `metadata["user_transcription"]` no longer appears anywhere in the codebase.
- [ ] Both providers emit `metadata["reconnect_required"]` at their session limit; Gemini reconnects using a resumption handle and falls back cold when it is rejected.
- [ ] Nova validates `voice_id` against its catalog and falls back to `"matthew"` with a warning.
- [ ] Nova accepts `stt_only=True` without raising, without filtering the model response, and reports `native_stt_only=False`.
- [ ] Nova's voice `max_tokens` default is `4096` (no hardcoded `1024`); `8192` is accepted.

**Structure (G5, G6)**
- [ ] `VoiceSession` forwards the projected options on the first turn **and** across reconnects.
- [ ] `_HandlerVoiceSession` no longer defines `_run_turn()`; exactly one reconnection loop exists in the codebase.
- [ ] `test_provider_conformance.py` runs parametrized over both providers and passes; adding a provider costs one parametrization entry.
- [ ] Descriptor-vs-behavior consistency is asserted, not just declared.

**Migration (breaking change, no deprecation window)**
- [ ] All 8 `user_transcription` sites migrated: `clients/live.py`, `bots/voice.py`, `voice/handler.py` (×2), `voice/ui/chat.html`, and tests in `ai-parrot-integrations` (×1) and `ai-parrot-server` (×2).
- [ ] `VoiceBot` conversation memory still records user turns (now via `role`), verified by test.
- [ ] `docs/frontend/voicebot-realtime-frontend-guide.md` documents the canonical envelope.
- [ ] Test suites of all three distributions pass: `pytest packages/ai-parrot/tests/voice/ packages/ai-parrot/tests/bots/ -v`, `pytest packages/ai-parrot-integrations/tests/voice/ -v`, `pytest packages/ai-parrot-server/tests/handlers/ -v`.

**Example (G7)**
- [ ] `examples/clients/voice/` serves two `VoiceChatHandler` instances on `/ws/gemini` and `/ws/nova` from one aiohttp app.
- [ ] The browser page switches provider, closing the old socket and starting a fresh session (no memory replay).
- [ ] The page renders a capability panel sourced from `voice_capabilities` and per-provider usage counters.
- [ ] The browser UI lives in a shared static asset, not inlined in a `.py` file.
- [ ] `examples/clients/nova/audio.py` uses `parrot.voice.session.VoiceSession` (its local `NovaVoiceSession` is gone) and still runs.
- [ ] `examples/voice/README.md` no longer documents a non-existent `bot.py`.
- [ ] On Python 3.11 the Nova route reports unavailable and the Gemini route works.

**Hygiene**
- [ ] `AbstractClient` (`parrot/clients/base.py`) is unmodified.
- [ ] No blocking I/O added to async paths; `aiohttp` only in the example.
- [ ] Google-style docstrings + type hints on all new public surface.
- [ ] No live AWS/Google calls in CI — every test runs against mocked streams.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All line numbers below were re-verified against the working tree on
> 2026-08-07 (31 of 35 brainstorm anchors matched exactly; the 4 that had
> drifted are corrected here).

### Verified Imports

```python
from parrot.clients.protocols import VoiceCapable            # clients/protocols.py:16
from parrot.clients.live import (                            # clients/live.py
    GeminiLiveClient, LiveVoiceResponse, LiveCompletionUsage, LiveToolCall,
    VoiceTurnMetadata, LiveToolAdapter,
)
from parrot.clients.nova import NovaClient                   # clients/nova/client.py
from parrot.voice.session import VoiceSession                # voice/session.py:36 (core; PEP 420 + pkgutil.extend_path)
from parrot.models.voice import VoiceConfig, VoiceProvider, AudioFormat   # models/voice.py:49, :30, :24
from parrot.bots import VoiceBot                             # bots/__init__.py:12, __all__ at :21
from parrot.voice.handler import VoiceChatHandler            # ai-parrot-integrations, handler.py:388
from google.genai import types                               # google-genai 2.17.0 installed
```

### Existing Class Signatures

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
```

```python
# packages/ai-parrot/src/parrot/clients/live.py
class LiveVoiceResponse:
    role: Optional[str] = None                                # line 187 — always None from stream_voice
    metadata: Dict[str, Any]                                  # carries user_transcription / go_away today

def _build_live_config(                                       # line 652
    self,
    system_prompt: Optional[str] = None,
    response_modalities: Optional[List[str]] = None,
    stt_only: bool = False,                                   # line 656
) -> types.LiveConnectConfig:
    ...
    temperature=self.temperature,                             # line 692 — constructor, NOT per-call
    max_output_tokens=self.max_tokens,                        # line 693 — constructor, NOT per-call
    # no top_p anywhere in this config

async def stream_voice(                                       # line 729
    self, audio_iterator, system_prompt=None, session_id=None,
    user_id=None,
    stt_only: bool = False,                                   # line 735
    **kwargs,
) -> AsyncIterator[LiveVoiceResponse]:
    parallel_tool_execution = kwargs.get("parallel_tool_execution", False)   # line 772
    live_config = self._build_live_config(                                   # line 774
        system_prompt=system_prompt,
        stt_only=stt_only,
        **{k: v for k, v in kwargs.items() if k in (                         # lines 777-780
            'response_modalities',
            'enable_input_transcription',      # ← NOT a _build_live_config param → TypeError
            'enable_output_transcription',     # ← NOT a _build_live_config param → TypeError
        )}
    )
    ...
    metadata={"user_transcription": text},                    # line 875 — to be REMOVED
    ...
    metadata={"go_away": True, "reason": str(response.go_away)},   # line 1077
    metadata={"go_away": True, "reason": "Server closed session (1008)"},  # line 1107
```

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py
_CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15                # line 271 (465 s)

async def stream_voice(                                       # line 712
    self, audio_iterator, system_prompt=None, session_id=None,
    user_id=None, **kwargs,                                   # no stt_only → silent no-op
) -> AsyncIterator[LiveVoiceResponse]:
    resolved_voice_id = kwargs.get("voice_id") or self.voice_id   # line 761 — UNVALIDATED
    parallel_tool_execution = kwargs.get("parallel_tool_execution", False)  # line 765
    temperature = kwargs.get("temperature", 0.7)              # line 789
    max_tokens = kwargs.get("max_tokens", 1024)               # line 790 — → 4096
    top_p = kwargs.get("top_p", 0.9)                          # line 791
    ...
    metadata={"reconnect_required": True},                    # line 860
    turn_state.role = content_start.get("role")               # line 897 — "USER"/"ASSISTANT" uppercase
```

```python
# packages/ai-parrot/src/parrot/clients/nova/client.py
def __init__(self, ..., voice_id: str = "matthew", ...):      # line 75
    self.voice_id = voice_id                                  # line 109
```

```python
# packages/ai-parrot/src/parrot/voice/session.py
class VoiceSession:                                           # line 36
    async def _run_turn(self, turn_no: int) -> None:          # line 165
        while True:                                           # line 180 — reconnect loop
            stream = self.client.stream_voice(                # line 182
                self._audio_iterator(queue),
                system_prompt=self.system_prompt,
                session_id=self.session_id,
            )                                                 # ← NO VoiceConfig kwargs
    async def _relay(self, resp, turn_no) -> None:            # line 253
        ... "role": resp.role                                 # line 271
```

```python
# packages/ai-parrot/src/parrot/models/voice.py
class AudioFormat(Enum):          # line 24
    PCM_16K = "audio/pcm;rate=16000"   # line 26
    PCM_24K = "audio/pcm;rate=24000"   # line 27
class VoiceProvider(str, Enum):   # line 30
    GOOGLE_LIVE = "google_live"   # line 40
    NOVA = "nova"                 # line 46
@dataclass
class VoiceConfig:                # line 49
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE   # line 60
    voice_name: str = "Puck"      # line 73
    max_tokens: int = 4096        # line 78
    top_p: float = 0.9            # line 79
    def get_model(self) -> str:   # line 107 — the ONLY method besides __post_init__ (line 99)
```

```python
# packages/ai-parrot/src/parrot/bots/voice.py
extra={'voice_id': kwargs.get('voice_id', self.voice_config.voice_name), …}  # line 198 — "Puck" → Nova
if not isinstance(client, VoiceCapable):                      # line 273
voice_stream_kwargs = { ... }                                 # lines 539-545 — to be replaced
if "user_transcription" in response.metadata:                 # line 583 — MEMORY PATH
    user_transcript += " " + response.metadata["user_transcription"]   # line 584
```

```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
def resolve_voice_client_class(provider) -> type:             # line 79
class _HandlerVoiceSession(VoiceSession):                     # line 264
    async def _run_turn(self, turn_no: int) -> None:          # line 305 — DELETE (dup of session.py:165)
class VoiceChatHandler:                                       # line 388
    if metadata.get("user_transcription"):                    # line 1481
    async def _run_voice_session(self, connection) -> None:   # line 1527
    if response.metadata.get("user_transcription"):           # line 1614
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VoiceStreamOptions` | `VoiceConfig.to_stream_options()` | new method on existing dataclass | `models/voice.py:49` |
| `VoiceCapabilities` | `VoiceCapable.voice_capabilities` | new Protocol property | `clients/protocols.py:16` |
| options threading | `VoiceSession._run_turn()` | `stream_voice(..., options=…)` | `voice/session.py:182` |
| options threading | `VoiceBot.ask_stream()` | replaces `voice_stream_kwargs` | `bots/voice.py:539-545` |
| `build_frames()` hook | `_HandlerVoiceSession` | override replaces `_run_turn()` | `handler.py:264`, `:305` |
| canonical `role` | `VoiceBot` memory persistence | `role == "user"` replaces metadata read | `bots/voice.py:583-584` |
| canonical `role` | `VoiceChatHandler` transcription frames | replaces metadata read | `handler.py:1481`, `:1614` |
| Gemini resumption | `types.SessionResumptionConfig` | `LiveConnectConfig` field | `google/genai/types.py:20484-20598` (v2.17.0) |
| conformance kit | existing mocks | extends `MockVoiceClient` / `ReconnectingMockClient` | `tests/voice/test_voice_session.py:9`, `test_voice_reconnection.py:11` |
| example handlers | `VoiceChatHandler` | two instances, two routes | `handler.py:388`; mount precedent `parrot/manager/manager.py:1528-1550` |

### Does NOT Exist (Anti-Hallucination)

- ~~`VoiceBotHandler`~~ — the class is `VoiceChatHandler` (`handler.py:388`). No `VoiceBotHandler` exists anywhere in the repo.
- ~~`examples/voice/bot.py`~~ — documented in detail by `examples/voice/README.md` but **not in the repository**. `examples/voice/` holds only `README.md` and `spike_liveavatar.py`.
- ~~`examples/clients/voice/`~~ — does not exist yet; this feature creates it.
- ~~`VoiceStreamOptions`~~, ~~`VoiceCapabilities`~~, ~~`UnsupportedVoiceCapability`~~, ~~`VoiceProviderAdapter`~~ — none exist; all introduced here.
- ~~`VoiceConfig.to_stream_options()`~~ — not a method today (`get_model()` at `models/voice.py:107` is the only one besides `__post_init__`).
- ~~`VoiceSession.build_frames()`~~ — not a method today; introduced by Module 6.
- ~~`GeminiLiveClient` `top_p` support~~ — `top_p` appears only in a `**kwargs` docstring (`live.py:574`); never reaches `LiveConnectConfig`.
- ~~`_build_live_config(enable_input_transcription=…)`~~ / ~~`enable_output_transcription=…`~~ — not parameters (`live.py:652-656`), despite `stream_voice` forwarding them (`:777-780`).
- ~~`NovaAudio.stream_voice(stt_only=…)`~~ — not a parameter; absorbed by `**kwargs`.
- ~~`GeminiLiveClient.stream_voice` setting `role`~~ — `role="user"` is set only in `ask()` (`live.py:1266`), never in the streaming path.
- ~~Nova emitting `metadata["go_away"]`~~ / ~~Gemini emitting `metadata["reconnect_required"]`~~ — each provider emits only its own signal today.
- ~~`VoiceSession` forwarding `VoiceConfig` params~~ — `_run_turn()` passes only `system_prompt` + `session_id` (`voice/session.py:182-186`).
- ~~A shared/extracted browser voice UI asset~~ — the only demo UI is inlined at `examples/clients/nova/audio.py:459`.
- ~~`parrot/voice/__init__.py` in the **core** package~~ — intentionally absent (bare PEP 420 dir); the integrations `__init__.py` merges both via `pkgutil.extend_path`. **Do not add one** — it would break `parrot.voice.session` resolution.
- ~~A voice handler in `ai-parrot-server` source~~ — the server only *mounts* `VoiceChatHandler` (`parrot/manager/manager.py:1528-1550`); only its **tests** touch the envelope.
- ~~`VoiceCapabilities` audio-format enforcement existing today~~ — no format negotiation exists anywhere; sample rates are hardcoded assumptions.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Protocol, not ABC.** Extend `VoiceCapable` in place, keeping
  `@runtime_checkable` (mirrors `AnthropicBackendProtocol` in
  `clients/anthropic_backends.py`). `AbstractClient` is not touched.
- **Frozen dataclasses** for both new types, matching the existing
  `VoiceConfig`/`AudioFormat` style in `models/voice.py` (this module uses
  stdlib dataclasses + Enum, not Pydantic — stay consistent with the file).
- **One projection, three consumers.** `VoiceConfig.to_stream_options()` is
  the only place config becomes per-call options.
- **Preserve FEAT-416 invariants** in `VoiceSession`: relay the frame
  (including its `tool_calls`) *before* evaluating `reconnect_required`
  (`voice/session.py:188-200`), and never `await` the current task when
  tearing down from inside it (`:216-219`).
- **Lazy Nova SDK.** `aws_sdk_bedrock_runtime==0.7.0` is Python ≥3.12-only
  and pre-alpha; `NovaClient` must keep importing on 3.11
  (`_require_voice_sdk` at first `stream_voice()`).
- **`aiohttp` only** for the example transport. Never `requests`/`httpx`.
- **`self.logger`**, Google-style docstrings, strict type hints throughout.

### Known Risks / Gotchas

- **`@runtime_checkable` gate breakage (Module 2).** `isinstance()` against a
  Protocol checks member *presence*. The moment `voice_capabilities` joins
  the Protocol, any client lacking it fails `bots/voice.py:273`. Land the
  property on both clients before/with the Protocol change.
- **Silent memory loss (Module 7).** `bots/voice.py:583-584` builds the user
  transcript from `metadata["user_transcription"]`. Removing the key without
  migrating this line makes `VoiceBot` persist empty user turns — a silent
  data bug, not a crash. `test_voicebot_memory_from_role` is the guard.
- **Three-distribution break.** The envelope change spans `ai-parrot`,
  `ai-parrot-integrations` and `ai-parrot-server`. Land the migration
  together or CI goes red in packages the change did not "belong" to.
- **Nova token-budget jump.** Dropping the hardcoded `1024` moves Nova voice
  turns to `4096` — a 4× budget change. Intended (resolved decision), but
  confirm Nova 2 Sonic's real ceiling against the Bedrock docs so `8192` is
  validated, not silently clamped.
- **STT-only on Nova is honest, not equivalent.** `stt_only=True` still
  returns the model's spoken answer and still costs tokens. Documented via
  `native_stt_only=False`; do **not** "fix" this by filtering the response.
- **Gemini resumption is not free continuity.** A rejected/expired handle
  must fall back to a cold reconnect rather than dropping the turn; mark the
  frame `resumed: false` so the UI can tell the difference.
- **Silence pacing is load-bearing.** `end_turn()`'s 20 ms-paced silence
  frames (`voice/session.py:121-127`) exist because bursting them makes VAD
  miss end-of-speech. Do not "optimize" the loop while touching this file.
- **`parrot.voice` is split across distributions.** Core ships
  `voice/session.py` with **no** `__init__.py`; integrations' `__init__.py`
  merges them with `pkgutil.extend_path`. Adding a core `__init__.py` breaks
  imports.
- **Provider switch = new session.** The example must close the old socket
  and tear down its `VoiceSession`; no memory replay across providers.
- **Voice catalogs need a source of truth.** The Nova list in the docstring
  (`nova/audio.py:737`: `matthew`, `tiffany`, `amy`) and the Gemini prebuilt
  voice list are both partial. Confirm both against provider docs before
  freezing `voice_catalog`, and prefer a warned fallback over a hard reject
  if the catalog turns out to be incomplete.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `google-genai` | `>=2.10.0` (2.17.0 installed) | `types.SessionResumptionConfig` / `LiveServerSessionResumptionUpdate` for Gemini resumption — verified at `google/genai/types.py:20484-20598` |
| `aws_sdk_bedrock_runtime` | `==0.7.0` | Nova Sonic bidirectional stream — unchanged, lazy, Python ≥3.12 |
| `aiohttp` | existing | Example transport (two WS routes) |
| `pytest`, `pytest-asyncio` | existing | Conformance kit |

No new dependencies are introduced.

---

## 8. Open Questions

All questions from the brainstorm were resolved before this spec was
written; two further scope questions were raised and answered during
codebase research for this spec.

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Scope of homologation — *Resolved in brainstorm*: real functional parity, not contract-only declarations. → §1 Goals G1-G3, §3 Modules 3-5.
- [x] Shape of the example — *Resolved in brainstorm*: two `VoiceChatHandler` instances on separate WS routes, one page with a provider switch. → §3 Module 12, §5 Example criteria.
- [x] `stt_only` on Nova — *Resolved in brainstorm*: accept it, do not raise, do not emulate by filtering; declare `native_stt_only=False`. The model response still reaches the consumer. → §3 Module 4, §7 Known Risks.
- [x] Gemini reconnection strategy — *Resolved in brainstorm*: both — map `GoAway` to `reconnect_required` for parity **and** use `SessionResumptionConfig` handles. → §3 Module 5.
- [x] Voice naming — *Resolved in brainstorm*: native provider strings, validated per client with a warned fallback; no abstract translation layer. → §3 Module 4, §1 Non-Goals.
- [x] Transcript envelope — *Resolved in brainstorm*: canonicalize lowercase `role` and break cleanly; remove `metadata["user_transcription"]`. → §2 Overview, §3 Modules 3/7/8/10.
- [x] `_HandlerVoiceSession` duplication — *Resolved in brainstorm*: relay extension hook on `VoiceSession`, delete the duplicated `_run_turn()`. → §3 Modules 6/8, §2 New Public Interfaces.
- [x] Browser UI for the example — *Resolved in brainstorm*: extract to a shared static asset under `examples/clients/voice/`; the Nova raw-client example survives. → §3 Module 11.
- [x] Conversation continuity across a provider switch — *Resolved in brainstorm*: never continue; always a fresh session. → §1 Non-Goals, §3 Module 12.
- [x] Deprecation window for the `role` break — *Resolved in brainstorm*: none; few consumers and they can be fixed. → §5 Migration criteria.
- [x] Audio formats in `VoiceCapabilities` — *Resolved in brainstorm*: yes, declare input/output formats and sample rates for future non-PCM providers. → §2 Data Models, §3 Module 6 (preflight).
- [x] Nova `max_tokens` unification — *Resolved in brainstorm*: accept `4096` as the shared default, `8192` explicitly supported, no voice-specific pin. → §3 Module 4, §7 Known Risks.
- [x] True blast radius of the envelope break — *Resolved during spec research*: 8 sites across 3 distributions (not the 2 + docs estimated in the brainstorm), including `VoiceBot`'s memory path and the shipped `chat.html`. All of them migrate **in this spec**. → §3 Modules 8/10, §5 Migration criteria.
- [x] Target version — *Resolved during spec research*: `0.26.0` — a minor bump, because the response envelope changes incompatibly (current version is `0.25.32`, `parrot/version.py:8`).
- [ ] What is Nova 2 Sonic's actual `max_output_tokens` ceiling? Needed to validate `8192` rather than let Bedrock clamp it silently. Blocks only the `max_output_tokens` value in Nova's descriptor, not the design — *Owner: Jesus Lara*
- [ ] Are the voice catalogs complete? `nova/audio.py:737` lists three Nova voices in a docstring and Gemini's prebuilt list is not enumerated in-repo. If either catalog is partial, validation must warn-and-pass rather than reject — *Owner: Jesus Lara*

---

## Worktree Strategy

**Default isolation unit**: `per-spec` — all tasks run sequentially in one
worktree.

**Rationale**: the dependency graph is a diamond with a narrow neck. Modules
1-2 (contract) are a hard prerequisite for everything; Modules 6-8 (session,
bot, handler) and 9-12 (kit, migration, example) all converge again at the
bottom. Only the two provider lanes — Module 3+5 (Gemini) and Module 4
(Nova) — are genuinely independent, and they share the conformance suite and
overlapping test files. Two worktrees would cost more in merge coordination
than they save in wall-clock.

**Parallelizable if needed**: Modules 3+5 (Gemini) and Module 4 (Nova) may be
split into sibling worktrees *after* Modules 1-2 land, if the Gemini session
resumption work proves large enough to warrant its own branch. Modules 6-12
must remain sequential.

**Cross-feature dependencies**: none blocking. FEAT-416
(voice-agent-framework) is merged and is this feature's direct base. The only
in-flight feature is FEAT-417 (commcenter-notify), which shares no files.

**Heads-up for adjacent work**: the LiveAvatar specs (`liveavatar-*`) consume
`VoiceChatHandler` frames. Nothing is in flight, but the canonical-`role`
break should be flagged to that work before it resumes.

**Worktree creation** (after `/sdd-task`):
```bash
git checkout dev
git worktree add -b feat-418-googlelive-nova2-audiobot-homologation \
  .claude/worktrees/feat-418-googlelive-nova2-audiobot-homologation HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-07 | Jesus Lara | Initial draft from `googlelive-nova2-audiobot-homologation.brainstorm.md` (Option C); all 13 brainstorm questions carried forward as resolved; blast radius and target version resolved during spec research |
| 1.0 | 2026-08-07 | Jesus Lara | **Approved.** The two remaining `[ ]` items in §8 (Nova's `max_output_tokens` ceiling, completeness of both voice catalogs) are provider-documentation lookups that set values, not design decisions — they are resolved during implementation and do not gate task decomposition |
