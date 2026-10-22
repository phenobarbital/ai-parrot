---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [audio-forms, voice, normalization, post-processors, llm-refine]
---

# Feature Specification: Audio form voice post-processors (typed spoken-value normalization + optional LLM refine)

**Feature ID**: FEAT-653
**Date**: 2026-10-12
**Author**: Jesus Lara (from Emmanuel Arroyo's brainstorm)
**Status**: approved
**Target version**: ships together with the FEAT-649 release (same parrot-formdesigner version; §8 Q5)

**Source**: `sdd/proposals/audio-form-voice-followups.brainstorm.md` (branch
`origin/feat/audio-form-voice-followups`, commit `fbd7a7a24d`, status `exploration`), defects 2–4
only. Defects 1 (session lock), 5 and 6 (STT language / confidence) are **not** in this spec.

---

## 1. Motivation & Business Requirements

### Problem Statement

End-to-end testing of FEAT-649 (audio form workflow) hosted by FieldSync FEAT-701 and rendered by
navigator-svelte FEAT-700 showed that every free-form spoken answer is stored as the raw transcript,
whatever the field type (`audio/engine.py:426-441`). The product is used in the United States, in
English, by field reps answering short forms by voice.

- **Spoken emails are stored as words.** "john at gmail dot com" is stored as words, not
  `john@gmail.com`.
- **Spoken phone numbers are stored with separators.** Whisper's written output "0,4,12,523,573" is
  stored verbatim. It then fails the submit gate's `PHONE_PATTERN` (`services/validators.py:58`),
  so the user learns of the error only at submit time.
- **Spoken numbers and dates are not parsed.** "twenty five" in a NUMBER field fails the submit
  gate's `float(...)` coercion (`services/validators.py:709-716`). "next Friday" in a DATE field is
  stored as words, because DATE/TIME values are not validated at all (`services/validators.py:723`).

Each question therefore needs a **post-processor**: a step that turns what was heard into the
canonical value its field type expects, before the value is accepted. The post-processor is
deterministic (rules) by default. As an opt-in, an **LLM post-processor** can correct what was
heard (decision by Jesús Lara, 2026-10-12).

### Corrections to the brainstorm's claims (verified on `d180783c5`)

| Brainstorm claim | Reality | What this spec does |
|---|---|---|
| "`email-validator` is already a dependency" | Only of `ai-parrot` (`packages/ai-parrot/pyproject.toml:57`). `parrot-formdesigner` does not depend on `ai-parrot` (`packages/parrot-formdesigner/pyproject.toml:33-50`). | Reuse the submit gate's own `EMAIL_PATTERN` / `PHONE_PATTERN` (`services/validators.py:56,58`). No new dependency, and a value accepted by voice can never then fail the gate. |
| "Phone: no format validation" | The submit gate validates phones with `PHONE_PATTERN` (`^\+?[\d\s\-().]{7,}$`). | A normalized phone must match `PHONE_PATTERN`; otherwise it goes to confirmation. |
| "The front already lets the user fix the text before confirming" | `ConfirmAnswer` carries no value (`audio/events.py:128-131`). `ConfirmRequest` carries only the `transcript` (`:334-341`). A correction is an `answer_text` sent during CONFIRMING (allowed by `_ANSWERING_PHASES`, `audio/engine.py:88`), so it is a *typed* answer. | Add an additive `ConfirmRequest.value` (normalized candidate, v2 only), so the front shows the post-processed value rather than the words. Typed corrections stay unnormalized, but EMAIL is validated. |
| "Extend the `Lexicon` cardinals beyond 10" | `Lexicon.cardinals` drives option-*position* matching ("option two", `audio/option_matcher.py:83-92`). | Leave `cardinals` alone. New tables live in a separate `Lexicon.spoken` block. |
| Input is "spoken words" | Whisper usually writes digits, punctuation and symbols ("0,4,12,523,573", "3/12", "john@gmail.com", "$25"). | Every normalizer accepts both the written form and the spoken-word form. |
| "No LLM per turn (FEAT-649 decision)" | That was FEAT-649's founding rule. | Reversed **as an opt-in**: the LLM post-processor is off by default and enabled per form or per field. |
| Timezone "stored on the session state" | Snapshots do not carry it, and a resumed session gets a new `start_session`. | `StartSession.timezone` is read on every start *and* on every resume. It is never snapshotted. |

### Goals

- G1. A deterministic post-processor per field-type family (EMAIL, PHONE, NUMBER/INTEGER,
  DATE/TIME/DATETIME). It turns a transcript into the canonical value that the submit gate
  (`FormValidator`) accepts.
- G2. Normalization applies to **spoken answers only**. Typed answers are stored as typed.
  **Email validation** applies to both (typed EMAIL answers are rejected early with `INVALID_EMAIL`).
- G3. A valid but uncertain result goes to the existing confirm flow, carrying the normalized
  candidate. A result that cannot be valid is rejected and re-asked, with the candidate offered
  for editing. Nothing invalid is stored, and nothing is stored as words.
- G4. Optional **LLM post-processor** (`llm_refine`): when enabled for a field of a typed family
  (EMAIL, PHONE, NUMBER/INTEGER, DATE/TIME/DATETIME — never TEXT/TEXT_AREA, §8 Q3), it runs on
  *every* spoken answer of that field, after the rules. Its value is accepted without confirmation only when
  all three hold:
  - its confidence is ≥ `llm_refine_threshold`;
  - its output passes the same deterministic normalizer/validator;
  - none of the existing confirmation gates fires.
- G5. Locale-driven: spoken-token tables live in the `en`/`es` narration YAML. English first (US
  product). Spanish keeps parity where its tables cover a phrase. A gap goes to confirmation, never
  to a wrong value.
- G6. Relative dates are resolved in the **client's IANA timezone**, sent in `start_session`.
- G7. Protocol changes are additive. v1 and v2 clients that send none of the new fields keep working.
- G8. Every spoken (non-sensitive) answer persists which post-processor produced it
  (`normalized_by`, plus `llm_confidence` when the LLM did) in its `VoiceEvidenceEnvelope`, for all
  field types (§8 Q2).
- G9. The LLM threshold/timeout defaults and the STT confirm threshold are set from a
  **calibration run** over real field recordings, not guessed (§8 Q4).

### Non-Goals (explicitly out of scope)

- Defect 1, the session lock (heartbeat, takeover, `SESSION_REPLACED`): a separate spec.
- Defects 5 and 6, STT language forcing and transcript-based confidence: a separate spec. That fix
  improves the input of this one but does not block it.
- Normalizing typed answers (G2), and normalizing option fields (SELECT, MULTI_SELECT, BOOLEAN,
  NPS, LIKERT). Option fields go through `match_option`, unchanged.
- URL, MASKED, LOCATION and other field types: they pass through unchanged.
- Wiring the existing but dead `VoiceFormConfig.llm_refine_options` / `LLMOptionRefiner`
  (`core/voice.py:64`, `audio/option_refiner.py:33`; nothing reads either). It is noted here and
  left alone.
- Third-party parsers (`dateparser`, `word2number`, `text2num`, `phonenumbers`): rejected in the
  brainstorm (Option B).

---

## 2. Architectural Design

### Overview

A new pure package `audio/normalize/` exposes one entry point:
`normalize_spoken(field_type, text, *, ctx) -> NormalizeResult | None`. It dispatches to one
normalizer per type family. `None` means "type not handled, pass through". A `NormalizeResult`
carries the canonical `value`, a three-way `status` and a `reason` code (design research S1):

- **`accepted`**: a valid canonical value, parsed with certainty.
- **`confirm`**: a *valid* canonical value whose reading is uncertain: an ambiguous numeric date,
  am/pm missing, a relative date without a timezone. "Yes" stores it.
- **`rejected`**: no valid value can be produced (an invalid email, a phone too short, no parse,
  several numbers, non-integral for INTEGER). This is **never** offered as a "yes" confirmation,
  because "yes" would store a value the submit gate rejects. The best-effort candidate, if any, is
  returned so the client can prefill an editable input.

The engine calls it on the **free-form speech path only** (`on_transcript`, after commands and
after the option path):

1. **Rules.** `det = normalize_spoken(...)`, unless `meta.voice.normalize` is false (then the raw
   text, `status="accepted"`, `normalized_by=None`).
2. **Optional LLM refine.** It runs when all three hold:
   - `llm_refine` is in effect for the field;
   - the field type is in `REFINABLE_TYPES` (the typed families, never TEXT/TEXT_AREA);
   - the field is not sensitive (S8: a sensitive value never leaves the process).

   The engine parks the answer and emits a `RefineValue` I/O request. The adapter awaits
   `LLMValueRefiner.refine(...)` with a timeout and feeds back `ValueRefined`. The LLM's string is
   **re-run through the same normalizer**:
   - If it comes out `accepted` or `confirm`, it becomes the candidate (`normalized_by="llm"`).
   - Otherwise, or on failure, timeout, no client or a stale reply, the rules result stands.
3. **Decision**, using the matrix below. The LLM never overrides the existing STT confidence rule or
   `confirm: "always"`; it can only add a reason to confirm (design research S9).
4. **Confirm.** `ConfirmRequest` carries `transcript` (the words, masked if sensitive) plus the new
   `value` (the candidate, v2 only, omitted if sensitive) and `refined_by`. "Yes" stores the
   candidate with its provenance. A typed correction (`answer_text`) is stored as typed. For EMAIL it
   is validated.
5. **Reject.** `AnswerRejected` gets `code` = `INVALID_EMAIL` (EMAIL) or `INVALID_VALUE` (other
   types) and the localized narration. The new optional `value` field carries the best-effort
   candidate (v2 only, omitted if sensitive). The question stays on the cursor (phase ASKING), like
   today's `NO_MATCH`.
6. **Accept.** `AudioAnswer.value` is the canonical value. `raw_transcript` keeps the words for
   audit (already true). The new `AudioAnswer.normalized_by` (`"rules"`, `"llm"` or `None`) and
   `AudioAnswer.llm_confidence` travel through `state.pending` and `_accept` (they survive a
   confirmation), into the snapshot (resume), and into the submission's `VoiceEvidenceEnvelope`
   via `wrap_voice` (G8, design research S8).

**Decision matrix.** "STT low" means `confidence < stt_confirm_threshold` and `confirm` ≠ `"never"`.
"LLM low" means the candidate came from the LLM with `confidence < llm_refine_threshold`.

| Candidate status | `confirm: "always"` | STT low | LLM low | Outcome |
|---|---|---|---|---|
| `rejected` | any | any | any | **reject** (`INVALID_EMAIL` / `INVALID_VALUE`), re-ask |
| `confirm` | any | any | any | **confirm**, even with `confirm: "never"` |
| `accepted` | yes | any | any | **confirm** |
| `accepted` | no | yes | any | **confirm** (unchanged FEAT-649 rule) |
| `accepted` | no | no | yes | **confirm** |
| `accepted` | no | no | no | **accept** |
| LLM timeout / failure / unavailable | — | — | — | the rules result goes through the same matrix |

Canonical output per type (what `FormValidator._coerce_value` / `_validate_by_type` accept):

| FieldType | Canonical value | `confirm` when | `rejected` when |
|---|---|---|---|
| EMAIL | lowercase `str` matching `EMAIL_PATTERN` | — | not exactly one `@`, or no `EMAIL_PATTERN` match |
| PHONE | `str`: optional leading `+`, then digits only, matching `PHONE_PATTERN` | — | fewer than 7 digits / no digits |
| INTEGER | `int` | — | no number, several numbers, non-integral |
| NUMBER | `int` if integral, else `float` | — | no number, several numbers |
| DATE | `"YYYY-MM-DD"` | relative phrase without a valid timezone (resolved in UTC); numeric date valid in both orders (e.g. 3/4; candidate uses the locale order) | no parse, impossible date |
| TIME | `"HH:MM"` (24 h) | hour 1–12 with no am/pm (candidate uses the literal hour) | no parse, out of range |
| DATETIME | `"YYYY-MM-DDTHH:MM"` (naive, client local, like HTML `datetime-local`; design research S5 offset part rejected) | either part `confirm` | either part `rejected` |
| anything else | — (`None`, pass-through) | — | — |

### Component Diagram
```
TranscriptReady ──→ AudioFormSession.on_transcript
                      │ commands / option path (unchanged)
                      ▼ free-form
                normalize_spoken(field_type, text, ctx)   ← audio/normalize/* + Lexicon.spoken
                      │
          llm_refine? ├── no ──────────────→ gate ─→ _accept | _request_confirm(value=…)
                      └── yes → RefineValue (I/O) ──→ AudioFormWSHandler._perform_one
                                                         └─ LLMValueRefiner.refine (AbstractClient.ask,
                                                            structured_output, timeout)
                             ValueRefined ←────────────────┘
                      on_value_refined → re-normalize LLM value → gate → accept | confirm
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AudioFormSession.on_transcript` (`audio/engine.py:348`) | modifies | Free-form block `:426-441` |
| `AudioFormSession.on_text` (`audio/engine.py:523`) | modifies | EMAIL validation → `INVALID_EMAIL` |
| `FormValidator` patterns (`services/validators.py:56,58`) | uses | Single source of email/phone validity |
| `Lexicon` / `load_lexicon` (`audio/narration/lexicon.py:23,96`) | extends | New `spoken: SpokenLexicon` block |
| `en`/`es` `narration.yaml` | extends | `lexicon.spoken` tables |
| `StartSession`, `ConfirmRequest` (`audio/events.py:93,334`) | extends | `timezone`; `value`, `refined_by` |
| `_IORequest` / `InboundEvent` (`audio/events.py:451,250`) | extends | `RefineValue`, `ValueRefined` |
| `AudioSessionState`, `AudioAnswer` (`audio/models.py:258,214`) | extends | `timezone`; `normalized_by` |
| `VoiceFormConfig`, `FieldVoiceMeta` (`core/voice.py:50,35`) | extends | refine config; `normalize`, `llm_refine` |
| `VoiceEvidenceEnvelope` / `wrap_voice` (`core/voice_answer.py:39,77`) | extends | `normalized_by`, `llm_confidence` persisted |
| `FormValidator._EVIDENCE_KEYS` (`services/validators.py:580`) | extends | the two new envelope keys |
| `AudioFormWSHandler` (`api/audio_ws.py`) | modifies | Timezone, `RefineValue` handling, v1 encode, refiner from `llm_client_getter` |
| `LLMOptionRefiner` (`audio/option_refiner.py:33`) | pattern only | Same shape for `LLMValueRefiner` |

### Data Models
```python
# audio/normalize/base.py
class NormalizeResult(BaseModel):
    value: Any = None                  # canonical value (accepted/confirm) or best-effort candidate / None (rejected)
    status: Literal["accepted", "confirm", "rejected"]
    reason: str | None = None          # confirm: "ambiguous_order" | "needs_timezone" | "ambiguous_meridiem"
                                       # rejected: "invalid_email" | "too_short" | "no_parse" | "multiple_values" | "non_integral" | "out_of_range"

REFINABLE_TYPES: frozenset[FieldType]  # {EMAIL, PHONE, NUMBER, INTEGER, DATE, TIME, DATETIME}

@dataclass(frozen=True)
class NormalizeContext:
    lexicon: Lexicon                    # carries .spoken
    now: datetime                       # tz-aware, already converted to the client tz (UTC if unknown)
    timezone_known: bool                # False → relative date phrases resolve in UTC with status="confirm" ("needs_timezone")

# audio/value_refiner.py
class RefinedValue(BaseModel):          # LLM structured output
    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
```

### New Public Interfaces
```python
def normalize_spoken(field_type: FieldType, text: str, *, ctx: NormalizeContext) -> NormalizeResult | None: ...
def validate_typed(field_type: FieldType, value: str) -> str | None: ...   # error code, EMAIL only ("INVALID_EMAIL")
class LLMValueRefiner:
    async def refine(self, *, transcript: str, candidate: Any, field_type: FieldType, label: str,
                     locale: str, today: str, timezone: str | None) -> RefinedValue | None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Spoken lexicon tables | yes | `SpokenLexicon` fields below; YAML keys under `lexicon.spoken` | — |
| M2: Normalize core + numbers | yes | `NormalizeResult`, `NormalizeContext`, `normalize_spoken`, `parse_number` grammar in §7 | — |
| M3: Email + phone | yes | Canonical table §2; patterns from validators | — |
| M4: Temporal | no | Grammar is specified, but the year roll-over and numeric-ambiguity edge rules need judgment | date semantics |
| M5: Config + protocol models | yes | Field names/types below; v1 drops new keys | — |
| M6: LLM value refiner | yes | Mirrors `LLMOptionRefiner`; prompt contract §7 | — |
| M7: Engine integration | no | Gate ordering and stale-refine handling are the design core | state machine |
| M8: WS adapter | yes | `_perform_one` row; timezone validation; refiner construction | — |
| M9: Docs | yes | Sections listed | — |
| M10: Evidence envelope | yes | Two optional fields; `wrap_voice` copies them; `_EVIDENCE_KEYS` extended | — |
| M11: Calibration harness + run | no | Metrics and decision rule below; corpus contents depend on the field recordings | threshold choice is a judgment over the report |

### Module 1: Spoken lexicon tables
- **Path**: `audio/narration/lexicon.py` (modify), `audio/narration/templates/{en,es}/narration.yaml` (modify)
- **Responsibility**: locale data for the normalizers. Phrases are pre-folded with `_strip_text`,
  like the other lexicon lists. `cardinals`/`ordinals` stay untouched (option matching).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # audio/narration/lexicon.py  (modifies; Lexicon verified :23, load_lexicon :96)
  class SpokenLexicon(BaseModel):
      """Spoken-token tables for typed post-processors (FEAT-653)."""
      units: dict[str, int] = {}          # zero..nineteen / cero..diecinueve (incl. veintiuno..veintinueve in es)
      tens: dict[str, int] = {}           # twenty..ninety
      scales: dict[str, int] = {}         # hundred=100, thousand=1000, million=1_000_000 (es: cien/ciento/cientos, mil, millón/millones)
      number_joiners: list[str] = []      # "and" / "y"
      decimal_words: list[str] = []       # "point" / "punto", "coma"
      minus_words: list[str] = []         # "minus", "negative" / "menos"
      decimal_separator: str = "."        # written-form decimal separator ("," for es)
      digit_aliases: dict[str, str] = {}  # phone only: "oh"→"0" / "o"→"0"
      repeat_words: dict[str, int] = {}   # "double"=2, "triple"=3 / "doble", "triple"
      plus_words: list[str] = []          # "plus" / "más"
      email_symbols: dict[str, str] = {}  # at→"@", dot/period→".", underscore→"_", dash/hyphen→"-", plus→"+" / arroba, punto, guion bajo, guion
      months: dict[str, int] = {}
      weekdays: dict[str, int] = {}       # monday=0 … sunday=6
      relative_days: dict[str, int] = {}  # today=0, tomorrow=1, yesterday=-1 / hoy, mañana, ayer, pasado mañana=2
      this_words: list[str] = []
      next_words: list[str] = []
      last_words: list[str] = []
      am_words: list[str] = []
      pm_words: list[str] = []
      noon_words: list[str] = []
      midnight_words: list[str] = []
      half_words: list[str] = []          # "thirty" handled by numbers; "half past" / "y media"
      date_order: Literal["MDY", "DMY"] = "MDY"   # en MDY, es DMY (decision 2026-10-12)
  class Lexicon(BaseModel):
      ...
      spoken: SpokenLexicon = Field(default_factory=SpokenLexicon)   # new, after review_change (:37)
  ```

### Module 2: Normalize core + numbers
- **Path**: `audio/normalize/__init__.py`, `audio/normalize/base.py`, `audio/normalize/numbers.py` (new)
- **Responsibility**: result/context models, the type→normalizer registry, the spoken/written
  number parser (shared by phone, email and temporal), and the NUMBER/INTEGER normalizer.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # audio/normalize/__init__.py
  def normalize_spoken(field_type: FieldType, text: str, *, ctx: NormalizeContext) -> NormalizeResult | None:
      """Dispatch to the family normalizer; None when the type is not handled (caller keeps the raw text). Never raises."""
  def validate_typed(field_type: FieldType, value: str) -> str | None:
      """Typed-answer check: 'INVALID_EMAIL' for a non-empty EMAIL value failing EMAIL_PATTERN; else None."""
  # audio/normalize/numbers.py
  def tokenize(text: str) -> list[str]:
      """Casefold + accent fold, keep digits, '.', ',', '/', ':', '-', '+', '@'; split words."""
  def parse_numbers(tokens: list[str], spoken: SpokenLexicon) -> list[float | int]:
      """Every number in the token stream (words and written digits, grouping commas, decimals, minus)."""
  def normalize_number(text: str, ctx: NormalizeContext, *, integer: bool) -> NormalizeResult:
      """Exactly one number → accepted int/float; 0 or >1 numbers → rejected (no_parse / multiple_values)."""
  ```

### Module 3: Email + phone
- **Path**: `audio/normalize/email.py`, `audio/normalize/phone.py` (new)
- **Depends on**: M2 (`tokenize`, `parse_numbers`)
- **Interface Skeleton**:
  ```python
  from ...services.validators import EMAIL_PATTERN, PHONE_PATTERN   # verified: services/validators.py:56,58 (import checked cycle-free on d180783c5)
  def normalize_email(text: str, ctx: NormalizeContext) -> NormalizeResult:
      """Map email_symbols, join spelled letters, number words → digits, drop spaces, lowercase; accepted iff EMAIL_PATTERN matches, else rejected (invalid_email) with the candidate."""
  def normalize_phone(text: str, ctx: NormalizeContext) -> NormalizeResult:
      """Leading plus word/'+' kept; digit words, digit_aliases, repeat_words, compound tens ('fifty five'→'55'); every
      separator (space , . - ( )) dropped; accepted iff PHONE_PATTERN matches, else rejected (too_short)."""
  ```

### Module 4: Temporal (DATE / TIME / DATETIME)
- **Path**: `audio/normalize/temporal.py` (new)
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  def normalize_date(text: str, ctx: NormalizeContext) -> NormalizeResult: ...
  def normalize_time(text: str, ctx: NormalizeContext) -> NormalizeResult: ...
  def normalize_datetime(text: str, ctx: NormalizeContext) -> NormalizeResult:
      """Split into a date phrase and a time phrase ('tomorrow at three pm'); worst status of the two parts wins."""
  ```

### Module 5: Config + protocol models
- **Path**: `core/voice.py`, `audio/events.py`, `audio/models.py` (modify)
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # core/voice.py
  class FieldVoiceMeta(BaseModel):                  # verified :35
      ...
      normalize: bool = True                        # rules post-processor on/off for this field
      llm_refine: bool | None = None                # None → inherit VoiceFormConfig.llm_refine_values
  class VoiceFormConfig(BaseModel):                 # verified :50
      ...
      llm_refine_values: bool = False               # LLM post-processor for free-form spoken answers (opt-in)
      llm_refine_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
      llm_refine_timeout_s: float = Field(default=4.0, gt=0.0)
  # audio/events.py
  class StartSession(_Inbound):                     # verified :93
      ...
      timezone: str | None = None                   # IANA, e.g. "America/New_York"
  class ConfirmRequest(_Wire):                      # verified :334
      ...
      value: Any = None                             # normalized candidate (v2 only; omitted when sensitive)
      refined_by: Literal["rules", "llm"] | None = None
  class AnswerRejected(_Wire):                      # verified :353
      ...
      value: Any = None                             # best-effort candidate for a rejected spoken value (v2 only; omitted when sensitive)
  class ValueRefined(_Inbound):                     # internal, joins InboundEvent (:250)
      type: Literal["_value_refined"]
      field_id: str
      request_id: str
      status: Literal["ok", "failed", "unavailable"]
      value: str | None = None
      confidence: float | None = None
  class RefineValue(_IORequest):                    # joins IORequest (:525)
      type: Literal["_refine_value"] = "_refine_value"
      field_id: str
      request_id: str
      transcript: str
      candidate: Any = None
      field_type: str
      label: str
      today: str                                    # ISO date in the client tz
  # audio/models.py
  class AudioSessionState(BaseModel):               # verified :258 (extra="forbid")
      ...
      timezone: Optional[str] = None
  class AudioAnswer(BaseModel):                     # verified :214 (extra="forbid")
      ...
      normalized_by: Optional[Literal["rules", "llm"]] = None
      llm_confidence: Optional[float] = None
  ```

### Module 6: LLM value refiner
- **Path**: `audio/value_refiner.py` (new)
- **Depends on**: `parrot.clients.base.AbstractClient` (TYPE_CHECKING only, as in `option_refiner.py`)
- **Interface Skeleton**:
  ```python
  class ValueRefiner(Protocol):
      async def refine(self, *, transcript: str, candidate: Any, field_type: FieldType, label: str,
                       locale: str, today: str, timezone: str | None) -> RefinedValue | None: ...
  class LLMValueRefiner:
      """`ValueRefiner` over ``AbstractClient.ask(structured_output=RefinedValue)``; never raises, None on any failure."""
      def __init__(self, client: "AbstractClient") -> None: ...
      async def refine(...) -> RefinedValue | None: ...
  ```

### Module 7: Engine integration
- **Path**: `audio/engine.py` (modify)
- **Depends on**: M2, M3, M4, M5
- **Interface Skeleton**:
  ```python
  class AudioFormSession:
      def __init__(self, *, ..., clock: Callable[[], datetime] | None = None) -> None:
          """New optional dep (default: UTC now); the adapter passes nothing."""
      def _normalize_ctx(self) -> NormalizeContext:
          """now = clock() converted to ZoneInfo(state.timezone) when valid, else UTC with timezone_known=False."""
      def _llm_refine_enabled(self, field: FormField, meta: FieldVoiceMeta) -> bool:
          """meta.llm_refine if not None else cfg.llm_refine_values; False for sensitive fields and for any type
          outside REFINABLE_TYPES = {EMAIL, PHONE, NUMBER, INTEGER, DATE, TIME, DATETIME}."""
      def _gate(self, evidence: AudioAnswer, candidate: NormalizeResult, *, refined_by, llm_confidence) -> list[Outbound]:
          """Single reject/confirm/accept decision: the §2 decision matrix, nothing else."""
      def _accept(self, field_id, value, *, source, confidence=None, raw=None, matched=None, evidence=None,
                  normalized_by: str | None = None, llm_confidence: float | None = None) -> list[Outbound]:
          """verified :464 — two new keyword args, copied onto the stored AudioAnswer; on_confirm passes them from
          state.pending (which _request_confirm now stamps with normalized_by / llm_confidence)."""
      def on_value_refined(self, ev: ValueRefined) -> list[Outbound]:
          """Drop when stale (no in-flight refine, field or request_id mismatch); else re-normalize and _gate."""
      def on_start(...)   # also records ev.timezone
      def _resume(...)    # also records ev.timezone (never from the snapshot)
      def on_text(...)    # validate_typed → AnswerRejected(code="INVALID_EMAIL")
  ```
  The in-flight refine (evidence, rules result, request_id) lives in a private attribute that is
  **never snapshotted**. A crash mid-refine resumes like a crash mid-confirm: `_resume` already
  drops `pending` and re-plans (`audio/engine.py:1085-1090`).

### Module 8: WS adapter
- **Path**: `api/audio_ws.py` (modify)
- **Depends on**: M5, M6, M7
- **Responsibility**:
  - Validate `start.timezone` with `zoneinfo.ZoneInfo`; an invalid value is logged and treated as
    `None`.
  - Store the timezone in `AudioSessionState`.
  - Perform `RefineValue`: get the client from `llm_client_getter`, call the refiner under
    `asyncio.wait_for(cfg.llm_refine_timeout_s)`, and return `ValueRefined`. A missing client gives
    `status="unavailable"`; an exception or timeout gives `"failed"`.
  - In `_encode`, v1 `confirm_request` pops `value` and `refined_by`, and v1 `answer_rejected` pops `value`.
- **Interface Skeleton**:
  ```python
  async def _do_refine(self, ctx: _ConnCtx, item: RefineValue) -> "InboundEvent": ...
  def _refiner_for(self, session_id: str) -> ValueRefiner | None: ...   # cached per session like _checker_for (:1019)
  ```

### Module 9: Docs
- **Path**: `docs/audio-form-voice-modes.md`, `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`
- **Depends on**: M7, M8
- **Responsibility**:
  - Document the per-type post-processors and canonical formats.
  - Document the `meta.voice.normalize` / `llm_refine` and form `llm_refine_*` settings.
  - Document `start_session.timezone`, `confirm_request.value` / `refined_by`, `answer_rejected.value`, and the `INVALID_EMAIL` / `INVALID_VALUE` codes.
  - Front note: show `value` (not `transcript`) as the editable candidate, and send `timezone`.


### Module 10: Evidence envelope (post-processor audit)
- **Path**: `core/voice_answer.py`, `services/validators.py` (modify)
- **Responsibility**: persist `normalized_by` and `llm_confidence` with every non-sensitive spoken
  answer, for all field types (§8 Q2). Pre-FEAT-653 envelopes keep validating.
- **Depends on**: M5 (`AudioAnswer.normalized_by`, `llm_confidence`)
- **Interface Skeleton**:
  ```python
  # core/voice_answer.py
  class VoiceEvidenceEnvelope(VoiceAnswerEnvelope):                       # verified :39
      ...
      normalized_by: Literal["rules", "llm"] | None = None                # new, after plausibility (:52)
      llm_confidence: float | None = None
  def wrap_voice(scalars, evidence) -> dict[str, Any]:                    # verified :77 — also copies the two fields
  # services/validators.py:580
  _EVIDENCE_KEYS = frozenset({..., "normalized_by", "llm_confidence"})
  ```

### Module 11: Calibration harness + run
- **Path**: `packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py` (new); report
  under `sdd/state/FEAT-653/calibration/` (`report.md`, `report.json`)
- **Responsibility**: measure the post-processors on real field recordings, then set the shipped
  defaults of `llm_refine_threshold`, `llm_refine_timeout_s` and `stt_confirm_threshold` from the
  measurement (§8 Q4).
- **Depends on**: M2, M3, M4, M6
- **Corpus** (never committed; user data): a JSONL manifest passed with `--corpus`. Each line holds
  `{audio, field_type, locale, timezone, label, expected}`, where `expected` is the canonical value
  the rep finally confirmed or typed. Source: FieldSync FEAT-701 test sessions (`store_recordings`
  is on by default). Minimum 30 items per field-type family per locale that is calibrated.
- **What it does per item**:
  1. Transcribe with `FasterWhisperBackend`, passing the language exactly as the WS handler does
     today, and record the STT confidence.
  2. Run `normalize_spoken` against a clock fixed at the recording date.
  3. Run `LLMValueRefiner`, timing it with no timeout.
  4. Re-normalize the LLM value.
  5. Compare everything with `expected`.
- **Metrics**, per type family and locale:
  - Rules: exact-match accuracy, accepted/confirm/rejected rates, and **false-accept rate** (accepted but wrong).
  - LLM: accuracy as a function of the confidence threshold (0.5–0.95, step 0.05), and false-accept
    rate among auto-accepted values.
  - LLM latency: p50, p95, p99.
  - STT: confidence distribution of correct vs. wrong transcripts, and false-accept rate as a
    function of the threshold.
- **Decision rule** (written into the report):
  - `llm_refine_threshold`: the lowest value with LLM false-accept ≤ 2 %.
  - `llm_refine_timeout_s`: p95 latency rounded up to 0.5 s, capped at 6 s.
  - `stt_confirm_threshold`: the lowest value with free-form false-accept ≤ 5 %.

  A family with too few items keeps the spec default and says so.
- **Privacy**: the committed report holds aggregates only. No transcripts, values, audio paths or
  user ids.
- **Interface Skeleton**:
  ```python
  class CorpusItem(BaseModel): audio: Path; field_type: FieldType; locale: str; timezone: str | None; label: str; expected: Any
  async def run_calibration(items: list[CorpusItem], *, transcriber: AbstractTranscriberBackend,
                            refiner: ValueRefiner | None, recorded_at: datetime | None = None) -> CalibrationReport: ...
  def recommend(report: CalibrationReport) -> dict[str, float]:
      """Apply the decision rule; returns the three defaults (or the spec defaults with a reason)."""
  def main(argv: list[str] | None = None) -> int: ...   # --corpus, --out, --llm (provider:model), --max-requests
  ```
  Real LLM calls need explicit `PARROT_TEST_REAL_LLM=1` and stay within the `--max-requests` budget.

---

## 4. Test Specification

Tests live in `packages/parrot-formdesigner/tests/formdesigner/`. Run them with
`PYTHONPATH=packages/parrot-formdesigner/src`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_spoken_lexicon_loads_en_es` | M1 | `load_lexicon("en"/"es").spoken` populated; `cardinals` unchanged (1–10) |
| `test_number_words_and_digits` | M2 | "twenty five"→25, "two hundred and five"→205, "1,250"→1250, "three point five"→3.5, "minus four"→-4, "veinticinco"→25, es "1,5"→1.5 |
| `test_number_rejects_many_or_none` | M2 | "five or six" → rejected `multiple_values`; "hello" → `no_parse`; INTEGER "3.5" → `non_integral` |
| `test_email_spoken_and_written` | M3 | "john dot smith at gmail dot com"→john.smith@gmail.com; "J O H N at gmail dot com"→john@gmail.com; "anne dash marie at x dot io"; "juan arroba gmail punto com" (es); "john at gmail" → rejected `invalid_email` with candidate `john@gmail` |
| `test_phone_variants` | M3 | "0,4,12,523,573"→0412523573; "five five five oh one two three"→5550123; "double five"→55; "plus one 555 0100"→+15550100; "123" → rejected `too_short`; output always matches PHONE_PATTERN when accepted |
| `test_date_grammar` | M4 | today/tomorrow/yesterday; "March third"; "third of March 2027"; "3/12" en→03-12, es→12-03; "3/4" → confirm `ambiguous_order` (candidate in locale order); "2026-03-12"; with the Monday 2026-10-12 clock "Friday"/"this Friday"/"next Friday" → 2026-10-16 and "next Monday" → 2026-10-19; relative without timezone → `needs_timezone` |
| `test_time_grammar` | M4 | "three thirty pm"→15:30; "noon"→12:00; "midnight"→00:00; "15:30"; "three thirty" → confirm `ambiguous_meridiem` (03:30) |
| `test_datetime_grammar` | M4 | "tomorrow at three pm" with a fixed clock + tz |
| `test_unhandled_type_passthrough` | M2 | TEXT/URL → `None` |
| `test_validate_typed_email` | M2 | invalid typed email → "INVALID_EMAIL"; other types → None |
| `test_llm_value_refiner_contract` | M6 | fake client returns `structured_output`; exception/garbage → None |
| `test_engine_freeform_normalizes` | M7 | PHONE transcript accepted as canonical; `raw_transcript` keeps words; `normalized_by="rules"` |
| `test_engine_decision_matrix` | M7 | one case per §2 matrix row: rejected → `AnswerRejected(INVALID_EMAIL / INVALID_VALUE, value=…)` and cursor unchanged; confirm-status with `confirm: never` → `ConfirmRequest(value=…)`; STT low + LLM high → confirm; LLM low → confirm; all clear → accept |
| `test_engine_provenance_survives_confirm_and_resume` | M7 | `normalized_by`/`llm_confidence` kept through `confirm_answer{yes}`, `snapshot()` → `from_snapshot` and `_submission_data()` |
| `test_engine_llm_refine_flow` | M7 | `RefineValue` emitted; `ValueRefined ok ≥ threshold` → accept (`normalized_by="llm"`); below threshold → confirm; LLM value failing re-normalization → rules candidate; `failed`/`unavailable` → rules candidate; stale request_id ignored |
| `test_engine_sensitive_never_refined` | M7 | sensitive field: rules applied, no `RefineValue`, confirm value omitted |
| `test_engine_text_never_refined` | M7 | TEXT/TEXT_AREA with `llm_refine: true` → no `RefineValue` (config ignored, warning logged once) |
| `test_wrap_voice_carries_postprocessor` | M10 | envelope has `normalized_by`/`llm_confidence`; old envelopes without them still validate; `_scalar_view` unwraps them |
| `test_calibration_report_shape` | M11 | harness over a 3-item fixture corpus with a fake transcriber/LLM writes the report with every metric |
| `test_engine_typed_email_rejected` | M7 | `answer_text` invalid email → `AnswerRejected(code="INVALID_EMAIL")`; typed phone "0,4,12" stored as typed |
| `test_engine_timezone_on_resume` | M7 | resumed session takes `timezone` from the new `start_session` |

### Integration Tests
| Test | Description |
|---|---|
| `test_audio_ws_postprocess_v2` | v2 WS session: spoken phone/email/number/date stored canonically; the submission passes `FormValidator`; `confirm_request.value` present |
| `test_audio_ws_postprocess_v1_compat` | v1 client: `confirm_request` without `value`/`refined_by`; existing v1 fixtures unchanged |
| `test_audio_ws_llm_refine_timeout` | slow fake client → falls back to rules within `llm_refine_timeout_s` |
| `test_audio_ws_timezone_validation` | invalid IANA string → logged, treated as absent; valid one reaches `AudioSessionState.timezone`; resume takes the new value |
| `test_audio_ws_refine_stale_reply` | a `ValueRefined` with an old `request_id` is ignored by the engine |

### Test Data / Fixtures
```python
@pytest.fixture
def fixed_clock():
    return lambda: datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)   # a Monday
```
Redis: none is needed (the normalizers are pure). Integration tests reuse the dict-backed stubs of
`test_audio_ws_v2_integration.py` (`fakeredis` is not installed).

---

## 5. Acceptance Criteria

- [ ] AC1. A spoken answer to an EMAIL/PHONE/NUMBER/INTEGER/DATE/TIME/DATETIME field is stored in
  the canonical form of §2. Every accepted value passes `FormValidator` for its type.
- [ ] AC2. Typed answers (`answer_text`, including corrections during CONFIRMING) are never
  normalized. A non-empty typed EMAIL failing `EMAIL_PATTERN` is rejected with `INVALID_EMAIL`.
- [ ] AC3. The §2 decision matrix holds. A `rejected` result is never stored and never offered as a
  "yes" confirmation (`AnswerRejected` `INVALID_EMAIL`/`INVALID_VALUE`, question re-asked). A
  `confirm` result always goes to `confirm_request`, even with `confirm: "never"`. The LLM never
  overrides the STT-confidence rule or `confirm: "always"`.
- [ ] AC4. `confirm_request.value` and `answer_rejected.value` carry the normalized candidate for v2
  clients. Both are omitted for sensitive fields and for v1 clients.
- [ ] AC5. `raw_transcript` keeps the original words. `AudioAnswer.normalized_by` is `"rules"`,
  `"llm"` or `None`. It and `llm_confidence` survive a confirmation (`state.pending` → `_accept`), a
  snapshot/resume round trip and `wrap_voice`.
- [ ] AC6. With `llm_refine` in effect, every spoken free-form answer of the field triggers exactly
  one `RefineValue`. Auto-accept requires LLM confidence ≥ `llm_refine_threshold`, a passing
  re-normalization, and no other confirmation gate firing. On failure, timeout or no client, the
  rules candidate is used. The turn is never lost.
- [ ] AC7. Sensitive fields never reach the LLM. Their values and transcripts are never echoed
  (S8 unchanged).
- [ ] AC8. `llm_refine_values` defaults to `False`. With every new setting at its default and no new
  protocol field sent, only the deterministic post-processor changes behaviour.
- [ ] AC9. `Lexicon.cardinals`/`ordinals` are unchanged. Option matching tests pass unmodified.
- [ ] AC10. Relative dates resolve in `start_session.timezone`. An absent or invalid timezone means
  UTC, and relative phrases then go to confirmation. Numeric dates use `date_order` (en MDY,
  es DMY).
- [ ] AC11. No new third-party dependency in `packages/parrot-formdesigner/pyproject.toml`.
- [ ] AC12. All `-k audio` tests in the formdesigner suite pass, and `ruff check` is clean on the
  touched files.
- [ ] AC13. `docs/audio-form-voice-modes.md` and the navigator-svelte handoff document the new
  fields, settings and error code.
- [ ] AC14. `llm_refine` never runs on TEXT/TEXT_AREA (or any type outside the typed families).
- [ ] AC15. Every non-sensitive spoken answer in a submission carries `normalized_by` (and
  `llm_confidence` when the LLM produced it) in its envelope, for all field types; pre-FEAT-653
  envelopes still validate.
- [ ] AC16. The calibration run has been executed on the real corpus. Its report is committed under
  `sdd/state/FEAT-653/calibration/`, and the shipped defaults of `llm_refine_threshold`,
  `llm_refine_timeout_s` and `stt_confirm_threshold` equal the report's recommendation (or the
  deviation is justified in the report).

---

## 6. Codebase Contract

`P` = `packages/parrot-formdesigner/src/parrot_formdesigner`. Verified on `d180783c5` (dev, FEAT-649 merged).

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType                              # P/core/types.py:16
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig, field_voice_meta, is_sensitive  # P/core/voice.py:35,50,84,72
from parrot_formdesigner.audio.narration.lexicon import Lexicon, load_lexicon, normalize  # P/audio/narration/lexicon.py:23,96,79
from parrot_formdesigner.services.validators import EMAIL_PATTERN, PHONE_PATTERN  # P/services/validators.py:56,58 — imported alongside audio.engine without a cycle (checked)
from parrot_formdesigner.audio.models import OptionMatch, Phase, AudioAnswer, AudioSessionState  # P/audio/models.py:59,43,214,258
from zoneinfo import ZoneInfo                                                     # stdlib
from parrot.voice.transcriber.backend import AbstractTranscriberBackend           # packages/ai-parrot-integrations/src/parrot/voice/transcriber/backend.py:18 (M11 only)
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend  # .../faster_whisper_backend.py:21 (M11 only)
```

### Existing Class Signatures
```python
# P/audio/engine.py
_ANSWERING_PHASES = (Phase.ASKING, Phase.CONFIRMING)                     # :88
class AudioFormSession:                                                  # :101
    def __init__(self, *, form, manifest, cfg: VoiceFormConfig, narrator, lexicon: Lexicon,
                 state: AudioSessionState, llm_cfg) -> None: ...         # :104-113
    self._handlers = {..., "_plausibility_done": self.on_plausibility_done}  # :155
    def handle(self, event) -> list[Outbound]: ...                       # :158 (never awaits)
    def on_start(self, ev: StartSession) -> list[Outbound]: ...          # :169 (sets state.locale)
    def on_transcript(self, ev: TranscriptReady) -> list[Outbound]: ...  # :348
    #   :383 option path; :400-404 command classification; :426-441 free-form (raw ev.text; low-confidence confirm)
    def _request_confirm(self, evidence, value, transcript, matched, alternatives) -> list[Outbound]: ...  # :442
    def _accept(self, field_id, value, *, source, confidence=None, raw=None, matched=None, evidence=None): ...  # :464
    def on_text(self, ev: AnswerText) -> list[Outbound]: ...             # :523 (stores ev.value as-is)
    def on_confirm(self, ev: ConfirmAnswer) -> list[Outbound]: ...       # :566 (accepts pending.value)
    def _resume(self, ev: StartSession) -> list[Outbound]: ...           # :1048; :1083 locale from ev; :1085 pending=None; :1090 phase=PLANNING

# P/audio/events.py
class StartSession(_Inbound): ... locale="en", protocol_version=1, ..., enumerate_options  # :93-106
class AnswerText(_Inbound): type, field_id, value: str = ""             # :109
class ConfirmAnswer(_Inbound): type, field_id="", confirmed=False       # :128 (no value)
class TranscriptReady(_Inbound): field_id, text, language, confidence, audio_mime, audio_bytes_len, duration_ms  # :173
class PlausibilityDone(_Inbound)                                        # :202 (internal feedback pattern)
InboundEvent = Annotated[Union[...], ...]                               # :250
class _Wire(BaseModel): to_wire() → model_dump(exclude_none=True)       # :281
class ConfirmRequest(_Wire): field_id, transcript, confidence, matched, alternatives, purpose  # :334
class AnswerRejected(_Wire): field_id, error, code                      # :353
class _IORequest(BaseModel)                                             # :451
class RunPlausibility(_IORequest)                                       # :486 (I/O request pattern)
IORequest = Union[Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan]  # :525
def is_io_request(item) -> bool                                         # :529

# P/audio/models.py
class Phase(str, Enum): IDLE … CONFIRMING … ABORTED                     # :43 (NOT extended by this spec)
class OptionMatch: method: Literal["exact","ordinal","yes_no","numeric","contains","fuzzy","llm"]  # :59,64
class AudioAnswer(BaseModel): extra="forbid"; … raw_transcript, stt_language (:253), version  # :214
class AudioSessionState(BaseModel): extra="forbid"; … locale="en" (:313), flagged (:317)  # :258

# P/core/voice.py
class FieldVoiceMeta: extra="ignore"; prompt … confirm: Literal["auto","always","never"]="auto" (:42) … sensitive (:48)  # :35
class VoiceFormConfig: … stt_confirm_threshold=0.6 (:58) … llm_refine_options=False (:64, unused) …  # :50

# P/audio/narration/lexicon.py
class Lexicon(BaseModel): locale, ordinals, cardinals, yes, no, all, none, conjunctions, fillers, commands, review_confirm, review_change(:37)  # :23
def _strip_text(text) -> str                                             # :71
def load_lexicon(locale) -> Lexicon  (lru_cache; builds via _list/_map)   # :96; review_change=_list(...) :123

# P/audio/option_matcher.py:83-92  _number_tokens uses lexicon.ordinals / lexicon.cardinals for option positions
# P/audio/option_refiner.py:18 RefinedOption, :33 LLMOptionRefiner(client, *, timeout_s=5.0) — ask(prompt, structured_output=...) pattern

# P/services/validators.py
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")   # :56
PHONE_PATTERN = re.compile(r"^\+?[\d\s\-().]{7,}$")                               # :58
FormValidator._coerce_value: NUMBER/INTEGER float()/int() (:709-716); DATE/DATETIME/TIME str().strip(), no format check (:723)
FormValidator._validate_by_type: EMAIL/PHONE pattern checks (:950-960)

# P/api/audio_ws.py
deps: dict[str, Any] = {"form", "manifest", "cfg", "narrator", "lexicon", "state", "llm_cfg"}  # :652-660
async def _perform_one(self, ws, ctx, item) -> InboundEvent | None   # :750; Transcribe row :780
def _encode(self, ctx, msg) -> dict                                   # :846; v1 confirm_request pops matched/alternatives :874
_V2_ONLY_TYPES = frozenset(...)                                       # :156
async def _do_transcribe(...)                                         # :970 (language=None for "en", :987 — out of scope)
def _checker_for(self, form, *, session_id="")                        # :1019 (per-session cache pattern, uses self._llm_client_getter)
# P/api/handlers.py:198 _get_llm_client() — what routes pass as llm_client_getter
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `normalize_spoken` | `AudioFormSession.on_transcript` free-form block | call | `P/audio/engine.py:426` |
| `validate_typed` | `AudioFormSession.on_text` | call | `P/audio/engine.py:523` |
| `on_value_refined` | `_handlers` | `"_value_refined"` key | `P/audio/engine.py:155` |
| `RefineValue` | `AudioFormWSHandler._perform_one` | new isinstance row | `P/api/audio_ws.py:780` |
| `LLMValueRefiner` | `llm_client_getter` | as `_checker_for` | `P/api/audio_ws.py:1019-1023` |
| `StartSession.timezone` | `AudioSessionState.timezone` | adapter + `on_start`/`_resume` | `P/audio/engine.py:169,1083` |

### Does NOT Exist (Anti-Hallucination)
- ~~`email_validator` in parrot-formdesigner~~: not a dependency of this distribution. Use `EMAIL_PATTERN`.
- ~~`dateparser`, `python-dateutil`, `word2number`, `text2num`, `num2words`, `phonenumbers`~~: in no package.
- ~~`FieldType.TEL`~~: it is `PHONE`.
- ~~`ConfirmAnswer.value` / an "edited confirm" message~~: corrections arrive as `answer_text`.
- ~~`ConfirmRequest.value`~~, ~~`AnswerRejected.value`~~ (added by M5), ~~`INVALID_VALUE`~~ error code (new), ~~`StartSession.timezone`~~ (M5), ~~`AudioSessionState.timezone`~~ (M5).
- ~~`Phase.REFINING`~~: deliberately not added. The in-flight refine is private engine state.
- ~~A wired `LLMOptionRefiner`~~: the class exists, and `llm_refine_options` exists, but nothing calls either.
- ~~Typed parsing of free-form transcripts~~: today raw text is stored for every type.
- ~~Cardinals above 10 in the lexicon~~ (and they must stay that way, AC9).
- ~~A clock dependency on `AudioFormSession`~~ (added by M7).

### Edit Sites (Blueprint Anchors)

Verified against: `d180783c5`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `P/audio/normalize/__init__.py`, `base.py`, `numbers.py`, `email.py`, `phone.py`, `temporal.py` | CREATE | — | — | — |
| `P/audio/value_refiner.py` | CREATE | — | — | — |
| `P/audio/narration/lexicon.py` | MODIFY | `    review_change: list[str] = Field(default_factory=list)` | `lexicon.py:37` | 1 |
| `P/audio/narration/lexicon.py` | MODIFY | `        review_change=_list("review_change"),` | `lexicon.py:123` | 1 |
| `P/audio/narration/templates/en/narration.yaml` | MODIFY | `  cardinals: {one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10}` | `:37` | 1 |
| `P/audio/narration/templates/es/narration.yaml` | MODIFY | `  cardinals: {uno: 1, una: 1, dos: 2, …, diez: 10}` | `:37` | 1 |
| `P/core/voice.py` | MODIFY | `    sensitive: bool = False` | `voice.py:48` | 1 |
| `P/core/voice.py` | MODIFY | `    llm_refine_options: bool = False` | `voice.py:64` | 1 |
| `P/audio/events.py` | MODIFY | `class StartSession(_Inbound):` | `events.py:93` | 1 |
| `P/audio/events.py` | MODIFY | `class ConfirmRequest(_Wire):` | `events.py:334` | 1 |
| `P/audio/events.py` | MODIFY | `class PlausibilityDone(_Inbound):` | `events.py:202` | 1 |
| `P/audio/events.py` | MODIFY | `class RunPlausibility(_IORequest):` | `events.py:486` | 1 |
| `P/audio/events.py` | MODIFY | `IORequest = Union[Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan]` | `events.py:525` | 1 |
| `P/audio/models.py` | MODIFY | `    stt_language: Optional[str] = None` | `models.py:253` | 1 |
| `P/audio/models.py` | MODIFY | `    flagged: dict[str, int] = Field(default_factory=dict)` | `models.py:317` | 1 |
| `P/audio/engine.py` | MODIFY | `        # Free-form answer` | `engine.py:426` | 1 |
| `P/audio/engine.py` | MODIFY | `    def on_text(self, ev: AnswerText) -> list[Outbound]:` | `engine.py:523` | 1 |
| `P/audio/engine.py` | MODIFY | `            "_plausibility_done": self.on_plausibility_done,` | `engine.py:155` | 1 |
| `P/audio/engine.py` | MODIFY | `        self.state.locale = ev.locale` (on_start) — 2 occurrences, the second is in `_resume` (`:1083`); quote `self.state.protocol_version = ev.protocol_version` below each | `engine.py:175,1083` | 2 |
| `P/api/audio_ws.py` | MODIFY | `            "llm_cfg": form.llm_validation,` | `audio_ws.py:659` | 1 |
| `P/api/audio_ws.py` | MODIFY | `        if isinstance(item, Transcribe):` | `audio_ws.py:780` | 1 |
| `P/api/audio_ws.py` | MODIFY | `        elif mtype == "confirm_request":` | `audio_ws.py:874` | 1 |
| `docs/audio-form-voice-modes.md` | MODIFY | (section anchors chosen at task time) | — | — |
| `P/core/voice_answer.py` | MODIFY | `    plausibility: PlausibilityVerdict \| None = None` | `voice_answer.py:52` | 1 |
| `P/core/voice_answer.py` | MODIFY | `            language=getattr(answer, "stt_language", None),` | `voice_answer.py:96` | 1 |
| `P/services/validators.py` | MODIFY | `    _EVIDENCE_KEYS = frozenset({"source", "confidence", "audio_mime", "duration_ms", "language", "plausibility"})` | `validators.py:580` | 1 |
| `packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Normalizers are **pure, sync, never raise**. Any internal error gives `status="rejected", reason="no_parse"`
  plus a `logger.debug`. The engine stays "never awaits" (`engine.py:158`).
- Tokenization is normalizer-specific. `lexicon.normalize()` strips `@ . , / : - +`, so it must not
  be used before email, phone or date parsing. Lexicon *phrases* are still pre-folded with
  `_strip_text`.
- Number grammar:
  - units, then tens, then tens+unit ("fifty five");
  - "hundred" multiplies the running group, and "thousand"/"million" close it;
  - joiners are ignored between number words;
  - a decimal word followed by a digit sequence; a minus word prefix;
  - written digits with grouping (`^\d{1,3}(,\d{3})+$` for `.`-decimal locales);
  - written decimals use the locale's `decimal_separator`.

  A sequence of separate numbers (Whisper's "0,4,12" style, or "five or six") is *several* numbers.
  NUMBER treats that as `multiple_values`; PHONE and EMAIL concatenate the parts.
- Dates:
  - Month-name forms in either order, with an optional year. A missing year means the current year
    in the client tz.
  - Written `M/D[/Y]` or `D/M[/Y]` per `date_order`. A two-digit year means 20YY. ISO `YYYY-MM-DD`
    is accepted in every locale.
  - `relative_days`. Bare weekday, `this <weekday>` and `next <weekday>` all mean **the nearest
    occurrence after today** (strictly > today; said on a Friday, "Friday" / "next Friday" is
    today + 7) — decision §8 Q1. `last <weekday>` means the nearest occurrence before today. All of
    them are `accepted` when the timezone is known.
- Times: `H[:MM]` with am/pm words, `H o'clock`, spoken "three thirty pm", noon, midnight,
  "half past" / "y media", and 24-hour written `HH:MM`.
- **LLM prompt contract** (`LLMValueRefiner`):
  - Input: the field type, the field label, locale, timezone, today's date (ISO), the transcript,
    the rules candidate, and the canonical format required (from the §2 table).
  - Output: `RefinedValue{value, confidence}` via `structured_output`. `null` means "cannot tell".
  - The value is always re-normalized by the engine. The LLM never bypasses validation.
  - The label is sent; answer values of *other* fields are not sent.
- Per-session refiner cache keyed by `session_id`, popped in the WS `finally` like `_checkers`
  (`audio_ws.py:398`).
- Logging: `self.logger`. Never log the transcript or value of a sensitive field.

### Known Risks / Gotchas
- **Latency**: with `llm_refine` on, each spoken answer waits up to `llm_refine_timeout_s`
  (default 4 s). This is why it is opt-in and per field. The receive loop is serial, so later
  inbound frames queue behind the refine; that is acceptable, since the client waits for
  `answer_accepted` / `confirm_request` anyway.
- **"Always on" LLM can rewrite correct values**: mitigated by re-normalization plus the confidence
  threshold, and by never running on free TEXT/TEXT_AREA (§8 Q3). `normalized_by="llm"`,
  `llm_confidence` and `raw_transcript` keep the audit trail.
- **Behaviour change of `confirm: "never"`**: a `confirm`-status candidate now confirms anyway, and a
  `rejected` one is re-asked instead of stored (AC3).
  Document this.
- **Whisper language misdetection** (out-of-scope defect 5): an English answer transcribed as
  Spanish words defeats the `en` tables, so the result goes to confirmation. The STT spec fixes the
  input.
- **Snapshots**: `AudioAnswer` is `extra="forbid"`, and snapshots dump answers. The new
  `normalized_by` has a default, so old snapshots load. Do not add required fields.
- **Envelope**: `VoiceEvidenceEnvelope` is `extra="forbid"` (inherited from `VoiceAnswerEnvelope`,
  `core/voice_answer.py:33`). The two new keys must be optional with a `None` default so stored
  pre-FEAT-653 envelopes and CSV/GSheet JSON strings still validate. JSONB sinks (migrations
  009/010) need no DDL change. Sensitive answers are never wrapped (S8), so they carry no evidence.
- **Calibration depends on STT confidence**: the 0.6 `stt_confirm_threshold` is calibrated against
  today's `info.language_probability` (`faster_whisper_backend.py:165`). When the out-of-scope STT
  spec switches to a transcript-based confidence, the run must be repeated. The harness is built to
  be re-runnable for exactly that reason.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | None. `zoneinfo` and `re` are stdlib; `AbstractClient` is already used through `llm_client_getter` |

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-653. The `sdd-coder` engine gives each task its own
  sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (reads `Lexicon.spoken`)
  - M3 → M2 (`tokenize`, `parse_numbers`)
  - M4 → M2 (`parse_numbers`)
  - M6 → M5 (`FieldType`, `RefinedValue` lives in M6, so the edge is weak; it runs in parallel with
    M2–M4)
  - M7 → M2, M3, M4, M5
  - M8 → M5, M6, M7
  - M9 → M7, M8
  - M10 → M5 (`AudioAnswer.normalized_by` / `llm_confidence`); the engine (M7) sets them
  - M11 → M2, M3, M4, M6 (runs the real normalizers and refiner); it is `parallel: false` because it
    needs the corpus, a real LLM (`PARROT_TEST_REAL_LLM=1`) and the STT model, and it writes the
    defaults back into M5's `core/voice.py`

  M1, M5 and M6 have no mutual edges, and neither do M3 and M4, so both groups run concurrently.
- **Shared files**: `core/voice.py` (M5 adds the settings, M11 may change their defaults; serialized).
  Otherwise `engine.py` is only M7, `events.py`/`models.py` only M5, `audio_ws.py` only M8,
  `voice_answer.py`/`validators.py` only M10.
- **Exclusive resources**: M11's calibration run (real LLM calls under a request budget, the local
  faster-whisper model, the recordings corpus).
- **Cross-feature dependencies**: FEAT-649 is merged. The future session-lock and STT specs from
  the same brainstorm also modify `api/audio_ws.py` and `audio/events.py`. Land them sequentially
  after this one, or rebase.

---

## 8. Open Questions

- [x] Q1. Meaning of "next <weekday>" — *Resolved 2026-10-12 (Jesús)*: always the nearest occurrence
  after today. Bare, `this` and `next` weekday phrases resolve the same way (§7). They are not
  confirmed when the timezone is known.
- [x] Q2. Persist `normalized_by` (and the LLM confidence) in the voice evidence envelope? —
  *Resolved 2026-10-12 (Jesús)*: yes, on all fields (M10, AC15).
- [x] Q3. Allow `llm_refine` on TEXT/TEXT_AREA? — *Resolved 2026-10-12 (Jesús)*: no. Only the typed
  families (AC14).
- [x] Q4. Calibrate the defaults (`llm_refine_threshold` 0.8, `llm_refine_timeout_s` 4 s,
  `stt_confirm_threshold` 0.6) — *Resolved 2026-10-12 (Jesús)*: yes, run a calibration (M11, AC16).
- [x] Q5. Release order — *Resolved 2026-10-12 (Jesús)*: everything ships together with the FEAT-649
  release.
- [x] Q6. Date grammar scope and numeric order (carried from the brainstorm) — *Resolved 2026-10-12
  (Jesús)*: order per locale, `en` M/D, `es` D/M, via `SpokenLexicon.date_order`. A numeric date
  valid in both orders with no way to disambiguate goes to confirmation.
- [x] Q7. When does the LLM post-processor run? — *Resolved 2026-10-12 (Jesús)*: on every spoken
  free-form answer of a typed-family field where it is enabled (opt-in), after the rules. It
  auto-accepts at or above `llm_refine_threshold`.
- [ ] Q8. Calibration corpus: who exports the FieldSync recordings plus their confirmed values, and
  for which locales (en only, or en + es)? — *Owner: Emmanuel / Juan*
- Brainstorm questions on marker TTL/heartbeat, `SESSION_REPLACED` close code and transcript
  confidence calibration belong to the out-of-scope session-lock / STT specs. They are not carried
  here.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the brainstorm (normalization scope) plus the
> owner's decisions of 2026-10-12. It never saw this spec. Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-653/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Typed normalization outputs and statuses (api) | CONFIRM | A plain `ok` flag let "yes" store a value the submit gate rejects; replaced with `accepted`/`confirm`/`rejected` and a reject path | §2 Overview + matrix, Data Models, AC3 |
| S2 | Propagate and validate timezone (architecture) | CONFIRM | Already designed (`StartSession.timezone`, `AudioSessionState.timezone`, `ZoneInfo`, `timezone_known`); the "persist in snapshot" part is rejected because resume receives a fresh `start_session` | M5, M7, M8 |
| S3 | Dedicated token grammar, not `normalize()` (architecture) | CONFIRM | Already designed: separate `Lexicon.spoken`, `cardinals` untouched, per-normalizer tokenizer | M1, M2, §7 |
| S4 | Make `email-validator` a direct dependency (risk) | REJECT | A second validator would disagree with the submit gate's `EMAIL_PATTERN` (`services/validators.py:56`), so a voice-accepted email could still fail at submit; the gate's regex stays the single source of truth. The typed `INVALID_EMAIL` part was already in scope | — |
| S5 | Canonical representations per family (api) | CONFIRM | Already in the §2 table; DATETIME keeps the naive local `YYYY-MM-DDTHH:MM` (offset part rejected: it matches HTML `datetime-local`, and the validator leaves temporal strings unparsed) | §2 table |
| S6 | LLM through the engine's I/O protocol (architecture) | CONFIRM | Already designed (`RefineValue` / `ValueRefined` with `request_id`, adapter timeout) | M5, M7, M8 |
| S7 | Separate refine config, not `LLMValidationConfig` (architecture) | CONFIRM | Already separate (`VoiceFormConfig.llm_refine_*`, `FieldVoiceMeta.llm_refine`, `REFINABLE_TYPES`). A per-feature model setting is rejected: it reuses `llm_client_getter` like plausibility | M5, M7 |
| S8 | Provenance through every representation (risk) | CONFIRM | Gap found: `_accept` rebuilds the `AudioAnswer`, so provenance would be lost across a confirmation. `_accept` now takes `normalized_by`/`llm_confidence`, stamped on `state.pending` | §2 step 6, M7, AC5 |
| S9 | Precedence between STT, normalization and LLM (risk) | CONFIRM | Explicit decision matrix; the LLM never overrides the STT rule or `confirm: "always"` | §2 matrix, AC3 |
| S10 | Phone normalization vs. final validation (risk) | CONFIRM | Already aligned with `PHONE_PATTERN`; short numbers are now `rejected`, not confirmable | §2 table |
| S11 | Layered test matrix + wire assertions (testing) | CONFIRM | Added matrix, provenance-round-trip, timezone-validation and stale-reply tests | §4 |

Summary: **10** confirmed (S2, S3, S5, S6, S7, S10 were already in the draft; S1, S8, S9, S11
changed it) · **1** rejected (S4) · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-12 | Jesus Lara | Initial draft: defects 2–4 of the voice follow-ups brainstorm, claims re-verified, optional LLM post-processor added |
| 0.2 | 2026-10-12 | Jesus Lara | Q1–Q5 resolved (nearest weekday, provenance in envelope, no LLM on TEXT, calibration module, ship with FEAT-649); codex design research folded in (three-way status + reject path, decision matrix, provenance through confirm); status approved |
