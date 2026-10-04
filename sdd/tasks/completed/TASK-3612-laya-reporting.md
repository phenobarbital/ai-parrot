# TASK-3612: Metrics, nearest-rank percentiles and JSON/Markdown report writer

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3605
**Assigned-to**: unassigned

---

## Context

Implements the `reporting.py` half of spec §3 **Module 4**: `summarize()` computes per-scenario
metrics with explicit denominators (accuracy, confusion matrix, abstention and error counts,
p50/p95 latencies by a documented nearest-rank definition, routing proportions, paired rubric pass
rates, usage sums, optional cost) and `write_report()` writes `results.json` + `report.md` into a
new or empty directory — never overwriting (spec §2 "New Public Interfaces"). Quality metrics use
one record per unique example (`repeat == 0`); prediction changes across repeats are reported
separately (spec §4). Failed samples are counted, never silently excluded. Unavailable values are
`null`, and a missing price file yields `cost: null`, never a savings claim.

---

## Scope

- Create `artifacts/laya/reporting.py`: `nearest_rank_percentile`, `confusion_matrix`,
  `summarize`, `render_markdown`, `write_report`, `load_prices`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_reporting.py` (spec §4 row "Reports").

**NOT in scope**: producing samples (TASK-3614/3615); CLI exit codes (TASK-3616).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/reporting.py` | CREATE | Metrics + Markdown/JSON writer |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_reporting.py` | CREATE | Percentiles, confusion matrix, nulls, failed samples, no-overwrite |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21; `models.py` symbols fixed by TASK-3605.

### Verified Imports
```python
import json, math, statistics  # stdlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from artifacts.laya.models import SCENARIO_LABELS, EvaluationReport, SampleResult   # TASK-3605
```

### Existing Signatures to Use
```python
# artifacts/laya/models.py (TASK-3605)
class SampleResult:   # case_id, scenario, repeat, arm ("local"|"primary"|"routed"), expected, predicted|None, status, error_code|None,
                      # timings_ms: dict[str, float|None], decision|None, requested_model, selected_model, reported_model, actual_model,
                      # fallback_metadata|None, usage|None, answer|None, quality_pass|None
class EvaluationReport:  # schema_version "1", status, config, environment, fixture_sha256, question_schemas, samples, metrics, limitations
# timings_ms keys this feature fixes (written by TASK-3614/3615): "inference_ms", "roundtrip_ms", "end_to_end_ms", "llm_ms"
```

### Does NOT Exist
- ~~`numpy`/`pandas` in reporting~~ — stdlib only; the report must render without the isolated env.
- ~~linear-interpolation percentiles~~ — nearest-rank only (spec §4 "documented deterministic nearest-rank definition").
- ~~a default price table~~ — prices come only from `--price-file` (spec §4); none ⇒ `cost: null`.
- ~~`write_report(..., overwrite=True)`~~ — no overwrite option exists (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/reporting.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_reporting.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Nearest-rank: for sorted values `v[0..n-1]` and percentile `p∈(0,100]`, rank `k = ceil(p/100·n)`,
  result `v[k-1]`; `n == 0` ⇒ `None`. Write this definition into `report.md`.
- Quality metrics: filter `repeat == 0 and arm == "local"` for injection/grounded/routing-classification;
  `status == "ok"` samples enter the confusion matrix; `status == "error"` samples are counted in
  `errors_by_code` and in the denominator `n_cases`.
- `prediction_flips`: per case, number of distinct `predicted` values across repeats minus 1, summed.
- Routing pairs (`arm in {"primary","routed"}`): rubric pass rate per arm with denominators,
  latency percentiles per arm, usage sums per arm, `fallback_samples` listed separately.
- Cost: only if a `prices` dict `{model_id: {"input_per_1k": float, "output_per_1k": float, "as_of": str}}`
  is given and `actual_model` is present; otherwise `null` per arm.
- `report.md` states: smoke dataset disclaimer, thresholds, warmup/repeat counts, limitations list,
  and the sentence that a logical-call cap is not an HTTP-attempt or money cap (spec §2).

---

## Implementation Blueprint

### Steps (in order)
1. `nearest_rank_percentile` + `confusion_matrix` — *why*: pure, tested first.
2. `summarize` — *why*: it is the only consumer of the sample list; keep denominators explicit.
3. `render_markdown` + `write_report` + `load_prices` — *why*: output must exist even for `incomplete` reports.
4. Tests, `git add -f`.

### `artifacts/laya/reporting.py` (CREATE — pure metrics)
```python
"""Metrics and report writers for the Laya evaluation (spec §3 Module 4, §4 metrics)."""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifacts.laya.models import SCENARIO_LABELS, EvaluationReport, SampleResult

PERCENTILE_DEFINITION = "nearest-rank: k = ceil(p/100 * n); value = sorted_values[k-1]; n == 0 -> null"


def nearest_rank_percentile(values: list[float], p: float) -> float | None:
    """Return the nearest-rank percentile ``p`` in (0, 100] of ``values`` (None when empty)."""
    clean = sorted(v for v in values if v is not None and math.isfinite(v))
    if not clean:
        return None
    k = max(1, math.ceil(p / 100.0 * len(clean)))
    return clean[k - 1]


def confusion_matrix(samples: list[SampleResult], labels: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """Return ``{expected: {predicted: count}}`` over ``labels`` plus an ``"__error__"`` predicted column."""
    matrix = {e: {p: 0 for p in (*labels, "__error__")} for e in labels}
    for s in samples:
        column = s.predicted if s.status == "ok" and s.predicted in labels else "__error__"
        matrix[s.expected][column] += 1
    return matrix


def _timing_stats(samples: list[SampleResult], key: str) -> dict[str, Any]:
    vals = [s.timings_ms.get(key) for s in samples if s.timings_ms.get(key) is not None]
    return {"n": len(vals), "p50_ms": nearest_rank_percentile(vals, 50), "p95_ms": nearest_rank_percentile(vals, 95)}


def summarize(samples: list[SampleResult], prices: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compute scenario metrics with explicit denominators and error/abstention counts."""
    out: dict[str, Any] = {"percentile_definition": PERCENTILE_DEFINITION, "scenarios": {}}
    by_scenario: dict[str, list[SampleResult]] = defaultdict(list)
    for s in samples:
        by_scenario[s.scenario].append(s)
    for scenario, group in by_scenario.items():
        local = [s for s in group if s.arm == "local"]
        first = [s for s in local if s.repeat == 0]  # one record per unique example (spec §4)
        ok = [s for s in first if s.status == "ok"]
        labels = SCENARIO_LABELS[scenario]
        block: dict[str, Any] = {
            "n_cases": len(first), "n_ok": len(ok), "n_error": len(first) - len(ok),
            "errors_by_code": dict(Counter(s.error_code for s in first if s.status == "error")),
            "accuracy": (sum(s.predicted == s.expected for s in ok) / len(first)) if first else None,
            "confusion_matrix": confusion_matrix(first, labels),
            "abstentions": sum(1 for s in ok if s.predicted in ("abstain", "insufficient_evidence")),
            "prediction_flips": _prediction_flips(local),
            "timings": {k: _timing_stats(local, k) for k in ("inference_ms", "roundtrip_ms", "end_to_end_ms")},
            "n_repeats_observed": max((s.repeat for s in local), default=-1) + 1,
        }
        if scenario == "routing":
            block["routing"] = _routing_block(group, prices)
        out["scenarios"][scenario] = block
    return out


def _prediction_flips(local: list[SampleResult]) -> int:
    per_case: dict[str, set[str | None]] = defaultdict(set)
    for s in local:
        per_case[s.case_id].add(s.predicted if s.status == "ok" else f"error:{s.error_code}")
    return sum(len(v) - 1 for v in per_case.values())


def _routing_block(group: list[SampleResult], prices: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Route proportions from local classification; per-arm rubric pass rate, latency, usage, cost, fallback list."""
    # FILL IN: proportions of decision.choice over local repeat-0 samples; for arm in ("primary","routed"):
    #          {"n": ..., "rubric_pass_rate": passes/n_with_quality or None, "timings": _timing_stats(arm, "llm_ms"),
    #           "usage": summed prompt/completion tokens or None, "cost": _cost(arm, prices) or None,
    #           "fallback_samples": [case_id where fallback_metadata and fallback_metadata.get("used_fallback_model")],
    #           "unverified_model_samples": [case_id where actual_model is None]} — bounded by spec §4 routing metrics + "missing prices yield null cost"
    raise NotImplementedError
```
**Why this shape**: every denominator is explicit (`n_cases`, `n_ok`, `n`) so a reader can see
what a rate is over; errors stay in the matrix under `__error__` instead of vanishing (spec §4 "failed samples not silently excluded").

### `artifacts/laya/reporting.py` (CREATE — continued: writers)
```python
def load_prices(path: Path | None) -> dict[str, dict[str, Any]] | None:
    """Load explicit per-model prices; None when no file was supplied (cost then stays null)."""
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    for model_id, row in data.items():
        if not {"input_per_1k", "output_per_1k", "as_of"} <= set(row):
            raise ValueError(f"price row for {model_id!r} must have input_per_1k, output_per_1k, as_of")
    return data


def render_markdown(report: EvaluationReport) -> str:
    """Render the human-readable report; every number here also exists in results.json."""
    lines = [f"# Laya CPU evaluation — {report.status}", "",
             "> Smoke datasets: these fixtures establish execution and reveal failure cases, not population accuracy.",
             f"> Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}; schema_version {report.schema_version}.", "",
             "## Configuration", f"- thresholds: injection={report.config.injection_threshold}, routing={report.config.routing_threshold}",
             f"- warmup={report.config.warmup}, repeats={report.config.repeats}, seed={report.config.seed}",
             f"- primary label `{report.config.primary_label}` → api model `{report.config.primary_api_model}`; cheap `{report.config.cheap_api_model}`",
             "- the logical-call cap counts `Agent.ask` calls; it is not an HTTP-attempt or money cap (client retries/fallback apply)", ""]
    # FILL IN: environment table; per-scenario sections (counts, accuracy, confusion matrix table, timings, flips);
    #          routing arms table; limitations bullet list; percentile definition footer — bounded by spec §4 "Report ..." paragraph
    lines.append(f"_Percentiles: {PERCENTILE_DEFINITION}_")
    return "\n".join(lines) + "\n"


def write_report(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]:
    """Write results.json and report.md to a new/empty directory without overwriting existing data.

    Raises:
        FileExistsError: ``output_dir`` exists and is not empty (spec §2: never overwrite implicitly).
    """
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory {output_dir} is not empty; choose a new directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = output_dir / "results.json", output_dir / "report.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
```
**Why**: `write_report` is the single place the non-overwrite rule lives; the CLI (TASK-3616) maps
`FileExistsError` to exit code 2 before any inference starts by calling a pre-check with the same rule.

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_reporting.py` (CREATE)
```python
"""FEAT-589 M4 — reporting: nearest-rank percentiles, confusion matrix, nulls, failed samples, no overwrite."""
from __future__ import annotations

from pathlib import Path

import pytest

from artifacts.laya.models import EvaluationConfig, EvaluationReport, SampleResult
from artifacts.laya.reporting import confusion_matrix, nearest_rank_percentile, summarize, write_report


def _s(case_id, expected, predicted=None, status="ok", repeat=0, error_code=None, **kw) -> SampleResult:
    return SampleResult(case_id=case_id, scenario="injection", repeat=repeat, expected=expected, predicted=predicted,
                        status=status, error_code=error_code, timings_ms=kw.pop("timings", {}), **kw)


def test_nearest_rank_matches_documented_definition():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert nearest_rank_percentile(vals, 50) == 30.0 and nearest_rank_percentile(vals, 95) == 50.0
    assert nearest_rank_percentile([7.0], 95) == 7.0 and nearest_rank_percentile([], 50) is None


def test_confusion_matrix_keeps_errors_in_a_visible_column():
    m = confusion_matrix([_s("a", "clean", "clean"), _s("b", "injection", "clean"), _s("c", "injection", status="error", error_code="inference_timeout")],
                         ("injection", "clean"))
    assert m["clean"]["clean"] == 1 and m["injection"]["clean"] == 1 and m["injection"]["__error__"] == 1


def test_summarize_counts_failed_samples_in_denominator_and_uses_repeat_zero_only():
    samples = [_s("a", "clean", "clean", timings={"inference_ms": 5.0}), _s("a", "clean", "injection", repeat=1, timings={"inference_ms": 6.0}),
               _s("b", "injection", status="error", error_code="worker_failed")]
    block = summarize(samples)["scenarios"]["injection"]
    assert block["n_cases"] == 2 and block["n_error"] == 1 and block["accuracy"] == 0.5
    assert block["prediction_flips"] == 1 and block["timings"]["inference_ms"]["n"] == 2
    assert block["errors_by_code"] == {"worker_failed": 1}


def test_unavailable_values_are_null_not_zero():
    block = summarize([_s("a", "clean", "clean")])["scenarios"]["injection"]
    assert block["timings"]["roundtrip_ms"]["p50_ms"] is None and block["timings"]["roundtrip_ms"]["n"] == 0


def test_write_report_refuses_non_empty_directory(tmp_path):
    cfg = EvaluationConfig(worker_python=Path("/bin/python3"), checkpoint_path=tmp_path, checkpoint_revision="r", output_dir=tmp_path / "out")
    report = EvaluationReport(status="incomplete", config=cfg, limitations=["no worker"])
    json_path, md_path = write_report(report, tmp_path / "out")
    assert json_path.exists() and md_path.read_text().startswith("# Laya CPU evaluation")
    with pytest.raises(FileExistsError):
        write_report(report, tmp_path / "out")


def test_routing_block_cost_is_null_without_prices_and_fallbacks_listed():
    # FILL IN: routing samples for arms primary/routed with usage + one fallback_metadata={"used_fallback_model": True};
    #          summarize(...)["scenarios"]["routing"]["routing"] has cost None per arm and lists the fallback case — bounded by spec §4
    raise NotImplementedError
```
**Why**: spec §4 "Reports" row: "Correct confusion matrix/quantiles, null unavailable values, failed
samples not silently excluded, no overwrite".

### FILL IN checklist
- [ ] `reporting.py::_routing_block` — proportions, per-arm rates, usage, cost, fallback/unverified lists
- [ ] `reporting.py::render_markdown` — sections listed in the block comment
- [ ] `test_laya_reporting.py::test_routing_block_cost_is_null_without_prices_and_fallbacks_listed`

---

## Acceptance Criteria

- [ ] AC-1 — Percentiles follow the documented nearest-rank definition (tested on 5 values and 1 value).
- [ ] AC-2 — Error samples appear in `n_error`, `errors_by_code` and the `__error__` column; accuracy denominator includes them.
- [ ] AC-3 — Missing timings/prices ⇒ `null`, never `0`; routing cost is `null` without a price file.
- [ ] AC-4 — `write_report` raises `FileExistsError` on a non-empty directory and writes both files otherwise.
- [ ] `ruff check artifacts/laya/reporting.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_reporting.py -q`

---

## Test Specification

See the CREATE block above. Add a Markdown snapshot check that `report.md` contains the words
"Smoke datasets" and "not an HTTP-attempt or money cap".

---

## Agent Instructions

1. Read spec §4 "Test Data / Fixtures" reporting paragraph and §2 "New Public Interfaces".
2. Confirm TASK-3605 is completed.
3. Implement from the Blueprint; run the Validation Command; `git add -f` both files; commit; move this file; update the index; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (native, backend=native, model=haiku, attempt_uid=a054817e6f0f4af18ff5bb0899d114b1), consolidated by sdd-worker orchestrator
**Date**: 2026-09-22
**Notes**: Created `artifacts/laya/reporting.py` (stdlib-only, no numpy/pandas): `nearest_rank_percentile`,
`confusion_matrix` (with an `__error__` column so failed samples stay visible), `summarize` (per-scenario
metrics with explicit denominators, `repeat==0` for quality metrics, prediction-flip counts across
repeats), `render_markdown`, `write_report` (refuses to overwrite a non-empty output dir) and
`load_prices`. Clean delivery, correctly force-added (`artifacts/laya/reporting.py`), only the two
declared files committed — no `sdd/` files touched, matching this model's corrected
`coder-touches-sdd-state` lesson. Merge-tier validation: 71/71 passed, 1 skipped (unrelated
benchmarks-import sys.path quirk).

**Deviations from spec**: none
