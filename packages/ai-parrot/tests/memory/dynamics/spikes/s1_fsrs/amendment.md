# Proposed spec amendment — S1 (TASK-3382) · status: PROPOSED (owner review required)

## Freeze

- **time_policy_id: `days-v1`** (whole elapsed calendar days, exactly as the pinned
  reference computes them) — because it is the only policy verified to exact (<1e-9)
  parity with the pinned FSRS-6 reference across 200 seeded sequences (1628 review steps,
  all four grades, same-day reviews, gaps up to 90 days, bounds saturation); see REPORT.md
  "Fast parity checks". `hours-v1` (fractional elapsed days) is proposed as a *recorded,
  versioned candidate variant only* — it diverges materially from `days-v1` whenever a gap
  carries a sub-day remainder (max Δstability = 16.54 over the same 1628 steps) and has no
  reference to validate against. Recommendation: ship `days-v1` for M1; keep `hours-v1`
  available behind an explicit `time_policy` argument for future agent-time experiments,
  never as the silent default.
- **MemoryParameters.defaults**: the reference's 21-value `DEFAULT_PARAMETERS` tuple
  (`(0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796,
  1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542)`),
  unrefit — no optimizer/training data exists yet for agent lessons specifically.
  Bounds: the reference's `LOWER_BOUNDS_PARAMETERS`/`UPPER_BOUNDS_PARAMETERS` tuples,
  copied verbatim (`STABILITY_MIN = 0.001` floor on the stability-scale parameters,
  `[1.0, 10.0]` on difficulty-scale parameter 4, etc. — see `reference/fsrs/scheduler.py`).
  Reference pin: v6.3.2 / `9446cb06605c597a063aeee49f7d188d42e34dc2` (MIT), recorded in
  `reference/PIN.md` with per-file SHA-256.
- **forget_threshold**: candidate `0.2` — used throughout this report's calibration; no
  counter-evidence surfaced against it (0% of lessons were "forgotten before first review"
  under it), but it was never load-bearing enough in this synthetic trace to be considered
  *validated*, only *not contradicted*. Recommend keeping `0.2` as the working default
  pending real usage data.
- **redistill_difficulty**: candidate `8.0` (out of the FSRS 1–10 difficulty scale) —
  **not exercised by this spike** (S1 scope was parity + retention/forgetting metrics, not
  the redistillation trigger); carried forward unchanged from the task's stated candidate
  value. Flagged **PENDING** validation in S2/M1, not evidenced here.
- **fixed vs. derived from desired_retention**: keep `forget_threshold` as a fixed,
  explicit config value (not derived from the reference's `desired_retention` scheduling
  parameter) — the reference's `desired_retention` drives *interval scheduling*
  (spaced-repetition due dates), which dynamics mode does not use; retention/forgetting in
  this feature is judged directly off `retrievability()` against `forget_threshold`.
- **promotion criterion (replaces `org_promotion_cycles=3` in dynamics mode)**: replace the
  legacy cycle-count criterion (`reinforcement_counts[page] >= org_promotion_cycles`,
  `parrot/memory/dream/runner.py:183-199`) with a retrievability-based criterion: promote
  when a lesson's `retrievability() >= forget_threshold` at evaluation time AND it has
  received at least one non-`AGAIN` (HARD/GOOD/EASY) review — mirrored by this report's
  "source pass check" (`fraction_good_review_survives_30d`, PASS at 1.0 for a `GOOD`
  review in both time policies). Lapse policy: a lesson that lapses (`AGAIN`) is not
  demoted immediately — its stability floor (`STABILITY_MIN = 0.001`) and subsequent
  recall-branch formulas already model recovery, so the criterion should re-evaluate on
  the *next* touch rather than hard-failing on a single `AGAIN`.
- **oversampling recommendation input for S2**: the ledger-cadence signal
  (`{"rows": 25, "patterns": 22}` over the shared `.parrot/ledger`, `first_seen` 2026-09-16
  to `last_seen` 2026-09-18) shows real but low-volume, bursty write cadence. S2's storage
  design should not assume high write throughput; 25 rows across 22 distinct patterns in
  ~2 days suggests read-heavy, write-light access is the common case for the retention
  store.

## Pass/Fail

- Parity within 1e-9 (all grades, same-day, long gap, bounds): **PASS** (`days-v1`; see
  REPORT.md raw metrics — max Δstability = max Δdifficulty = 0.0 over 1628 steps)
- Non-lapsed lesson with ≥1 GOOD review survives 30 days: **PASS** (1.0 in both time
  policies, n=32 lessons)
- Useful-forgetting / stale-persistence assessment (U3 target: **owner decision pending**):
  **PENDING** — the synthetic 30-day trace produced 0 lessons dormant for the full 30-day
  window (lessons are created uniformly across the window, so few reach 30 days of
  dormancy inside a single 30-day run); no evidence for or against over-retention was
  collected. The rank-correlation metric between the FSRS-weighted composite score and the
  `(scope_score, recurrence, timestamp)` baseline was also negative (~-0.66) in both
  policies using this report's documented proxies for "relevance" and "scope_score" —
  flagged for owner interpretation, not treated as a pass or fail on its own.

## Sections to edit on acceptance

§2 "FSRS, Ranking and Retention", §2 Data Models (MemoryParameters bounds), §3 M1
eligibility row, §8 time-unit + threshold questions.
