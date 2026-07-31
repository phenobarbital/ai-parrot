---
type: feature
base_branch: dev
---

# Feature Specification: Unified Guardrails Infrastructure

**Feature ID**: FEAT-396
**Date**: 2026-07-24
**Author**: Jesús Lara (spec drafted with Claude Code)
**Status**: draft
**Target version**: 0.27.0

> Source brainstorm: `sdd/proposals/guardrails-infrastructure.brainstorm.md`
> (Recommended Option A). Plugin features: FEAT-324
> (`pii-detection-redaction`, v0.4) and FEAT-325
> (`deterministic-groundedness-scoring`, v0.2) deliver their integration
> layers as plugins of this infrastructure; their engines are unchanged.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has five uncoordinated input/output control mechanisms (verified
on `dev` @ `58829cf9`): the hardcoded prompt-injection check in
`AbstractBot._sanitize_question()` (the only one that can block), the
input-only `PromptPipeline` (cannot block, swallows exceptions), the
`OutputScrubber` wired ad-hoc at four seams behind `enable_redaction`,
provider-native guardrails (Bedrock; Google safety pinned to BLOCK_NONE),
and hand-rolled redactors in flows and the server package. There is no
output guardrail chain, no per-bot registry of pluggable checks, no
uniform blocking/error semantics, and no content moderation at all — and
two spec'd features (PII, groundedness) were about to add yet more
bespoke seam wiring.

This feature centralizes all of it: a pluggable guardrails infrastructure
in `parrot/bots/guardrails/` where controls attach to the input or output
of any bot and PII, groundedness, prompt-injection, secrets and future
modes (moderation, jailbreak, topic filters) are plugins of one
abstraction.

### Goals

- One `Guardrail` abstraction with four stages — INPUT, TOOL_OUTPUT,
  OUTPUT, OUTPUT_STREAM — and four verdicts — PASS, TRANSFORM, FLAG,
  BLOCK.
- Per-stage, priority-ordered `GuardrailPipeline` with BLOCK
  short-circuit, per-guardrail error contract (`fail_open`/`fail_closed`),
  idempotency stamping, and uniform telemetry (name + action + duration +
  counts, never content) via FEAT-176 observers.
- One bot-level config surface (`guardrails=[...]`) with a named registry;
  legacy flags (`injection_detection`, `strict_mode`, `block_on_threat`,
  `injection_probability_threshold`, `enable_redaction`) keep working,
  mapped internally.
- Built-in plugins: `PromptInjectionGuardrail` (migrates
  `_sanitize_question`), `SecretsGuardrail` (wraps `OutputScrubber`),
  sockets for FEAT-324 (`PIIGuardrail`/`PseudonymizeGuardrail`) and
  FEAT-325 (`GroundednessGuardrail`), `ModerationGuardrail` reference
  interface + stub backend.
- `StreamingGuardrail` adapter contract (`feed`/`flush`) so transforming
  output guardrails can run on `ask_stream` chunks.
- Zero behavior change with default configuration; zero new runtime deps.

### Non-Goals (explicitly out of scope)

- Concrete moderation backends (OpenAI moderation API, local classifiers,
  keyword lists) — follow-ups behind the `ModerationBackend` protocol.
- Implementing the FEAT-324/FEAT-325 engines — separate features; this
  spec defines the sockets their plugins fill.
- Wrapping provider-native guardrails (Bedrock `apply_guardrail_text`,
  Google safety settings) — noted as a possible future `ProviderGuardrail`.
- Server-package (handler-level) guardrail execution for non-bot egress.
- Removing `PromptPipeline` — deprecated but kept working (wrapped as a
  legacy TRANSFORM guardrail); removal horizon is an open question.

---

## 2. Architectural Design

### Overview

`parrot/bots/guardrails/` (structural sibling of `bots/mixins/`) defines:

- **`GuardrailStage`**: INPUT (user text before LLM), TOOL_OUTPUT
  (ToolResult egress), OUTPUT (final answer), OUTPUT_STREAM (chunks).
- **`GuardrailResult`**: `action` ∈ {PASS, TRANSFORM, FLAG, BLOCK} +
  `content` (TRANSFORM), `report` (FLAG, attached to
  `AIMessage.metadata["guardrails"][<name>]`), `reason` (BLOCK — a
  category label, never the offending content).
- **`Guardrail` ABC**: `name`, `stages`, `priority` (fixed default bands:
  sanitizers 0–99 → transformers 100–199 → observers 200+), `on_error`
  (`fail_open` default for transformers/observers; `fail_closed` default
  for enforce-mode injection/moderation), `async check(content, ctx) →
  GuardrailResult`. `ctx` carries agent_name/user_id/session_id/stage/
  method plus stage-specific extras (tool_name; the outgoing `AIMessage`
  at OUTPUT).
- **`GuardrailPipeline`**: ordered execution; BLOCK short-circuits and
  discards prior TRANSFORMs in favor of the canned response; FLAG reports
  accumulate; exceptions honor `on_error`; every run emits telemetry;
  processed-content stamping prevents double transformation (the
  `_already_scrubbed` precedent, `security/redaction.py:122`).
- **Registry/config**: named factories (`"prompt_injection"`, `"secrets"`,
  `"pii"`, `"pseudonymize"`, `"groundedness"`, `"moderation"`); bot kwarg
  `guardrails=[...]` accepting names, `{"name": ..., "policy": {...}}`
  dicts, or `Guardrail` instances — coerced like other structured bot
  configs. Legacy flags map to registrations at `__init__` time.

**Seam integration** replaces the ad-hoc wiring:

- The three `_sanitize_question` call sites + catches in `BaseBot`
  (`bots/base.py:625/632, 997/1004, 1641/1648`) and the pipeline runs at
  `:641/:1017/:1657` collapse into one INPUT-pipeline invocation each,
  preserving two invariants exactly: (1) sanitized/transformed text binds
  only to `prompt_for_llm` — the canonical `question` stays clean for
  memory/events/vector retrieval; (2) BLOCK produces the same canned
  `AIMessage`/string shapes the injection path produces today.
- The FEAT-252 tool hook (`tools/abstract.py:784-810`) delegates to the
  TOOL_OUTPUT pipeline; `SecretsGuardrail` keeps identical semantics and
  ordering (secrets always first).
- `get_response()` (`bots/abstract.py`, non-streaming funnel) runs OUTPUT;
  `ask_stream` wraps chunk yields through registered `StreamingGuardrail`s
  and runs remaining OUTPUT guardrails on the final `AIMessage`. The
  channel-egress scrub (`bots/base.py:1445`, 4 chat modes only) folds into
  the OUTPUT pipeline for all modes.
- Empty pipelines short-circuit (`has_guardrails`, mirroring
  `has_middlewares`) — zero overhead when nothing is registered.

### Component Diagram

```
                       ┌──────────── AbstractBot.__init__ ────────────┐
 guardrails=[...] ────►│ registry + legacy-flag mapping               │
 legacy flags ────────►│  → 4 × GuardrailPipeline (per stage)         │
                       └───────┬───────────┬───────────┬──────────────┘
        user input             │           │           │
BaseBot.invoke/ask/ask_stream  ▼           │           │
        ── INPUT ──► [PromptInjection, Moderation, legacy PromptPipeline]
                               │           ▼           │
AbstractTool.execute() ─ TOOL_OUTPUT ─► [Secrets, PII, Pseudonymize]
                               │                       ▼
get_response()/stream close ── OUTPUT ─► [Secrets, PII, Moderation,
                               │                       Groundedness(FLAG)]
ask_stream chunk loop ── OUTPUT_STREAM ─► [StreamingGuardrail adapters]
                               │
                    BLOCK → canned AIMessage        FLAG → metadata["guardrails"]
                    telemetry → FEAT-176 observers (name+action+counts only)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `bots/base.py:625/632, 997/1004, 1641/1648` (+ `:641/:1017/:1657`) | modifies | INPUT pipeline replaces `_sanitize_question` + `PromptPipeline` calls; canned responses and `prompt_for_llm` invariant preserved |
| `bots/abstract.py` `__init__` (`:294-297, :365, :379, :661-664, :672-685`) | modifies | pipeline construction + legacy-flag mapping; detector singletons reused |
| `bots/abstract.py` `_sanitize_question` (`:1836-1942`) | migrates | body moves into `PromptInjectionGuardrail`; method kept as thin delegate for compat |
| `tools/abstract.py:784-810` | modifies | hook delegates to TOOL_OUTPUT pipeline; `enable_redaction` semantics unchanged |
| `bots/base.py:1445` channel-egress scrub | folds in | OUTPUT pipeline, all output modes |
| `bots/middleware.py` + registration sites (`bots/search.py:119`, `skills/mixin.py:178`) | deprecates | wrapped as legacy TRANSFORM guardrail; sites migrated |
| `security/` engines (`prompt_injection.py:27`, `redaction.py:128,149`) | uses | unchanged; plugins are thin wrappers |
| FEAT-176 observers | uses | uniform telemetry |
| FEAT-324 / FEAT-325 | provides sockets | their plugins register here (spec v0.4 / v0.2) |

No breaking changes: with no `guardrails` kwarg and default legacy flags,
behavior is bit-identical to today.

### Data Models

```python
# parrot/bots/guardrails/base.py — design signatures
class GuardrailStage(str, Enum):
    INPUT = "input"; TOOL_OUTPUT = "tool_output"
    OUTPUT = "output"; OUTPUT_STREAM = "output_stream"

class GuardrailAction(str, Enum):
    PASS = "pass"; TRANSFORM = "transform"; FLAG = "flag"; BLOCK = "block"

class GuardrailResult(BaseModel):
    action: GuardrailAction
    content: Optional[str] = None          # TRANSFORM
    report: Optional[dict] = None          # FLAG
    reason: Optional[str] = None           # BLOCK (category, never content)

class GuardrailContext(BaseModel):
    stage: GuardrailStage
    agent_name: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    method: str = ""                       # invoke | ask | ask_stream
    tool_name: Optional[str] = None        # TOOL_OUTPUT only
    extras: dict = {}

class Guardrail(ABC):
    name: str
    stages: set[GuardrailStage]
    priority: int                          # bands: 0-99 sanitize, 100-199 transform, 200+ observe
    on_error: Literal["fail_open", "fail_closed"]
    @abstractmethod
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult: ...

# parrot/bots/guardrails/streaming.py
class StreamingGuardrail(ABC):
    def feed(self, chunk: str) -> str: ...   # "" while withholding
    def flush(self) -> str: ...
```

### New Public Interfaces

```python
# parrot/bots/guardrails/pipeline.py
class GuardrailPipeline:
    def add(self, guardrail: Guardrail) -> None: ...
    @property
    def has_guardrails(self) -> bool: ...
    async def run(self, content: str, ctx: GuardrailContext) -> "PipelineOutcome":
        """PipelineOutcome: final content, blocked flag + reason, flag reports."""

# parrot/bots/guardrails/registry.py
def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None: ...
def build_guardrails(spec: list[str | dict | Guardrail]) -> list[Guardrail]: ...

# Built-ins (parrot/bots/guardrails/builtin/)
class PromptInjectionGuardrail(Guardrail): ...   # INPUT; can BLOCK; wraps shared detector
class SecretsGuardrail(Guardrail): ...           # TOOL_OUTPUT+OUTPUT; TRANSFORM; wraps OutputScrubber
class ModerationGuardrail(Guardrail): ...        # INPUT+OUTPUT; policy: categories/threshold/action
class ModerationBackend(Protocol):
    async def classify(self, text: str) -> dict[str, float]: ...
class StubModerationBackend: ...                 # allow-all reference backend
```

New bot kwarg: `guardrails: list[str | dict | Guardrail] | None = None`.

---

## 3. Module Breakdown

### Module 1: guardrails-core
- **Path**: `parrot/bots/guardrails/` (`base.py`, `pipeline.py`,
  `registry.py`, `config.py`, `streaming.py`, `__init__.py`)
- **Responsibility**: stages, verdicts, ABC, context, pipeline (ordering,
  BLOCK short-circuit, error contract, idempotency stamping, telemetry),
  registry + config coercion, `StreamingGuardrail` contract. No bot
  wiring yet.
- **Depends on**: nothing new.

### Module 2: guardrails-input-migration
- **Path**: `builtin/prompt_injection.py` + wiring in `bots/abstract.py`
  and the three `BaseBot` input sites
- **Responsibility**: `PromptInjectionGuardrail` encapsulating the
  `_sanitize_question` flow (trusted-source bypass, framework-pattern
  strip, pytector/native detection, `SecurityEventLogger`,
  block-vs-`_wrap_flagged_input` mitigation); legacy ctor-flag mapping;
  `PromptPipeline` wrapped as legacy TRANSFORM guardrail and its two
  registration sites migrated; behavioral-compat test suite.
- **Depends on**: Module 1.

### Module 3: guardrails-output-plugins
- **Path**: `builtin/secrets.py` + wiring in `tools/abstract.py` hook,
  `get_response()`, `ask_stream`, channel egress
- **Responsibility**: `SecretsGuardrail` (identical scrub semantics,
  always-first ordering); TOOL_OUTPUT/OUTPUT/OUTPUT_STREAM pipeline
  execution at the seams; sockets documented for FEAT-324/325 plugins.
- **Depends on**: Module 1. Parallel with Module 2 (disjoint files).

### Module 4: guardrails-moderation-reference
- **Path**: `builtin/moderation.py`
- **Responsibility**: `ModerationPolicy` (categories, threshold, action
  flag|block), `ModerationBackend` protocol, `StubModerationBackend`,
  docs marking concrete backends as follow-ups.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pipeline_ordering` | M1 | Priority bands honored; stable order within band |
| `test_pipeline_block_shortcircuit` | M1 | BLOCK stops the chain and discards prior TRANSFORMs |
| `test_pipeline_error_contract` | M1 | `fail_open` → warn+continue; `fail_closed` → BLOCK |
| `test_pipeline_flag_accumulation` | M1 | Multiple FLAG reports land under distinct names |
| `test_pipeline_idempotency` | M1 | Re-running on stamped content is a no-op |
| `test_registry_config_coercion` | M1 | names / dicts / instances / invalid name → clear error |
| `test_zero_overhead_empty` | M1 | `has_guardrails` False → no pipeline invocation |
| `test_injection_guardrail_compat` | M2 | For each of invoke/ask/ask_stream: same canned response, same `threats_detected` metadata, same `prompt_for_llm`-only rewriting as the legacy path (golden tests against current behavior) |
| `test_legacy_flag_mapping` | M2 | The four ctor flags + `enable_redaction` produce equivalent registrations; defaults → bit-identical behavior |
| `test_prompt_pipeline_wrapped` | M2 | Existing middlewares (competitor, skill-trigger) still apply via the legacy wrapper |
| `test_secrets_guardrail_compat` | M3 | Tool-seam scrub results identical to direct `OutputScrubber` for the FEAT-252 corpus; scrub failure non-fatal |
| `test_output_stage_all_modes` | M3 | Channel-egress scrub now applies beyond the 4 chat modes |
| `test_streaming_adapter` | M3 | `StreamingGuardrail.feed/flush` invariant: concatenated == non-streaming transform |
| `test_moderation_stub` | M4 | Policy threshold/action logic against stub scores; flag vs block |

### Integration Tests

| Test | Description |
|---|---|
| `test_ask_end_to_end_guardrails` | Bot with injection+secrets+custom FLAG guardrail: blocked input → canned AIMessage; clean input → transforms applied, reports in `metadata["guardrails"]` |
| `test_ask_stream_end_to_end` | Streaming: chunk transforms via adapter, OUTPUT observers at close |
| `test_default_config_regression` | Full existing bot test-suite subset passes with zero guardrails config (bit-identical behavior) |

### Performance

| Benchmark | Gate |
|---|---|
| Pipeline overhead, 3 no-op guardrails, 1 KB content | p99 < 0.5 ms |
| Empty-pipeline path | no measurable overhead vs baseline |

### Test Data / Fixtures

```python
@pytest.fixture
def golden_injection_cases():  # captured from current _sanitize_question behavior
    ...
@pytest.fixture
def stub_guardrails():  # PASS/TRANSFORM/FLAG/BLOCK/raise stand-ins
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests pass (`pytest tests/ -v`).
- [ ] **Compat invariant**: with no `guardrails` kwarg and default legacy
      flags, bot behavior is bit-identical (golden tests for the three
      injection call sites, tool-seam scrubbing, canned responses).
- [ ] The four legacy injection ctor params and `enable_redaction` work
      unchanged, mapped to guardrail registrations.
- [ ] A custom `Guardrail` subclass can be attached per bot via
      `guardrails=[...]` at any stage, with all four verdicts honored.
- [ ] BLOCK produces the existing canned-`AIMessage`/string shapes and
      never leaks the offending content; FLAG reports appear under
      `AIMessage.metadata["guardrails"]`.
- [ ] Per-guardrail `on_error` enforced; a raising `fail_open` guardrail
      cannot break a turn; a raising `fail_closed` one blocks it.
- [ ] `PromptPipeline` middlewares keep working via the legacy wrapper;
      both existing registration sites migrated.
- [ ] Telemetry emits guardrail name/stage/action/duration/counts and
      never content, via existing FEAT-176 observers.
- [ ] `ModerationGuardrail` interface + stub backend ship with docs
      marking backends as follow-ups.
- [ ] FEAT-324/325 sockets documented (registry names reserved:
      `pii`, `pseudonymize`, `groundedness`).
- [ ] Pipeline-overhead benchmark gate met; empty pipeline adds no
      measurable overhead.
- [ ] Zero new runtime dependencies; no breaking changes to public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified on branch base `origin/dev` @ `58829cf9` (2026-07-24).
> Paths relative to `packages/ai-parrot/src/parrot/`.

### Verified Imports

```python
from parrot.security.prompt_injection import (
    PromptInjectionDetector,      # security/prompt_injection.py:27
    PromptInjectionException,     # :19
    SecurityEventLogger,          # :222
)
from parrot.security.redaction import OutputScrubber, ScrubPolicy  # :149 / :128
from parrot.bots.middleware import PromptPipeline, PromptMiddleware  # bots/middleware.py:23 / :8
```

### Existing Class Signatures

```python
# bots/abstract.py
_get_shared_injection_detector()          # :78 (singleton block :64-95)
# ctor params strict_mode/block_on_threat/injection_detection/threshold  # :294-297 → :661-664
self._framework_sanitizer / self._injection_detector / self._security_logger  # :672-685
self._prompt_pipeline = None              # :365 (property :715-720)
self.enable_redaction = bool(kwargs.pop('enable_redaction', False))  # :379 → :390
def _sanitize_question(...)               # :1836-1942 ; _wrap_flagged_input :1944
# trusted-source bypass :1862; gate :1864; strip :1879; pytector :1884;
# native sanitize :1904; log :1911; raise-if-block :1927; soft-wrap :1937

# bots/base.py — input sites and catches (invariant: prompt_for_llm only):
#   invoke :625/:632 · ask :997/:1004 · ask_stream :1641/:1648
# PromptPipeline runs at :641/:1017/:1657 (ask_stream passes method:'ask' — known
#   inconsistency near :1663, fix in migration)
# channel-egress scrub singleton :61, applied :1445 (TELEGRAM/MSTEAMS/SLACK/WHATSAPP only)

# bots/middleware.py (49 lines)
class PromptMiddleware  # :8 — priority :11 (lower first), apply :17
class PromptPipeline    # :23 — add :30, apply :37, exceptions swallowed :42-45, has_middlewares :48

# tools/abstract.py
# FEAT-252 hook :784-810 gated `if self.enable_redaction:` (:784); error path :856-858
# _default_scrubber :63; tool attr enable_redaction :155

# security/redaction.py
class ScrubPolicy  # :128 (frozen); OutputScrubber :149; _already_scrubbed :122

# enable_redaction stamping chain (config-propagation precedent):
#   bots/abstract.py:379 → :390 → tools/manager.py:276,570-571,632-633,1425-1426
#   → client stamping bots/abstract.py:937,956
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| INPUT pipeline | 3 `BaseBot` call sites + catches | replaces `_sanitize_question` + `PromptPipeline` calls | `bots/base.py:625/632,997/1004,1641/1648` |
| `PromptInjectionGuardrail` | shared detector + logger | reuses singletons | `bots/abstract.py:78,672-685` |
| TOOL_OUTPUT pipeline | FEAT-252 hook | delegation | `tools/abstract.py:784-810` |
| `SecretsGuardrail` | `OutputScrubber` | wrap | `security/redaction.py:149` |
| OUTPUT pipeline | `get_response()` / stream close / channel egress | seam calls | `bots/abstract.py` funnel; `bots/base.py:1445,1846` |
| telemetry | FEAT-176 observers | emit | `core/events/lifecycle/` |

### Does NOT Exist (Anti-Hallucination)

- ~~Anything named `guardrail*` in the repo~~ (provider params in
  `clients/bedrock.py:79-80,444` aside).
- ~~An output/response transform chain~~ — `PromptPipeline` is input-only.
- ~~Blocking or error-propagation semantics in `PromptPipeline`~~ —
  transforms only; exceptions swallowed (`middleware.py:42-45`).
- ~~Content-moderation code~~ — all `moderate` hits are
  `SecurityLevel.MODERATE` in command/python sanitizers.
- ~~`parrot.security.pii` / `parrot.security.groundedness`~~ — FEAT-324/
  325 are specs; this feature only reserves their registry names.
- ~~Server-package usage of the security stack~~ — handlers' `guardian`
  is navigator-auth authn/authz.
- ~~`AIMessage.guardrails` field~~ — reports live inside the existing
  `metadata` dict.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic for results/context/policies; Google docstrings; strict type
  hints; `self.logger`.
- Async-first: `check()` is async (moderation backends will await I/O);
  hot built-ins (secrets) do CPU work synchronously inside.
- Generalize, don't reinvent: `ScrubPolicy`-style policy objects; the
  `enable_redaction` stamping chain for propagation; `_already_scrubbed`
  for idempotency; FEAT-176 for telemetry.
- Migration discipline: golden tests captured **before** touching
  `_sanitize_question`; the `prompt_for_llm` vs canonical-`question`
  invariant is the highest-risk compat point.
- Fix the `ask_stream` context `method:'ask'` copy-paste (near
  `bots/base.py:1663`) as part of the migration.

### Known Risks / Gotchas

- Touches the three hottest `BaseBot` methods — mitigate with the
  default-config regression suite and empty-pipeline zero-overhead gate.
- Two skills packages exist (`parrot/skills/` and `parrot/memory/skills/`)
  with middleware in both; migrate the live registration site
  (`skills/mixin.py:178`) and leave the duplicate for a cleanup feature.
- Ordering matters for correctness: secrets must transform before PII
  (never scan already-`***REDACTED***` text) and observers must run last
  on final content — encoded in the default priority bands.
- `fail_closed` on a misconfigured guardrail can block every turn —
  registry validates configs eagerly at bot construction, not first use.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | none — stdlib + Pydantic already in core |

---

## Worktree Strategy

- **Default isolation unit**: mixed — Module 1 first (sequential; the
  abstraction is load-bearing); then Module 2 ∥ Module 3 in separate
  worktrees (disjoint seams: input sites vs tool hook/output funnel);
  Module 4 after Module 1 (small, independent).
- **Cross-feature dependencies**: FEAT-324/325 implementations depend on
  this feature's Modules 1+3 (their sockets); schedule them after.

---

## 8. Open Questions

> Carried forward from the brainstorm; session-default resolutions are
> reflected in the body and flagged for review.

- [x] Engines vs guardrails placement — *Resolved (session default)*:
  engines in `parrot/security/`, abstraction + plugins in
  `parrot/bots/guardrails/` (§2, §6).
- [x] FEAT-324/325 fate — *Resolved (session default)*: v-bumped as
  plugins (v0.4 / v0.2); engines unchanged.
- [x] Moderation scope — *Resolved (session default)*: interface + stub
  here; backends are follow-ups (§1 Non-Goals, §3 Module 4).
- [ ] Should `SecretsGuardrail` become unconditional instead of
  `enable_redaction` opt-in, now that ordering is explicit? —
  *Owner: Jesús*
- [ ] Deprecation horizon for `PromptPipeline` and the four legacy
  injection ctor params (mapped indefinitely vs DeprecationWarning in
  0.27)? — *Owner: Jesús*
- [ ] Channel-egress extension to all output modes: ship here (current
  plan, §2) or split out if compat risk emerges? — *Owner: Jesús*
- [ ] `ProviderGuardrail` wrapper for Bedrock/Google native guardrails —
  later feature? — *Owner: Jesús*
- [ ] Handler-level (server package) guardrail execution — later
  feature? — *Owner: Jesús*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-24 | Jesús Lara / Claude Code | Initial draft from `guardrails-infrastructure.brainstorm.md` (Option A) |
