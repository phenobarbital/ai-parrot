---
id: F006
query_id: Q006
type: grep
intent: Verify the anti-hallucination contract GroundednessReport and how deterministic-first / LLM-judge grounding is structured
executed_at: 2026-08-23T00:21:58Z
depth: 0
parent_id: null
---

# F006 — GroundednessReport and a deterministic scorer exist as a full subsystem under parrot/security/groundedness/

## Summary

The claim is confirmed and is stronger than stated. `parrot/security/groundedness/` is a
complete package: `policy.py` defines `GroundednessReport`, `scorer.py` defines
`GroundednessScorer.score(answer_text, evidence: EvidenceIndex) -> GroundednessReport`, and
there are companion `evidence.py`, `extractors.py`, `normalize.py` and `guardrail.py` modules.
The scorer is documented as deterministic (detection-only), matching the source's
"deterministic-first" §1.4 principle, and there is a governing spec.

## Citations

- path: `packages/ai-parrot/src/parrot/security/groundedness/policy.py`
  lines: 58
  symbol: `GroundednessReport`
  excerpt: |
    class GroundednessReport(BaseModel):

- path: `packages/ai-parrot/src/parrot/security/groundedness/scorer.py`
  lines: 56-74
  symbol: `GroundednessScorer.score`
  excerpt: |
    class GroundednessScorer:
        def score(self, answer_text: str, evidence: EvidenceIndex) -> GroundednessReport:

- path: `packages/ai-parrot/src/parrot/security/groundedness/`
  excerpt: |
    evidence.py  extractors.py  guardrail.py  models.py
    normalize.py  policy.py  scorer.py

- path: `sdd/specs/deterministic-groundedness-scoring.spec.md`
  excerpt: |
    Feature Specification: Deterministic Groundedness Scoring
    (Anti-Hallucination, Detection-Only)

## Notes

`guardrail.py` in the same package suggests groundedness can already be wired as a pipeline
guardrail, which is the natural home for the source's §4.2 "ToolNode ground" stage.
