"""Prompt-injection guardrail benchmark harness.

Measures, per tier: cold-load time, RSS cost, per-call latency
(p50/p95/p99), and detection quality on a labelled EN/ES corpus — then
composes the tiers into the pipeline proposed in
``sdd/proposals/nlproxy-guardrails.comparison.md`` §5.3 and reports the
**escalation rate**: how often the cheap tiers already decide, so the
classifier never runs.

Usage::

    source .venv/bin/activate

    # 1. Export the ONNX graphs (once)
    python -m benchmarks.injection_guardrail_latency.export \\
        --output-dir models/injection-clf

    # 2. Full run, one process per tier (clean RSS attribution)
    python -m benchmarks.injection_guardrail_latency.harness \\
        --onnx-dir models/injection-clf --isolate \\
        --output-dir benchmarks/injection_guardrail_latency/results

    # Quick smoke run, no models
    python -m benchmarks.injection_guardrail_latency.harness \\
        --tiers regex --repeats 3 --output-dir /tmp/bench

Thread affinity
---------------
BLAS/OMP thread counts are pinned to 1 at *import time* so numbers are
reproducible across machines with different core counts. ONNX Runtime and
torch are capped separately via ``--intra-op-threads``.
"""
from __future__ import annotations

# ── Pin BLAS/OMP threads BEFORE numpy/torch import ──────────────────────────
from .detectors import pin_thread_env

pin_thread_env(1)
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import gc
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import corpus as corpus_mod
from .detectors import ALL_TIERS, DEFAULT_CLASSIFIER, DEFAULT_EMBEDDER, build_detector
from .metrics import (
    current_rss_mb,
    effective_latency_ms,
    latency_percentiles,
    peak_rss_mb,
    quality,
    sweep_thresholds,
)
from .report import build_report

logger = logging.getLogger("benchmarks.injection_guardrail_latency.harness")

#: The threshold each tier is evaluated at by default. ``clf-*`` uses the
#: value AI-Parrot ships today (``injection_probability_threshold=0.98``,
#: see ``bots/guardrails/builtin/prompt_injection.py``) — whether that is
#: the right operating point is one of the questions this benchmark exists
#: to answer, so the sweep below reports every alternative too.
PRODUCTION_THRESHOLDS: dict[str, float] = {
    "regex": 0.9,
    "embed-cosine": 0.85,
    "clf": 0.98,
}

#: Thresholds explored for every tier.
SWEEP_GRID: list[float] = [
    0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.65, 0.70, 0.75,
    0.80, 0.85, 0.90, 0.95, 0.98, 0.99,
]

#: Candidate (low, high) cosine bands for the tiering analysis. Below
#: ``low`` the middle tier calls it benign; at or above ``high`` it calls
#: it an attack; in between the classifier is consulted.
#:
#: Calibrated against the measured cosine distribution (2026-08-20), NOT
#: against NLProxy's published 0.85 similarity threshold. At 0.85 this
#: tier's recall on held-out attacks is 0.02 — their threshold only works
#: against a corpus that contains near-duplicates of the eval set. Useful
#: separation on a disjoint corpus lives around 0.30-0.55.
ESCALATION_BANDS: list[tuple[float, float]] = [
    (0.20, 0.45),
    (0.25, 0.50),
    (0.30, 0.55),
    (0.30, 0.60),
    (0.35, 0.60),
]

WARMUP_RUNS: int = 5
MIN_REPEATS: int = 10


def _preimport_framework() -> None:
    """Import AI-Parrot's security package before any RSS measurement.

    In a real bot process ``parrot.security`` is already resident, so
    charging its ~90 MB import cost to the `regex` tier would overstate
    that tier by three orders of magnitude. Importing it up front makes
    every tier's ``rss_delta_mb`` the *marginal* cost of enabling it.
    """
    try:
        import parrot.security.prompt_injection  # noqa: F401  # pylint: disable=unused-import
    except Exception as exc:  # noqa: BLE001 - benchmark convenience only
        logger.warning("Could not pre-import parrot.security (%s); regex RSS will be inflated", exc)


def _production_threshold(tier: str) -> float:
    """Return the default decision threshold for *tier*."""
    for prefix, value in PRODUCTION_THRESHOLDS.items():
        if tier.startswith(prefix):
            return value
    return 0.5


# ---------------------------------------------------------------------------
# Single-tier measurement
# ---------------------------------------------------------------------------


def run_tier(
    tier: str,
    texts: list[str],
    labels: list[int],
    *,
    seed_corpus: list[str],
    classifier_id: str,
    embedder_id: str,
    onnx_dir: Path | None,
    intra_op_threads: int,
    n_warmup: int,
    n_repeats: int,
) -> dict[str, Any]:
    """Benchmark one tier end to end.

    Args:
        tier: Tier name (see :data:`~.detectors.ALL_TIERS`).
        texts: Evaluation texts.
        labels: Ground-truth labels aligned with *texts*.
        seed_corpus: Attack catalogue for the cosine tier.
        classifier_id: HF id of the classifier under test.
        embedder_id: HF id of the sentence encoder.
        onnx_dir: Directory of exported ONNX graphs.
        intra_op_threads: ORT/torch thread cap.
        n_warmup: Warm-up calls discarded before timing.
        n_repeats: Timed passes over the whole corpus.

    Returns:
        A result dict. ``error`` is populated (and the metric fields left
        ``None``) when the tier could not run — a missing ONNX graph or an
        uninstalled backend degrades this tier only, never the whole run.
    """
    result: dict[str, Any] = {
        "tier": tier,
        "load_s": None,
        "rss_delta_mb": None,
        "peak_rss_mb": None,
        "latency": None,
        "quality": None,
        "sweep": None,
        "scores": None,
        "n_samples": len(texts),
        "error": None,
    }

    try:
        detector = build_detector(
            tier,
            seed_corpus=seed_corpus,
            classifier_id=classifier_id,
            embedder_id=embedder_id,
            onnx_dir=onnx_dir,
            intra_op_threads=intra_op_threads,
        )
    except Exception as exc:  # noqa: BLE001 - per-tier degradation
        result["error"] = f"build_failed: {exc}"
        logger.error("[%s] build failed: %s", tier, exc)
        return result

    gc.collect()
    rss_before = current_rss_mb()
    logger.info("[%s] loading …", tier)
    load_start = time.perf_counter()
    try:
        detector.load()
    except Exception as exc:  # noqa: BLE001 - per-tier degradation
        result["error"] = f"load_failed: {exc}"
        logger.error("[%s] load failed: %s", tier, exc)
        return result
    result["load_s"] = round(time.perf_counter() - load_start, 3)
    gc.collect()
    result["rss_delta_mb"] = round(current_rss_mb() - rss_before, 1)
    logger.info(
        "[%s] loaded in %.2fs (+%.1f MB RSS)", tier, result["load_s"], result["rss_delta_mb"]
    )

    # Warm-up — JIT, lazy kernels, allocator churn.
    try:
        for i in range(n_warmup):
            detector.score(texts[i % len(texts)])
    except Exception as exc:  # noqa: BLE001 - per-tier degradation
        result["error"] = f"warmup_failed: {exc}"
        logger.error("[%s] warm-up failed: %s", tier, exc)
        return result

    # Timed passes. Scores are captured on the first pass only — they are
    # deterministic, and re-collecting them every pass would just grow the
    # result payload.
    timings: list[float] = []
    scores: list[float] = []
    try:
        for pass_index in range(n_repeats):
            for i, text in enumerate(texts):
                start = time.perf_counter()
                score = detector.score(text)
                timings.append(time.perf_counter() - start)
                if pass_index == 0:
                    scores.append(float(score))
    except Exception as exc:  # noqa: BLE001 - per-tier degradation
        result["error"] = f"bench_failed: {exc}"
        logger.error("[%s] bench failed: %s", tier, exc)
        return result

    result["latency"] = {k: round(v, 4) for k, v in latency_percentiles(timings).items()}
    result["peak_rss_mb"] = round(peak_rss_mb(), 1)
    result["scores"] = [round(s, 6) for s in scores]

    threshold = _production_threshold(tier)
    result["quality"] = {k: round(v, 4) for k, v in quality(scores, labels, threshold).items()}
    result["sweep"] = [
        {k: round(v, 4) for k, v in entry.items()}
        for entry in sweep_thresholds(scores, labels, SWEEP_GRID)
    ]

    logger.info(
        "[%s] p50=%.2fms p95=%.2fms p99=%.2fms | @%.2f P=%.2f R=%.2f F1=%.2f",
        tier,
        result["latency"]["p50_ms"],
        result["latency"]["p95_ms"],
        result["latency"]["p99_ms"],
        threshold,
        result["quality"]["precision"],
        result["quality"]["recall"],
        result["quality"]["f1"],
    )
    return result


# ---------------------------------------------------------------------------
# Tiering analysis
# ---------------------------------------------------------------------------


def analyse_tiering(
    results: list[dict[str, Any]],
    labels: list[int],
    *,
    clf_threshold: float,
) -> dict[str, Any] | None:
    """Compose regex + cosine + classifier and measure the escalation rate.

    The composed rule, per sample:

    1. ``regex >= 0.9``          -> attack (decided, classifier skipped)
    2. ``cosine >= high``        -> attack (decided)
    3. ``cosine <= low``         -> benign (decided)
    4. otherwise                 -> classifier verdict at *clf_threshold*

    Quality is computed from the **actual** classifier scores for the
    escalated samples, so the reported end-to-end numbers are measured,
    not projected.

    Args:
        results: Per-tier results from :func:`run_tier`.
        labels: Ground-truth labels.
        clf_threshold: Decision threshold for the classifier tier.

    Returns:
        A dict with one entry per candidate band, or ``None`` when the
        three required tiers are not all present in *results*.
    """
    by_tier = {r["tier"]: r for r in results if r.get("scores")}
    regex = by_tier.get("regex")
    cosine = next(
        (r for name, r in by_tier.items() if name.startswith("embed-cosine")), None
    )
    classifier = next(
        (r for name, r in by_tier.items() if name.startswith("clf-")), None
    )
    if not (regex and cosine and classifier):
        missing = [
            name
            for name, present in (
                ("regex", regex), ("embed-cosine-*", cosine), ("clf-*", classifier)
            )
            if not present
        ]
        logger.warning("Tiering analysis skipped — missing tiers: %s", ", ".join(missing))
        return None

    regex_scores = regex["scores"]
    cosine_scores = cosine["scores"]
    clf_scores = classifier["scores"]

    bands: list[dict[str, Any]] = []
    for low, high in ESCALATION_BANDS:
        verdicts: list[int] = []
        decided: list[bool] = []
        for r_score, c_score, k_score in zip(regex_scores, cosine_scores, clf_scores):
            if r_score >= 0.9 or c_score >= high:
                verdicts.append(1)
                decided.append(True)
            elif c_score <= low:
                verdicts.append(0)
                decided.append(True)
            else:
                verdicts.append(1 if k_score >= clf_threshold else 0)
                decided.append(False)

        escalated = sum(1 for d in decided if not d)
        rate = escalated / len(decided) if decided else 0.0
        composed = quality(verdicts, labels, 0.5)
        effective = effective_latency_ms(
            [regex["latency"]["p50_ms"], cosine["latency"]["p50_ms"]],
            rate,
            classifier["latency"]["p50_ms"],
        )
        bands.append({
            "low": low,
            "high": high,
            "escalation_rate": round(rate, 4),
            "escalated_n": escalated,
            "precision": round(composed["precision"], 4),
            "recall": round(composed["recall"], 4),
            "f1": round(composed["f1"], 4),
            "accuracy": round(composed["accuracy"], 4),
            "effective_p50_ms": round(effective, 3),
        })

    return {
        "regex_tier": regex["tier"],
        "cosine_tier": cosine["tier"],
        "classifier_tier": classifier["tier"],
        "clf_threshold": clf_threshold,
        "classifier_alone_p50_ms": classifier["latency"]["p50_ms"],
        "bands": bands,
    }


def analyse_parity(
    results: list[dict[str, Any]],
    *,
    reference_tier: str = "clf-torch",
    threshold: float,
    max_abs_delta: float = 0.05,
    max_disagreement: float = 0.02,
) -> dict[str, Any] | None:
    """Compare every classifier backend's scores against a reference.

    A quantized or re-exported graph that is faster but no longer produces
    the reference model's answers is a regression wearing a speed-up's
    clothes. This gate makes that failure impossible to report as a win:
    the backends run the same weights on the same inputs, so their scores
    must agree within numerical noise.

    Args:
        results: Per-tier results from :func:`run_tier`.
        reference_tier: Tier whose scores define ground truth (the
            unquantized PyTorch path).
        threshold: Decision threshold used for the verdict-disagreement
            rate.
        max_abs_delta: Largest per-sample score difference tolerated.
        max_disagreement: Largest fraction of flipped verdicts tolerated.

    Returns:
        ``{tier: {...}}`` with per-backend deltas and a ``parity_ok`` flag,
        or ``None`` when the reference tier has no scores in this run.
    """
    by_tier = {r["tier"]: r for r in results if r.get("scores")}
    reference = by_tier.get(reference_tier)
    if reference is None:
        logger.warning("Parity gate skipped — reference tier %r absent", reference_tier)
        return None

    ref_scores = reference["scores"]
    report: dict[str, Any] = {}
    for tier, result in by_tier.items():
        if tier == reference_tier or not tier.startswith("clf-"):
            continue
        scores = result["scores"]
        if len(scores) != len(ref_scores):
            report[tier] = {"error": "sample count mismatch", "parity_ok": False}
            continue
        deltas = [abs(a - b) for a, b in zip(ref_scores, scores)]
        flips = sum(
            1 for a, b in zip(ref_scores, scores)
            if (a >= threshold) != (b >= threshold)
        )
        disagreement = flips / len(scores)
        worst = max(deltas)
        parity_ok = worst <= max_abs_delta and disagreement <= max_disagreement
        report[tier] = {
            "reference": reference_tier,
            "max_abs_delta": round(worst, 4),
            "mean_abs_delta": round(sum(deltas) / len(deltas), 4),
            "verdict_disagreement": round(disagreement, 4),
            "flipped_verdicts": flips,
            "parity_ok": parity_ok,
        }
        if not parity_ok:
            logger.error(
                "[%s] PARITY FAILED vs %s — max|Δ|=%.3f, %d/%d verdicts flipped. "
                "Its latency numbers are real but the graph does not compute the "
                "same function; do not report it as a speed-up.",
                tier, reference_tier, worst, flips, len(scores),
            )
    return report


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def _run_isolated(tier: str, argv_common: list[str]) -> dict[str, Any]:
    """Run one tier in a fresh subprocess and return its result dict.

    Peak RSS is monotonic per process, so attributing memory to a single
    model requires one process per tier.

    Args:
        tier: The tier to run.
        argv_common: Arguments to forward to the child.

    Returns:
        The child's result dict, or an error stub if the child failed.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        child_out = Path(handle.name)
    cmd = [
        sys.executable, "-m", "benchmarks.injection_guardrail_latency.harness",
        "--tiers", tier, "--child-result-json", str(child_out), *argv_common,
    ]
    logger.info("[%s] spawning isolated child …", tier)
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        logger.error("[%s] child exited %d:\n%s", tier, completed.returncode, completed.stderr[-2000:])
        return {"tier": tier, "error": f"child_exit_{completed.returncode}", "scores": None}
    try:
        payload = json.loads(child_out.read_text())
        return payload["results"][0]
    except Exception as exc:  # noqa: BLE001 - child contract
        logger.error("[%s] unreadable child result: %s", tier, exc)
        return {"tier": tier, "error": f"child_result_unreadable: {exc}", "scores": None}
    finally:
        child_out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (``0`` unless every tier failed).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiers", nargs="+", default=ALL_TIERS, help=f"Subset of {ALL_TIERS}")
    parser.add_argument("--output-dir", type=Path, default=None, help="Where to write results.json + report.md")
    parser.add_argument("--onnx-dir", type=Path, default=Path("models/injection-clf"))
    parser.add_argument("--classifier", default=DEFAULT_CLASSIFIER)
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    parser.add_argument("--warmup", type=int, default=WARMUP_RUNS)
    parser.add_argument("--repeats", type=int, default=MIN_REPEATS, help="Timed passes over the corpus")
    parser.add_argument("--intra-op-threads", type=int, default=2, help="ORT/torch thread cap (0 = library default)")
    parser.add_argument("--clf-threshold", type=float, default=PRODUCTION_THRESHOLDS["clf"])
    parser.add_argument("--isolate", action="store_true", help="Run each tier in its own process (clean RSS)")
    parser.add_argument(
        "--reanalyse",
        type=Path,
        default=None,
        help=(
            "Recompute tiering/parity/report from a prior results.json instead of "
            "re-running any model. Threshold and band tuning should not cost minutes "
            "of inference."
        ),
    )
    parser.add_argument("--child-result-json", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.reanalyse is not None:
        return _reanalyse(args)

    _preimport_framework()
    corpus_mod.assert_seed_disjoint()
    texts, labels, buckets = corpus_mod.build_eval_set()
    summary = corpus_mod.corpus_summary()
    logger.info(
        "Corpus: %d samples (%d benign, %d injection), seed catalogue %d",
        summary["total"],
        sum(1 for label in labels if label == 0),
        sum(1 for label in labels if label == 1),
        summary["seed_corpus"],
    )

    common_argv = [
        "--onnx-dir", str(args.onnx_dir),
        "--classifier", args.classifier,
        "--embedder", args.embedder,
        "--warmup", str(args.warmup),
        "--repeats", str(args.repeats),
        "--intra-op-threads", str(args.intra_op_threads),
        "--clf-threshold", str(args.clf_threshold),
    ]

    results: list[dict[str, Any]] = []
    for tier in args.tiers:
        if args.isolate and args.child_result_json is None:
            results.append(_run_isolated(tier, common_argv))
            continue
        results.append(run_tier(
            tier, texts, labels,
            seed_corpus=corpus_mod.ATTACK_SEED_CORPUS,
            classifier_id=args.classifier,
            embedder_id=args.embedder,
            onnx_dir=args.onnx_dir,
            intra_op_threads=args.intra_op_threads,
            n_warmup=args.warmup,
            n_repeats=args.repeats,
        ))

    payload: dict[str, Any] = {
        "corpus": summary,
        "config": {
            "classifier": args.classifier,
            "embedder": args.embedder,
            "intra_op_threads": args.intra_op_threads,
            "clf_threshold": args.clf_threshold,
            "repeats": args.repeats,
            "warmup": args.warmup,
            "isolated": bool(args.isolate),
            "python": sys.version.split()[0],
        },
        "results": results,
    }

    # A child process reports only its own tier; the parent composes.
    if args.child_result_json is not None:
        args.child_result_json.write_text(json.dumps(payload))
        return 0

    payload["parity"] = analyse_parity(results, threshold=args.clf_threshold)
    payload["tiering"] = analyse_tiering(results, labels, clf_threshold=args.clf_threshold)
    payload["per_bucket"] = _per_bucket_recall(results, buckets)

    report = build_report(payload)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2))
        (args.output_dir / "report.md").write_text(report)
        logger.info("Wrote %s/results.json and report.md", args.output_dir)
    print(report)

    return 0 if any(r.get("error") is None for r in results) else 1


def _reanalyse(args: argparse.Namespace) -> int:
    """Recompute the analysis layer from a stored ``results.json``.

    Per-sample scores are already persisted, so band calibration, threshold
    choice, and the parity gate can all be re-derived without touching a
    model. Latency and RSS figures are carried through untouched from the
    original run.

    Args:
        args: Parsed CLI namespace; ``reanalyse`` points at the stored file.

    Returns:
        Process exit code.
    """
    payload = json.loads(args.reanalyse.read_text())
    _, labels, buckets = corpus_mod.build_eval_set()
    results = payload["results"]

    stored = payload["results"][0].get("n_samples")
    if stored is not None and stored != len(labels):
        logger.error(
            "Stored run has %d samples but the current corpus has %d — the corpus "
            "changed since that run; re-run the harness instead of reanalysing.",
            stored, len(labels),
        )
        return 1

    threshold = args.clf_threshold
    for result in results:
        scores = result.get("scores")
        if not scores:
            continue
        tier_threshold = _production_threshold(result["tier"])
        result["quality"] = {
            k: round(v, 4) for k, v in quality(scores, labels, tier_threshold).items()
        }
        result["sweep"] = [
            {k: round(v, 4) for k, v in entry.items()}
            for entry in sweep_thresholds(scores, labels, SWEEP_GRID)
        ]

    payload["parity"] = analyse_parity(results, threshold=threshold)
    payload["tiering"] = analyse_tiering(results, labels, clf_threshold=threshold)
    payload["per_bucket"] = _per_bucket_recall(results, buckets)
    payload.setdefault("config", {})["reanalysed"] = True

    report = build_report(payload)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "results.json").write_text(json.dumps(payload, indent=2))
        (args.output_dir / "report.md").write_text(report)
        logger.info("Rewrote %s/results.json and report.md", args.output_dir)
    print(report)
    return 0


def _per_bucket_recall(
    results: list[dict[str, Any]],
    buckets: list[str],
) -> dict[str, dict[str, float]]:
    """Per-bucket hit rate for each tier at its production threshold.

    Answers the question the aggregate F1 hides: *which* attacks does the
    regex tier miss, and does the cosine tier actually catch the
    paraphrases it exists for?

    Args:
        results: Per-tier results.
        buckets: Bucket name per sample.

    Returns:
        ``{tier: {bucket: flag_rate}}`` — for benign buckets the rate is
        the false-positive rate; for attack buckets it is recall.
    """
    output: dict[str, dict[str, float]] = {}
    for result in results:
        scores = result.get("scores")
        if not scores:
            continue
        threshold = _production_threshold(result["tier"])
        per_bucket: dict[str, list[int]] = {}
        for score, bucket in zip(scores, buckets):
            per_bucket.setdefault(bucket, []).append(1 if score >= threshold else 0)
        output[result["tier"]] = {
            bucket: round(sum(flags) / len(flags), 4) for bucket, flags in per_bucket.items()
        }
    return output


if __name__ == "__main__":
    sys.exit(main())
