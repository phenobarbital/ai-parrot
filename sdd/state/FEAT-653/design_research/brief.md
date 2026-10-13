<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
End-to-end testing of FEAT-649 (audio form workflow) hosted by FieldSync FEAT-701 and rendered by
navigator-svelte FEAT-700 surfaced five backend defects. The product is used in the United States,
in English, by field reps answering short forms by voice.

2. **Spoken emails are stored as words.** "john at gmail dot com" was stored as
   "en man 6321 arroyenme el punto con". The free-form path stores the raw transcript whatever the
   field type.
3. **Spoken phone numbers are stored with separators** ("0,4,12,523,573").
4. **Spoken numbers and dates are not parsed** ("twenty five", "next Friday").
5. **STT guesses the language.** With `locale == "en"` the handler passes `language=None`, so

### Constraints and goals
From the brainstorm (normalization scope only):

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

Decisions taken by the product owner after the brainstorm (requirements, scope of this feature):
- Scope is ONLY the spoken-value normalization (defects 2-4). The session lock and STT language/confidence defects are separate features.
- Optional LLM post-processor: a per-form / per-field opt-in step where an LLM client (through the project's AbstractClient) corrects what was heard. When enabled for a field it runs on EVERY spoken answer of that field, after the deterministic rules; its value is accepted without confirmation when its confidence reaches a configurable threshold. Restricted to the typed families (email, phone, number, date/time) — not allowed on free TEXT fields. Sensitive fields never go to the LLM.
- "next <weekday>" always means the nearest such weekday after today.
- Numeric dates: order per locale (en M/D, es D/M).
- Persist which post-processor produced the value (rules / llm) with every voice-answered field's stored evidence.
- Calibrate the LLM confidence threshold and timeout (and the existing 0.6 STT confirm threshold) with a calibration run.
- Ships together with the FEAT-649 release.

### Recommended option / probable scope
Option A (recommended in brainstorm) — normalization part:
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

Internal behavior (normalization part):
- **Protocol (additive):**
  - StartSession gains timezone: str | None (IANA).
  - New error code: INVALID_EMAIL if surfaced.
- **Engine:** the free-form speech path asks `normalize_spoken(field_type, text, lexicon, tz, now)`.
  - Unknown types pass through unchanged.
  - The result's `ok=False`, or the existing low-confidence rule, routes to `_request_confirm` with
    the normalized value. `raw_transcript` keeps the original words for audit.
  - Typed answers skip normalization. Email validation also runs on typed answers (`REQUIRED`-style
    `AnswerRejected` with a clear message).

Edge cases (normalization part):
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

### Verified code anchors (paths only — open them yourself)
packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/events.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/en/narration.yaml
packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/es/narration.yaml
packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_matcher.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_refiner.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
packages/parrot-formdesigner/pyproject.toml
packages/ai-parrot/pyproject.toml
packages/ai-parrot-integrations/src/parrot/voice/transcriber/faster_whisper_backend.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
