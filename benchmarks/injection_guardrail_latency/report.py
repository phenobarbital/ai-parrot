"""Markdown report generation for the injection-guardrail benchmark.

Turns the harness payload into four tables that answer, in order, the four
questions the benchmark exists for:

1. **Cost** — what does each tier charge per call, to load, and in RAM?
2. **Quality** — what does each tier catch at its production threshold,
   and what would a better threshold catch?
3. **Blind spots** — per bucket: which attacks does the regex tier miss,
   and does the cosine tier actually cover the paraphrases?
4. **Tiering** — how often would the classifier actually run, and what
   does the composed pipeline cost and catch?
"""
from __future__ import annotations

from typing import Any

#: p95 above this flags a tier as too slow for an inline (on-loop) seam.
INLINE_GATE_MS: float = 5.0


def _fmt(value: float | None, decimals: int = 2, dash: str = "—") -> str:
    """Format an optional number for a table cell."""
    if value is None:
        return dash
    return f"{value:.{decimals}f}"


def _pct(value: float | None) -> str:
    """Format a ``[0, 1]`` ratio as a percentage."""
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _cost_table(results: list[dict[str, Any]]) -> list[str]:
    """Build the per-tier cost table."""
    lines = [
        "## 1. Cost per tier",
        "",
        "| Tier | load (s) | RSS Δ (MB) | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | inline-safe | status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        tier = result["tier"]
        if result.get("error"):
            lines.append(f"| `{tier}` | — | — | — | — | — | — | — | **{result['error']}** |")
            continue
        lat = result["latency"]
        inline_ok = "yes" if lat["p95_ms"] <= INLINE_GATE_MS else "**no**"
        lines.append(
            f"| `{tier}` | {_fmt(result['load_s'])} | {_fmt(result['rss_delta_mb'], 1)} "
            f"| {_fmt(lat['p50_ms'])} | {_fmt(lat['p95_ms'])} | {_fmt(lat['p99_ms'])} "
            f"| {_fmt(lat['max_ms'])} | {inline_ok} | ok |"
        )
    lines += [
        "",
        f"*inline-safe* = p95 ≤ {INLINE_GATE_MS:.0f} ms, the budget for an on-loop "
        "guardrail stage. Anything above belongs behind `run_in_executor` with a "
        "`BudgetRouter`/`CircuitBreaker` (see the comparison doc §5.2).",
        "",
    ]
    return lines


def _quality_table(results: list[dict[str, Any]]) -> list[str]:
    """Build the detection-quality table with the best-F1 alternative."""
    lines = [
        "## 2. Detection quality",
        "",
        "| Tier | thr | precision | recall | F1 | FP | FN | best-F1 thr | best F1 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    from .metrics import best_threshold

    for result in results:
        if result.get("error") or not result.get("quality"):
            continue
        q = result["quality"]
        best = best_threshold(result.get("sweep") or [])
        lines.append(
            f"| `{result['tier']}` | {_fmt(q['threshold'])} | {_fmt(q['precision'])} "
            f"| {_fmt(q['recall'])} | {_fmt(q['f1'])} | {int(q['fp'])} | {int(q['fn'])} "
            f"| {_fmt(best['threshold']) if best else '—'} "
            f"| {_fmt(best['f1']) if best else '—'} |"
        )
    lines += [
        "",
        "`thr` is the threshold the tier would run at in production. For `clf-*` "
        "that is AI-Parrot's current `injection_probability_threshold=0.98`; the "
        "best-F1 column shows what the same model would score if it were retuned.",
        "",
    ]
    return lines


def _bucket_table(per_bucket: dict[str, dict[str, float]]) -> list[str]:
    """Build the per-bucket flag-rate table."""
    if not per_bucket:
        return []
    buckets = sorted({b for rates in per_bucket.values() for b in rates})
    header = "| Tier | " + " | ".join(f"`{b}`" for b in buckets) + " |"
    sep = "|---" * (len(buckets) + 1) + "|"
    lines = [
        "## 3. Where each tier is blind",
        "",
        header,
        sep,
    ]
    for tier, rates in per_bucket.items():
        cells = " | ".join(_pct(rates.get(b)) for b in buckets)
        lines.append(f"| `{tier}` | {cells} |")
    lines += [
        "",
        "Flag rate per bucket. For `clean*` buckets **lower is better** (false "
        "positives); for `attack_*` buckets **higher is better** (recall). "
        "`clean_framework` is the `<user_context>` wrapper AI-Parrot's integrations "
        "inject — a tier that flags those is unusable in Telegram/Slack.",
        "",
    ]
    return lines


def _parity_table(parity: dict[str, Any] | None) -> list[str]:
    """Build the numerical-parity table for alternate classifier backends."""
    if not parity:
        return []
    lines = [
        "## 2b. Numerical parity vs the PyTorch reference",
        "",
        "| Backend | max \\|Δ\\| | mean \\|Δ\\| | flipped verdicts | parity |",
        "|---|---|---|---|---|",
    ]
    failures: list[str] = []
    for tier, entry in parity.items():
        if entry.get("error"):
            lines.append(f"| `{tier}` | — | — | — | **{entry['error']}** |")
            failures.append(tier)
            continue
        verdict = "ok" if entry["parity_ok"] else "**FAILED**"
        if not entry["parity_ok"]:
            failures.append(tier)
        lines.append(
            f"| `{tier}` | {_fmt(entry['max_abs_delta'], 3)} "
            f"| {_fmt(entry['mean_abs_delta'], 3)} "
            f"| {entry['flipped_verdicts']} ({_pct(entry['verdict_disagreement'])}) "
            f"| {verdict} |"
        )
    lines.append("")
    lines.append(
        "Same weights, same inputs — so scores must agree within numerical noise. "
        "A backend that fails here is **not** a faster version of the model; it is "
        "a different, wrong function that happens to run faster."
    )
    if failures:
        lines += [
            "",
            "> ⚠️ **Do not read the latency table as a win for "
            + ", ".join(f"`{t}`" for t in failures)
            + ".** Its timings are real; its answers are not.",
        ]
    lines.append("")
    return lines


def _tiering_table(tiering: dict[str, Any] | None) -> list[str]:
    """Build the composed-pipeline / escalation table."""
    if not tiering:
        return [
            "## 4. Tiering",
            "",
            "_Skipped — needs `regex`, an `embed-cosine-*`, and a `clf-*` tier in the "
            "same run._",
            "",
        ]
    solo = tiering["classifier_alone_p50_ms"]
    lines = [
        "## 4. Tiering — does the classifier earn its keep?",
        "",
        f"Composed: `{tiering['regex_tier']}` → `{tiering['cosine_tier']}` → "
        f"`{tiering['classifier_tier']}` @ {tiering['clf_threshold']}.",
        "",
        "| cosine band (low, high) | escalation | escalated n | precision | recall | F1 | effective p50 (ms) | vs classifier-always |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for band in tiering["bands"]:
        speedup = f"{solo / band['effective_p50_ms']:.1f}×" if band["effective_p50_ms"] else "—"
        lines.append(
            f"| ({band['low']:.2f}, {band['high']:.2f}) | {_pct(band['escalation_rate'])} "
            f"| {band['escalated_n']} | {_fmt(band['precision'])} | {_fmt(band['recall'])} "
            f"| {_fmt(band['f1'])} | {_fmt(band['effective_p50_ms'], 3)} | {speedup} |"
        )
    lines += [
        "",
        f"*effective p50* = regex + cosine (always) + escalation × classifier. "
        f"Classifier-always would be {solo:.2f} ms p50 on every turn.",
        "",
        "Quality here is **measured, not projected**: escalated samples are scored "
        "with the classifier's real output, not assumed correct.",
        "",
    ]
    return lines


def build_report(payload: dict[str, Any]) -> str:
    """Render the full markdown report.

    Args:
        payload: The harness payload — ``corpus``, ``config``, ``results``,
            and optionally ``tiering`` / ``per_bucket``.

    Returns:
        A markdown document.
    """
    corpus = payload.get("corpus", {})
    config = payload.get("config", {})
    results = payload.get("results", [])

    lines = [
        "# Prompt-Injection Guardrail Benchmark",
        "",
        "Baseline for `PromptInjectionGuardrail` — regex vs embedding-similarity vs "
        "the deBERTa classifier under torch / ONNX / ONNX-int8.",
        "",
        "## Setup",
        "",
        f"- Classifier: `{config.get('classifier', '—')}`",
        f"- Embedder: `{config.get('embedder', '—')}`",
        f"- ORT / torch thread cap: `{config.get('intra_op_threads', '—')}` "
        "(BLAS/OMP pinned to 1)",
        f"- Timed passes: {config.get('repeats', '—')} × {corpus.get('total', '—')} samples "
        f"(warm-up {config.get('warmup', '—')})",
        f"- Per-tier process isolation: `{config.get('isolated', False)}`",
        f"- Python {config.get('python', '—')}",
        "",
        "Corpus: "
        + ", ".join(
            f"`{name}` {size}"
            for name, size in corpus.items()
            if name not in {"total", "seed_corpus"}
        )
        + f" — **{corpus.get('total', 0)} total**, seed catalogue "
        f"{corpus.get('seed_corpus', 0)} (held disjoint from every eval bucket).",
        "",
    ]

    lines += _cost_table(results)
    lines += _quality_table(results)
    lines += _parity_table(payload.get("parity"))
    lines += _bucket_table(payload.get("per_bucket", {}))
    lines += _tiering_table(payload.get("tiering"))

    lines += [
        "## Caveats",
        "",
        "- Single machine, single run — treat **ratios** as robust and absolute "
        "numbers as indicative, the same standard applied in "
        "`sdd/proposals/pii-detection-redaction.comparison.md` §6.",
        "- The corpus is synthetic and small (tens per bucket). It is built to "
        "expose *structural* blind spots (paraphrase, obfuscation, framework "
        "wrappers), not to estimate production accuracy.",
        "- Latency is measured per single call. Real seams may batch; a batched "
        "classifier amortises far better than these numbers suggest.",
        "- int8 dynamic quantization is calibration-free; static quantization with "
        "a calibration corpus would likely be faster still, and is untested here.",
        "",
    ]
    return "\n".join(lines)
