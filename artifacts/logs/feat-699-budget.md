# FEAT-699 Replay Budget Measurements

**Feature under replay**: FEAT-698 (`sdd-brief-hotfix-flow`)
**Commits measured**: Tip `d7e03cb93` vs Fork point `49806c49f`
**Timestamp / Date**: 2025-02-22

## Environment Notes
- Python 3.11 / Pytest runner via `scripts.sdd.select_tests`
- PYTHONPATH pointing to scratch worktree `packages/ai-parrot/src`
- Copied compiled C-extension `.so` utilities (`packages/ai-parrot/src/parrot/utils/`)

## Measured Replay Results

| Tier | Mode | Fresh / Cached | Tests Collected | Wall Time (s) | Exit Code / Outcome |
|---|---|---|---:|---:|---|
| merge | before (FEAT-563 heuristics) | fresh | 2990 | 87.00 | pass |
| feature | before (FEAT-563 heuristics) | fresh | 2562 | — | — |
| merge | contract | fresh | 197 | 38.62 | pass (0) |
| merge | contract | cached (2nd run) | 197 | 39.37 | pass (0) |
| feature | contract | fresh | 197 | 38.81 | pass (0) |
| merge | fallback | fresh | 2219 | 228.67 | fail (1 - pre-existing test debt) |
| feature | fallback | fresh | 2219 | — | skipped (identical invocation set) |

## Key Findings & Budget Verification
- **Merge Tier Budget (< 120 s)**: Replayed in **38.62 s** (Contract mode) vs baseline **87 s** — **PASS**
- **Feature Tier Budget (< 300 s)**: Replayed in **38.81 s** (Contract mode) — **PASS**
- **Fallback Comparison**: Without contract declaration, test selection falls back to heuristics collecting 2,219 tests taking **228.67 s**, demonstrating the efficiency gains of the Validation Contract.
