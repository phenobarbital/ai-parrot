# Deterministic Groundedness Scoring

**Feature**: FEAT-398 | **Package**: `parrot.security.groundedness` | **Status**: detection-only

Groundedness scoring is a deterministic, stdlib-only check that flags when
an agent's final answer invents or corrupts a hard fact that its own tools
just returned — a transposed revenue figure, a ticket id that never
existed, a date shifted by a month. It never rewrites, masks, or blocks a
response; it only attaches a report.

## What it does — and doesn't do

Groundedness scoring is a **tripwire, not a truth oracle**.

It works by extracting verifiable "hard-data atoms" — money, percent,
number, date, and identifier (email/URL/ticket-code) literals — from the
agent's final answer, and checking each one against the same kinds of
atoms extracted from the turn's own tool-call results
(`AIMessage.tool_calls[].result`). Every answer atom gets a verdict:

- **`supported`** — the atom matches evidence exactly, or (for numeric
  atoms) matches within a precision-aware tolerance of the answer's own
  stated significant digits (see [Report semantics](#report-semantics)).
- **`contradicted`** — a numeric atom is close to an evidence value (same
  order of magnitude, within `contradicted_band`) but outside tolerance —
  the classic transposed-digit case (`$1,234,500` vs. evidence
  `$1,243,500`).
- **`unsupported`** — the atom has no trace in the evidence at all
  (invented identifier, fabricated figure, or simply outside-knowledge the
  agent added on its own).

The report says **"these specific atoms are unsupported/contradicted by
this turn's evidence"** — it never says "this answer is true" or "this
answer is false". It is deliberately blind to:

- Semantic or paraphrased hallucinations, and any claim that carries no
  hard data at all — these are flagged `no_factual_content` (score `1.0`,
  neutral), not judged.
- Legitimate outside knowledge the agent adds correctly but that isn't in
  this turn's tool outputs — scores `unsupported`, same as a fabrication.
  Read `unsupported` as **"verify"**, not **"wrong"**.
- General truth or correctness of the answer as a whole.

It is **detection only**: no redaction, no blocking, no re-asking, no
enforcement of any kind. Consumers (UI badges, logging, alerting, a future
auto-re-ask workflow) decide what to do with the report.

## Enabling it

Groundedness scoring is **opt-in per agent**, following the same
convention as `enable_redaction`/`enable_pii_protection`:

```python
from parrot.bots.basic import BasicBot

bot = BasicBot(
    name="FinanceBot",
    enable_groundedness=True,
    # Optional: tune the policy (dict is coerced to GroundednessPolicy).
    groundedness_policy={
        "contradicted_band": 0.15,
        "min_alert_score": 0.8,
    },
)
```

`groundedness_policy` accepts either a plain `dict` or a
`GroundednessPolicy` instance directly:

```python
from parrot.security.groundedness import GroundednessPolicy

bot = BasicBot(
    name="FinanceBot",
    enable_groundedness=True,
    groundedness_policy=GroundednessPolicy(min_number_digits=3),
)
```

When `enable_groundedness=False` (the default), no `GroundednessGuardrail`
is registered — zero scoring cost, and no `"groundedness"` key ever
appears in `AIMessage.metadata["guardrails"]`.

### Where the report lands

Scoring runs as an OUTPUT-stage guardrail (part of the unified guardrails
infrastructure, FEAT-396), at the end of every turn — after
`ask()`/`ask_stream()` produce the final answer, on the same text the
caller receives. The report is attached to:

```python
result = await bot.ask("What was the revenue?")
report = result.metadata["guardrails"]["groundedness"]
```

`ask_stream()` attaches the report to the final `AIMessage` yielded at
stream close (chunks streamed before that carry no report — groundedness
is a whole-answer property, never scored per-chunk).

Because the guardrail is FLAG-only, the response text delivered to the
caller is **byte-identical** whether `enable_groundedness` is `True` or
`False` — the scoring-only invariant.

## Report semantics

`result.metadata["guardrails"]["groundedness"]` is a serialized
`GroundednessReport`:

| Field | Type | Meaning |
|---|---|---|
| `score` | `float` | `supported_atoms / total_atoms`. `1.0` when there are no atoms to check (`no_factual_content`) or no tool evidence at all (`no_evidence`). |
| `total_atoms` | `int` | Total hard-data atoms extracted from the answer. |
| `supported` | `list[AtomVerdict]` | Atoms matched (exactly, or within precision tolerance). |
| `contradicted` | `list[AtomVerdict]` | Same-magnitude atoms outside tolerance but within `contradicted_band`. |
| `unsupported` | `list[AtomVerdict]` | Atoms with no trace in the evidence. |
| `no_factual_content` | `bool` | `True` when the answer had no verifiable atoms at all. |
| `no_evidence` | `bool` | `True` when the turn had no tool-call results to check against. |
| `evidence_truncated` | `bool` | `True` when `max_evidence_bytes` was hit while building the evidence index — can only produce false `unsupported`, never false `supported`. |

Each `AtomVerdict` carries the atom (`kind`, `raw` text, normalized
value, character span) plus its `verdict`, and — for `contradicted`
atoms only — `nearest_evidence` (the closest evidence candidate's raw
text, a diagnostic aid).

**The precision-aware tolerance rule** (the normative comparison rule for
numeric atoms — money/percent/number): a claim is tolerated to be off by
up to half a unit of *its own* last stated significant digit. A rounded
statement like `"$1.24M"` (3 significant digits) tolerates being off by
up to `$5,000` from an evidence value of `$1,243,500` — legitimate
rounding, `supported`. A fully written `"$1,234,500"` (7 significant
digits) tolerates almost nothing — a single transposed digit against
evidence `$1,243,500` is `contradicted`. A fixed global percentage
tolerance was tried and rejected during prototyping: it let a
digit-transposition case hide inside the rounding allowance.

## Policy knobs

All knobs live on `GroundednessPolicy` (see
`parrot/security/groundedness/policy.py`) — every one of them tunes
*classification*, never mutation or blocking; there is no "enforce mode".

| Knob | Default | Effect |
|---|---|---|
| `enabled_kinds` | all 5 (`money`, `percent`, `number`, `date`, `identifier`) | Restrict which atom kinds are extracted/scored. |
| `include_user_prompt_as_evidence` | `True` | Treat the user's own question as legitimate evidence — an agent echoing a user-stated figure isn't flagged `unsupported`. |
| `contradicted_band` | `0.15` | Upper relative delta (15%) for the `contradicted` (same-magnitude) classification; beyond this, a numeric mismatch is `unsupported` instead. |
| `min_alert_score` | `0.8` | Below this score, an INFO-level telemetry log fires. The score itself is always emitted regardless. |
| `max_evidence_bytes` | `262144` (256 KiB) | Cap on the evidence-index input size per turn; further input sets `evidence_truncated=True` and is skipped. |
| `min_number_digits` | `4` | Bare integers/decimals shorter than this are skipped as noise (see [Known limits](#known-limits)). Money and magnitude-suffixed numbers (`"2.5M"`) are exempt from this floor. |

## Known limits

- **Small-integer blindness**: bare integers below `min_number_digits`
  (default 4) are skipped entirely as noise — a corrupted 3-digit count
  goes unverified on either side of the comparison. The floor is
  per-agent configurable via `groundedness_policy={"min_number_digits": N}`.
- **Legitimate outside knowledge scores `unsupported`**: an agent that
  correctly adds a well-known fact not present in this turn's tool
  outputs is indistinguishable, to the scorer, from one that fabricated
  it. Read `unsupported` as "verify this", not "this is wrong".
  `include_user_prompt_as_evidence=True` (the default) covers the common
  case where the user themselves stated the figure.
- **en-US locale bias (v1)**: date formats (`MM/DD/YYYY`, `Month DD,
  YYYY`, `YYYY-MM-DD`) and decimal/thousands separators are en-US only.
  Misparse risk is bounded because the answer and the evidence both pass
  through the *same* normalizer — a systematic locale mismatch fails
  closed (more `unsupported`), not silently open. Locale packs are a
  documented open question for a future iteration.
- **Blind to semantic/paraphrase hallucinations**: the scorer only checks
  hard-data atoms it can extract with the pattern catalog above — it
  cannot judge whether a sentence with no hard data is true, only flag
  that there was nothing to verify (`no_factual_content`).
- **Not a general LLM-judge replacement**: this is a fast, deterministic
  tripwire on the exact-fact failure mode of tool-using agents, not a
  substitute for a semantic hallucination check. It is complementary to
  (not a replacement for) an offline LLM-judge evaluator, should one be
  added later.

## Performance

Benchmarked in `tests/benchmarks/test_groundedness_perf.py`
(`time.perf_counter()`, 1000 iterations, p50/p99/max reported):

| Case | Gate | Measured |
|---|---|---|
| 1 KB answer vs. 3×2 KB tool-output evidence | p99 < 10 ms | ~1.2 ms |
| 4 KB answer vs. 10×4 KB tool-output evidence | p99 < 50 ms (informational) | ~6.1 ms |

Both are orders of magnitude under the 1000 ms per-turn budget, and
several thousand times faster than an equivalent LLM-judge check
(Guardrails' hallucination-detection check publishes P50 ~7 s / P95 ~43 s).
No LLM call, no model download, no network call, no external runtime
dependency — pure stdlib (`re`, `datetime`, `unicodedata`).
