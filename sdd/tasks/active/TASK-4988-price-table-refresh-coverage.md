# TASK-4988: Refresh price tables, add cache-creation tier, prove ≥90% coverage

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4987
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (data half), goal G8, AC-6 (**blocking**, U3). Price coverage is 1.2%
(13 of 1090 recorded attempts), the oldest file is 165 days stale, and no file has a
cache-creation tier. Without this, no per-spec cost number is meaningful. Spec §3 marks
this module **not delegation-eligible**: which models to price, and at what rates, is a
data/judgement call that needs current vendor pricing.

> **Open question (spec §8)**: the ≥90% threshold is *proposed*. Confirm it with the user
> before closing. If they choose a different number, record it in the Completion Note and
> in `pricing/README.md`.

---

## Scope

- Refresh every bundled provider file under `observability/cost/pricing/`: update `last_updated` and the rates, and add `cache_creation_per_1m` to every model entry that has a cache tier.
- Add the models actually run by the sdd-coder roster: `gpt-5.6-terra`, `gpt-5.6-sol`, `zai.glm-4.7-flash`, `qwen*`, `minimax.minimax-m2.5`, `mistral.devstral-2-123b`, `gemini-3.5-flash`, and the Claude 5 family (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1`). Use exactly the model strings that appear in `artifacts/logs/sdd-coder-usage/*.jsonl` (`resolved_model` / `configured_model`), so the lookup hits.
- Decide the provider-file key for Bedrock-hosted models (`zai.*`, `minimax.*`, `mistral.*`, `qwen`), using whatever `resolve_gen_ai_system` returns for those backends. Create a new provider file only if no existing key fits.
- Add a coverage script `scripts/sdd/price_coverage.py` that reads the attempt rows and reports priced/unpriced `(provider, model)` pairs plus the coverage ratio. Add a test that runs it on a frozen fixture.
- Document the result (ratio, date, rows read) in `pricing/README.md`.

**NOT in scope**: calculator code (TASK-4987); policy (TASK-4989).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/cost/pricing/anthropic.json` | MODIFY | Refresh + Claude 5 + cache_creation tier |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/openai.json` | MODIFY | Refresh + gpt-5.6-* |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/google.json` | MODIFY | Refresh + gemini-3.5-flash |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/groq.json` | MODIFY | Refresh `last_updated`/rates |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/nvidia.json` | MODIFY | Refresh `last_updated`/rates |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/huggingface.json` | MODIFY | Refresh `last_updated` |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/README.md` | MODIFY | Coverage evidence + tier docs |
| `scripts/sdd/price_coverage.py` | CREATE | Coverage reporter |
| `tests/sdd_scripts/test_price_coverage.py` | CREATE | Script test on a fixture |
| `packages/ai-parrot/src/parrot/observability/cost/pricing/aws.bedrock.json` | CREATE | New provider file: Bedrock-hosted roster models |
| `packages/ai-parrot/src/parrot/observability/attributes.py` | MODIFY | Map dev-loop backend ids `codex`->`openai`, `google-compat`->`gemini` |
| `packages/ai-parrot/tests/unit/observability/test_attributes.py` | MODIFY | Test the new backend-id mappings |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.cost.calculator import CostCalculator   # calculator.py:135 (cost_usd widened by TASK-4987)
from parrot.observability.attributes import resolve_gen_ai_system   # used by clients/base.py:803
```

### Existing Signatures to Use
```python
# pricing/anthropic.json shape:
# {"pricing": {"last_updated": "2026-06-10", "source": "...", "currency": "USD"},
#  "models": {"<model>": {"input_per_1m": .., "output_per_1m": .., "cached_input_per_1m": ..}}}
# "cached_input_per_1m" occurs 19x in anthropic.json (one per model) — edit them all
# AttemptUsageRow fields used for coverage: backend, configured_model, resolved_model (sdd_coder/telemetry.py)
```

### Does NOT Exist
- ~~`usage/prices.yaml`~~ / any second price table — forbidden by spec Non-Goals
- ~~`cache_creation_per_1m`~~ in any JSON today — this task adds it
- ~~`scripts/sdd/price_coverage.py`~~ — this task creates it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/anthropic.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/openai.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/google.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/groq.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/nvidia.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/huggingface.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/cost/pricing/README.md", "action": "MODIFY"},
    {"path": "scripts/sdd/price_coverage.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_price_coverage.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/cost/calculator.py#CostCalculator"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every rate needs a citable `source` URL in the file header. **Never guess a price**: a model with no published price stays out, which leaves `cost_usd` as `None`.
- Subscription/plan seats are handled by policy (TASK-4989), not by zeroing prices here.
- The live logs under `artifacts/logs/sdd-coder-usage/` exist only in the **main checkout** (FEAT-554 durable root). Run the script against that path for the README evidence. The test uses a fixture.

---

## Implementation Blueprint

### Steps (in order)
1. Run the coverage script (step 4 first, as a draft) against the live logs to list unpriced pairs. That list *is* the work list.
2. Gather current vendor prices with sources, and update each JSON.
3. Re-run, iterate until the ratio ≥ threshold, and write the evidence into the README.
4. Finalize the script and its test.

### `scripts/sdd/price_coverage.py` (CREATE)
```python
"""Report price-table coverage over sdd-coder attempt rows (FEAT-783 AC-6)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def coverage(rows_dir: Path) -> dict:
    """Return {"rows": N, "priced": P, "ratio": P/N, "unpriced": {(provider, model): count}}."""
    from parrot.observability.attributes import resolve_gen_ai_system
    from parrot.observability.cost.calculator import CostCalculator

    calc = CostCalculator()
    # FILL IN: iterate *.jsonl, kind == "attempt" rows only; model = resolved_model or configured_model;
    # provider = resolve_gen_ai_system(backend); priced when calc.cost_usd(..., 1, 1) is not None — bounded by AC-6
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI: --rows-dir <dir> [--threshold 0.9]; exit 1 when below threshold."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows-dir", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args(argv)
    report = coverage(args.rows_dir)
    sys.stdout.write(json.dumps({**report, "unpriced": {f"{p}/{m}": c for (p, m), c in report["unpriced"].items()}}, indent=2) + "\n")
    return 0 if report["ratio"] >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### `tests/sdd_scripts/test_price_coverage.py` (CREATE)
```python
"""FEAT-783 AC-6 — price coverage script."""
from scripts.sdd.price_coverage import coverage, main


def test_coverage_counts_priced_and_unpriced(tmp_path) -> None:
    # FILL IN: write 3 attempt rows (2 priced models from the bundled tables, 1 bogus) + 1 outcome row;
    # assert rows == 3, priced == 2, the bogus pair is reported
    ...


def test_main_exit_code_follows_threshold(tmp_path) -> None:
    # FILL IN
    ...
```

### FILL IN checklist
- [ ] Each price with a `source`; bounded by "never guess"
- [ ] Bedrock provider key decision; bounded by `resolve_gen_ai_system`
- [ ] Coverage ≥ threshold (confirm the threshold with the user); bounded by AC-6
- [ ] Script + test bodies

---

## Acceptance Criteria

- [ ] AC-6: every price file has a `cache_creation_per_1m` tier where the vendor publishes one.
- [ ] AC-6: the README records ≥90% (or the user-confirmed threshold) of attempt rows resolving to a priced pair, with the date and row count.
- [ ] No `last_updated` older than 90 days (no stale warning at boot).

## Validation Commands
- `pytest tests/sdd_scripts/test_price_coverage.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_calculator.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Not delegation-eligible: needs current vendor pricing and a user-confirmed threshold. Stop and ask if a model has no published price.

## Completion Note
_(filled at close)_
