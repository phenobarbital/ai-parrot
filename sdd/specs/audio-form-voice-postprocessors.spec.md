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
**Status**: draft
**Target version**: next parrot-formdesigner release after FEAT-649

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
- G3. A result that is not certain goes to the existing confirm flow, carrying the normalized
  candidate. It is never stored silently and never stored as words.
- G4. Optional **LLM post-processor** (`llm_refine`): when enabled for a field, it runs on *every*
  spoken answer of that field, after the rules. Its value is accepted without confirmation only when
  all three hold:
  - its confidence is ≥ `llm_refine_threshold`;
  - its output passes the same deterministic normalizer/validator;
  - none of the existing confirmation gates fires.
- G5. Locale-driven: spoken-token tables live in the `en`/`es` narration YAML. English first (US
  product). Spanish keeps parity where its tables cover a phrase. A gap goes to confirmation, never
  to a wrong value.
- G6. Relative dates are resolved in the **client's IANA timezone**, sent in `start_session`.
- G7. Protocol changes are additive. v1 and v2 clients that send none of the new fields keep working.

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
carries the canonical `value`, `ok` (certain and valid) and a `reason` code when not ok.

The engine calls it on the **free-form speech path only** (`on_transcript`, after commands and
after the option path), then applies the gates in this order:

1. **Rules.** `det = normalize_spoken(...)`, unless `meta.voice.normalize` is false.
2. **Optional LLM refine.** It runs when `llm_refine` is in effect for the field and the field is not
   sensitive (S8: a sensitive value never leaves the process). The engine parks the answer and
   emits a `RefineValue` I/O request. The adapter awaits `LLMValueRefiner.refine(...)` with a
   timeout and feeds back `ValueRefined`. The LLM's string is **re-run through the same normalizer**:
   - If it comes out ok, it becomes the candidate (`normalized_by="llm"`).
   - Otherwise, or on failure, timeout or no client, the rules candidate stands.
3. **Gate.** Confirm when any of these holds:
   - the field's `confirm` is `"always"`;
   - the candidate is not ok (even with `confirm: "never"`, because an invalid value must never be
     stored silently);
   - the STT confidence is below `stt_confirm_threshold` and `confirm` is not `"never"` (unchanged
     rule);
   - the candidate came from the LLM with confidence below `llm_refine_threshold`.

   Otherwise accept.
4. **Confirm.** `ConfirmRequest` carries `transcript` (the words, masked if sensitive) plus the new
   `value` (the normalized candidate, v2 only, omitted if sensitive) and `refined_by`. "Yes" stores
   the candidate. A typed correction (`answer_text`) is stored as typed. For EMAIL it is validated.
5. **Accept.** `AudioAnswer.value` is the canonical value. `raw_transcript` keeps the words for
   audit (already true). The new `AudioAnswer.normalized_by` records `"rules"`, `"llm"` or `None`.

Canonical output per type (what `FormValidator._coerce_value` / `_validate_by_type` accept):

| FieldType | Canonical value | `ok=False` when |
|---|---|---|
| EMAIL | lowercase `str` matching `EMAIL_PATTERN` | not exactly one `@`, or no `EMAIL_PATTERN` match |
| PHONE | `str`: optional leading `+`, then digits only | fails `PHONE_PATTERN` (fewer than 7 digits) |
| INTEGER | `int` | no number, several numbers, non-integral |
| NUMBER | `int` if integral, else `float` | no number, several numbers |
| DATE | `"YYYY-MM-DD"` | no parse; relative phrase without a valid timezone; `"next <weekday>"` (§8 Q1); numeric date valid in both orders (e.g. 3/4) |
| TIME | `"HH:MM"` (24 h) | no parse; hour 1–12 with no am/pm |
| DATETIME | `"YYYY-MM-DDTHH:MM"` (naive, client local, like HTML `datetime-local`) | either part not ok |
| anything else | — (`None`, pass-through) | — |

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
| `AudioFormWSHandler` (`api/audio_ws.py`) | modifies | Timezone, `RefineValue` handling, v1 encode, refiner from `llm_client_getter` |
| `LLMOptionRefiner` (`audio/option_refiner.py:33`) | pattern only | Same shape for `LLMValueRefiner` |

### Data Models
```python
# audio/normalize/base.py
class NormalizeResult(BaseModel):
    value: Any
    ok: bool
    reason: str | None = None          # "invalid_email" | "too_short" | "ambiguous" | "no_parse" | "needs_timezone" | "ambiguous_meridiem" | "non_integral" | "multiple_values"

@dataclass(frozen=True)
class NormalizeContext:
    lexicon: Lexicon                    # carries .spoken
    now: datetime                       # tz-aware, already converted to the client tz (UTC if unknown)
    timezone_known: bool                # False → relative date phrases are ok=False ("needs_timezone")

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
| M4: Temporal | no | Grammar is specified, but the relative-date edge rules (§8 Q1, year roll-over) need judgment | date semantics |
| M5: Config + protocol models | yes | Field names/types below; v1 drops new keys | — |
| M6: LLM value refiner | yes | Mirrors `LLMOptionRefiner`; prompt contract §7 | — |
| M7: Engine integration | no | Gate ordering and stale-refine handling are the design core | state machine |
| M8: WS adapter | yes | `_perform_one` row; timezone validation; refiner construction | — |
| M9: Docs | yes | Sections listed | — |

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
      """Exactly one number → int/float; 0 or >1 numbers → ok=False."""
  ```

### Module 3: Email + phone
- **Path**: `audio/normalize/email.py`, `audio/normalize/phone.py` (new)
- **Depends on**: M2 (`tokenize`, `parse_numbers`)
- **Interface Skeleton**:
  ```python
  from ...services.validators import EMAIL_PATTERN, PHONE_PATTERN   # verified: services/validators.py:56,58 (import checked cycle-free on d180783c5)
  def normalize_email(text: str, ctx: NormalizeContext) -> NormalizeResult:
      """Map email_symbols, join spelled letters, number words → digits, drop spaces, lowercase; ok iff EMAIL_PATTERN matches."""
  def normalize_phone(text: str, ctx: NormalizeContext) -> NormalizeResult:
      """Leading plus word/'+' kept; digit words, digit_aliases, repeat_words, compound tens ('fifty five'→'55'); every
      separator (space , . - ( )) dropped; ok iff PHONE_PATTERN matches."""
  ```

### Module 4: Temporal (DATE / TIME / DATETIME)
- **Path**: `audio/normalize/temporal.py` (new)
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  def normalize_date(text: str, ctx: NormalizeContext) -> NormalizeResult: ...
  def normalize_time(text: str, ctx: NormalizeContext) -> NormalizeResult: ...
  def normalize_datetime(text: str, ctx: NormalizeContext) -> NormalizeResult:
      """Split into a date phrase and a time phrase ('tomorrow at three pm'); ok iff both are ok."""
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
          """meta.llm_refine if not None else cfg.llm_refine_values; always False for sensitive fields."""
      def _gate(self, evidence: AudioAnswer, candidate: NormalizeResult, *, refined_by, llm_confidence) -> list[Outbound]:
          """Single confirm/accept decision (§2 step 3)."""
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
  - In `_encode`, v1 `confirm_request` pops `value` and `refined_by`.
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
  - Document `start_session.timezone`, `confirm_request.value` / `refined_by`, and `INVALID_EMAIL`.
  - Front note: show `value` (not `transcript`) as the editable candidate, and send `timezone`.

---

## 4. Test Specification

Tests live in `packages/parrot-formdesigner/tests/formdesigner/`. Run them with
`PYTHONPATH=packages/parrot-formdesigner/src`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_spoken_lexicon_loads_en_es` | M1 | `load_lexicon("en"/"es").spoken` populated; `cardinals` unchanged (1–10) |
| `test_number_words_and_digits` | M2 | "twenty five"→25, "two hundred and five"→205, "1,250"→1250, "three point five"→3.5, "minus four"→-4, "veinticinco"→25, es "1,5"→1.5 |
| `test_number_rejects_many_or_none` | M2 | "five or six" → ok=False `multiple_values`; "hello" → `no_parse`; INTEGER "3.5" → `non_integral` |
| `test_email_spoken_and_written` | M3 | "john dot smith at gmail dot com"→john.smith@gmail.com; "J O H N at gmail dot com"→john@gmail.com; "anne dash marie at x dot io"; "juan arroba gmail punto com" (es); "john at gmail" → ok=False |
| `test_phone_variants` | M3 | "0,4,12,523,573"→0412523573; "five five five oh one two three"→5550123; "double five"→55; "plus one 555 0100"→+15550100; "123" → ok=False `too_short`; output always matches PHONE_PATTERN when ok |
| `test_date_grammar` | M4 | today/tomorrow/yesterday; "March third"; "third of March 2027"; "3/12" en→03-12, es→12-03; "3/4" with both orders valid in a locale → ok=False `ambiguous`; "2026-03-12"; "next Friday" → ok=False (§8 Q1); relative without timezone → `needs_timezone` |
| `test_time_grammar` | M4 | "three thirty pm"→15:30; "noon"→12:00; "midnight"→00:00; "15:30"; "three thirty" → ok=False `ambiguous_meridiem` |
| `test_datetime_grammar` | M4 | "tomorrow at three pm" with a fixed clock + tz |
| `test_unhandled_type_passthrough` | M2 | TEXT/URL → `None` |
| `test_validate_typed_email` | M2 | invalid typed email → "INVALID_EMAIL"; other types → None |
| `test_llm_value_refiner_contract` | M6 | fake client returns `structured_output`; exception/garbage → None |
| `test_engine_freeform_normalizes` | M7 | PHONE transcript accepted as canonical; `raw_transcript` keeps words; `normalized_by="rules"` |
| `test_engine_not_ok_confirms_even_never` | M7 | invalid email with `confirm: never` → `ConfirmRequest(value=…)` |
| `test_engine_llm_refine_flow` | M7 | `RefineValue` emitted; `ValueRefined ok ≥ threshold` → accept (`normalized_by="llm"`); below threshold → confirm; LLM value failing re-normalization → rules candidate; `failed`/`unavailable` → rules candidate; stale request_id ignored |
| `test_engine_sensitive_never_refined` | M7 | sensitive field: rules applied, no `RefineValue`, confirm value omitted |
| `test_engine_typed_email_rejected` | M7 | `answer_text` invalid email → `AnswerRejected(code="INVALID_EMAIL")`; typed phone "0,4,12" stored as typed |
| `test_engine_timezone_on_resume` | M7 | resumed session takes `timezone` from the new `start_session` |

### Integration Tests
| Test | Description |
|---|---|
| `test_audio_ws_postprocess_v2` | v2 WS session: spoken phone/email/number/date stored canonically; the submission passes `FormValidator`; `confirm_request.value` present |
| `test_audio_ws_postprocess_v1_compat` | v1 client: `confirm_request` without `value`/`refined_by`; existing v1 fixtures unchanged |
| `test_audio_ws_llm_refine_timeout` | slow fake client → falls back to rules within `llm_refine_timeout_s` |

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
- [ ] AC3. An `ok=False` result always goes to `confirm_request`, even with `confirm: "never"`. No
  invalid or unparsed value is accepted silently.
- [ ] AC4. `confirm_request.value` carries the normalized candidate for v2 clients. It is omitted for
  sensitive fields and for v1 clients.
- [ ] AC5. `raw_transcript` keeps the original words. `AudioAnswer.normalized_by` is `"rules"`,
  `"llm"` or `None`.
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
- ~~`ConfirmRequest.value`~~ (added by M5), ~~`StartSession.timezone`~~ (M5), ~~`AudioSessionState.timezone`~~ (M5).
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

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Normalizers are **pure, sync, never raise**. Any internal error gives `ok=False, reason="no_parse"`
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
  - `relative_days`. Bare weekday or `this <weekday>` means the nearest occurrence ≥ today.
    `next <weekday>` is parsed (nearest occurrence > today) but is ok=False until §8 Q1 is decided.
    `last <weekday>` means the nearest occurrence < today.
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
  threshold. On TEXT/TEXT_AREA fields (no validator) an enabled LLM may change wording. The form
  author opts in per field; `normalized_by="llm"` and `raw_transcript` keep the audit trail.
- **Behaviour change of `confirm: "never"`**: an `ok=False` candidate now confirms anyway (AC3).
  Document this.
- **Whisper language misdetection** (out-of-scope defect 5): an English answer transcribed as
  Spanish words defeats the `en` tables, so the result goes to confirmation. The STT spec fixes the
  input.
- **Snapshots**: `AudioAnswer` is `extra="forbid"`, and snapshots dump answers. The new
  `normalized_by` has a default, so old snapshots load. Do not add required fields.
- **Envelope**: `normalized_by` is not added to the voice evidence envelope (`wrap_voice`,
  `core/voice_answer.py:77`), so it is not persisted with the submission (§8 Q2).

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

  M1, M5 and M6 have no mutual edges, and neither do M3 and M4, so both groups run concurrently.
- **Shared files**: none across modules. `engine.py` is only M7, `events.py`/`models.py`/`voice.py`
  only M5, `audio_ws.py` only M8.
- **Exclusive resources**: none (no migration, lockfile or extension rebuild).
- **Cross-feature dependencies**: FEAT-649 is merged. The future session-lock and STT specs from
  the same brainstorm also modify `api/audio_ws.py` and `audio/events.py`. Land them sequentially
  after this one, or rebase.

---

## 8. Open Questions

- [ ] Q1. Meaning of "next <weekday>" for US field reps: the nearest occurrence after today, or the
  occurrence in the following week? Until decided, it is parsed but always confirmed. — *Owner: Jesús*
- [ ] Q2. Should `normalized_by` (and the LLM confidence) be persisted in the voice evidence envelope
  for audit? — *Owner: Juan*
- [ ] Q3. Should `llm_refine` be allowed on TEXT/TEXT_AREA fields at all, or restricted to the typed
  families? The spec currently allows it per explicit field opt-in. — *Owner: Jesús*
- [ ] Q4. Default `llm_refine_threshold` 0.8 and `llm_refine_timeout_s` 4 s: calibrate on real
  field recordings. — *Owner: Emmanuel / Juan*
- [ ] Q5. Release order relative to the FieldSync PR blocked on the FEAT-649 release (carried from
  the brainstorm). — *Owner: Juan*
- [x] Q6. Date grammar scope and numeric order (carried from the brainstorm: "confirm that the
  US-only M/D order is right") — *Resolved 2026-10-12 (Jesús)*: order per locale, `en` M/D, `es`
  D/M, via `SpokenLexicon.date_order`. A numeric date valid in both orders and with no way to
  disambiguate goes to confirmation.
- [x] Q7. When does the LLM post-processor run? — *Resolved 2026-10-12 (Jesús)*: on every spoken
  free-form answer of a field where it is enabled (opt-in), after the rules. It auto-accepts above
  `llm_refine_threshold`.
- Brainstorm questions on marker TTL/heartbeat, `SESSION_REPLACED` close code and transcript
  confidence calibration belong to the out-of-scope session-lock / STT specs. They are not carried
  here.

---

## 9. Design Research Cross-Check

Status: skipped (brainstorm status is `exploration`, not `accepted`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-12 | Jesus Lara | Initial draft: defects 2–4 of the voice follow-ups brainstorm, claims re-verified, optional LLM post-processor added |
