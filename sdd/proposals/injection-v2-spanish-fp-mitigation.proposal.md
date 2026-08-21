---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Proposal: Mitigate the v2 Prompt-Injection Classifier's Spanish False-Positive Regression

**Date**: 2026-08-21
**Author**: Jesús Lara (drafted with Claude Code, filed as a mandatory
follow-up of FEAT-439)
**Status**: exploration

> Filed per FEAT-439 spec §5 acceptance criterion: v2 was approved for
> shipping ONLY with this follow-up ticket in hand.
> Evidence: `benchmarks/injection_guardrail_latency/results-v2/delta-v1-to-v2.md`,
> `benchmarks/injection_guardrail_latency/results-v2/report.md`.

---

## Problem

FEAT-439 moved `PromptInjectionGuardrail`'s primary classifier from
`protectai/deberta-v3-base-prompt-injection` (v1) to
`protectai/deberta-v3-base-prompt-injection-v2`, whenever a local graph
resolves. This is a measured, deliberate behaviour change — not free:

Measured on the 96-sample corpus (threshold 0.98, the shipping default):

| Metric | v1 | v2 | Δ |
|---|---|---|---|
| Overall recall | 0.70 | 0.92 | +0.22 (better) |
| Direct-attack recall | 15/20 | 20/20 | +5 (better) |
| Paraphrase-attack recall | 10/20 | 16/20 | +6 (better) |
| **Spanish benign false-positive rate** | **18.8%** | **43.8%** | **+25.0pp (worse)** |
| `clean_framework` (wrapper) pass rate | 12/12 | 11/12 | -1 (worse) |

The Spanish bucket is small (n=16), so the *magnitude* of 43.8% carries
real uncertainty — but the *direction* is unambiguous and the effect size
is large enough that a Spanish-language deployment running the shipping
default (`block_on_threat=False`, so TRANSFORM not BLOCK) will see
plain business Spanish wrapped in `<potentially_unsafe_input>` markers
meaningfully more often than under v1.

This was a known, accepted trade-off at FEAT-439 spec time (v2's attack
recall gains were judged worth it, and TRANSFORM — not BLOCK — is the
default mitigation already in place), but it is not something to leave
unaddressed indefinitely.

## Evidence

- `benchmarks/injection_guardrail_latency/results-v2/delta-v1-to-v2.md` —
  full v1→v2 verdict delta, per-bucket breakdown, 21/96 flipped verdicts
  (21.9%: 14 better, 7 worse).
- `benchmarks/injection_guardrail_latency/results-v2/report.md` — v2
  headline quality/latency figures at threshold sweep granularity (the
  `sweep` field in `results.json` has per-threshold precision/recall,
  useful for retuning analysis).
- `benchmarks/injection_guardrail_latency/corpus.py` — the Spanish benign
  bucket's actual sample texts, for qualitative review of what's being
  misflagged.

## Candidate directions

None of these are decided — that's what a spec (after this proposal is
approved) would resolve:

1. **Threshold retune, Spanish-aware or global.** The benchmark already
   sweeps thresholds (`SWEEP_GRID` in `harness.py`) and reports best-F1
   per tier — re-examine whether a threshold other than 0.98 changes the
   Spanish false-positive rate materially without giving back too much of
   v2's attack-recall gain. A per-language or per-locale threshold would
   need a locale signal at the guardrail call site (not currently
   plumbed through `GuardrailContext`).
2. **Corpus expansion.** n=16 Spanish benign samples is thin evidence for
   a permanent decision either way. A larger, more representative Spanish
   business-language corpus (and ideally other high-usage locales) would
   sharpen both the diagnosis and any retuning decision.
3. **Multilingual eval as a standing gate.** Fold a per-language quality
   breakdown into the benchmark harness's standard report (it currently
   reports `clean`/`clean_framework`/`attack_*` buckets, not
   language-segmented ones) so future classifier swaps can't silently
   regress a specific locale again without it showing up in the parity
   gate.
4. **Do nothing beyond the existing TRANSFORM default**, if investigation
   concludes the impact is acceptable in practice (e.g., most affected
   users tolerate the wrapper marker fine since it doesn't change the
   agent's answer, only annotates the input) — an explicit decision, not
   a default by inaction.

## Non-Goals (for this proposal's eventual spec)

- Rolling back to v1 — FEAT-439 already decided v2 ships; this proposal
  is about the FP regression specifically, not re-litigating that choice.
- Fixing the guardrail's event-loop blocking (tracked as its own,
  separate follow-up feature).
- int8/quantization work (disqualified separately — 39/96 flipped
  verdicts, 0% recall, unrelated axis).

## Open Questions

- [ ] Is a per-request/per-bot locale signal available anywhere today
  (`GuardrailContext.extras`? bot config?) that a retuned threshold could
  key off, or does this require new plumbing?
- [ ] What corpus size/sourcing is realistic for a materially more
  confident Spanish (and other-locale) false-positive estimate?
- [ ] Should the multilingual eval gate (candidate direction 3) be scoped
  into THIS follow-up, or filed as its own, smaller benchmark-tooling
  ticket?
- [ ] Target severity/urgency: is this a "next sprint" fix or a
  "monitor and revisit if a Spanish-deployment customer complains" item?

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-21 | Jesús Lara + Claude Code | Initial filing per FEAT-439 spec §5 mandatory follow-up |
