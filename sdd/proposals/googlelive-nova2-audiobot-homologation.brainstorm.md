---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Google Gemini Live ↔ Nova 2 Sonic Homologation (drop-in voice providers)

**Date**: 2026-08-07
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option C

---

## Problem Statement

FEAT-416 (voice-agent-framework, merged 2026-08-06) built the *scaffolding*
for provider-agnostic voice: `VoiceCapable` (a structural Protocol), a
unified `VoiceConfig`, a promoted `VoiceSession`, and parallel tool
execution on both clients. What it did **not** build is *behavioral
equivalence*. Today `GeminiLiveClient` and `NovaClient` satisfy the same
Protocol while behaving differently in at least seven observable ways, so
swapping `VoiceConfig.provider` between `google_live` and `nova` silently
changes what the application receives.

The concrete, verified divergences (all line numbers confirmed against the
current tree — see **Code Context**):

| # | Dimension | Gemini Live | Nova 2 Sonic |
|---|---|---|---|
| 1 | Per-call `temperature`/`max_tokens` | **ignored** — `_build_live_config` reads `self.temperature`/`self.max_tokens` from the constructor (`live.py:692-693`) | honored from `stream_voice(**kwargs)` (`nova/audio.py:789-796`) |
| 2 | `top_p` | **does not exist anywhere** in the Live config | honored (`nova/audio.py:791`) |
| 3 | `stt_only` | native, real suppression via empty `response_modalities` (`live.py:678-684`) | swallowed by `**kwargs`, no-op → full-duplex |
| 4 | Reconnection signal | emits `metadata["go_away"]` only (`live.py:1072-1077`, `1107`) — `VoiceSession`'s reconnect loop never fires | emits `metadata["reconnect_required"]` at 465 s (`nova/audio.py:271`, `860`) |
| 5 | Transcript envelope | `role` is **always `None`** in `stream_voice`; user transcription hidden in `metadata["user_transcription"]` (`live.py:875`) | `role="USER"`/`"ASSISTANT"` on the response (`nova/audio.py:897`, `926-940`) |
| 6 | Voice selection | constructor-only `voice_name` (no per-call override) | per-call `voice_id` kwarg + constructor default `"matthew"` (`nova/client.py:75`) |
| 7 | Voice naming | `"Puck"`, `"Charon"`, `"Kore"`… | `"matthew"`, `"tiffany"`, `"amy"`… — and `VoiceBot` forwards `voice_config.voice_name` (default `"Puck"`) straight into Nova's `voice_id` (`bots/voice.py:198`), producing an invalid voice id on the very first Nova session |

Two structural leaks compound this:

- **`VoiceSession` doesn't thread anything.** `_run_turn()` calls
  `stream_voice(audio_iterator, system_prompt=…, session_id=…)` and nothing
  else (`voice/session.py:182-186`). Every `VoiceConfig` knob FEAT-416 added
  — `temperature`, `max_tokens`, `top_p`, `parallel_tool_execution`,
  `enable_*_transcription` — is dropped on the floor for any consumer that
  drives the session directly instead of going through `VoiceBot.ask_stream()`.
  Only the integrations handler escapes this, because
  `_HandlerVoiceSession._run_turn()` (`handler.py:305-360`) re-implements the
  whole loop on top of `bot.ask_stream()` — a ~60-line duplicate of the base
  class's reconnection logic, kept in sync by hand.
- **A latent crash on the transcription path.** `stream_voice` forwards
  `enable_input_transcription` / `enable_output_transcription` to
  `_build_live_config` (`live.py:777-780`), but that method's signature is
  `(system_prompt, response_modalities, stt_only)` (`live.py:652-656`).
  The moment anybody threads those two `VoiceConfig` fields — the obvious
  next step of this very homologation — Gemini raises `TypeError`.

Finally, the artifact that would make all of this visible does not exist.
`examples/voice/README.md` documents `examples/voice/bot.py` ("Provider
Switch & Usage Tracking") — that file **is not in the repository**.
`examples/clients/nova/audio.py` is the only working browser demo, it is
Nova-only, it still carries its own pre-FEAT-416 `NovaVoiceSession`
(line 116) instead of the promoted core class, and its ~560-line browser UI
(`INDEX_HTML`, line 459) is welded into the Python file.

**Who is affected**: framework users choosing a voice provider (they hit
silent behavior changes), the integrations `VoiceChatHandler` (carries the
duplicated loop), and any frontend consuming the WS frame protocol (Nova
transcripts render, Gemini transcripts do not).

**Why now**: FEAT-416 established the contract surface. Every additional
provider (`OPENAI_REALTIME`, `WHISPER_TTS` are already declared in the
`VoiceProvider` enum) multiplies the divergence if the contract is not
pinned down and *tested* while there are only two implementations.

---

## Constraints & Requirements

- **Drop-in in both directions.** Changing only `VoiceConfig.provider` must
  not change the observable contract: same kwargs honored, same
  `LiveVoiceResponse` envelope, same frame sequence out of `VoiceSession`.
- **`VoiceCapable` stays structural.** No new ABC and no forced inheritance;
  `typing.Protocol` + `@runtime_checkable` is the established pattern
  (`clients/protocols.py:15`) and third-party clients must remain able to
  satisfy it.
- **`AbstractClient` is untouched.** Voice is a cross-cutting capability,
  not a base-class concern (CLAUDE.md: never modify `abstract_client.py`
  without discussion).
- **Async-first, `aiohttp` only** for the example's transport. No `requests`,
  no `httpx`.
- **Nova's SDK stays lazy.** `aws_sdk_bedrock_runtime==0.7.0` is Python
  ≥3.12-only and pre-alpha; importing `NovaClient` must keep working on 3.11
  (`_require_voice_sdk` is called at first `stream_voice()`, not import).
  The example must degrade to Gemini-only on 3.11 rather than fail to start.
- **Breaking change is accepted, scoped.** Per Round 3, `role` becomes
  canonical (lowercase `"user"`/`"assistant"`) and
  `metadata["user_transcription"]` is **removed**, not aliased. That makes
  `VoiceChatHandler` (`handler.py:1576+`) and
  `docs/frontend/voicebot-realtime-frontend-guide.md` part of this spec's
  scope — they must migrate in the same change.
- **Nova cannot truly do STT-only.** Nova 2 Sonic always generates voice +
  text and there is no documented switch to disable generation. Per Round 3,
  `stt_only=True` on Nova must **not** raise and must **not** be emulated by
  client-side filtering: it is accepted, declared unsupported in the
  capability descriptor, logged once, and the model response still arrives.
- **Deterministic tests.** No live AWS/Google calls in CI — the conformance
  suite must run against mocked provider streams.

---

## Options Explored

### Option A: Point fixes in each client

Walk the divergence table row by row and patch each client until the two
line up: teach `GeminiLiveClient` to read inference params from
`stream_voice(**kwargs)` and to accept `top_p`; map `go_away` →
`reconnect_required`; set canonical `role` on both; add per-call voice
override to Gemini; make `VoiceSession._run_turn()` forward the
`VoiceConfig`-derived kwargs.

✅ **Pros:**
- Smallest diff, no new abstractions, easy to review row by row.
- Every fix is independently valuable and independently revertable.
- Directly closes all seven verified gaps.

❌ **Cons:**
- Nothing *prevents* the eighth gap. Parity is asserted in prose, never
  enforced by anything executable.
- `VoiceCapable`'s `**kwargs` remains untyped, so "which knobs does this
  provider honor?" stays unanswerable at runtime — the exact question a
  drop-in guarantee needs to answer.
- `OPENAI_REALTIME` / `WHISPER_TTS` arrive later with no checklist to meet.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai>=2.10.0` (2.17.0 installed) | Gemini Live session config | `types.LiveConnectConfig` already used |
| `aws_sdk_bedrock_runtime==0.7.0` | Nova Sonic bidirectional stream | pre-alpha, Python ≥3.12, lazy-imported |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/live.py:652-727` — `_build_live_config`, the single place Gemini's session knobs are assembled.
- `packages/ai-parrot/src/parrot/clients/nova/audio.py:789-796` — the already-correct kwargs-to-`sessionStart` threading, as the reference shape.
- `packages/ai-parrot/src/parrot/voice/session.py:182-186` — the `stream_voice()` call site that must forward config.

---

### Option B: Normalization adapter layer in `VoiceSession`

Leave both clients exactly as they are. Introduce a per-provider
`VoiceProviderAdapter` that sits between `VoiceSession` and the client:
inbound it translates a canonical options object into each provider's kwargs
(`voice_name`→`voice_id`, drop `top_p` for Gemini, …), outbound it rewrites
`LiveVoiceResponse` into the canonical envelope (`go_away`→
`reconnect_required`, `metadata["user_transcription"]`→`role="user"`).

✅ **Pros:**
- Zero risk to the two clients; all translation lives in one reviewable file.
- New providers only need an adapter, never a client rewrite.
- Easiest path to keeping old consumers working during a migration window.

❌ **Cons:**
- **The drop-in guarantee only holds above the adapter.** Anyone using
  `GeminiLiveClient` / `NovaClient` directly — which is exactly what
  `examples/clients/nova/audio.py` does, deliberately, "so the client
  contract is visible end to end" — still sees the divergence. The user's
  own example flow is the counter-example.
- Adapters can't manufacture capability: Gemini physically cannot honor
  `top_p` unless `_build_live_config` is changed, so Option B still needs
  Option A's client edits for rows 1, 2 and 6 — it only truly solves the
  envelope rows.
- Adds a translation hop to the hot audio path for every frame.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib only | dataclass-based adapters | no new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py:264-303` — `_HandlerVoiceSession`, the existing precedent for "override `_relay()` to reshape frames".
- `packages/ai-parrot/src/parrot/voice/session.py:253-316` — `_relay()`, the natural adapter seam.

---

### Option C: Versioned voice contract + provider conformance kit *(recommended)*

Promote "drop-in" from a claim to an executable contract, in three pieces:

1. **A typed options object** — `VoiceStreamOptions` (frozen dataclass:
   `temperature`, `max_tokens`, `top_p`, `voice`, `language`,
   `stt_only`, `parallel_tool_execution`, `enable_input_transcription`,
   `enable_output_transcription`). `VoiceCapable.stream_voice()` gains it as
   an optional parameter; `**kwargs` stays for provider-specific extras.
   `VoiceConfig` gets a `to_stream_options()` projection so `VoiceBot`,
   `VoiceSession` and the handler all derive the same options from the same
   config — killing the three divergent threading paths.
2. **A capability descriptor** — `VoiceCapabilities` (frozen dataclass) +
   a `voice_capabilities` property on the Protocol, declaring per provider:
   `native_stt_only`, `supports_top_p`, `supports_per_call_voice`,
   `emits_reconnect_signal`, `supports_session_resumption`,
   `max_session_seconds`, `voice_catalog`. Unsupported-but-requested knobs
   are logged once per session and surfaced as a `capability_notice` frame
   — never a silent divergence, and (per Round 3) never a hard failure.
3. **A conformance kit** — a shared, parametrized pytest suite
   (`tests/voice/test_provider_conformance.py`) that runs *every* declared
   `VoiceCapable` implementation against mocked provider streams and asserts
   the canonical contract: options honored, canonical `role`, canonical
   reconnect signal, identical frame sequence out of `VoiceSession`. Adding
   a provider means adding one line to the parametrization; the suite tells
   you what's missing.

The client fixes from Option A are absorbed as the work needed to make both
providers pass the kit. Option B's normalization is used only where a
provider genuinely cannot comply (Nova's non-native `stt_only`), and is then
*declared* rather than hidden.

✅ **Pros:**
- The drop-in property becomes a test that fails when it regresses — the
  only form of the guarantee that survives future features.
- Answers "what does this provider actually support?" at runtime, which is
  what the example's live provider switch needs to render honestly.
- Typed options remove the `**kwargs` guessing game and eliminate the latent
  `_build_live_config` `TypeError` by construction.
- `OPENAI_REALTIME` / `WHISPER_TTS` inherit a ready-made acceptance checklist.

❌ **Cons:**
- Largest surface: touches both clients, `protocols.py`, `models/voice.py`,
  `session.py`, `bots/voice.py`, and the integrations handler.
- Two new public types to design well (or regret).
- The capability descriptor can drift from reality if not itself asserted —
  mitigated by making the kit assert descriptor-vs-behavior consistency.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai>=2.10.0` (2.17.0 installed) | `types.SessionResumptionConfig` / `LiveServerSessionResumptionUpdate` — verified present at `google/genai/types.py:20484-20598` | enables real Gemini resumption, not just reconnect |
| `aws_sdk_bedrock_runtime==0.7.0` | Nova Sonic stream | unchanged, lazy |
| `pytest` / `pytest-asyncio` | conformance kit | already project standard |
| stdlib `dataclasses` / `typing.Protocol` | contract types | matches existing `VoiceConfig` / `VoiceCapable` style |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/protocols.py:15-37` — extend `VoiceCapable` in place, keeping `@runtime_checkable`.
- `packages/ai-parrot/src/parrot/models/voice.py:49-109` — `VoiceConfig` is already the single source of truth; add the projection here.
- `packages/ai-parrot/src/parrot/voice/session.py:165-251` — the reconnection loop that both `_run_turn()` implementations should collapse into.
- `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py` — existing provider-switch test, the seed for the parametrized kit.

---

### Option D: Single façade client (`VoiceRouterClient`)

Hide both providers behind one `AbstractClient` that owns the provider
choice internally, so `VoiceBot` only ever holds one client type and
switching is a method call on the façade.

✅ **Pros:**
- Trivially drop-in from the bot's perspective — there is nothing to swap.
- Natural home for runtime hot-swap and for fallback ("Nova failed → Gemini").
- Would make the example's provider switch a one-liner.

❌ **Cons:**
- Inverts the framework's own design: `VoiceBot._resolve_llm_config()` /
  `_create_llm_client()` (`bots/voice.py:158-279`) already *is* the
  provider-selection layer. A façade duplicates it and creates two competing
  answers to "who picks the provider?".
- Divergence doesn't disappear, it moves inside the façade and becomes
  harder to see — the opposite of the goal.
- Anyone using a client directly (`examples/clients/nova/audio.py`) gets
  nothing.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib only | delegation wrapper | no new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py:79-111` — `resolve_voice_client_class()`, the existing provider→class resolver a façade would wrap.

---

## Recommendation

**Option C** is recommended.

Options A and C close the same seven gaps; the difference is whether parity
is *asserted* or *enforced*. Given that FEAT-416 shipped the abstractions
three weeks ago and the divergences above accumulated anyway — inside a
feature whose explicit goal (G2) was a shared voice contract — prose parity
demonstrably does not hold in this codebase. The conformance kit is the part
that makes the next provider cheap and the next regression loud.

Option C also happens to be the cheapest correct answer to the two decisions
already taken in discovery. Canonical `role` with a clean break (Round 3)
requires migrating the handler and the frontend guide in lockstep — a
parametrized suite is what proves the migration is complete. And Nova's
`stt_only` being "accepted, honest, not emulated" is *only* expressible if
there is a capability descriptor to be honest in; without one, the
alternative is the silent no-op we have today.

What we trade off: this is the High-effort option and it introduces two
public types (`VoiceStreamOptions`, `VoiceCapabilities`) that become
API surface. That is acceptable because both are small, frozen, and derived
from `VoiceConfig` — which is already public and already the single source
of truth. We also accept a breaking change to the response envelope
(`metadata["user_transcription"]` removed) rather than carrying a deprecated
alias; the blast radius is two in-repo consumers plus one docs page, all
enumerated, and the pre-0.26 window is the cheapest moment to take it.

Option B is folded in as a technique, not an architecture. Option D is
rejected: it would create a second provider-selection authority alongside
`VoiceBot._resolve_llm_config()`.

---

## Feature Description

### User-Facing Behavior

**For framework users.** Building a voice agent stops depending on which
provider you picked:

```
VoiceBot(name=…, tools=[…], voice_config=VoiceConfig(provider="google_live", …))
VoiceBot(name=…, tools=[…], voice_config=VoiceConfig(provider="nova", …))
```

Both honor `temperature`, `max_tokens`, `top_p`, `parallel_tool_execution`,
and the transcription flags. Both yield `LiveVoiceResponse` objects with a
canonical lowercase `role` (`"user"` for transcribed input, `"assistant"`
for the model). Both signal the end of a provider-imposed session window as
`metadata["reconnect_required"]`, so `VoiceSession`'s reconnect loop works
identically for each. `voice_name` stays the provider's native string
(`"Puck"`, `"matthew"`) and an invalid one falls back to that provider's
default with an explicit warning instead of an opaque API error.

Where a provider genuinely cannot comply, the user is told rather than
misled: `client.voice_capabilities` is inspectable up front, and requesting
an unsupported knob emits a one-time log plus a `capability_notice` frame.
Concretely, `stt_only=True` on Nova is accepted and the session still
returns the model's spoken answer — Nova cannot suppress generation, this is
documented, and `native_stt_only=False` says so in the descriptor.

**For the example.** A new `examples/clients/voice/` runs one aiohttp server
with **two** `VoiceChatHandler` instances mounted on separate routes —
`/ws/gemini` and `/ws/nova` — each backed by its own `VoiceBot` built from
the same name, system prompt and tools, differing only in `VoiceConfig`.
One browser page, one push-to-talk button, one provider toggle: flip it and
the page reconnects to the other socket. Same UI, same agent, same tools,
same rendered transcript — with a live capability panel showing what each
provider declares, and per-provider token/latency counters underneath.
That is the drop-in claim, demonstrated rather than described. On Python
3.11 (no `aws_sdk_bedrock_runtime`) the Nova route reports itself
unavailable and the Gemini route runs normally.

### Internal Behavior

1. **Contract layer.** `VoiceStreamOptions` and `VoiceCapabilities` land in
   the core models/protocols; `VoiceConfig.to_stream_options()` is the one
   projection every caller uses. `VoiceCapable` gains the options parameter
   and the `voice_capabilities` property, staying a `@runtime_checkable`
   Protocol so `VoiceBot._create_llm_client()`'s existing `isinstance` gate
   (`bots/voice.py:273`) keeps working unchanged.
2. **Gemini lane.** `_build_live_config` starts accepting per-call inference
   values (with the constructor values as fallback), gains `top_p`, and
   grows real parameters for the two transcription flags it is already
   being handed — closing the latent `TypeError`. Per-call voice override
   arrives. `session_resumption` is enabled on connect; the handle from
   `LiveServerSessionResumptionUpdate` is retained, and on `GoAway` the
   client emits `metadata["reconnect_required"]=True` (keeping `go_away` as
   an additional informational flag) so `VoiceSession` reconnects — resuming
   with the stored handle rather than cold-starting.
3. **Nova lane.** Voice-id validation against the Nova catalog with a
   warned fallback to `"matthew"`; canonical lowercase `role` mapping from
   the `contentStart` role it already tracks; `stt_only` accepted, declared
   non-native, logged once.
4. **Session layer.** `VoiceSession._run_turn()` forwards the projected
   `VoiceStreamOptions` on every turn *and across reconnects*, and gains a
   relay extension hook so `_HandlerVoiceSession` can keep its richer frame
   protocol while deleting its duplicated `_run_turn()` — one reconnection
   loop in the codebase, not two.
5. **Envelope migration.** `metadata["user_transcription"]` is removed;
   `VoiceChatHandler._send_voice_response()` and
   `docs/frontend/voicebot-realtime-frontend-guide.md` migrate to canonical
   `role` in the same change.
6. **Conformance kit.** One parametrized suite drives both clients through
   mocked streams and asserts the contract, including that each declared
   capability matches observed behavior.
7. **Example.** The browser UI is extracted from
   `examples/clients/nova/audio.py:459` (`INDEX_HTML`) into a shared static
   asset under `examples/clients/voice/`; the new dual-handler demo serves
   it with the provider switch. `examples/clients/nova/audio.py` keeps
   working as the raw-client demo and is migrated off its stale local
   `NovaVoiceSession` (line 116) onto the promoted core class. The stale
   `examples/voice/README.md`, which documents a non-existent
   `examples/voice/bot.py`, is reconciled.

### Edge Cases & Error Handling

- **Unsupported knob requested** → one-time `logger.warning` naming provider
  and knob + `capability_notice` frame; the session proceeds. Never raises.
- **`stt_only=True` on Nova** → accepted; model response still arrives
  (unfiltered, per Round 3); descriptor reports `native_stt_only=False`.
- **Invalid `voice_name` for the active provider** → warned fallback to the
  provider default (`"matthew"` / `"Puck"`); never an opaque provider error.
- **Reconnect during an in-flight tool call** → preserve FEAT-416's ordering
  invariant: relay the frame (and its `tool_calls`) *before* evaluating
  `reconnect_required` (`voice/session.py:188-200`).
- **Gemini resumption handle rejected/expired** → fall back to a cold
  reconnect with the same `system_prompt`/`session_id`; emit `reconnect`
  with a `resumed: false` marker.
- **`max_reconnects` exhausted** → unchanged FEAT-416 behavior: `error`
  frame, session torn down without self-awaiting the task
  (`voice/session.py:202-219`).
- **Nova SDK missing (Python 3.11)** → `NovaClient` still imports; the
  example marks the Nova route unavailable at startup; `stream_voice()`
  raises only if actually invoked.
- **Provider switch mid-conversation in the example** → treated as a new
  session on the target socket. Cross-provider conversation-memory continuity
  is explicitly **not** claimed (see Open Questions).
- **Transport drops mid-turn** → unchanged: `ConnectionResetError` suppressed
  in `VoiceSession._send()` (`voice/session.py:318-326`).

---

## Capabilities

### New Capabilities
- `voice-stream-options`: typed per-call option object projected from `VoiceConfig`, forwarded identically by `VoiceBot`, `VoiceSession` and `VoiceChatHandler`.
- `voice-capabilities-descriptor`: per-provider declaration of what is natively supported, inspectable at runtime and asserted by tests.
- `voice-response-envelope-canonical`: canonical lowercase `role` on `LiveVoiceResponse`; removal of `metadata["user_transcription"]`.
- `gemini-live-session-resumption`: `GoAway` → `reconnect_required` parity plus resumption-handle continuity.
- `voice-provider-conformance-suite`: parametrized pytest kit every `VoiceCapable` implementation must pass.
- `voice-provider-switch-example`: `examples/clients/voice/` — dual `VoiceChatHandler`, shared extracted browser UI, live provider toggle.

### Modified Capabilities
- `voice-agent-framework` (FEAT-416) — `VoiceCapable`, `VoiceSession`, `VoiceConfig`, `VoiceBot` all extended; `_HandlerVoiceSession`'s duplicated `_run_turn()` removed.
- `novaclient-amazon-aws` (FEAT-315) — voice-id validation, canonical role, capability descriptor.
- `nova-sonic-protocol-fidelity` (FEAT-408) — role semantics documented there move to the canonical form.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/protocols.py` | extends | `VoiceCapable` gains options param + `voice_capabilities`; stays `@runtime_checkable` |
| `parrot/models/voice.py` | extends | `VoiceStreamOptions`, `VoiceCapabilities`, `VoiceConfig.to_stream_options()` |
| `parrot/clients/live.py` | modifies | per-call inference params, `top_p`, transcription-flag params, per-call voice, session resumption, `reconnect_required`, canonical `role` |
| `parrot/clients/nova/audio.py` | modifies | voice-id validation, canonical lowercase `role`, `stt_only` acceptance + descriptor |
| `parrot/clients/nova/client.py` | modifies | capability descriptor + voice catalog |
| `parrot/voice/session.py` | modifies | options threading (incl. across reconnect), relay extension hook |
| `parrot/bots/voice.py` | modifies | uses the projection instead of the ad-hoc `voice_stream_kwargs` dict (`bots/voice.py:539-545`); stops mapping `voice_name`→`voice_id` blindly (`:198`) |
| `parrot/voice/handler.py` (integrations) | **breaking** | `_HandlerVoiceSession._run_turn()` deleted in favor of the hook; `_send_voice_response()` migrated off `metadata["user_transcription"]` |
| `docs/frontend/voicebot-realtime-frontend-guide.md` | **breaking** | frame protocol doc must document canonical `role` and drop the removed metadata key |
| `examples/clients/nova/audio.py` | modifies | migrate to core `VoiceSession`; UI extracted to shared asset |
| `examples/clients/voice/` | new | dual-handler provider-switch demo + shared static UI |
| `examples/voice/README.md` | modifies | reconcile with reality (documents a non-existent `bot.py`) |
| `parrot/clients/base.py` (`AbstractClient`) | **unmodified** | voice stays a Protocol-level capability |
| External deps | none added | `google-genai` 2.17.0 already installed; Nova SDK unchanged |

---

## Code Context

### User-Provided Code

No code snippets were provided by the user during discovery. The request was
specified in prose: homologate Gemini Live against the FEAT-416 Nova 2 Sonic
improvements (Voice Session, Parallel Tool Calling) so the two are drop-in
replacements, and add an `examples/clients/voice` demo running two
`VoiceBotHandler`s — one per provider.

> Terminology note for downstream agents: the class the user calls
> **`VoiceBotHandler`** is named **`VoiceChatHandler`** in the codebase
> (`packages/ai-parrot-integrations/src/parrot/voice/handler.py:388`).
> There is no class named `VoiceBotHandler`.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/clients/protocols.py:15
@runtime_checkable
class VoiceCapable(Protocol):
    async def stream_voice(                                    # line 29
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...
```

```python
# From packages/ai-parrot/src/parrot/clients/live.py:652
def _build_live_config(
    self,
    system_prompt: Optional[str] = None,
    response_modalities: Optional[List[str]] = None,
    stt_only: bool = False,
) -> types.LiveConnectConfig:
    ...
    live_config = types.LiveConnectConfig(
        response_modalities=modalities,
        speech_config=speech_config,
        temperature=self.temperature,        # line 692 — constructor, NOT per-call
        max_output_tokens=self.max_tokens,   # line 693 — constructor, NOT per-call
        ...                                  # no top_p anywhere
    )

# From packages/ai-parrot/src/parrot/clients/live.py:729
async def stream_voice(
    self,
    audio_iterator: AsyncIterator[bytes],
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    stt_only: bool = False,          # line 734 — Gemini-only parameter
    **kwargs,
) -> AsyncIterator[LiveVoiceResponse]:
    parallel_tool_execution = kwargs.get("parallel_tool_execution", False)   # line 772
    live_config = self._build_live_config(                                   # line 777
        system_prompt=system_prompt,
        stt_only=stt_only,
        **{k: v for k, v in kwargs.items() if k in (
            'response_modalities',
            'enable_input_transcription',      # ← NOT a _build_live_config param
            'enable_output_transcription',     # ← NOT a _build_live_config param
        )}                                     # → TypeError if ever passed
    )
```

```python
# From packages/ai-parrot/src/parrot/clients/nova/audio.py:712
async def stream_voice(
    self,
    audio_iterator: AsyncIterator[bytes],
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs,                                  # no stt_only → silent no-op
) -> AsyncIterator[LiveVoiceResponse]:
    resolved_voice_id = kwargs.get("voice_id") or self.voice_id   # line 764 — no validation
    parallel_tool_execution = kwargs.get("parallel_tool_execution", False)  # line 765
    temperature = kwargs.get("temperature", 0.7)                  # line 789
    max_tokens = kwargs.get("max_tokens", 1024)                   # line 790
    top_p = kwargs.get("top_p", 0.9)                              # line 791
    # sessionStart inferenceConfiguration                          # lines 793-798
```

```python
# From packages/ai-parrot/src/parrot/voice/session.py:165
async def _run_turn(self, turn_no: int) -> None:
    while True:                                       # line 180 — reconnect loop
        stream = self.client.stream_voice(            # line 182
            self._audio_iterator(queue),
            system_prompt=self.system_prompt,
            session_id=self.session_id,
        )                                             # ← NO VoiceConfig kwargs at all

# From packages/ai-parrot/src/parrot/voice/session.py:253
async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None:
    if resp.text:
        await self._send({"type": "text", "turn": turn_no,
                          "text": resp.text, "role": resp.role})   # line 271
```

```python
# From packages/ai-parrot/src/parrot/models/voice.py:30
class VoiceProvider(str, Enum):
    GOOGLE_LIVE = "google_live"      # line 40
    OPENAI_REALTIME = "openai_realtime"
    WHISPER_TTS = "whisper_tts"
    NOVA = "nova"                    # line 46

# From packages/ai-parrot/src/parrot/models/voice.py:49
@dataclass
class VoiceConfig:
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE   # line 60
    voice_name: str = "Puck"                              # line 73
    temperature: float = 0.7                              # line 77
    max_tokens: int = 4096                                # line 78
    top_p: float = 0.9                                    # line 79
    enable_input_transcription: bool = True               # line 87
    enable_output_transcription: bool = True              # line 88
    reconnect_on_limit: bool = True                       # line 93
    max_reconnects: int = 3                               # line 94
    parallel_tool_execution: bool = False                 # line 97
    def __post_init__(self): ...                          # line 99 — coerces str → enum
```

```python
# From packages/ai-parrot/src/parrot/bots/voice.py:158
def _resolve_llm_config(self, llm=None, model=None, preset=None, model_config=None, **kwargs):
    if provider == 'nova':                                              # line 177
        resolved_model = model or self.voice_config.model or "nova-2-sonic"  # line 190
        extra={'voice_id': kwargs.get('voice_id',
                                      self.voice_config.voice_name), …} # line 198 ← "Puck" → Nova

# From packages/ai-parrot/src/parrot/bots/voice.py:220
def _create_llm_client(self, config, conversation_memory=None) -> VoiceCapable:
    if not isinstance(client, VoiceCapable):                            # line 273
        raise TypeError(...)                                            # line 274

# From packages/ai-parrot/src/parrot/bots/voice.py:419
async def ask_stream(self, audio_input, session_id=None, user_id=None,
                     stt_only: bool = False, **kwargs):                 # line 424
    voice_stream_kwargs = {                                             # line 539
        'temperature': self.voice_config.temperature,
        'max_tokens': self.voice_config.max_tokens,
        'top_p': self.voice_config.top_p,
        'parallel_tool_execution': self.voice_config.parallel_tool_execution,
        **kwargs,
    }                                                                   # line 545
```

```python
# From packages/ai-parrot-integrations/src/parrot/voice/handler.py:79
def resolve_voice_client_class(provider: "VoiceProvider"):
    if provider == _VoiceProvider.NOVA:      # line 106
        from parrot.clients.nova import NovaClient
        return NovaClient
    from parrot.clients.live import GeminiLiveClient
    return GeminiLiveClient                  # line 111

# From packages/ai-parrot-integrations/src/parrot/voice/handler.py:264
class _HandlerVoiceSession(VoiceSession):
    async def _run_turn(self, turn_no: int) -> None:   # line 305 — ~60-line duplicate
        stream = bot.ask_stream(                       # line 328 — drives VoiceBot, not the client
            audio_input=self._audio_iterator(queue),
            session_id=self.session_id,
            user_id=self._connection.user_id,
            stt_only=self._connection.stt_only,
        )

# From packages/ai-parrot-integrations/src/parrot/voice/handler.py:388
class VoiceChatHandler:                                # ← the user's "VoiceBotHandler"
    async def _run_voice_session(self, connection) -> None:   # line 1527
        if bot._llm is None:                                   # line 1550
            config = bot._resolve_llm_config()
            bot._llm = bot._create_llm_client(config, bot.conversation_memory)
```

#### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot.clients.protocols import VoiceCapable          # clients/protocols.py:16
from parrot.clients.live import GeminiLiveClient, LiveVoiceResponse, LiveCompletionUsage
from parrot.clients.nova import NovaClient                 # clients/nova/client.py
from parrot.voice.session import VoiceSession              # voice/session.py:36 (core, PEP 420 + pkgutil.extend_path)
from parrot.models.voice import VoiceConfig, VoiceProvider, AudioFormat
from parrot.voice.handler import VoiceChatHandler          # ai-parrot-integrations
from google.genai import types                             # google-genai 2.17.0 installed
```

#### Key Attributes & Constants

- `NovaAudio._CONNECTION_LIMIT_SECONDS` → `float` = `8*60 - 15` (465 s) — `clients/nova/audio.py:271`
- `NovaClient.voice_id` default `"matthew"` — `clients/nova/client.py:75`, assigned `:109`
- `LiveVoiceResponse.role` → `Optional[str]`, default `None` — `clients/live.py:187`
- `VoiceTurnMetadata.was_interrupted` → `bool` — `clients/live.py:146`
- Nova reconnect signal: `metadata={"reconnect_required": True}` — `clients/nova/audio.py:860`
- Gemini GoAway signal: `metadata={"go_away": True, "reason": …}` — `clients/live.py:1077` and `:1107` (server close 1008)
- Gemini user transcription: `metadata={"user_transcription": text}` — `clients/live.py:875`
- Nova role source: `turn_state.role = content_start.get("role")` → `"USER"`/`"ASSISTANT"` uppercase — `clients/nova/audio.py:897`, emitted `:940`
- Interruption parity **already correct**: Gemini `clients/live.py:809-815`; Nova `clients/nova/audio.py:173-196`, `907-916`
- Parallel tool execution **already present on both**: `clients/live.py:994`; `clients/nova/audio.py:683`
- Gemini session resumption types available: `google/genai/types.py:20484-20598` (`LiveServerSessionResumptionUpdate`, `session_resumption_update`) — google-genai **2.17.0**
- Nova example's stale local session class: `examples/clients/nova/audio.py:116` (`NovaVoiceSession`)
- Nova example's embedded browser UI: `examples/clients/nova/audio.py:459` (`INDEX_HTML`, ~560 lines)

### Does NOT Exist (Anti-Hallucination)

- ~~`VoiceBotHandler`~~ — the class is `VoiceChatHandler` (`parrot/voice/handler.py:388`). No `VoiceBotHandler` exists anywhere.
- ~~`examples/voice/bot.py`~~ — documented in detail by `examples/voice/README.md` (provider switch, usage report, sample CLI) but **the file is not in the repository**. `examples/voice/` contains only `README.md` and `spike_liveavatar.py`.
- ~~`examples/clients/voice/`~~ — directory does not exist yet; this feature creates it.
- ~~`VoiceStreamOptions`~~, ~~`VoiceCapabilities`~~, ~~`UnsupportedVoiceCapability`~~, ~~`VoiceProviderAdapter`~~ — none exist; all are proposed by this brainstorm.
- ~~`VoiceConfig.to_stream_options()`~~ — not a method today. `VoiceConfig.get_model()` (`models/voice.py:107`) is the only method besides `__post_init__`.
- ~~`GeminiLiveClient` top_p support~~ — `top_p` appears only in a `**kwargs` docstring (`clients/live.py:574`); it is never placed in `LiveConnectConfig`.
- ~~`_build_live_config(enable_input_transcription=…)`~~ / ~~`enable_output_transcription=…`~~ — not parameters (`clients/live.py:652-656`); passing them raises `TypeError`, despite `stream_voice` being written to forward them (`:777-780`).
- ~~`NovaAudio.stream_voice(stt_only=…)`~~ — not a parameter; absorbed by `**kwargs` and ignored.
- ~~`GeminiLiveClient.stream_voice` setting `role`~~ — `role="user"` is set only in `ask()` (`clients/live.py:1266`), never in the streaming path.
- ~~Nova emitting `metadata["go_away"]`~~ / ~~Gemini emitting `metadata["reconnect_required"]`~~ — each provider emits only its own signal today.
- ~~`VoiceSession` forwarding `VoiceConfig` inference params~~ — `_run_turn()` passes only `system_prompt` and `session_id` (`voice/session.py:182-186`).
- ~~A shared/extracted browser voice UI asset~~ — the only UI is inlined in `examples/clients/nova/audio.py`.
- ~~`parrot/voice/__init__.py` in the core package~~ — intentionally absent (bare PEP 420 dir); the integrations `__init__.py` uses `pkgutil.extend_path` to merge them. Do not add one.

---

## Parallelism Assessment

- **Internal parallelism**: Partial, and gated. The contract layer
  (`protocols.py`, `models/voice.py`) is a hard prerequisite for everything
  else. Once it lands, the **Gemini lane** (`clients/live.py`) and the
  **Nova lane** (`clients/nova/*.py`) are genuinely independent and could run
  in separate worktrees. The session/handler layer and the example both
  depend on all three.
- **Cross-feature independence**: No conflict. The only in-flight feature is
  **FEAT-417 commcenter-notify** (11/11 tasks pending), which shares no
  files. FEAT-416 (voice-agent-framework) is merged and is this feature's
  direct base. Watch the LiveAvatar specs (`liveavatar-*`) — they consume
  `VoiceChatHandler` frames, so the canonical-`role` break should be flagged
  to them even though nothing is in flight.
- **Recommended isolation**: `per-spec`
- **Rationale**: The dependency graph is a diamond with a narrow neck — one
  shared contract at the top, one shared session/handler + example at the
  bottom, and only the two provider lanes independent in the middle. The
  provider lanes also touch overlapping test files and the same conformance
  suite. Two worktrees would spend more on merge coordination than they save
  on wall-clock; sequential tasks in one worktree is the right call, with the
  parallel-lane option kept in reserve if the Gemini resumption work turns
  out to be large enough to warrant its own branch.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] Scope of "homologation": contract-only vs real functional parity — *Owner: Jesus Lara*: real functional parity — close the actual gaps in both clients, don't just declare them.
- [x] Shape of the example — *Owner: Jesus Lara*: two `VoiceChatHandler` instances mounted simultaneously on separate WS routes, one browser page with a provider switch. Same agent, same tools, different provider.
- [x] `stt_only` on Nova — *Owner: Jesus Lara*: Nova always returns voice **and** text and generation cannot be turned off. So `stt_only=True` must not fail and must not be emulated by client-side filtering: accept it, document it, declare `native_stt_only=False`. The model response still reaches the consumer.
- [x] Gemini reconnection strategy — *Owner: Jesus Lara*: both — map `GoAway` to `reconnect_required` for signal parity with Nova **and** use `SessionResumptionConfig` handles so the reconnect preserves context.
- [x] Voice naming across providers — *Owner: Jesus Lara*: `voice_name` stays the provider's native string. Each client validates against its own catalog and falls back to its default with a clear warning. No abstract voice-name translation layer.
- [x] Transcript envelope normalization — *Owner: Jesus Lara*: canonicalize and break cleanly. Both clients emit lowercase `role` (`"user"`/`"assistant"`); `metadata["user_transcription"]` is **removed**, and `VoiceChatHandler` plus `docs/frontend/voicebot-realtime-frontend-guide.md` migrate within this spec.
- [x] `_HandlerVoiceSession` duplication — *Owner: Jesus Lara*: give `VoiceSession` a relay extension hook and delete the duplicated `_run_turn()`, so the handler inherits kwargs threading and reconnection from one implementation.
- [x] Browser UI for the example — *Owner: Jesus Lara*: extract the UI from `examples/clients/nova/audio.py` into a shared static asset under `examples/clients/voice/` and serve it from the new demo. The Nova raw-client example survives.
- [ ] Should the example's provider switch attempt conversation continuity across providers (replaying memory into the new session), or is each provider a fresh session? Current assumption: **fresh session**, since `VoiceSession` is explicitly stateless w.r.t. history (`voice/session.py:14-18`) and cross-provider transcript replay is its own design problem — *Owner: Jesus Lara*
- [ ] Does the canonical `role` break warrant a deprecation window (one minor release emitting both forms) for out-of-repo consumers, or is the clean break at 0.25.x acceptable given the pre-1.0 status? Round 3 chose the clean break for in-repo consumers; this asks only about external ones — *Owner: Jesus Lara*
- [ ] Should `VoiceCapabilities` also declare audio-format constraints (Nova and Gemini agree today at 16 kHz in / 24 kHz out, so nothing is broken — but a third provider may not), or keep the descriptor limited to the behavioral knobs this feature homologates? — *Owner: Jesus Lara*
- [ ] Nova's `max_tokens` default in `stream_voice` is `1024` (`clients/nova/audio.py:790`) while `VoiceConfig.max_tokens` defaults to `4096` (`models/voice.py:78`). Once threading is complete, Nova voice turns silently get 4× the previous budget. Accept as the intended unification, or pin a voice-specific default? — *Owner: Jesus Lara*
