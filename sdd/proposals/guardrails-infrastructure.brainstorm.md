---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Unified Guardrails Infrastructure (Pluggable Input/Output Controls)

**Date**: 2026-07-24
**Author**: Jesús Lara (with Claude Code research)
**Status**: exploration
**Recommended Option**: A

> Candidate feature id: FEAT-396 (assigned at spec time; highest on dev is
> FEAT-395). Supersedes the *integration layers* of FEAT-324
> (`pii-detection-redaction`) and FEAT-398
> (`deterministic-groundedness-scoring`) — their engines are unchanged;
> their seam wiring becomes guardrail plugins of this infrastructure.

---

## Problem Statement

AI-Parrot has grown **five uncoordinated input/output control mechanisms**,
each with its own configuration style, seam, and semantics (all refs
verified on `dev` @ `58829cf9`):

1. **Prompt-injection check** — hardcoded into
   `AbstractBot._sanitize_question()` (`bots/abstract.py:1836-1942`),
   invoked from exactly 3 call sites in `BaseBot`
   (`bots/base.py:625, 997, 1641`). The only mechanism that can **block**
   (via `PromptInjectionException`). Configured through four explicit ctor
   params (`strict_mode`, `block_on_threat`, `injection_detection`,
   `injection_probability_threshold`, `bots/abstract.py:294-297`).
2. **`PromptPipeline`** (`bots/middleware.py`, 49 lines) — input-only
   string→string transforms, **cannot block**, **swallows exceptions**
   (`middleware.py:42-45`), defaults to `None` so most bots have none;
   only two registration sites in the whole tree (`bots/search.py:119`,
   `skills/mixin.py:178`).
3. **`OutputScrubber`** (secrets, FEAT-252) — policy-driven and genuinely
   pluggable, but wired ad-hoc at four seams (tool egress
   `tools/abstract.py:784-810`, channel egress `bots/base.py:1445` for
   only 4 chat modes, Google client `clients/google/client.py:~2533`,
   PythonREPL `tools/pythonrepl.py:599`), opt-in via a popped kwarg
   (`enable_redaction`, `bots/abstract.py:379`).
4. **Provider-native guardrails** — Bedrock `apply_guardrail_text()`
   (`clients/bedrock.py:444-469`); Google safety settings hardcoded to
   `BLOCK_NONE` (`clients/google/client.py:3085-3092`).
5. **Hand-rolled redactors** outside any policy — `scrub_git_output()`
   (`flows/dev_loop/nodes/base.py:39`), server-side `_redact()`
   (`ai-parrot-server .../handlers/agents/users.py:37`).

Meanwhile two spec'd features (FEAT-324 PII, FEAT-398 groundedness) are
about to add *more* per-feature seam wiring, and there is **no content
moderation at all**. Every new control repeats the same work: find the
seams, invent a config toggle, decide error semantics, wire telemetry.

**Goal**: one pluggable guardrails infrastructure in
`parrot/bots/guardrails/` — attach controls to the **input** or the
**output** (tool egress, final response, streaming) of any bot, with
uniform policy, ordering, blocking semantics, error contracts and audit —
so PII, groundedness, prompt-injection, moderation and future modes are
plugins of one abstraction instead of five parallel inventions.

## Constraints & Requirements

- **One abstraction, four stages**: `input` (user → LLM), `tool_output`
  (tool → LLM), `output` (LLM → caller), `output_stream` (chunked).
- **Verdict semantics richer than transform-only**: a guardrail must be
  able to PASS, TRANSFORM (rewrite content), FLAG (observe/annotate, never
  mutate), or BLOCK (abort with a controlled response) — today only the
  injection check can block, and the pipeline cannot.
- **Explicit error contract per guardrail**: fail-open (log + continue,
  today's scrubber behavior) or fail-closed (block on internal error) —
  the current `PromptPipeline` silently swallowing exceptions is not an
  acceptable base for security checks.
- **Deterministic ordering** (priority), per-bot registry, uniform config
  (Pydantic policy per guardrail + one bot-level `guardrails=[...]`),
  following the `enable_redaction` stamping precedent
  (`bots/abstract.py:379→390` → `tools/manager.py` → clients).
- **Latency discipline inherited from FEAT-324/325**: hot-path guardrails
  must be sub-10 ms; expensive checks (LLM/API moderation) must declare
  themselves and default to observe/async where possible.
- **Backwards compatible**: existing ctor flags (`strict_mode`,
  `block_on_threat`, `injection_detection`, `enable_redaction`) keep
  working, internally mapped to guardrail registrations; secrets scrubbing
  semantics unchanged.
- **Engines stay reusable**: analysis engines live in `parrot/security/`
  (injection detector, scrubber, future pii/groundedness engines);
  `parrot/bots/guardrails/` holds the abstraction and thin plugin wrappers
  — engines remain importable outside bots (handlers, flows, offline).

---

## Options Explored

### Option A: Native guardrails package — `Guardrail` ABC + per-stage pipelines in `parrot/bots/guardrails/`

New subpackage (structural sibling of `bots/mixins/`):

- `base.py`: `GuardrailStage` enum (INPUT, TOOL_OUTPUT, OUTPUT,
  OUTPUT_STREAM); `GuardrailAction` (PASS, TRANSFORM, FLAG, BLOCK);
  `GuardrailResult` (action, content, report, reason); abstract
  `Guardrail` (name, stages, priority, `on_error: fail_open|fail_closed`,
  `async check(content, ctx) -> GuardrailResult`).
- `pipeline.py`: `GuardrailPipeline` — priority-ordered, short-circuits on
  BLOCK, accumulates FLAG reports into `AIMessage.metadata["guardrails"]`,
  honors per-guardrail error contract, emits telemetry (guardrail name +
  action + duration, never content) via FEAT-176 observers.
- `registry.py` + `config.py`: named factories; bot kwarg
  `guardrails=[...]` (names, instances, or dicts) coerced per the existing
  structured-kwargs pattern; legacy flags mapped for compatibility.
- `streaming.py`: `StreamingGuardrail` adapter contract
  (`feed(chunk) -> str` / `flush()`), generalizing FEAT-324's sliding
  window so any transforming output guardrail can run on streams.
- Built-in plugins (thin wrappers over `parrot/security/` engines):
  `PromptInjectionGuardrail` (migrates `_sanitize_question` logic; INPUT;
  can BLOCK), `SecretsGuardrail` (wraps `OutputScrubber`; TOOL_OUTPUT +
  OUTPUT; TRANSFORM), `PIIGuardrail` + `PseudonymizeGuardrail` (FEAT-324
  engines), `GroundednessGuardrail` (FEAT-398 scorer; OUTPUT; FLAG-only),
  `ModerationGuardrail` (reference interface + stub backend — concrete
  backends are a follow-up).
- Seam integration replaces the ad-hoc wiring: the 3
  `_sanitize_question`/pipeline call sites in `BaseBot` run the INPUT
  pipeline; the FEAT-252 tool hook runs TOOL_OUTPUT; `get_response()` and
  `ask_stream` run OUTPUT/OUTPUT_STREAM.

✅ **Pros:**
- Closes all four verified gaps at once (no output chain, no block
  semantics in pipeline, no per-bot registry, split configuration).
- FEAT-324/325 integration layers become ~thin plugins instead of
  bespoke seam wiring — their specs shrink, their engines don't change.
- Moderation and future modes (jailbreak, topic filters, compliance) are
  additive: implement `Guardrail`, register, done.
- Generalizes the two best existing patterns (`ScrubPolicy`-style policy
  objects; `enable_redaction`-style per-bot propagation).
- Uniform audit/telemetry surface (name + action + counts, never values).

❌ **Cons:**
- Touches the three hottest methods in `BaseBot` (invoke/ask/ask_stream)
  — needs careful compat testing of the canned-response semantics
  (`bots/base.py:632, 1004, 1648`).
- Migration of `_sanitize_question` must preserve a subtle invariant: the
  sanitized text feeds only `prompt_for_llm`; the canonical `question`
  stays clean for memory/events/vector retrieval.
- One more abstraction to learn; risk of over-engineering if kept too
  generic (mitigated: four fixed stages, one result type).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib + Pydantic | abstraction, config | zero new deps |

🔗 **Existing Code to Reuse:**
- `security/prompt_injection.py:27` `PromptInjectionDetector` (+ shared
  singleton `bots/abstract.py:64-95`) — engine for the INPUT plugin.
- `security/redaction.py:128,149` `ScrubPolicy`/`OutputScrubber` — engine
  for `SecretsGuardrail`; its idempotency/audit patterns are the template.
- `bots/middleware.py` `PromptPipeline` — priority/ordering model to
  generalize (and then wrap as a legacy TRANSFORM guardrail).
- `enable_redaction` stamping chain (`bots/abstract.py:379→390`,
  `tools/manager.py:276,570,632,1425`) — config-propagation precedent.
- FEAT-176 observers — telemetry emission.
- FEAT-324/325 specs — plugin payloads (engines + policies already
  designed).

---

### Option B: Adopt an external guardrails framework (openai-guardrails-python style config)

Configure checks via a JSON/YAML "guardrails config" with named checks per
stage, executed by a generic runner (possibly vendoring parts of
`openai-guardrails-python`).

✅ **Pros:**
- Familiar config surface for users coming from OpenAI's ecosystem.
- Some checks come pre-built.

❌ **Cons:**
- The comparative analysis (FEAT-324 comparison doc) already showed the
  flagship checks are unusable in our hot paths: PII masks input-only,
  hallucination check is an LLM judge at P50 ~7 s; we would keep only the
  runner shape and rewrite every check anyway.
- External model deps (spaCy models, OpenAI API) at the security boundary;
  no streaming story; no per-agent policy model.
- Doesn't integrate with our seams, `AIMessage`, FEAT-176 telemetry, or
  the `enable_redaction` compat surface — the adapter *is* Option A.

📊 **Effort:** Medium-High (adapter + rewrites)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `openai-guardrails-python` | check runner/config | brings model deps |

🔗 **Existing Code to Reuse:** same seams as Option A.

---

### Option C: Incremental — extend `PromptPipeline` and add a symmetric `ResponsePipeline`

Keep string→string middlewares; add blocking by convention (raise from a
middleware); add an output twin; wire features one by one.

✅ **Pros:**
- Smallest diff; no new concepts.

❌ **Cons:**
- The middleware contract is the *problem*: exceptions swallowed
  (`middleware.py:42-45`), no verdicts, no FLAG/observe mode (groundedness
  needs non-mutating), no per-guardrail error contract, `None` by default.
- Blocking-by-exception from a chain that swallows exceptions is a
  security anti-pattern.
- Config remains scattered (ctor params + popped kwargs + pipeline
  registration in subclasses).

📊 **Effort:** Low (but re-paid on every future control)

📦 **Libraries / Tools:** none.

🔗 **Existing Code to Reuse:** `bots/middleware.py` as-is.

---

## Recommendation

**Option A** is recommended because:

- The exploration shows the fragmentation is structural, not incidental:
  five mechanisms, four config styles, one blocking path, zero output
  chain. Only a first-class abstraction closes that; Option C rebuilds on
  a contract (swallowed exceptions, transform-only) that disqualifies
  itself for security checks, and Option B converges to Option A after
  discarding checks we already proved unusable in the hot path.
- It is the cheapest path for the *in-flight* work: FEAT-324 and FEAT-398
  each planned bespoke seam wiring; as plugins they reuse one pipeline,
  one config surface, one telemetry stream — and their engines (the hard
  part, already prototyped and benchmarked) are untouched.
- Extensibility is the user's stated goal ("agregar moderation u otros
  modos"): `ModerationGuardrail` as a reference plugin proves the point
  without expanding scope.

Trade-off accepted: a migration of `_sanitize_question` and the tool-seam
hook with strict behavioral-compat tests, and the discipline to keep the
abstraction at exactly four stages and one result type.

---

## Feature Description

### User-Facing Behavior

- One bot-level configuration surface:
  `guardrails=[...]` accepting names (`"pii"`, `"prompt_injection"`,
  `"groundedness"`, `"secrets"`, `"moderation"`), configured dicts
  (`{"name": "pii", "policy": {...}}`), or `Guardrail` instances.
- Legacy flags keep working and map internally:
  `injection_detection/strict_mode/block_on_threat/…` →
  `PromptInjectionGuardrail`; `enable_redaction` → `SecretsGuardrail`.
- Blocked turns return the same canned-`AIMessage` shape used today by
  the injection path (metadata `error: guardrail_block`, guardrail name,
  reason category — never the offending content).
- FLAG-mode guardrails (groundedness; any check in `detect_only`) attach
  reports under `AIMessage.metadata["guardrails"][<name>]`.
- Custom guardrails: subclass `Guardrail`, implement `check()`, register
  by name or pass the instance.

### Internal Behavior

- `parrot/bots/guardrails/` — `base.py`, `pipeline.py`, `registry.py`,
  `config.py`, `streaming.py`, `builtin/` (one module per plugin).
- Bot wiring: `AbstractBot.__init__` builds four `GuardrailPipeline`s from
  config + legacy flags. `BaseBot.invoke/ask/ask_stream` replace the
  direct `_sanitize_question` + `PromptPipeline` calls with the INPUT
  pipeline (preserving the `prompt_for_llm` vs canonical-`question`
  invariant and the existing canned-response catch sites). The FEAT-252
  tool hook delegates to the TOOL_OUTPUT pipeline (secrets guardrail
  first, unconditional when `enable_redaction`). `get_response()` runs
  OUTPUT; `ask_stream` wraps chunks through registered
  `StreamingGuardrail`s and runs non-streaming OUTPUT guardrails on the
  final `AIMessage`.
- Ordering: fixed priority bands — sanitizers (secrets) → transformers
  (PII) → observers (groundedness) — overridable per guardrail.
- Telemetry: pipeline emits (guardrail, stage, action, duration_ms,
  counts) via FEAT-176 observers; content never leaves the process.
- `ModerationGuardrail`: policy model (`categories`, `threshold`,
  `action`), `ModerationBackend` protocol, one `StubBackend`
  (allow-all, logs shape) — concrete backends (OpenAI moderation API,
  local classifier, keyword lists) are explicit follow-ups.

### Edge Cases & Error Handling

- Guardrail exception → per-guardrail `on_error`: `fail_open` (warn,
  continue; default for observers/transformers) or `fail_closed` (BLOCK;
  default for injection/moderation in enforce mode).
- BLOCK short-circuits the remaining pipeline; already-applied TRANSFORMs
  are discarded in favor of the canned response.
- Streaming: only `StreamingGuardrail`-capable plugins run per-chunk;
  others run at stream close on the final text (FEAT-398 semantics).
- Empty pipeline == today's behavior; zero overhead when nothing is
  registered (guard on `has_guardrails`, mirroring `has_middlewares`).
- Double-wrapping protection: pipeline stamps processed content
  (idempotency, `_already_scrubbed` precedent).

---

## Capabilities

### New Capabilities
- `guardrails-core`: stages, verdicts, `Guardrail` ABC, pipelines,
  registry, config coercion, telemetry.
- `guardrails-input-migration`: `PromptInjectionGuardrail` +
  `_sanitize_question`/`PromptPipeline` migration with behavioral compat.
- `guardrails-output-plugins`: `SecretsGuardrail` (wraps FEAT-252 seams),
  hooks in `get_response`/`ask_stream`, `StreamingGuardrail` contract.
- `guardrails-moderation-reference`: `ModerationGuardrail` interface +
  stub backend.

### Modified Capabilities
- `pii-detection-redaction` (FEAT-324): Modules 1/3/4 integration layer
  re-targeted to guardrail plugins (`PIIGuardrail`,
  `PseudonymizeGuardrail`, streaming via `StreamingGuardrail`); engines
  (`parrot/security/pii/`, `pii-rs`) unchanged.
- `deterministic-groundedness-scoring` (FEAT-398): Module 3 reporting
  becomes `GroundednessGuardrail` (FLAG-only); engine unchanged.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/guardrails/` | new | the infrastructure |
| `bots/base.py:625,997,1641` (+ catches `:632,1004,1648`) | modifies | INPUT pipeline replaces direct `_sanitize_question` + `PromptPipeline` calls; canned responses preserved |
| `bots/abstract.py` (`__init__`, `_sanitize_question`, `:365,379,661-664,672-685`) | modifies | pipeline construction; legacy-flag mapping; `_sanitize_question` body moves into the plugin |
| `tools/abstract.py:784-810` | modifies | hook delegates to TOOL_OUTPUT pipeline (secrets semantics unchanged) |
| `bots/middleware.py` | deprecates | kept working; wrapped as legacy TRANSFORM guardrail; the two registration sites (`bots/search.py:119`, `skills/mixin.py:178`) migrate |
| `bots/base.py:1445` channel egress scrub | modifies | folds into OUTPUT pipeline (all modes, not just 4 chat modes) |
| `security/` package | unchanged | engines stay; export surface intact |
| FEAT-324 / FEAT-398 specs | modified | v-bump: integration sections re-targeted (see Modified Capabilities) |
| Provider guardrails (Bedrock/Google) | unchanged | out of scope; potential future `ProviderGuardrail` wrapper noted |

No breaking changes: defaults preserve today's behavior exactly.

---

## Code Context

### User-Provided Code

(none — requirement provided as prose)

### Verified Codebase References

All verified on branch base `origin/dev` @ `58829cf9`; paths relative to
`packages/ai-parrot/src/parrot/`.

#### Classes & Signatures
```python
# security/prompt_injection.py
class ThreatLevel: ...                    # :10
class PromptInjectionException: ...       # :19
class PromptInjectionDetector: ...        # :27  (regex engine; pytector optional)
class SecurityEventLogger: ...            # :222

# bots/abstract.py
_SHARED_INJECTION_DETECTOR / _get_shared_injection_detector()  # :64-95 (:78)
# ctor params: strict_mode=True (:294), block_on_threat=False (:295),
#   injection_detection=True (:296), injection_probability_threshold=0.98 (:297)
#   assigned :661-664; detector/logger wiring :672-685
self._prompt_pipeline = None              # :365 (property/setter :715-720)
self.enable_redaction = bool(kwargs.pop('enable_redaction', False))  # :379 → :390
def _sanitize_question(...)               # :1836-1942; _wrap_flagged_input :1944

# bots/base.py — the three input call sites + canned-response catches:
#   invoke :625/:632, ask :997/:1004, ask_stream :1641/:1648
# invariant: sanitized text → prompt_for_llm only; canonical question stays clean
# PromptPipeline runs after sanitize: :641, :1017, :1657
# channel egress scrub singleton :61, applied :1445 (4 chat modes only)

# bots/middleware.py (49 lines)
class PromptMiddleware: ...               # :8  (priority :11, apply :17)
class PromptPipeline: ...                 # :23 (add :30, apply :37 — swallows exceptions :42-45)

# tools/abstract.py
# FEAT-252 hook :784-810, gated `if self.enable_redaction:` (:784);
# _default_scrubber :63; tool attr enable_redaction :155

# security/redaction.py
class ScrubPolicy: ...                    # :128 (frozen dataclass)
class OutputScrubber: ...                 # :149; _already_scrubbed :122
```

#### Verified Imports
```python
from parrot.security.prompt_injection import PromptInjectionDetector  # security/__init__.py exports :8-55
from parrot.security.redaction import OutputScrubber, ScrubPolicy
from parrot.bots.middleware import PromptPipeline, PromptMiddleware
```

#### Key Attributes & Constants
- `bots/` structure: `mixins/` is the closest sibling for `guardrails/`;
  `bots/__init__.py` exports only bot classes.
- Config-propagation precedent: `enable_redaction` stamping
  (`tools/manager.py:276,570-571,632-633,1425-1426`; client stamping
  `bots/abstract.py:937,956`).
- `flows/dev_loop/nodes/base.py:39` `scrub_git_output()` — hand-rolled
  redactor worth folding into `SecretsGuardrail` later.

### Does NOT Exist (Anti-Hallucination)
- ~~Anything named `guardrail*` in the repo~~ — `find -iname` is empty
  (Bedrock/Nova provider params aside: `clients/bedrock.py:79-80,444`).
- ~~An output/response transform chain~~ — `PromptPipeline` is input-only.
- ~~Blocking semantics in `PromptPipeline`~~ — transforms only; exceptions
  swallowed (`middleware.py:42-45`).
- ~~Content-moderation API/code~~ — all `moderate` hits are
  `SecurityLevel.MODERATE` in command/python sanitizers; no toxicity or
  content_filter anywhere.
- ~~`parrot.security.pii` / `parrot.security.groundedness`~~ — FEAT-324/
  325 are specs, not implemented; this feature defines the sockets their
  plugins will fill.
- ~~Server-side usage of the security stack~~ — handlers' `guardian` is
  navigator-auth authn/authz, unrelated.

---

## Parallelism Assessment

- **Internal parallelism**: medium — `guardrails-core` first (blocks
  everything); then input-migration ∥ output-plugins in separate
  worktrees (disjoint seams: `bots/base.py` input sites vs tool hook +
  `get_response`); moderation-reference after core only.
- **Cross-feature independence**: FEAT-324/325 implementations should
  build *on top of* this feature (their specs get v-bumped to plugins);
  implementing them first would create the bespoke wiring this feature
  removes.
- **Recommended isolation**: mixed (core sequential, then two parallel
  worktrees).
- **Rationale**: the abstraction is small but load-bearing; the two
  migrations touch disjoint files once core is frozen.

---

## Open Questions

- [x] Where do engines vs guardrails live? — *Resolved (session default,
  confirm in review)*: engines in `parrot/security/` (reusable outside
  bots), abstraction + plugins in `parrot/bots/guardrails/`.
- [x] Fate of FEAT-324/325 specs — *Resolved (session default)*: v-bump
  as plugins of this infrastructure; engines and acceptance criteria
  unchanged.
- [x] Moderation scope — *Resolved (session default)*: interface +
  reference stub in this feature; concrete backends are follow-ups.
- [ ] Should `SecretsGuardrail` become *unconditional* (like FEAT-252
  intended) instead of `enable_redaction` opt-in, now that ordering is
  explicit? — *Owner: Jesús*
- [ ] Deprecation horizon for `PromptPipeline` and the four legacy
  injection ctor params (keep mapped indefinitely vs warn in 0.27)? —
  *Owner: Jesús*
- [ ] Should the channel-egress scrub extension (all output modes, not 4)
  ship here or as a follow-up? — *Owner: Jesús*
- [ ] `ProviderGuardrail` wrapper for Bedrock/Google native guardrails —
  in-scope later? — *Owner: Jesús*
- [ ] Handler-level (server package) guardrail execution for non-bot
  egress — follow-up feature? — *Owner: Jesús*
