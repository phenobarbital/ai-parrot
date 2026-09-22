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
    matrix = {e: dict.fromkeys((*labels, "__error__"), 0) for e in labels}
    for s in samples:
        column = s.predicted if s.status == "ok" and s.predicted in labels else "__error__"
        matrix[s.expected][column] += 1
    return matrix


def _timing_stats(samples: list[SampleResult], key: str) -> dict[str, Any]:
    vals = [s.timings_ms.get(key) for s in samples if s.timings_ms.get(key) is not None]
    return {"n": len(vals), "p50_ms": nearest_rank_percentile(vals, 50), "p95_ms": nearest_rank_percentile(vals, 95)}


def _prediction_flips(local: list[SampleResult]) -> int:
    per_case: dict[str, set[str | None]] = defaultdict(set)
    for s in local:
        per_case[s.case_id].add(s.predicted if s.status == "ok" else f"error:{s.error_code}")
    return sum(len(v) - 1 for v in per_case.values())


def _cost(samples: list[SampleResult], prices: dict[str, dict[str, Any]] | None) -> float | None:
    """Calculate total cost for a list of samples given price config."""
    if prices is None:
        return None
    total_cost = 0.0
    for s in samples:
        if s.actual_model is None or s.usage is None:
            continue
        price_row = prices.get(s.actual_model)
        if price_row is None:
            continue
        input_tokens = s.usage.get("prompt_tokens")
        output_tokens = s.usage.get("completion_tokens")
        if input_tokens is None or output_tokens is None:
            continue
        input_per_1k = price_row.get("input_per_1k")
        output_per_1k = price_row.get("output_per_1k")
        if input_per_1k is None or output_per_1k is None:
            continue
        total_cost += (input_tokens / 1000.0) * input_per_1k
        total_cost += (output_tokens / 1000.0) * output_per_1k
    return total_cost if total_cost > 0 else None


def _routing_block(group: list[SampleResult], prices: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Route proportions from local classification; per-arm rubric pass rate, latency, usage, cost, fallback list."""
    # Get local repeat-0 samples for routing
    local = [s for s in group if s.arm == "local"]
    first = [s for s in local if s.repeat == 0]

    # Compute proportions of decision.choice
    proportions: dict[str, int] = {"primary": 0, "cheap": 0, "abstain": 0}
    for s in first:
        if s.decision and s.decision.choice in proportions:
            proportions[s.decision.choice] += 1

    # Build per-arm statistics
    routing_arms: dict[str, Any] = {}
    for arm in ("primary", "routed"):
        arm_samples = [s for s in group if s.arm == arm]
        arm_repeat0 = [s for s in arm_samples if s.repeat == 0]

        if not arm_repeat0:
            continue

        # Count rubric pass rate
        with_quality = [s for s in arm_repeat0 if s.quality_pass is not None]
        passes = sum(1 for s in with_quality if s.quality_pass)
        rubric_pass_rate = (passes / len(with_quality)) if with_quality else None

        # Sum usage (prompt + completion tokens)
        total_prompt_tokens = 0
        total_completion_tokens = 0
        for s in arm_repeat0:
            if s.usage:
                total_prompt_tokens += s.usage.get("prompt_tokens", 0) or 0
                total_completion_tokens += s.usage.get("completion_tokens", 0) or 0

        usage_sum = None
        if total_prompt_tokens > 0 or total_completion_tokens > 0:
            usage_sum = {"prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens}

        # Calculate cost
        cost = _cost(arm_repeat0, prices)

        # List fallback and unverified model samples
        fallback_samples = [
            s.case_id for s in arm_repeat0 if s.fallback_metadata and s.fallback_metadata.get("used_fallback_model")
        ]
        unverified_model_samples = [s.case_id for s in arm_repeat0 if s.actual_model is None]

        routing_arms[arm] = {
            "n": len(arm_repeat0),
            "rubric_pass_rate": rubric_pass_rate,
            "timings": _timing_stats(arm_repeat0, "llm_ms"),
            "usage": usage_sum,
            "cost": cost,
            "fallback_samples": fallback_samples,
            "unverified_model_samples": unverified_model_samples,
        }

    return {
        "proportions": proportions,
        "arms": routing_arms,
    }


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
            "n_cases": len(first),
            "n_ok": len(ok),
            "n_error": len(first) - len(ok),
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
    lines = [
        f"# Laya CPU evaluation — {report.status}",
        "",
        "> Smoke datasets: these fixtures establish execution and reveal failure cases, not population accuracy.",
        f"> Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}; schema_version {report.schema_version}.",
        "",
        "## Configuration",
        f"- thresholds: injection={report.config.injection_threshold}, routing={report.config.routing_threshold}",
        f"- warmup={report.config.warmup}, repeats={report.config.repeats}, seed={report.config.seed}",
        f"- primary label `{report.config.primary_label}` → api model `{report.config.primary_api_model}`; cheap `{report.config.cheap_api_model}`",
        "- the logical-call cap counts `Agent.ask` calls; it is not an HTTP-attempt or money cap (client retries/fallback apply)",
        "",
    ]

    # Environment table
    if report.environment:
        lines.append("## Environment")
        for key, value in sorted(report.environment.items()):
            lines.append(f"- {key}: {value}")
        lines.append("")

    # Per-scenario sections
    if report.metrics and "scenarios" in report.metrics:
        lines.append("## Results by Scenario")
        for scenario_name, scenario_data in report.metrics["scenarios"].items():
            lines.append(f"### {scenario_name.capitalize()}")
            lines.append(
                f"- Cases: {scenario_data['n_cases']} (ok: {scenario_data['n_ok']}, errors: {scenario_data['n_error']})"
            )

            # Error codes
            if scenario_data["errors_by_code"]:
                lines.append(f"- Error codes: {scenario_data['errors_by_code']}")

            # Accuracy
            if scenario_data["accuracy"] is not None:
                lines.append(f"- Accuracy: {scenario_data['accuracy']:.1%}")

            # Abstentions
            abstentions = scenario_data.get("abstentions", 0)
            if abstentions > 0:
                lines.append(f"- Abstentions: {abstentions}")

            # Prediction flips
            flips = scenario_data.get("prediction_flips", 0)
            if flips > 0:
                lines.append(f"- Prediction flips across repeats: {flips}")

            # Confusion matrix
            cm = scenario_data["confusion_matrix"]
            lines.append("- Confusion matrix:")
            # Build header
            all_predicted = set()
            for row in cm.values():
                all_predicted.update(row.keys())
            all_predicted_sorted = sorted(all_predicted)
            header = "| expected | " + " | ".join(all_predicted_sorted) + " |"
            lines.append(header)
            lines.append("|---|" + "|".join(["---"] * len(all_predicted_sorted)) + "|")
            for expected in sorted(cm.keys()):
                row_data = cm[expected]
                cells = [expected] + [str(row_data.get(p, 0)) for p in all_predicted_sorted]
                lines.append("| " + " | ".join(cells) + " |")

            # Timings
            timings = scenario_data.get("timings", {})
            for timing_key in ("inference_ms", "roundtrip_ms", "end_to_end_ms"):
                timing_data = timings.get(timing_key, {})
                n = timing_data.get("n", 0)
                if n > 0:
                    p50 = timing_data.get("p50_ms")
                    p95 = timing_data.get("p95_ms")
                    lines.append(f"- {timing_key}: n={n}, p50={p50}, p95={p95}")

            # Repeats observed
            n_repeats = scenario_data.get("n_repeats_observed", 0)
            lines.append(f"- Repeats observed: {n_repeats}")

            # Routing block
            if scenario_name == "routing" and "routing" in scenario_data:
                routing = scenario_data["routing"]
                lines.append("")
                lines.append("#### Routing")

                # Proportions
                if "proportions" in routing:
                    props = routing["proportions"]
                    lines.append(f"- Choice proportions: primary={props.get('primary', 0)}, cheap={props.get('cheap', 0)}, abstain={props.get('abstain', 0)}")

                # Per-arm statistics
                if "arms" in routing:
                    for arm_name in ("primary", "routed"):
                        arm_data = routing["arms"].get(arm_name)
                        if not arm_data:
                            continue
                        lines.append(f"- {arm_name.capitalize()} arm:")
                        lines.append(f"  - Samples: {arm_data['n']}")
                        if arm_data.get("rubric_pass_rate") is not None:
                            lines.append(f"  - Rubric pass rate: {arm_data['rubric_pass_rate']:.1%}")
                        timings_llm = arm_data.get("timings", {})
                        if timings_llm.get("n", 0) > 0:
                            lines.append(
                                f"  - LLM latency: p50={timings_llm.get('p50_ms')}, p95={timings_llm.get('p95_ms')}"
                            )
                        if arm_data.get("usage"):
                            usage = arm_data["usage"]
                            lines.append(
                                f"  - Usage: {usage.get('prompt_tokens', 0)} prompt, {usage.get('completion_tokens', 0)} completion"
                            )
                        if arm_data.get("cost") is not None:
                            lines.append(f"  - Cost: ${arm_data['cost']:.4f}")
                        if arm_data.get("fallback_samples"):
                            lines.append(f"  - Fallback samples: {arm_data['fallback_samples']}")
                        if arm_data.get("unverified_model_samples"):
                            lines.append(f"  - Unverified model samples: {arm_data['unverified_model_samples']}")

            lines.append("")

    # Limitations
    if report.limitations:
        lines.append("## Limitations")
        for limitation in report.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    # Percentile definition footer
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
