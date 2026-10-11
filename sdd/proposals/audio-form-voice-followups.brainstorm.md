---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: feat-FEAT-649-audio-form-interaction-workflow
projects: [parrot-formdesigner, ai-parrot-integrations]
tags: [audio-forms, voice, stt, normalization, session-lock]
---

# Brainstorm: Audio form voice follow-ups (session lock, typed spoken answers, STT language)

**Date**: 2026-10-11
**Author**: Emmanuel Arroyo
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

End-to-end testing of FEAT-649 (audio form workflow) hosted by FieldSync FEAT-701 and rendered by
navigator-svelte FEAT-700 surfaced five backend defects. The product is used in the United States,
in English, by field reps answering short forms by voice.

1. **A dead server locks the user out of every voice form for an hour.** The active-session marker
   (`parrot:audio:active:<user_id>`, TTL 3600 s) is released in the WS handler's `finally`. A killed
   process (restart, crash, deploy) never runs it. Every later `start_session`, on any form, gets
   `SESSION_ACTIVE` until the TTL expires, and the client has no way out.
2. **Spoken emails are stored as words.** "john at gmail dot com" was stored as
   "en man 6321 arroyenme el punto con". The free-form path stores the raw transcript whatever the
   field type.
3. **Spoken phone numbers are stored with separators** ("0,4,12,523,573").
4. **Spoken numbers and dates are not parsed** ("twenty five", "next Friday").
5. **STT guesses the language.** With `locale == "en"` the handler passes `language=None`, so
   Whisper auto-detects. On short clips it misdetects ("Emmanuel" heard as "en Manuel").

Fixing (5) by forcing the language exposes a sixth defect: the transcript "confidence" that gates
low-confidence confirmations is Whisper's **language-ID probability**
(`info.language_probability`). With a forced language it is ~1.0, and confirmations would stop
firing.

## Constraints & Requirements

- English first (US product). Spanish keeps parity where the lexicon already supports it.
- The runtime stays deterministic: no LLM per turn (FEAT-649 decision). Normalization is rules.
- **Normalization applies to spoken answers only.** Typed answers are stored as typed. Email
  *validation* applies to both.
- **Email:** normalize spoken tokens ("at", "dot", "underscore", "dash", "hyphen", spelled letters)
  and validate. If the result is not a valid address, ask for confirmation with the normalized
  value. The front already lets the user fix the text before confirming.
- **Phone:** join digits only ("oh" → 0, "double five" → 55). No format validation.
- **Numbers / dates:** parse spoken cardinals and dates, including relative dates ("today",
  "tomorrow", "next Friday"), resolved in the **client's timezone**, which the client sends in
  `start_session`.
- **Session lock:**
  - A short TTL renewed by a heartbeat while the socket lives, so an orphan expires in 1–2 min.
  - **Take over:** a user who hits `SESSION_ACTIVE` can claim the session.
  - The replaced connection, if still alive, is told and closed. Its snapshot stays resumable.
- **STT language:** pass the session language to Whisper always, including "en". The transcript
  confidence must come from the transcript, not from language ID.
- **Protocol:** additive changes only (new optional fields, new event). v2 clients that do not send
  them keep working.
- **Front:** the "Continue here" button, the timezone field and the replaced-session screen are a
  separate navigator-svelte task that depends on this one.

---

## Options Explored

### Option A: Typed normalizers in the engine + marker heartbeat with takeover (stdlib, rules)

Add a small `audio/normalize/` package: one deterministic normalizer per field-type family
(email, phone, number, date/datetime/time).

- **Where it runs:** the engine calls it on the free-form speech path before the confidence gate.
  A normalizer returns `(value, ok, reason)`. A failed validation (email) or an ambiguous parse
  routes to the existing `_request_confirm`, carrying the normalized value.
- **Locale:** spoken-token tables extend the existing `Lexicon` (en/es YAML), including cardinals
  beyond 10, so the language stays data, not code.
- **Validation:** emails are validated with `email-validator`, already a dependency of ai-parrot.
- **Dates:** relative dates are resolved with `zoneinfo` (stdlib) and the client's IANA timezone,
  stored on the session state.

Session lock:

- **Heartbeat:** the WS handler runs a heartbeat task per connection. Every ~30 s it renews the
  marker with a Lua compare-and-set ("refresh only if the value is still my session id") and a TTL
  of ~90 s.
- **Atomic release:** release becomes the same atomic Lua compare-and-delete.
- **Takeover:** `start_session` gains `takeover: bool`. With it, the server overwrites the marker
  with the new session id.
- **The old connection finds out at its next heartbeat:** the compare-and-set fails because the
  marker is no longer its own. It saves its snapshot, sends a new `session_replaced` event, and
  closes. This works across processes and pods without pub/sub, because Redis is already shared.

STT:

- Pass the normalized primary language subtag (`en-US` → `en`) to the transcriber always.
- In `FasterWhisperBackend`, derive confidence from the segments (`exp(mean(avg_logprob))`,
  clamped, and lowered by `no_speech_prob`).
- Keep `language_probability` as a separate field for diagnostics.

✅ **Pros:**
- No new dependencies (`email-validator` and `zoneinfo` are already available).
- Fully deterministic and unit-testable per normalizer.
- Takeover and orphan expiry use the Redis the store already has: no new infrastructure.
- Reuses the existing confirm flow and front UI (editable confirm field) for every
  "not sure" case.

❌ **Cons:**
- Hand-written date parsing covers a defined grammar, not everything people say. Out-of-grammar
  phrases fall back to confirmation.
- The heartbeat adds one Redis call per connection every 30 s (negligible at field-rep scale).
- An old connection learns it was replaced up to one heartbeat (~30 s) late.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `email-validator` (>=2.0) | Email syntax validation | Already in `packages/ai-parrot/pyproject.toml:57` |
| `zoneinfo` (stdlib) | Resolve relative dates in the client's timezone | Python ≥3.9 |
| Redis (existing via `PartialSaveStore._get_redis()`) | Marker refresh/release via Lua | No pub/sub needed |

🔗 **Existing Code to Reuse:**
- `P/audio/engine.py:348` `on_transcript`, `:426-441` free-form path, `:442` `_request_confirm`, `:464` `_accept`
- `P/audio/narration/lexicon.py:23` `Lexicon`, `:79` `normalize`, `:96` `load_lexicon`
- `P/audio/session_store.py:20-28` `_CAS_SCRIPT` (pattern for the refresh/release scripts), `:173` `claim_active`, `:163` `release_active`
- `P/api/audio_ws.py:330` `WebSocketResponse(heartbeat=30.0)`, `:363-398` receive loop + `finally`, `:669-681` claim on start
- `packages/ai-parrot-integrations/src/parrot/voice/transcriber/faster_whisper_backend.py:146-166`

---

### Option B: Third-party parsers + Redis pub/sub takeover

Same structure, but parse with libraries:
- `dateparser` for dates, including relative dates and timezones.
- `text2num` / `word2number` for spoken numbers.
- `phonenumbers` for phones.

Takeover publishes on a Redis channel `parrot:audio:replaced:<user_id>`, and live connections
subscribe and close immediately.

✅ **Pros:**
- Broad date and number grammar for free, and many locales.
- An old connection is closed instantly on takeover.

❌ **Cons:**
- Three new dependencies. `dateparser` is heavy (regex, tzlocal, a large language data set) and
  known to be slow to import.
- Library behaviour is less predictable than a defined grammar: `dateparser` guesses aggressively
  (e.g. "may" as a month), which is risky for a deterministic runtime.
- Pub/sub needs a subscriber task per connection and connection management on the Redis side.
  The heartbeat is still needed for the crash case, so it is extra machinery, not a replacement.
- Phone validation was explicitly not wanted, so `phonenumbers` is mostly unused.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `dateparser` | Natural-language dates | Heavy; import cost |
| `text2num` | Spoken numbers → int | Multi-locale |
| `phonenumbers` | Phone parsing | Validation not wanted |
| `email-validator` | Email validation | Existing |

🔗 **Existing Code to Reuse:**
- Same engine and store entry points as Option A.

---

### Option C: Value extraction at design time + LLM-assisted normalization behind the confirm step (unconventional)

Keep the runtime raw. When the transcript does not match the field type, call the existing
optional `llm_validation` endpoint to propose a normalized value, and always route it through
confirmation.

For the lock, drop the active marker entirely: allow concurrent sessions per user, and rely on
per-session snapshots plus the snapshot CAS (`_CAS_SCRIPT`) to reject conflicting writes.

✅ **Pros:**
- Handles any phrasing.
- Removing the marker removes the orphan problem by construction.

❌ **Cons:**
- Breaks the FEAT-649 decision: a deterministic runtime, no tokens per turn.
- Adds latency and cost on every typed field.
- Without the marker, two devices could fill the same form at once.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (existing LLM client) | Normalize free text | Per-turn tokens |

🔗 **Existing Code to Reuse:**
- `P/audio/engine.py` `llm_cfg` / `form.llm_validation` (FEAT-649 optional validation)

---

## Recommendation

**Option A.** It fixes all six defects with no new dependencies and keeps the runtime
deterministic, which was the founding decision of FEAT-649. Every uncertain case lands in the
confirm flow the user already sees, and the front's editable confirm field makes that cheap. We
trade breadth of grammar (B) for predictability. A defined English grammar for dates and numbers,
with confirmation as the fallback, is the right default for short field forms. Takeover through the
heartbeat that already has to exist for crash recovery avoids a second mechanism (pub/sub). The cost
is that an old tab learns it was replaced up to ~30 s late, which is acceptable because it is
usually the dead one.

---

## Feature Description

### User-Facing Behavior

- **After a server restart** the user can start a voice form again within ~1–2 minutes, not an
  hour.
- **If they hit "This form is open in another tab or device",** the front offers **Continue here**.
  The session moves to this device. The other tab, if still open, shows "Continued on another
  device" and stops; its progress stays resumable.
- **Saying "john dot smith at gmail dot com"** stores `john.smith@gmail.com`. If the result is not a
  valid email, the user sees "Did I get that right?" with the normalized text, editable.
- **Saying "five five five, oh one two three"** stores `5550123`.
- **Saying "twenty five"** in a number field stores `25`. Saying "next Friday" in a date field
  stores the date of next Friday in the rep's own timezone. Anything outside the grammar asks for
  confirmation instead of storing words.
- **Short English answers are transcribed as English.** Low-confidence transcripts still ask for
  confirmation.

### Internal Behavior

- **Protocol (additive):**
  - `StartSession` gains `timezone: str | None` (IANA) and `takeover: bool = False`.
  - A new outbound event `SessionReplaced`.
  - New error codes: `INVALID_EMAIL` if surfaced, and `SESSION_REPLACED`.
- **Engine:** the free-form speech path asks `normalize_spoken(field_type, text, lexicon, tz, now)`.
  - Unknown types pass through unchanged.
  - The result's `ok=False`, or the existing low-confidence rule, routes to `_request_confirm` with
    the normalized value. `raw_transcript` keeps the original words for audit.
  - Typed answers skip normalization. Email validation also runs on typed answers (`REQUIRED`-style
    `AnswerRejected` with a clear message).
- **Session store:**
  - `refresh_active(user_id, session_id, ttl)` (Lua CAS refresh) and an atomic `release_active`.
  - `claim_active(..., force: bool)` overwrites on takeover.
  - The marker TTL drops to ~90 s. The snapshot TTL is unchanged.
- **WS handler:** after `session_started`, a per-connection heartbeat task calls `refresh_active`
  every ~30 s. If the refresh fails because the marker belongs to another session:
  1. autosave;
  2. send `SessionReplaced`;
  3. close (normal close code). The client must not treat it as a dropped connection.

  The task is cancelled in `finally`.
- **STT:**
  - The language passed to the transcriber is the session locale's primary subtag, always.
  - `FasterWhisperBackend` computes transcript confidence from the segments and still reports
    `language_probability`.
  - Other backends keep their behaviour. OpenAI already takes `language`; Moonshine is English-only.

### Edge Cases & Error Handling

- **Takeover race (two tabs press "Continue here"):** last writer wins, and the other one is
  replaced at its next heartbeat.
- **Takeover of a session on another form:** the old one is replaced and stays resumable for its
  own form. The new session starts fresh.
- **Redis unavailable:** `claim_active` is already fail-open. Refresh and release failures are
  logged, never fatal.
- **Heartbeat on a connection that never started a session:** nothing to refresh.
- **Email with spoken punctuation inside a name** ("anne-marie" said as "anne dash marie"):
  supported. Spelled letters ("j o h n") are joined.
- **Phone with extension words ("extension 12"):** digits only. The extension is joined too
  (documented limitation).
- **Numbers:**
  - A decimal said as "point" is supported.
  - Negative numbers ("minus") are supported.
  - Ranges are not supported and go to confirmation.
- **Relative date without a client timezone** (old client): the server falls back to UTC and asks
  for confirmation.
- **Time and datetime:** "three thirty pm", "noon" and "midnight" are supported. Anything else
  goes to confirmation.
- **Sensitive fields:** normalization still applies. The transcript is never echoed (existing
  masking).
- **Locale `es`:** the same tables come from the `es` lexicon. A gap in the `es` grammar goes to
  confirmation, never to a wrong value.

---

## Capabilities

### New Capabilities
- `spoken-value-normalization`: deterministic, per field type, from transcript to typed value (email, phone, number, date/time), locale-driven.
- `audio-session-takeover`: claim an active voice session from another device; notify and close the replaced one.
- `audio-session-heartbeat`: short-TTL active marker renewed while the socket lives.

### Modified Capabilities
- `audio-form-engine` (`on_transcript` free-form path): normalize spoken answers; validate emails on all answers.
- `audio-session-store`: atomic release, CAS refresh, forced claim.
- `audio-ws-protocol` v2: `StartSession.timezone`, `StartSession.takeover`, `SessionReplaced`.
- `voice-transcriber` (faster-whisper): explicit language; transcript-based confidence.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `P/audio/engine.py` | modifies | Free-form speech path calls the normalizer; email validation on typed answers |
| `P/audio/normalize/` (new) | extends | Normalizers + tests |
| `P/audio/narration/templates/{en,es}/narration.yaml` + `lexicon.py` | modifies | Spoken tokens for email/phone, cardinals beyond 10, month and weekday names |
| `P/audio/session_store.py` | modifies | Refresh/release Lua, forced claim, shorter marker TTL |
| `P/api/audio_ws.py` | modifies | Heartbeat task, takeover on start, `SessionReplaced`, explicit STT language |
| `P/api/routes.py:495` | modifies | Marker TTL vs snapshot TTL separated |
| `P/audio/events.py` | modifies | `StartSession.timezone`, `StartSession.takeover`, `SessionReplaced` |
| `ai-parrot-integrations/.../faster_whisper_backend.py` | modifies | Confidence from segments |
| navigator-svelte FEAT-700 voice renderer | depends on | Separate task: send `timezone` + `takeover`, "Continue here" button, "Continued on another device" screen |
| FieldSync FEAT-701 | none | Hosts the handler; picks the change up through the parrot release |

---

## Code Context

### User-Provided Code
None.

### Verified Codebase References

`P` = `packages/parrot-formdesigner/src/parrot_formdesigner`. Verified on `18be18e09`
(FEAT-649 HEAD).

#### Classes & Signatures
```python
# P/audio/session_store.py
AUDIO_KEY_PREFIX = "parrot:audio:"                                   # :16
_CAS_SCRIPT = """..."""  # GET==ARGV[1] → SET ARGV[2] EX ARGV[3]       # :20-28 (snapshots only)
class AudioSessionStore:
    def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None: ...  # :73
    @staticmethod
    def _active_key(user_id: str) -> str: ...                          # :83  f"{AUDIO_KEY_PREFIX}active:{user_id}"
    async def delete(self, form_uid, session_id, *, user_id=None): ... # :139
    async def _release(self, redis, user_id, session_id): ...          # :157  GET + compare + DEL (not atomic)
    async def release_active(self, user_id: str, session_id: str) -> None: ...  # :163
    async def claim_active(self, user_id: str, session_id: str) -> bool: ...    # :173  SET NX EX ttl; fail-open

# P/api/routes.py:495
session_store = AudioSessionStore(partial_store, ttl_seconds=3600)

# P/api/audio_ws.py
web.WebSocketResponse(heartbeat=30.0, max_msg_size=..., protocols=offered_protocols)  # :330-334
# :363-385 `async for msg in ws:` TEXT/BINARY/ERROR/CLOSE; :387-398 finally: _autosave(final=True), release_active
# :669-681 claim_active on start → _send_error(ws, "SESSION_ACTIVE", "Another session is already active"); socket stays open
# :929  language = state.locale if state.locale != "en" else None      (narration)
# :985-987 result = await self.transcriber.transcribe(tmp_path, language=locale if locale != "en" else None)
# :1359 _send_error → {"type":"error","code":...,"message":...}

# P/audio/engine.py
def on_transcript(self, ev: TranscriptReady) -> list[Outbound]: ...   # :348
#   :382 option path when q.options or BOOLEAN → match_option(...)
#   :426-441 free-form: raw ev.text; confirm when confidence < cfg.stt_confirm_threshold (default 0.6, models.py:119)
def _request_confirm(self, evidence: AudioAnswer, value: Any, transcript: str,
                     matched: OptionMatch | None, alternatives: list[OptionMatch]) -> list[Outbound]: ...  # :442
def _accept(self, field_id: str, value: Any, *, source: str, confidence: float | None = None,
            raw: str | None = None, matched: OptionMatch | None = None,
            evidence: AudioAnswer | None = None) -> list[Outbound]: ...  # :464
def on_confirm(self, ev: ConfirmAnswer) -> list[Outbound]: ...        # :566

# P/audio/narration/lexicon.py
class Lexicon: locale, ordinals, cardinals, yes, no, all, none, conjunctions, fillers,
               commands, review_confirm, review_change              # :23
def normalize(text: str, lexicon: Lexicon) -> str: ...                # :79
def load_lexicon(locale) -> Lexicon: ...                              # :96 (lru_cache); cardinals only 1–10

# P/audio/events.py
class StartSession: type, form_uid, locale="en", protocol_version=1, prefetch=True,
    resume_session_id=None, stt_confirm_threshold=None, tts_backend, tts_voice,
    tts_mime_format, auto_advance, enumerate_options                  # :93 (no timezone)
class TranscriptReady: field_id, text, language, confidence, audio_mime, audio_bytes_len, duration_ms  # :173
class ConfirmRequest: field_id, transcript: str, confidence, matched, alternatives,
    purpose: Literal["answer", "stop"] = "answer"                     # :334
class Error: code: str, message: str                                  # :441

# P/core/types.py:16  FieldType: NUMBER, INTEGER, DATE, DATETIME, TIME, EMAIL, PHONE, URL, MASKED,
#                     TEXT, TEXT_AREA, BOOLEAN, SELECT, MULTI_SELECT, NPS, LIKERT

# packages/ai-parrot-integrations/src/parrot/voice/transcriber/
#   backend.py:39  async def transcribe(self, audio_path: Path, language: Optional[str] = None) -> TranscriptionResult
#   faster_whisper_backend.py:146-150 self._model.transcribe(str(audio_path), language=language, beam_size=5, vad_filter=True)
#   faster_whisper_backend.py:165   confidence=info.language_probability   ← language-ID, not transcript confidence
```

#### Verified Imports
```python
from parrot_formdesigner.audio.narration.lexicon import Lexicon, normalize, load_lexicon
from parrot_formdesigner.audio.session_store import AudioSessionStore, AUDIO_KEY_PREFIX
from parrot_formdesigner.core.types import FieldType
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
from email_validator import validate_email  # email-validator>=2.0, packages/ai-parrot/pyproject.toml:57
from zoneinfo import ZoneInfo               # stdlib
```

#### Key Attributes & Constants
- Marker TTL today: 3600 s (`routes.py:495`), shared with snapshots.
- `cfg.stt_confirm_threshold` default 0.6 (`models.py:119`).
- aiohttp WS heartbeat 30 s (`audio_ws.py:330`).

### Does NOT Exist (Anti-Hallucination)
- ~~A registry of live WebSockets~~: `self._checkers` (`audio_ws.py:299`) holds plausibility checkers only.
- ~~Redis pub/sub in `AudioSessionStore`~~
- ~~A heartbeat that renews the active marker~~: only `claim_active` refreshes it.
- ~~An atomic (Lua) release of the active marker~~
- ~~`StartSession.timezone` / `StartSession.takeover` / a `SessionReplaced` event~~
- ~~Locale normalization (`es-MX` → `es`) before STT~~
- ~~Typed parsing of free-form transcripts~~: raw text is stored for every type.
- ~~`FieldType.TEL`~~: the name is `PHONE`.
- ~~`dateparser`, `python-dateutil`, `word2number`, `text2num`, `num2words`, `phonenumbers`~~ in any package.
- ~~Cardinals above 10 in the narration lexicon~~
- `packages/ai-parrot-tools/.../procedures/verifier.py:83` `_CARDINAL_WORDS` exists, but it is a private regex helper, not a parser to reuse.

---

## Parallelism Assessment

- **Internal parallelism:** three independent tracks.
  1. Normalizers + lexicon + engine hook.
  2. Session store + WS heartbeat/takeover + events.
  3. Transcriber language + confidence.

  They share `audio_ws.py` (tracks 2 and 3) and `events.py` (track 2 only).
- **Cross-feature independence:** depends on FEAT-649 (not merged) and touches its files. The
  navigator-svelte task depends on the protocol fields from track 2.
- **Recommended isolation:** `mixed`. Track 1 can run in its own worktree; tracks 2 and 3 run
  sequentially in one, because both touch `audio_ws.py`.
- **Rationale:** the normalizers are pure functions with their own tests. The lock and STT changes
  meet in the WS handler.

---

## Open Questions

- [ ] Marker TTL and heartbeat interval: 90 s / 30 s proposed. Is a 1–2 min wait after a crash acceptable? — *Owner: Juan*
- [ ] Should `SESSION_REPLACED` close with a specific WS close code (e.g. 4001) so clients never auto-reconnect? — *Owner: Juan*
- [ ] Transcript confidence formula (`exp(mean(avg_logprob))` with a `no_speech_prob` penalty): calibrate the 0.6 threshold on real field recordings. — *Owner: Emmanuel / Juan*
- [ ] Release order: must this ship with FEAT-649's release, or after it? The FieldSync PR is blocked on that release. — *Owner: Juan*
- [ ] Date grammar scope for v1 (weekday names, "next/this/last", ordinals with month names, numeric US M/D/Y): confirm that the US-only M/D order is right. — *Owner: Jesús*
