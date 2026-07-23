---
type: feature
base_branch: dev
---

# Feature Specification: Deterministic Groundedness Scoring (Anti-Hallucination, Detection-Only)

**Feature ID**: FEAT-325
**Date**: 2026-07-22
**Author**: Jesús Lara (spec drafted with Claude Code)
**Status**: draft
**Target version**: 0.26.0

> Source brainstorm: `sdd/proposals/deterministic-groundedness-scoring.brainstorm.md`
> (Recommended Option A, prototype-validated). Companion feature: FEAT-324
> (`sdd/specs/pii-detection-redaction.spec.md`) — shares seams and, later,
> extraction machinery; neither depends on the other to ship.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Agents compose their final answer *from* tool outputs — and sometimes invent
or corrupt the very facts those tools returned: a transposed revenue figure,
a ticket id that never existed, a date shifted by a month. Today AI-Parrot
has no way to notice. The OpenAI Guardrails "Hallucination Detection" check
solves this with an **LLM judge + FileSearch over an OpenAI vector store**
(gpt-4.1-mini default, ROC AUC 0.876; **P50 ~7 s / P95 ~43 s per check**,
extra API cost, a vector store to maintain, degraded accuracy beyond ~11 MB,
non-deterministic verdicts). That profile cannot run in the hot path — and
it verifies against a *static* knowledge base, when the freshest ground
truth for a turn is already in hand: **the turn's own tool outputs**.

This feature adds a deterministic groundedness *scorer*: extract verifiable
hard-data atoms from the agent's final answer, check each against the same
atoms extracted from the turn's tool results, and emit a report. Detection
only — no redaction, no blocking, no enforcement of any kind.

### Goals

- Score every final answer against the turn's tool outputs
  (`AIMessage.tool_calls[].result`) — per-atom verdicts
  `supported` / `contradicted` / `unsupported` plus an aggregate score.
- **Deterministic**: same answer + same evidence → same report. No LLM, no
  model download, no network call.
- Latency far under the 1000 ms budget: gate p99 < 10 ms per turn
  (prototype measured 2.4 ms for a 1 KB answer vs 3×2 KB of evidence,
  including index build).
- Scoring-only contract: the response text is **never** modified; the
  report rides `AIMessage.metadata` and telemetry.
- Per-agent opt-in via the established kwargs/policy convention; zero new
  runtime dependencies (stdlib extractors).
- Precision-aware numeric tolerance as the normative comparison rule
  (resolved by prototype — see §2).

### Non-Goals (explicitly out of scope)

- Semantic/paraphrase hallucinations and claims without hard data — the
  scorer flags them with `no_factual_content`, it does not judge them.
- General truth verification: the report says "these atoms are unsupported
  by this turn's evidence", never "this answer is true/false".
- Any enforcement action (mask, block, re-ask). Consumers decide.
- An in-line LLM judge (rejected as brainstorm Option B for the hot path:
  seconds of latency, per-turn cost, non-determinism, circular trust). A
  future *offline* judge is complementary, not part of this feature.
- N-gram / quoted-span overlap scoring (brainstorm Option C) — a possible
  future extractor kind; noisy on paraphrase and blind to single-digit
  corruption, the highest-value failure here.

---

## 2. Architectural Design

### Overview

A new `parrot/security/groundedness/` subpackage (sibling to the planned
FEAT-324 `pii/`) implements a three-stage, stdlib-only pipeline:

1. **Extract** (`extractors.py` + `normalize.py`): pull hard-data atoms —
   `money`, `percent`, `number` (formatted/large numerics), `date`,
   `identifier` (emails, URLs, ticket/SKU-style codes) — from text, with
   span de-overlap (a money hit is not re-counted as a bare number).
   Normalization folds formats: `$1.24M` ≡ `1 240 000`; multi-format dates
   → ISO-8601; identifiers case-folded; NFKC Unicode pre-pass.
2. **Index** (`evidence.py`): build a per-turn `EvidenceIndex` from every
   `ToolCall.result` on the outgoing `AIMessage` (values traversed
   recursively for dict/list results) — an exact hash-set per atom kind
   plus a numeric list for tolerance checks. Bounded by
   `max_evidence_bytes` (report flags `evidence_truncated`).
3. **Score** (`scorer.py`): classify each answer atom —
   - `supported`: exact normalized match, **or** numeric match within the
     **precision-aware tolerance**: half a unit of the answer's last
     *stated* significant digit. A fully written `$1,234,500` (7 sig
     digits) demands exact equality; a rounded `$1.24M` (3 sig digits)
     tolerates ±0.5%. *Normative rule — a fixed 2% tolerance was tested
     and rejected: it swallowed digit transpositions (0.72% delta).*
   - `contradicted`: same-magnitude numeric (≤15% off an evidence value)
     outside the stated precision — the classic transposed/corrupted-digit
     signal, the strongest hallucination indicator.
   - `unsupported`: no trace in evidence (invented id, email, figure).

   `score = supported / total_atoms`; no atoms → score 1.0 with
   `no_factual_content: true`; no tool calls → `no_evidence: true`.

**Reporting** (never mutating): the `GroundednessReport` is attached to
`AIMessage.metadata["groundedness"]` and a summary (score + per-verdict
counts, **never atom values**) is emitted through the existing FEAT-176
lifecycle observers. The single seam is end-of-turn — `get_response()` for
non-streaming and the final `AIMessage` of `ask_stream` (groundedness is a
whole-answer property; no per-chunk work). When FEAT-324 lands, scoring
runs *after* the PII pass so answer and evidence are scrubbed by the same
catalog and placeholders match on both sides.

Failure contract mirrors the FEAT-252 scrubbers: any scorer exception logs
a warning and the response ships without a report — never breaks the turn.

### Component Diagram

```
                    ┌────────────────────────────────────────────┐
AIMessage           │ end-of-turn seam                           │
 ├─ tool_calls[]────┤► EvidenceIndex (per-kind sets + numerics)  │
 │    .result       │            ▲                               │
 └─ response ───────┤► extract_atoms() ──► GroundednessScorer    │
                    │                          │                 │
                    └──────────────────────────┼─────────────────┘
                                               ▼
                              GroundednessReport (score, supported,
                              contradicted, unsupported, flags)
                                   │                    │
                                   ▼                    ▼
                        AIMessage.metadata     FEAT-176 observers
                        ["groundedness"]       (score + counts only)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.get_response()` (`bots/abstract.py:3390`) | extends | score + attach report before return (non-streaming) |
| `BaseBot.ask_stream()` final `AIMessage` (`bots/base.py:1846`) | extends | same scoring at stream close; no per-chunk hook |
| `AbstractBot.__init__` | extends | kwargs `enable_groundedness` / `groundedness_policy` (mirrors `enable_tools` convention, `bots/abstract.py:~383-400`) |
| `AIMessage` / `ToolCall` models | uses | `tool_calls[].result` as evidence, `metadata` as report carrier — **no model changes** |
| Lifecycle observers (FEAT-176) | uses (observer) | telemetry emission; no new event types |
| FEAT-324 `parrot/security/pii/` | soft, future | when present, scoring runs after the PII pass; shared extraction engine is a follow-up — **no import of `parrot.security.pii` in this feature** |

No breaking changes; default off; zero new dependencies.

### Data Models

```python
# parrot/security/groundedness/ — design signatures (not implementation)
class AtomKind(str, Enum):
    MONEY = "money"
    PERCENT = "percent"
    NUMBER = "number"
    DATE = "date"
    IDENTIFIER = "identifier"

class Atom(BaseModel):
    kind: AtomKind
    raw: str                  # as stated in the text
    normalized: str | float   # comparison key
    start: int                # char offsets in the answer
    end: int

class AtomVerdict(BaseModel):
    atom: Atom
    verdict: Literal["supported", "contradicted", "unsupported"]
    nearest_evidence: Optional[str] = None   # raw evidence candidate (contradicted only)

class GroundednessReport(BaseModel):
    score: float                      # supported / total_atoms; 1.0 if none
    total_atoms: int
    supported: list[AtomVerdict]
    contradicted: list[AtomVerdict]
    unsupported: list[AtomVerdict]
    no_factual_content: bool = False  # answer had no verifiable atoms
    no_evidence: bool = False         # turn had no tool results
    evidence_truncated: bool = False  # max_evidence_bytes hit
    duration_ms: float

class GroundednessPolicy(BaseModel):
    """Per-agent groundedness policy. Scoring-only — there is no enforce mode.

    Attributes:
        enabled_kinds: Atom kinds to extract. Default: all five.
        include_user_prompt_as_evidence: Treat the user's question as
            legitimate evidence (agent echoing a user-stated figure).
            Default True.
        contradicted_band: Upper relative delta for "contradicted"
            (same-magnitude) classification. Default 0.15.
        min_alert_score: Below this, telemetry marks the turn flagged.
            Default 0.8. Score is always emitted regardless.
        max_evidence_bytes: Evidence-index input cap. Default 262_144.
        min_number_digits: Bare integers shorter than this are skipped
            (noise floor). Default 4.
```

### New Public Interfaces

```python
# parrot/security/groundedness/extractors.py
def extract_atoms(text: str, policy: GroundednessPolicy) -> list[Atom]: ...

# parrot/security/groundedness/evidence.py
class EvidenceIndex:
    @classmethod
    def from_tool_calls(cls, tool_calls: list[ToolCall],
                        policy: GroundednessPolicy,
                        user_prompt: str | None = None) -> "EvidenceIndex": ...

# parrot/security/groundedness/scorer.py
class GroundednessScorer:
    def score(self, answer_text: str,
              evidence: EvidenceIndex) -> GroundednessReport: ...
```

New bot kwargs: `enable_groundedness: bool = False`,
`groundedness_policy: dict | GroundednessPolicy | None`.

---

## 3. Module Breakdown

> These map 1:1 to the brainstorm's capabilities; strict sequential chain.

### Module 1: groundedness-extractors
- **Path**: `parrot/security/groundedness/extractors.py`, `normalize.py`,
  `models.py` (`Atom`, `AtomKind`), `__init__.py`
- **Responsibility**: the five atom extractors with span de-overlap
  (money/percent/date/identifier claim spans before bare numbers); NFKC
  pre-pass; normalization (magnitude suffixes `k/M/B`, thousand/decimal
  separators, common date formats → ISO, identifier case-folding);
  significant-digit counting for the tolerance rule. Stdlib only
  (`re`, `datetime`, `unicodedata`).
- **Depends on**: nothing new.

### Module 2: groundedness-scorer
- **Path**: `parrot/security/groundedness/evidence.py`, `scorer.py`,
  `policy.py` (`GroundednessPolicy`, `GroundednessReport`, `AtomVerdict`)
- **Responsibility**: `EvidenceIndex.from_tool_calls()` (recursive value
  traversal of `ToolCall.result` payloads, `max_evidence_bytes` cap,
  optional user-prompt evidence); scorer with exact match →
  precision-aware tolerance → contradicted band (≤`contradicted_band`) →
  unsupported; report assembly with flags and timing.
- **Depends on**: Module 1.

### Module 3: groundedness-reporting
- **Path**: wiring in `parrot/bots/abstract.py` (`__init__` kwargs +
  `get_response()`) and `parrot/bots/base.py` (`ask_stream` final message)
- **Responsibility**: policy coercion (dict → `GroundednessPolicy`);
  end-of-turn scoring behind `enable_groundedness`; attach report to
  `AIMessage.metadata["groundedness"]`; telemetry emission via existing
  lifecycle observers (score + counts only — atom values never leave the
  process through telemetry); non-fatal try/except contract; single INFO
  log when a turn falls below `min_alert_score`.
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_extractors_per_kind` | M1 | Positive/negative corpora per atom kind; `min_number_digits` floor; NFKC (fullwidth digits extracted) |
| `test_extractor_deoverlap` | M1 | `$1,243,500` yields one `money` atom, not money+number |
| `test_normalize_numbers` | M1 | `$1.24M` ≡ `1,240,000` ≡ `1240000`; percents; sig-digit counting |
| `test_normalize_dates` | M1 | `06/28/2026`, `June 28, 2026`, `2026-06-28` → same ISO key |
| `test_evidence_index` | M2 | Built from `ToolCall.result` incl. dict/list payloads; `max_evidence_bytes` → `evidence_truncated`; user-prompt evidence toggle |
| `test_scorer_canonical_cases` | M2 | The 5 prototype cases as canonical fixtures: faithful→1.0; transposed `$1,234,500` vs `$1,243,500`→`contradicted`; invented `INV-9999`/foreign email→`unsupported`; no hard data→`no_factual_content`; rounded `$1.24M`→`supported` |
| `test_precision_tolerance` | M2 | Full-precision statement requires exact match; rounded statement passes within half-ULP of last sig digit; both against the same evidence value |
| `test_determinism` | M2 | Same (answer, evidence) → byte-identical report across runs |
| `test_no_evidence_turn` | M2 | Zero tool calls → `no_evidence: true`, score 1.0 |
| `test_reporting_seam` | M3 | Bot stub: report present in `AIMessage.metadata`; **response text byte-identical with scoring on vs off**; scorer exception → warning + no report, turn succeeds |
| `test_telemetry_no_values` | M3 | Emitted telemetry contains score/counts, never raw atom values (`caplog`/observer capture) |

### Integration Tests

| Test | Description |
|---|---|
| `test_ask_end_to_end` | Mock-LLM bot + PII-free stub tools → `ask()` returns report; verdicts match canonical expectations |
| `test_ask_stream_end_to_end` | Same via `ask_stream`; report only on the final `AIMessage` |
| `test_default_off` | Without `enable_groundedness`, no report, no scoring cost incurred |

### Performance Benchmarks (`tests/benchmarks/`)

| Benchmark | Gate |
|---|---|
| 1 KB answer vs 3×2 KB evidence (index built per call) | p99 < 10 ms (prototype: 2.4 ms) |
| 4 KB answer vs 10 tools × 4 KB | p99 < 50 ms (informational ceiling) |

### Test Data / Fixtures

```python
# tests/fixtures/groundedness/ — canonical corpus from the brainstorm
# prototype (Appendix A): two tool outputs + five answer cases with
# expected per-atom verdicts, stored as YAML.
@pytest.fixture
def groundedness_corpus() -> list[GroundednessCase]: ...

@pytest.fixture
def stub_bot_with_tools():  # mock LLM + tools returning the corpus evidence
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests pass (`pytest tests/ -v`).
- [ ] **Scoring-only invariant**: with groundedness enabled, the response
      text delivered to the caller is byte-identical to scoring disabled —
      the scorer never mutates, masks, or blocks.
- [ ] **Determinism**: identical (answer, evidence) inputs produce
      identical reports across runs and processes.
- [ ] The five canonical prototype cases pass: faithful → 1.0; transposed
      digits → `contradicted`; invented identifiers → `unsupported`; no
      hard data → `no_factual_content`; rounded paraphrase → `supported`.
- [ ] Precision-aware tolerance is the implemented comparison rule
      (half-unit of the answer's last stated significant digit); a fixed
      global percentage is not used.
- [ ] Report attached to `AIMessage.metadata["groundedness"]` on both
      `ask()` and `ask_stream()` paths; telemetry carries score + counts
      and never atom values.
- [ ] Default off (`enable_groundedness=False`); existing test suite
      passes untouched; zero new runtime dependencies.
- [ ] Benchmark gate met: p99 < 10 ms for 1 KB answer vs 3×2 KB evidence.
- [ ] Scorer failure is non-fatal: exception → warning log, turn completes
      without a report.
- [ ] Documentation updated in `docs/` (report semantics + honest limits:
      tripwire, not truth oracle).
- [ ] No breaking changes to the existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references verified on 2026-07-22 on branch
> `claude/pii-detection-ai-parrot-a48mat` (based on `origin/main`).
> Paths relative to `packages/ai-parrot/src/parrot/`.

### Verified Imports

```python
from parrot.models.basic import ToolCall        # models/basic.py:23
from parrot.models.responses import AIMessage   # models/responses.py:72
```

### Existing Class Signatures

```python
# models/basic.py:23
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None      # line 28 — the turn's evidence payload
    error: Optional[str] = None
    execution_time: Optional[float] = None

# models/responses.py:72
class AIMessage(BaseModel):
    output: Any
    response: Optional[str]           # the final answer text
    tool_calls: List[ToolCall]        # aggregated per turn
    metadata: Dict[str, Any]          # line 202 — report carrier

# ToolCall.result IS populated in the ask loop:
#   clients/claude.py:584 and :766 — `tc.result = tool_result`
#   (same pattern across provider clients, e.g. bedrock.py:728/1040)

# End-of-turn seams:
#   bots/abstract.py:3390 — def get_response(  (sync; all non-streaming paths)
#   bots/base.py:1846    — final AIMessage yield in ask_stream()

# Bot kwarg-toggle convention: self.enable_tools (bots/abstract.py:~383-400)
# Policy-model template: ObservabilityConfig (observability/config.py:18)

# FEAT-176 lifecycle events are METADATA-ONLY (no text payloads):
#   core/events/lifecycle/events/invoke.py:34 — AfterInvokeEvent
#   core/events/lifecycle/events/tool.py:30   — AfterToolCallEvent
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GroundednessScorer` | `AIMessage.tool_calls[].result` | evidence source | `models/basic.py:28`, `clients/claude.py:584` |
| report attach | `AIMessage.metadata` | dict entry `"groundedness"` | `models/responses.py:202` |
| non-streaming seam | `AbstractBot.get_response()` | score before return | `bots/abstract.py:3390` |
| streaming seam | `ask_stream` final message | score before final yield | `bots/base.py:1846` |
| telemetry | FEAT-176 observers | score + counts only | `core/events/lifecycle/events/*.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.security.groundedness`~~ — created by this feature.
- ~~Text payloads on lifecycle events~~ — FEAT-176 events carry names/
  durations/sizes only, by design; the scorer must read texts from the
  `AIMessage`, never from events.
- ~~A per-turn tool-output collector~~ — unnecessary:
  `AIMessage.tool_calls` already aggregates `ToolCall.result`.
- ~~Any existing groundedness/hallucination/factuality check in runtime~~.
- ~~`parrot.security.pii`~~ — FEAT-324 is spec'd, **not implemented**.
  This feature MUST NOT import it; extractors are stdlib-first, and a
  shared native engine is an explicit follow-up once FEAT-324 lands.
- ~~`AIMessage.groundedness` field~~ — the report lives inside the
  existing `metadata` dict; no model changes.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic models for policy/report/atoms; Google-style docstrings; strict
  type hints; `self.logger`, never print.
- Scorer is deliberately **sync** (pure CPU, single-digit-ms budget;
  `get_response()` is sync). Async only at the seam wiring.
- Mirror the FEAT-252 scrubber failure contract: non-fatal try/except at
  the seam; warnings, never raised into the turn.
- Telemetry hygiene: score and counts only — atom raw values may contain
  the very data (emails, ids) FEAT-324 exists to protect.
- Kwargs coercion pattern: accept `dict | GroundednessPolicy | None`, as
  the bots do for other structured configs.

### Known Risks / Gotchas

- **Legitimate outside knowledge scores `unsupported`** (agent adds a
  well-known constant not present in evidence). Mitigation: the report is
  advisory; consumers read `unsupported` as "verify", not "wrong";
  `include_user_prompt_as_evidence` covers user-stated figures.
- **Small-integer blindness**: bare integers < `min_number_digits` (default
  4) are skipped as noise — a corrupted "3-digit count" goes unverified.
  Documented; floor is per-agent configurable.
- **en-US locale bias in v1** (decimal point, MM/DD dates). Locale packs
  are an open question; misparse risk is bounded because both answer and
  evidence pass through the *same* normalizer.
- **Evidence explosion** on tool-heavy turns: linear index build, capped by
  `max_evidence_bytes` with an explicit `evidence_truncated` flag —
  a truncated index can only produce false `unsupported`, never false
  `supported`.
- **Coordination with FEAT-324**: both features wire `get_response()` /
  `ask_stream`; if implemented concurrently, land FEAT-324's hooks first
  and chain groundedness after the PII pass.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | **none** — stdlib only (`re`, `datetime`, `unicodedata`, `hashlib`) |

---

## Worktree Strategy

- **Default isolation unit**: per-spec — one worktree, tasks sequential
  (M1 → M2 → M3); the modules form a strict dependency chain with no
  parallelizable seams.
- **Cross-feature dependencies**: none blocking. File-disjoint from
  FEAT-324 code (`groundedness/` vs `pii/`), but both touch the
  `get_response()`/`ask_stream` wiring — serialize that integration
  (FEAT-324 first if concurrent).

---

## 8. Open Questions

> Carried forward from the brainstorm with resolution state; resolved
> items are reflected in the spec body (§2, §4, §5).

- [x] Numeric tolerance model — *Resolved in brainstorm prototype round*:
  precision-aware (half-unit of the answer's last stated significant
  digit), NOT a fixed percentage; a fixed 2% swallowed digit
  transpositions in testing (§2 Overview, §5 criteria).
- [ ] User prompt as evidence — proposed default **True**
  (`include_user_prompt_as_evidence`); confirm during implementation
  telemetry. — *Owner: Jesús*
- [ ] Multi-locale numbers/dates (`1.234,5`, DD/MM): v1 ships en-US-biased
  extractors; locale packs later? — *Owner: Jesús*
- [ ] Telemetry alert threshold: `min_alert_score` proposed default 0.8
  (score always emitted; threshold only marks the turn flagged). —
  *Owner: Jesús*
- [ ] Small-integer floor: `min_number_digits` proposed default 4,
  per-agent configurable — right default? — *Owner: Jesús*
- [ ] Offline batch evaluator (score historical conversation logs with the
  same scorer) as a follow-up feature? — *Owner: Jesús*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-22 | Jesús Lara / Claude Code | Initial draft from `deterministic-groundedness-scoring.brainstorm.md` (Option A, prototype-validated) |
