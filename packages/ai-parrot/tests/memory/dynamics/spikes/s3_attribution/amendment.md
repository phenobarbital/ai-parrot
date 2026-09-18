# Proposed spec amendment — S3 (TASK-3384) · status: PROPOSED (owner review; U1/U3 decisions)

## Freeze

- **Attribution default for generic agents**: `cited` only, with overlap heuristics as an explicit
  opt-in (recommendation, not a decision — see U1 below). Evidence: `cited` measured
  **precision 1.000** at every cap on this corpus, vs. `overlap_tokens`/`combined` at
  **precision 0.920** with **false_reinforcement 0.080** and **collision_rate 0.080** once cap ≥ 3.
  `overlap_error_signature` and `recovery_linkage` alone never produced a false positive on this
  corpus (precision 1.000) because they require an exact normalized-signature match or a structural
  recovery ref — both harder to satisfy by accident than a lexical Jaccard threshold. `cited`'s cost
  is a higher **missed_attribution (0.300)**: it cannot credit a memory the agent never explicitly
  named, even when the tool trace makes the connection obvious.
- **Overlap cap**: 3 (the candidate value) is where `overlap_tokens`/`combined` numbers stabilize
  on this corpus (cap 1 has precision 1.000 but only because the collision items' second overlap
  hit is truncated away; cap ≥ 3 exposes the true collision/false-reinforcement rate). Overlap
  token threshold: 0.3 Jaccard (`harness.OVERLAP_TOKEN_THRESHOLD`) — both remain experiment inputs
  pending a real-trace re-run (see Limitations).
- **Recovery-linkage predicate**: structural refs only — `evidence.recovery_refs` populated by the
  trusted-receipt adapter with the actual correction/check artifact id(s) (fix commit sha, passed
  check id, or a before/after error-signature pair), intersected with the exposure's delivered
  refs (`harness.recovery_linkage`). Prose equality between a lesson and a suggested/corrective
  action is explicitly excluded — `test_recovery_linkage_ignores_prose_equality` pins this: a memory
  whose `lesson_tokens` are identical to `evidence.tool_tokens` (i.e. would be attributed by
  `overlap_tokens`) is NOT attributed by `recovery_linkage` unless its id also appears in
  `evidence.recovery_refs`.
- **Evidence schema fields** (from the harness dataclasses, feeding spec §2 `ReviewSignal` /
  `MemoryExposure` / `MemoryCitation`):
  - `MemoryExposure` ~ `harness.Exposure`: `exposure_id`, `attempt_or_turn_id`, `delivered: tuple[MemoryRef, ...]`
    (`harness.DeliveredRef`: `memory_id`, `content_version`, `kind`, `error_signature`), `packed_sha256`.
  - `ReviewSignal` ~ `harness.OutcomeEvidence`: `outcome_id`, `verified: bool`, `success: bool`,
    `first_attempt: bool`, `correction_count: int`, `error_signature: str | None`,
    `recovery_refs: tuple[str, ...]` (structural, memory-id-keyed), `cited: tuple[str, ...]`
    (untrusted until validated against `delivered`), `source: Literal["tool_runtime", "coder_engine", "synthetic"]`.
  - `MemoryCitation` ~ the output of `harness.cited()`: a subset of `Exposure.delivered` ids, never
    a caller-supplied grade.
- **Trusted-receipt adapters**:
  - `tool_runtime`: the runtime tool executor must supply an explicit success/failure with a
    normalized error signature (on failure) and a correction count observed across retries of the
    *same* tool call — never `getattr(tool_result, "success"/"status", ...)` defaults
    (`core/memory/episodic/store.py:260,262`).
  - `coder_engine`: `SddCoderEngine.record_review`'s existing fix-commit reachability check
    (`engine.py:1476-1486`) plus at least one relevant passed check id from the review; a bare
    merge or a zero-`fix_commits` review is **not** sufficient on its own — completion must pair
    with a relevant passed check, matching spec §2 step 2 ("a successful transport call ... is
    insufficient proof").
- **Untrusted sources (never sufficient alone)**: `ToolInvocation.status` default
  (`core/memory/compaction/models.py:71`), `ToolResult.success`/`status` `getattr(...)` defaults
  (`core/memory/episodic/store.py:260,262`), an empty corrections list, a model's own summary, a
  successful transport call, and the coder engine's `"[coder-feedback:" in context` exposure
  marker alone (`engine.py:1488-1492` — it flags a cohort, it carries no memory ids and cannot
  attribute anything).

## Pass/Fail

- Corpus: 50 items (real: 0, synthetic: 50, judge: `model:claude-sonnet-5`)
- Precision (cited / overlap_tokens / combined @ cap 3): **1.000 / 0.920 / 0.920**
- False reinforcement (cited / overlap_tokens / combined @ cap 3): **0.000 / 0.080 / 0.080**
- Missed attribution (cited / overlap_tokens / combined @ cap 3): **0.300 / 0.080 / 0.080**
- Collisions (cited / overlap_tokens / combined @ cap 3): **0.000 / 0.080 / 0.080**
- Against U3 target: **PENDING — owner decision** (spec §8 U3 has not set a numeric target; this
  gate reports the measured numbers above so the owner can set one).

## Sections to edit on acceptance

§2 "Review Admission and Grade Precedence", §2 Data Models (ReviewSignal/MemoryExposure/
MemoryCitation/CheckedPattern), §3 M1 (grade schema freeze), M3 eligibility, §8 overlap question, U1.

## Limitations (carried from REPORT.md)

- **No real trace coverage.** This worktree has no coder-review/coder-feedback ledger data (no
  `sdd/state/**/*.jsonl` review log, no episodic-store backend snapshot) to mine real outcomes
  from; the 50-item corpus is **100% synthetic**, hand-constructed so each item exercises exactly
  one grade-table branch (again / easy-via-citation / easy-via-overlap-capped-to-good / hard / good
  / no-review-unverified / no-review-irrelevant-success) and one attribution edge case (cross-scope
  citation, prose-equivalent-but-structurally-unlinked recovery, token-overlap collision). Per
  spec §3 G3 this is an explicit, declared gate limitation: the precision/false-reinforcement
  numbers above characterize the candidate strategies' *behavior on controlled scenarios*, not
  measured field precision on real agent traffic. **Re-running this gate against real traces once
  the coder-feedback ledger accumulates verified reviews is a prerequisite before U1/U3 are treated
  as final**, not just reviewed once.
- The overlap token threshold (0.3) and candidate caps (1/3/5/unbounded) are the spec's declared
  experiment inputs, not frozen production defaults — the "Freeze" section above is this gate's
  recommendation, subject to the owner's U1/U3 decision.
