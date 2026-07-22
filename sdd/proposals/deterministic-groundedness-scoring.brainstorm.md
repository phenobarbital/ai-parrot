---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Deterministic Groundedness Scoring (Anti-Hallucination, Detection-Only)

**Date**: 2026-07-22
**Author**: Jesús Lara (with Claude Code research)
**Status**: exploration
**Recommended Option**: A

> Candidate feature id: FEAT-325 (assigned at spec time; highest on main is
> FEAT-323, FEAT-324 is the in-flight PII spec on this branch).
> Companion docs: `pii-detection-redaction.brainstorm.md` / `.comparison.md`
> (FEAT-324) — this feature reuses its catalog/engine machinery and seams.

---

## Problem Statement

Agents compose their final answer *from* tool outputs — and sometimes invent
or corrupt the very facts those tools returned: a transposed revenue figure,
a ticket id that never existed, a date shifted by a month. Today AI-Parrot
has no way to notice. The OpenAI Guardrails "Hallucination Detection" check
(https://openai.github.io/openai-guardrails-python/ref/checks/hallucination_detection/)
addresses this with an **LLM judge + FileSearch over an OpenAI vector
store**: gpt-4.1-mini by default (ROC AUC 0.876; gpt-5-mini 0.934), **P50
~7 s / P95 ~43 s per check**, extra FileSearch API cost, a vector store to
build and maintain, degraded accuracy beyond ~11 MB of documents, and
inherently non-deterministic verdicts.

That profile cannot run in AI-Parrot's hot path, and it verifies against a
*static* knowledge base — but in an agent framework the freshest ground
truth for a turn is already in hand: **the turn's own tool outputs**. What's
missing is a deterministic, sub-budget (<1000 ms) way to check the answer
against that evidence and *score* it — detection only: no redaction, no
blocking, no enforcement.

## Constraints & Requirements

- **Detection/scoring only** — never mutates or blocks the response; the
  report is advisory (caller/UI/telemetry decide what to do).
- **Deterministic**: same answer + same evidence → same score. No LLM, no
  model download, no network call.
- **Latency**: well under the 1000 ms budget per turn; target same order as
  the FEAT-324 scanners (single-digit ms in Python, sub-ms with the Rust
  engine later).
- **Evidence = the turn's tool outputs** (already carried by
  `AIMessage.tool_calls[].result` — verified below), not an external
  knowledge base.
- Per-agent opt-in via the established kwargs/policy convention; zero new
  runtime dependencies.
- Honest scope: verifies **hard-data atoms** only (numbers/amounts/percents,
  dates, identifiers). Semantic/paraphrase hallucinations are explicitly out
  of scope — this is a high-precision tripwire, not a truth oracle.

---

## Options Explored

### Option A: Deterministic hard-data atom verification (evidence = turn's tool outputs)

Extract "verifiable atoms" from the final answer — money amounts, percents,
large/formatted numbers, dates, emails/URLs/ticket-style identifiers — via
the same catalog+regex machinery as FEAT-324. Build an `EvidenceIndex` from
the same atoms extracted from every `ToolCall.result` in the turn. Compare
with normalization (`$1.24M` ≡ `1,243,500` within rounding; multi-format
dates → ISO) and classify each answer atom:

- `supported` — present in evidence (exact normalized match, or within a
  **precision-aware rounding tolerance**: half a unit of the answer's last
  stated significant digit, so `$1.24M` matches `$1,243,500` but a
  fully-written `$1,234,500` demands exact equality);
- `contradicted` — numerically close (same magnitude, ≤15% off) to an
  evidence value but outside its stated precision → classic transposed/
  corrupted digits, the strongest hallucination signal;
- `unsupported` — no trace in evidence (invented id, email, figure).

`score = supported / total_atoms`; an answer with no atoms scores 1.0 with
a `no_factual_content` flag (nothing verifiable ≠ verified).

✅ **Pros:**
- Deterministic, explainable (every flagged atom is quotable), zero deps.
- **Prototype validated** (Appendix A): 5/5 synthetic cases correct,
  including the transposed-digits → `contradicted` case; p99 **2.37 ms**
  for a 1 KB answer against 3×2 KB tool outputs — ~400× under budget,
  ~3 000–18 000× faster than the Guardrails LLM judge.
- Evidence is per-turn and always fresh — no vector store to maintain.
- Reuses FEAT-324's catalog pattern, seams, and (later) Rust `RegexSet`
  engine; extractors are data, not code.
- High precision by construction: a hard atom absent from evidence is
  near-certainly not grounded in it.

❌ **Cons:**
- Blind to paraphrased/semantic hallucinations and claims without hard data
  (mitigated by the explicit `no_factual_content` flag).
- Small bare integers (≤3 digits) are too noisy to verify and are skipped —
  documented coverage gap.
- Legitimate outside knowledge (e.g. the agent adds a well-known constant)
  scores as `unsupported`; needs an allow-mechanism or tolerant reading of
  mid scores.

📊 **Effort:** Low–Medium (Python engine) — the hard parts (extraction,
normalization, seams) are shared with FEAT-324.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `re`, `datetime` | extraction + normalization | zero new deps |
| (later) `pii-rs`/Rust `RegexSet` | shared native scan pass | same crate as FEAT-324, optional |

🔗 **Existing Code to Reuse:**
- `models/basic.py:23` `ToolCall` — `result: Optional[Any]` (line 28)
  already carries each tool's output through the turn.
- `models/responses.py:72` `AIMessage` — `tool_calls: List[ToolCall]`,
  `response`, and `metadata: Dict[str, Any]` (line 202) as report carrier.
- FEAT-324 catalog/policy/engine patterns (`sdd/specs/pii-detection-redaction.spec.md`).
- FEAT-176 lifecycle observers for telemetry emission.

---

### Option B: LLM-judge groundedness (Guardrails-style, self-hosted)

Run a second LLM pass ("is this answer supported by these tool outputs?")
per turn, prompt-only (no vector store — evidence inlined).

✅ **Pros:**
- Catches semantic/paraphrase hallucinations Option A cannot.
- No FileSearch/vector-store maintenance (evidence inlined per turn).

❌ **Cons:**
- Seconds of added latency (Guardrails publishes P50 ~7 s / P95 ~43 s for
  their variant) and per-turn token cost — breaks the ≤1000 ms budget.
- Non-deterministic; verdicts drift with model/prompt versions.
- Circular trust: an LLM auditing an LLM inherits the same failure class.

📊 **Effort:** Medium (prompting, output parsing, eval harness)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| existing `AbstractClient` | judge calls | any provider |

🔗 **Existing Code to Reuse:**
- `parrot/clients/` for the judge call; could live as an *offline/async*
  evaluator later, complementary to Option A.

---

### Option C: N-gram / quoted-span overlap scoring

Score lexical overlap: long n-grams and quoted spans of the answer must
appear in tool outputs (ROUGE-style precision against evidence).

✅ **Pros:**
- Deterministic; catches invented *sentences*, not just atoms.

❌ **Cons:**
- Penalizes legitimate paraphrase heavily → noisy scores that erode trust
  in the report; needs careful thresholds per language.
- Much larger index cost per turn (all n-grams vs a handful of atoms).
- Weak on the highest-value failure (a single corrupted digit changes one
  token — invisible to n-gram overlap, decisive in Option A).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib only | n-gram hashing | — |

🔗 **Existing Code to Reuse:**
- Same seams as Option A.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies the constraint set as given —
  deterministic, scoring-only, and orders of magnitude inside the 1000 ms
  budget (measured p99 2.37 ms vs Guardrails' published P50 7 000 ms).
- It targets the failure mode that matters most in a tool-using agent:
  corruption or invention of the *hard facts the tools just returned* —
  and the prototype proves the precision-aware tolerance cleanly separates
  legitimate rounding (`$1.24M`) from digit transposition (`$1,234,500` →
  `contradicted`).
- Its blind spots are honest and bounded (`no_factual_content` flag), and
  the catalog-driven extractor design leaves clean extension points for
  Option C's n-grams as a future extractor kind, and Option B as an
  *offline* complementary judge — neither is foreclosed.

Trade-off accepted: this is a tripwire, not full hallucination coverage.
The report says "these specific atoms are unsupported/contradicted", never
"this answer is true".

---

## Feature Description

### User-Facing Behavior

- New bot kwargs (same convention as `enable_pii_protection`):
  `enable_groundedness: bool = False`, `groundedness_policy: dict |
  GroundednessPolicy` (`extractors` toggle per kind, `numeric_tolerance`
  mode, `include_user_prompt_as_evidence: bool`, `min_alert_score`).
- After each `ask()` (and at stream close), the `AIMessage` carries
  `metadata["groundedness"] = GroundednessReport` with `score`,
  `no_factual_content`, and the `supported` / `unsupported` /
  `contradicted` atom lists (kind + raw text + best evidence candidate).
- The same summary (score + counts, never full atom values) is emitted to
  telemetry via the existing lifecycle observers.
- Nothing is ever rewritten or blocked — consumers decide (UI badge,
  logging, future auto-re-ask).

### Internal Behavior

- `parrot/security/groundedness/` (sibling to `pii/`): `extractors.py`
  (catalog-driven atom extraction: money/percent/number/date/identifier,
  with span de-overlap), `normalize.py` (numeric magnitude+suffix folding,
  multi-format date → ISO, identifier lowercasing), `evidence.py`
  (`EvidenceIndex`: exact hash-set per kind + numeric list for tolerance
  checks, built once per turn from `AIMessage.tool_calls[].result`),
  `scorer.py` (`GroundednessScorer.score()` with precision-aware
  tolerance), `policy.py` (`GroundednessPolicy` Pydantic model).
- **Seam**: end-of-turn only — in `get_response()` after the FEAT-324 PII
  pass (scoring runs on the same text the user will see), and at
  `ask_stream`'s final `AIMessage`. No per-chunk work: groundedness is a
  whole-answer property.
- Evidence uses the *scrubbed* tool outputs (post-PII); since answer and
  evidence are scrubbed by the same catalog, redaction placeholders match
  on both sides and do not distort the score.
- Failure contract mirrors the scrubbers: any scorer exception logs a
  warning and the response ships without a report — never breaks the turn.

### Edge Cases & Error Handling

- **No tool calls in the turn** → no evidence → report emitted with
  `no_evidence: true` and score 1.0 (nothing checkable), distinct from
  `no_factual_content`.
- **Rounded answers**: precision-aware tolerance (half-unit of last stated
  significant digit) accepts honest rounding, rejects digit corruption.
- **Small integers (≤3 digits)** skipped by design (noise); documented.
- **Structured tool results** (dicts/lists): serialized values traversed
  recursively, same as the scrubbers traverse `ToolResult`.
- **Unicode**: reuses FEAT-324's NFKC normalization pre-pass so fullwidth
  digits can't dodge extraction.
- **Huge evidence** (many/large tool outputs): index build is linear; cap
  via `max_evidence_bytes` with a `evidence_truncated` flag on the report.

---

## Capabilities

### New Capabilities
- `groundedness-extractors`: catalog-driven hard-data atom extraction +
  normalization (shared foundations with the FEAT-324 catalog).
- `groundedness-scorer`: `EvidenceIndex` + precision-aware scoring +
  `GroundednessReport` model.
- `groundedness-reporting`: `AIMessage.metadata` attachment + telemetry
  emission via lifecycle observers + bot kwargs/policy wiring.

### Modified Capabilities
- (none — FEAT-324 artifacts are reused read-only; if its spec lands first,
  its engine protocol is the preferred extraction backend)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/security/` | extends | new `groundedness/` subpackage |
| `AbstractBot.get_response()` (`bots/abstract.py:3390`) | extends | score after PII pass, attach report to `AIMessage.metadata` |
| `BaseBot.ask_stream()` final `AIMessage` (`bots/base.py:1846`) | extends | same scoring at stream close (whole-answer, no per-chunk cost) |
| `AbstractBot.__init__` | extends | `enable_groundedness` / `groundedness_policy` kwargs |
| `AIMessage` / `ToolCall` models | uses | `tool_calls[].result` as evidence; `metadata` as report carrier — no model changes |
| Lifecycle observers (FEAT-176) | uses | telemetry emission (score + counts only) |
| FEAT-324 catalog/engine | depends on (soft) | shares extraction machinery when present; stdlib fallback otherwise |

No breaking changes; default off; zero new dependencies.

---

## Code Context

### User-Provided Code

(none — requirement provided as prose)

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/models/basic.py:23
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None      # line 28 — the turn's evidence payload
    error: Optional[str] = None
    execution_time: Optional[float] = None

# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    output: Any
    response: Optional[str]
    tool_calls: List[ToolCall]        # populated with results (see below)
    metadata: Dict[str, Any]          # line 202 — report carrier

# ToolCall.result is populated in the ask loop:
#   clients/claude.py:584 and :766 — `tc.result = tool_result`
#   (pattern repeated across provider clients; bedrock.py:728/1040 etc.)

# End-of-turn seams (same as FEAT-324):
#   bots/abstract.py:3390 — get_response() (non-streaming)
#   bots/base.py:1846    — final AIMessage yield in ask_stream()

# Observer-only telemetry (FEAT-176):
#   core/events/lifecycle/events/invoke.py:34 — AfterInvokeEvent (metadata only)
#   core/events/lifecycle/events/tool.py:30   — AfterToolCallEvent (metadata only)
```

#### Verified Imports
```python
from parrot.models.basic import ToolCall        # models/basic.py:23
from parrot.models.responses import AIMessage   # models/responses.py:72
```

#### Key Attributes & Constants
- `AIMessage.metadata: Dict[str, Any]` — `models/responses.py:202`.
- Bot kwarg-toggle convention: `self.enable_tools` (`bots/abstract.py:~383-400`).
- Policy-model template: `ObservabilityConfig` (`observability/config.py:18`).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.security.groundedness`~~ — created by this feature.
- ~~Text payloads on lifecycle events~~ — FEAT-176 events carry metadata
  only (names/durations/sizes), by design; the scorer must read texts from
  the `AIMessage`, not from events.
- ~~A per-turn tool-output collector~~ — not needed: `AIMessage.tool_calls`
  already aggregates `ToolCall.result` for the turn.
- ~~Any existing groundedness/hallucination/factuality check in runtime~~ —
  none found in `parrot/`.
- ~~`parrot.security.pii` at implementation time~~ — FEAT-324 is spec'd,
  not yet implemented; this feature must NOT import it until it lands
  (stdlib extractor fallback first, shared engine as a follow-up).

---

## Parallelism Assessment

- **Internal parallelism**: low — the three capabilities form a short
  dependency chain (extractors → scorer → reporting); one worktree,
  sequential tasks.
- **Cross-feature independence**: file-disjoint from FEAT-324 code
  (`groundedness/` vs `pii/`) but both touch `get_response()`/`ask_stream`
  wiring — if implemented concurrently, land FEAT-324's seam hooks first
  and chain after them.
- **Recommended isolation**: per-spec (single worktree).
- **Rationale**: small surface, strict ordering, shared seam with an
  in-flight feature argues for sequential integration.

---

## Open Questions

- [x] Numeric tolerance model — *Resolved in prototype round*:
  precision-aware (half-unit of the answer's last stated significant
  digit), NOT a fixed percentage; a fixed 2% swallowed digit
  transpositions in testing (Appendix A, case b).
- [ ] Should the user's prompt count as legitimate evidence (user states a
  figure, agent echoes it)? Proposed default: yes, behind
  `include_user_prompt_as_evidence=True`. — *Owner: Jesús*
- [ ] Multi-locale numbers/dates (`1.234,5`, DD/MM vs MM/DD): v1 ships
  en-US biased extractors; locale packs via catalog overlays later? —
  *Owner: Jesús*
- [ ] Telemetry alert threshold: emit score always, or only below
  `min_alert_score` (default 0.8)? — *Owner: Jesús*
- [ ] Small-integer gap: skip ≤3-digit bare numbers (current prototype) or
  make the floor configurable per agent? — *Owner: Jesús*
- [ ] Future: expose the scorer as a standalone evaluation tool (offline
  batch over conversation logs) in addition to the runtime seam? —
  *Owner: Jesús*

---

## Appendix A — Prototype validation & latency (reproducible)

Stdlib-only prototype (~170 lines): extractors (money/percent/number/date/
identifier with span de-overlap), magnitude+suffix normalization
(`$1.24M` → 1 240 000), multi-format date → ISO, `EvidenceIndex`
(exact set + numeric tolerance list), precision-aware scorer.

Synthetic evidence: two tool outputs (sales query: `$1,243,500`, `4,812`
orders, `2026-06-30`, `finance@acme.example.com`, `INV-2210`; inventory
API: `312` units, `15%`, `06/28/2026`).

| Case | Expectation | Result |
|---|---|---|
| (a) faithful answer | score 1.0, all atoms supported | ✅ 1.0 — money/date/number supported |
| (b) transposed digits (`$1,234,500`) | flagged | ✅ 0.5 — money atom **contradicted** |
| (c) invented id + email (`INV-9999`, other domain) | flagged | ✅ 0.0 — both **unsupported** |
| (d) no hard data in answer | neutral | ✅ 1.0 + `no_factual_content: true` |
| (e) rounded paraphrase (`$1.24M`, `312 units`) | supported | ✅ 1.0 — precision-aware tolerance |

Latency (1 KB answer vs 3 × 2 KB tool outputs, 200 warm iterations,
including per-call `EvidenceIndex` build — a per-turn cache would roughly
halve it): **p50 1.81 ms, p95 1.95 ms, p99 2.37 ms** — ~400× under the
1000 ms budget; Guardrails' LLM judge publishes P50 ~7 s / P95 ~43 s for
its equivalent check (~3 000–18 000× slower).

Design finding worth preserving: with a fixed 2% tolerance, case (b)
scored `supported` — the transposition (`0.72%` off) hid inside the
rounding allowance. The precision-aware rule (tolerance derived from the
answer's own stated significant digits) fixed (b) without breaking (e).
This is the recommended normative rule for the spec.

```python
# Core of the precision-aware tolerance (full script: ~170 lines, stdlib):
def sig_digits(raw: str) -> int:
    digits = re.sub(r"[^0-9]", "", raw).lstrip("0")
    return max(len(digits), 1)

def rel_tolerance(raw: str) -> float:
    """Half a unit of the last stated significant digit:
    '$1,234,500' (7 sig digits) -> ~5e-7 (exact match in practice)
    '$1.24M'     (3 sig digits) -> 0.5%  (legitimate rounding passes)"""
    return 0.5 * 10.0 ** (-(sig_digits(raw) - 1))

# classification per answer atom vs EvidenceIndex:
#   exact normalized match ................. supported
#   |Δ|/ev <= rel_tolerance(stated) ........ supported   (honest rounding)
#   |Δ|/ev <= 0.15 ......................... contradicted (corrupted digits)
#   otherwise .............................. unsupported  (no trace)
```

## References

- OpenAI Guardrails hallucination check: https://openai.github.io/openai-guardrails-python/ref/checks/hallucination_detection/
- FEAT-324 spec (shared machinery): `sdd/specs/pii-detection-redaction.spec.md`
- FEAT-324 comparison (latency methodology reused here): `sdd/proposals/pii-detection-redaction.comparison.md`
