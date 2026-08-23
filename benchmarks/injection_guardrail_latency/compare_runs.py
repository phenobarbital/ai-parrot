"""Compare the per-sample scores of two benchmark runs.

The harness computes *parity* only within a single run — it compares
backends against a reference tier that ran in the same process, over the
same corpus, with the same weights. That answers "did the ONNX export
preserve the model?" but it cannot answer "did switching the model change
what we block?", because the two models were never in the same run.

This module closes that gap. It aligns the per-sample ``scores`` arrays of
two ``results.json`` files by corpus index and reports the verdict delta at
the production threshold, bucket by bucket.

Holding the *backend* constant (``clf-torch`` on both sides) isolates the
model change; holding the *model* constant isolates the backend change.

Example:
    python -m benchmarks.injection_guardrail_latency.compare_runs \
        --baseline benchmarks/injection_guardrail_latency/results/results.json \
        --candidate benchmarks/injection_guardrail_latency/results-v2/results.json \
        --tier clf-torch
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Final

from .corpus import build_eval_set

logger = logging.getLogger(__name__)

#: Production decision threshold, mirroring ``PRODUCTION_THRESHOLDS["clf"]``.
DEFAULT_THRESHOLD: Final[float] = 0.98


def load_run(path: Path) -> dict[str, Any]:
    """Load a harness ``results.json``.

    Args:
        path: Path to the file written by ``harness.py``.

    Returns:
        The parsed run document.

    Raises:
        SystemExit: If the file is missing or unparseable.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read run at {path}: {exc}") from exc


def extract_scores(run: dict[str, Any], tier: str, origin: str) -> list[float]:
    """Pull one tier's per-sample scores out of a run document.

    Args:
        run: A parsed ``results.json``.
        tier: Tier name to extract, e.g. ``"clf-torch"``.
        origin: Human-readable label for error messages.

    Returns:
        The tier's per-sample scores, in corpus order.

    Raises:
        SystemExit: If the tier is absent, errored, or carries no scores.
    """
    for entry in run.get("results", []):
        if entry.get("tier") != tier:
            continue
        if entry.get("error"):
            raise SystemExit(f"{origin}: tier {tier!r} failed: {entry['error']}")
        scores = entry.get("scores")
        if not scores:
            raise SystemExit(f"{origin}: tier {tier!r} recorded no per-sample scores")
        return [float(value) for value in scores]

    available = sorted(e.get("tier", "?") for e in run.get("results", []))
    raise SystemExit(f"{origin}: no tier {tier!r}; run has {available}")


def assert_same_corpus(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Fail loudly if the two runs did not score the same corpus.

    Aligning scores by index is only meaningful when both runs enumerated
    the same samples in the same order. The corpus summary is the cheapest
    available proxy for that.

    Args:
        baseline: Parsed baseline run.
        candidate: Parsed candidate run.

    Raises:
        SystemExit: If the corpus summaries differ.
    """
    left = baseline.get("corpus", {})
    right = candidate.get("corpus", {})
    if left != right:
        raise SystemExit(
            "Refusing to compare: the runs scored different corpora.\n"
            f"  baseline:  {left}\n"
            f"  candidate: {right}"
        )


def compare(
    baseline_scores: list[float],
    candidate_scores: list[float],
    threshold: float,
) -> dict[str, Any]:
    """Compute the per-bucket verdict delta between two score arrays.

    Args:
        baseline_scores: Per-sample scores from the baseline run.
        candidate_scores: Per-sample scores from the candidate run.
        threshold: Decision threshold; ``score >= threshold`` is an attack.

    Returns:
        A dict with overall score-delta statistics, per-bucket verdict
        counts, and the individual samples whose verdict flipped.

    Raises:
        SystemExit: If the two arrays disagree with each other or with the
            corpus on length.
    """
    texts, labels, buckets = build_eval_set()
    if not len(baseline_scores) == len(candidate_scores) == len(texts):
        raise SystemExit(
            "Score arrays are not aligned with the corpus: "
            f"baseline={len(baseline_scores)}, candidate={len(candidate_scores)}, "
            f"corpus={len(texts)}"
        )

    per_bucket: dict[str, dict[str, int]] = {}
    flips: list[dict[str, Any]] = []
    deltas: list[float] = []

    for index, (text, label, bucket) in enumerate(zip(texts, labels, buckets)):
        before = baseline_scores[index]
        after = candidate_scores[index]
        deltas.append(after - before)

        stats = per_bucket.setdefault(
            bucket,
            {"n": 0, "flips": 0, "gained": 0, "lost": 0, "base_tp": 0, "cand_tp": 0},
        )
        stats["n"] += 1

        base_attack = before >= threshold
        cand_attack = after >= threshold
        # "Correct" means the verdict matches the label (1 = injection).
        if base_attack == bool(label):
            stats["base_tp"] += 1
        if cand_attack == bool(label):
            stats["cand_tp"] += 1

        if base_attack == cand_attack:
            continue

        stats["flips"] += 1
        # Gained = the candidate is now right where the baseline was wrong.
        improved = cand_attack == bool(label)
        stats["gained" if improved else "lost"] += 1
        flips.append(
            {
                "index": index,
                "bucket": bucket,
                "label": label,
                "baseline_score": round(before, 6),
                "candidate_score": round(after, 6),
                "baseline_verdict": "attack" if base_attack else "benign",
                "candidate_verdict": "attack" if cand_attack else "benign",
                "improved": improved,
                "text": text[:120],
            }
        )

    abs_deltas = [abs(value) for value in deltas]
    return {
        "threshold": threshold,
        "n_samples": len(texts),
        "max_abs_delta": round(max(abs_deltas), 6),
        "mean_abs_delta": round(sum(abs_deltas) / len(abs_deltas), 6),
        "flipped_verdicts": len(flips),
        "verdict_disagreement": round(len(flips) / len(texts), 6),
        "gained": sum(1 for flip in flips if flip["improved"]),
        "lost": sum(1 for flip in flips if not flip["improved"]),
        "per_bucket": per_bucket,
        "flips": flips,
    }


def render(
    delta: dict[str, Any],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    tiers: tuple[str, str],
) -> str:
    """Render the comparison as a markdown report.

    Args:
        delta: The dict returned by :func:`compare`.
        baseline: Parsed baseline run, for its config header.
        candidate: Parsed candidate run, for its config header.
        tiers: The ``(baseline_tier, candidate_tier)`` pair compared.

    Returns:
        A markdown document.
    """
    base_cfg = baseline.get("config", {})
    cand_cfg = candidate.get("config", {})
    lines: list[str] = [
        "# Run comparison — per-sample verdict delta",
        "",
        "|  | baseline | candidate |",
        "|---|---|---|",
        f"| classifier | `{base_cfg.get('classifier')}` | `{cand_cfg.get('classifier')}` |",
        f"| tier | `{tiers[0]}` | `{tiers[1]}` |",
        f"| threshold | {delta['threshold']} | {delta['threshold']} |",
        "",
        "## Score delta",
        "",
        f"- samples: **{delta['n_samples']}**",
        f"- max |Δ|: **{delta['max_abs_delta']}**",
        f"- mean |Δ|: **{delta['mean_abs_delta']}**",
        (
            f"- flipped verdicts: **{delta['flipped_verdicts']}** "
            f"({delta['verdict_disagreement']:.1%})"
        ),
        f"- of which better: **{delta['gained']}**, worse: **{delta['lost']}**",
        "",
        "## Per bucket",
        "",
        "| bucket | n | correct (baseline) | correct (candidate) | flips | better | worse |",
        "|---|---|---|---|---|---|---|",
    ]
    for bucket, stats in delta["per_bucket"].items():
        lines.append(
            f"| `{bucket}` | {stats['n']} | {stats['base_tp']}/{stats['n']} | "
            f"{stats['cand_tp']}/{stats['n']} | {stats['flips']} | "
            f"{stats['gained']} | {stats['lost']} |"
        )

    lines += ["", "## Flipped samples", ""]
    if not delta["flips"]:
        lines.append("_None — the two runs agree on every verdict._")
    else:
        lines += [
            "| bucket | label | baseline | candidate | Δ | better? | text |",
            "|---|---|---|---|---|---|---|",
        ]
        for flip in delta["flips"]:
            change = flip["candidate_score"] - flip["baseline_score"]
            label = "injection" if flip["label"] else "benign"
            text = flip["text"].replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{flip['bucket']}` | {label} | "
                f"{flip['baseline_verdict']} ({flip['baseline_score']:.4f}) | "
                f"{flip['candidate_verdict']} ({flip['candidate_score']:.4f}) | "
                f"{change:+.4f} | {'yes' if flip['improved'] else 'NO'} | {text} |"
            )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline results.json")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate results.json")
    parser.add_argument("--tier", default="clf-torch", help="Tier to compare on both sides")
    parser.add_argument("--baseline-tier", default=None, help="Override the baseline tier")
    parser.add_argument("--candidate-tier", default=None, help="Override the candidate tier")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--output", type=Path, default=None, help="Write markdown here too")
    parser.add_argument("--json", type=Path, default=None, help="Write the raw delta here")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    baseline = load_run(args.baseline)
    candidate = load_run(args.candidate)
    assert_same_corpus(baseline, candidate)

    base_tier = args.baseline_tier or args.tier
    cand_tier = args.candidate_tier or args.tier

    base_model = baseline.get("config", {}).get("classifier")
    cand_model = candidate.get("config", {}).get("classifier")
    if base_model == cand_model and base_tier == cand_tier:
        logger.warning(
            "Baseline and candidate are the same model on the same tier (%s) — "
            "this comparison measures nothing.",
            base_model,
        )

    delta = compare(
        extract_scores(baseline, base_tier, "baseline"),
        extract_scores(candidate, cand_tier, "candidate"),
        args.threshold,
    )
    report = render(delta, baseline, candidate, (base_tier, cand_tier))
    print(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        logger.info("Wrote %s", args.output)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(delta, indent=2), encoding="utf-8")
        logger.info("Wrote %s", args.json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
