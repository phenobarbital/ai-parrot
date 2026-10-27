"""FEAT-761 jailbreak bake-off runner and pre-registered decision rule.

Usage (TASK-4832, needs network for the first download)::

    python -m benchmarks.injection_guardrail_latency.compare_jailbreak \
        --onnx-root <dir> --out benchmarks/injection_guardrail_latency/results-jailbreak
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from benchmarks.injection_guardrail_latency.detectors import (
    EmbedCosineDetector,
    TransformerDetector,
    pin_thread_env,
)
from benchmarks.injection_guardrail_latency.jailbreak_corpus import BUCKETS, JAILBREAK_EN, JAILBREAK_ES

ES_BENIGN_MAX_FP = 0
P50_BUDGET_MS = 30.0
LICENSE_RANK = {"apache-2.0": 0, "mit": 0, "llama4": 1}


@dataclass(frozen=True)
class Candidate:
    """One model admitted to the pre-registered bake-off matrix."""

    model_id: str
    kind: Literal["classifier", "embedding", "static"]
    license: str
    eligible: bool
    backend: str = "onnx"
    graph_path: str = "onnx/model.onnx"
    positive_labels: tuple[str, ...] = ("jailbreak", "malicious")
    note: str = ""


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        model_id="vllm-sr/mmbert32k-jailbreak-detector-merged",
        kind="classifier",
        license="apache-2.0",
        eligible=True,
    ),
    Candidate(
        model_id="madhurjindal/Jailbreak-Detector-Large",
        kind="classifier",
        license="mit",
        eligible=True,
        note="Requires a local ONNX export.",
    ),
    Candidate(
        model_id="gravitee-io/Llama-Prompt-Guard-2-86M-onnx",
        kind="classifier",
        license="llama4",
        eligible=True,
        graph_path="model.onnx",
        note="Conditional Llama attribution; fp32 graph only.",
    ),
    Candidate(
        model_id="enguard/medium-guard-128m-xx-prompt-jailbreak-binary-in-the-wild",
        kind="static",
        license="mit",
        eligible=True,
        backend="model2vec",
        graph_path="",
    ),
    Candidate(
        model_id="0dinai/jailbreak-embeddings-base-onnx",
        kind="embedding",
        license="none",
        eligible=False,
        note="No declared license; measurement only.",
    ),
    Candidate(
        model_id="protectai/deberta-v3-base-prompt-injection-v2",
        kind="classifier",
        license="apache-2.0",
        eligible=False,
        note="Prompt-injection baseline; excluded for Spanish benign false positives.",
    ),
)


@dataclass
class CandidateResult:
    """Measured scores, latency, memory, and provenance for one candidate."""

    candidate: Candidate
    scores: dict[str, list[float]] = field(default_factory=dict)
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    load_s: float = 0.0
    rss_mb: float = 0.0
    artifact_mb: float = 0.0
    sha256: str = ""
    revision: str = ""


class _Detector(Protocol):
    """Minimal detector interface consumed by the benchmark runner."""

    def load(self) -> None:
        """Load model artifacts."""

    def score(self, text: str) -> float:
        """Return a positive-class score in ``[0, 1]``."""


class _StaticModelDetector:
    """Adapter for an enguard model2vec classification pipeline."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._model: Any = None

    def load(self) -> None:
        """Load the optional model2vec classification pipeline lazily."""
        try:
            model2vec_inference = importlib.import_module("model2vec.inference")
            pipeline_type = model2vec_inference.StaticModelPipeline
        except (ImportError, AttributeError) as exc:
            raise RuntimeError("The enguard candidate requires model2vec with StaticModelPipeline support.") from exc
        self._model = pipeline_type.from_pretrained(self.model_id)

    def score(self, text: str) -> float:
        """Return the model2vec pipeline's positive-class probability."""
        probabilities = self._model.predict_proba([text])
        row = probabilities[0]
        return float(row[-1])


def _f1(scores: list[float], labels: list[int], threshold: float) -> float:
    """Calculate binary F1 for ``score >= threshold``."""
    true_positive = false_positive = false_negative = 0
    for score, label in zip(scores, labels, strict=True):
        predicted = int(score >= threshold)
        true_positive += int(predicted == 1 and label == 1)
        false_positive += int(predicted == 1 and label == 0)
        false_negative += int(predicted == 0 and label == 1)
    denominator = (2 * true_positive) + false_positive + false_negative
    return (2 * true_positive / denominator) if denominator else 0.0


def _language_samples(result: CandidateResult, language: str) -> tuple[list[float], list[int]]:
    """Collect all scored buckets for one language in corpus order."""
    scores: list[float] = []
    labels: list[int] = []
    for bucket_name, (items, label, bucket_language) in BUCKETS.items():
        if bucket_language != language:
            continue
        bucket_scores = result.scores.get(bucket_name, [])
        if len(bucket_scores) != len(items):
            raise ValueError(
                f"Candidate {result.candidate.model_id!r} has {len(bucket_scores)} scores for "
                f"{bucket_name!r}; expected {len(items)}"
            )
        scores.extend(bucket_scores)
        labels.extend([label] * len(items))
    return scores, labels


def _metrics_at(result: CandidateResult, threshold: float) -> dict[str, float]:
    """Calculate the pre-registered gate metrics at one threshold."""
    scores_en, labels_en = _language_samples(result, "en")
    scores_es, labels_es = _language_samples(result, "es")
    combined_scores = scores_en + scores_es
    combined_labels = labels_en + labels_es
    benign_es = result.scores["benign_es"]
    jailbreak_es = result.scores["jailbreak_es"]
    es_benign_fp = sum(score >= threshold for score in benign_es)
    recall_jailbreak_es = sum(score >= threshold for score in jailbreak_es) / len(jailbreak_es) if jailbreak_es else 0.0
    return {
        "f1_en": _f1(scores_en, labels_en, threshold),
        "f1_es": _f1(scores_es, labels_es, threshold),
        "f1_combined": _f1(combined_scores, combined_labels, threshold),
        "es_benign_fp": float(es_benign_fp),
        "recall_jailbreak_es": recall_jailbreak_es,
    }


def sweep_threshold(result: CandidateResult) -> tuple[float, dict[str, float]]:
    """Select maximum combined F1 among thresholds with zero benign-ES FPs.

    Returns:
        The selected ``(threshold, metrics)``. ``1.01`` and zeroed metrics
        are returned when none of the pre-registered thresholds satisfies
        the Spanish-benign gate.
    """
    all_scores = [score for bucket_scores in result.scores.values() for score in bucket_scores]
    candidates = sorted(set(all_scores) | {1.01})
    valid: list[tuple[float, dict[str, float]]] = []
    for threshold in candidates:
        metrics = _metrics_at(result, threshold)
        if int(metrics["es_benign_fp"]) <= ES_BENIGN_MAX_FP:
            valid.append((threshold, metrics))
    if not valid:
        return 1.01, {
            "f1_en": 0.0,
            "f1_es": 0.0,
            "f1_combined": 0.0,
            "es_benign_fp": float(len(result.scores.get("benign_es", []))),
            "recall_jailbreak_es": 0.0,
        }
    return max(valid, key=lambda item: (item[1]["f1_combined"], item[0]))


def evaluate_gate(
    result: CandidateResult,
    threshold: float,
    metrics: dict[str, float],
) -> tuple[bool, list[str]]:
    """Return whether eligibility, Spanish-benign, and latency gates pass."""
    del threshold
    reasons: list[str] = []
    if not result.candidate.eligible:
        reasons.append(f"not-eligible:{result.candidate.license}")
    es_benign_fp = int(metrics["es_benign_fp"])
    if es_benign_fp > ES_BENIGN_MAX_FP:
        reasons.append(f"es-benign-fp:{es_benign_fp}")
    if result.p50_ms > P50_BUDGET_MS:
        reasons.append(f"p50:{result.p50_ms:.2f}")
    return not reasons, reasons


def pick_winner(
    evaluated: list[tuple[CandidateResult, float, dict[str, float], bool]],
) -> CandidateResult | None:
    """Pick highest F1 among passing candidates, then license and size."""
    passing = [entry for entry in evaluated if entry[3] and entry[0].candidate.eligible]
    if not passing:
        return None
    winner = min(
        passing,
        key=lambda entry: (
            -entry[2]["f1_combined"],
            LICENSE_RANK.get(entry[0].candidate.license, 99),
            entry[0].artifact_mb,
            entry[0].candidate.model_id,
        ),
    )
    return winner[0]


def write_manifest(
    out_dir: str | Path,
    evaluated: list[tuple[CandidateResult, float, dict[str, float], bool]],
    winner: CandidateResult | None,
) -> None:
    """Write deterministic provenance manifest and raw benchmark results."""
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest_candidates: list[dict[str, Any]] = []
    raw_candidates: list[dict[str, Any]] = []
    for result, threshold, metrics, passes in evaluated:
        gate_passes, reasons = evaluate_gate(result, threshold, metrics)
        if gate_passes != passes:
            raise ValueError(f"Stale gate verdict for {result.candidate.model_id}")
        manifest_candidates.append(
            {
                "model_id": result.candidate.model_id,
                "revision": result.revision,
                "sha256": result.sha256,
                "license": result.candidate.license,
                "eligible": result.candidate.eligible,
                "threshold": threshold,
                "metrics": metrics,
                "verdict": "pass" if passes else "fail",
                "reasons": reasons,
            }
        )
        raw_candidates.append(
            {
                "model_id": result.candidate.model_id,
                "scores": result.scores,
                "p50_ms": result.p50_ms,
                "p95_ms": result.p95_ms,
                "load_s": result.load_s,
                "rss_mb": result.rss_mb,
                "artifact_mb": result.artifact_mb,
            }
        )
    manifest = {
        "winner": winner.candidate.model_id if winner is not None else None,
        "candidates": manifest_candidates,
    }
    results = {"candidates": raw_candidates}
    (output_path / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_path / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a local artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_candidate_detector(candidate: Candidate, model_root: Path) -> tuple[_Detector, Path | None]:
    """Construct one unloaded detector and resolve its hashed artifact."""
    if candidate.kind == "classifier":
        graph_path = model_root / candidate.model_id / candidate.graph_path
        detector = TransformerDetector(
            model_id=candidate.model_id,
            backend=candidate.backend,
            onnx_dir=graph_path.parent,
            intra_op_threads=1,
            inter_op_threads=1,
            max_length=512,
            positive_labels=candidate.positive_labels,
        )
        return detector, graph_path
    if candidate.kind == "embedding":
        detector = EmbedCosineDetector(
            seed_corpus=JAILBREAK_EN + JAILBREAK_ES,
            model_name=candidate.model_id,
            backend=candidate.backend,
        )
        graph_path = model_root / candidate.model_id / candidate.graph_path
        return detector, graph_path
    return _StaticModelDetector(candidate.model_id), None


def _measure_candidate(candidate: Candidate, model_root: Path) -> CandidateResult:
    """Load and measure one candidate over every committed corpus item."""
    psutil = importlib.import_module("psutil")
    huggingface_hub = importlib.import_module("huggingface_hub")
    detector, artifact_path = _build_candidate_detector(candidate, model_root)
    process = psutil.Process()
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    detector.load()
    load_s = time.perf_counter() - started
    rss_mb = max(0, process.memory_info().rss - rss_before) / (1024 * 1024)

    scores: dict[str, list[float]] = {}
    latencies_ms: list[float] = []
    for bucket_name, (items, _, _) in BUCKETS.items():
        bucket_scores: list[float] = []
        for item in items:
            started = time.perf_counter()
            bucket_scores.append(detector.score(item))
            latencies_ms.append((time.perf_counter() - started) * 1000)
        scores[bucket_name] = bucket_scores

    if artifact_path is not None and not artifact_path.is_file():
        raise FileNotFoundError(f"Candidate artifact not found: {artifact_path}")
    artifact_mb = artifact_path.stat().st_size / (1024 * 1024) if artifact_path is not None else 0.0
    sha256 = _sha256(artifact_path) if artifact_path is not None else ""
    model_info = huggingface_hub.model_info(candidate.model_id, files_metadata=True)
    revision = str(model_info.sha or "")
    if artifact_path is None:
        artifact_bytes = sum((sibling.size or 0) for sibling in (model_info.siblings or []))
        artifact_mb = artifact_bytes / (1024 * 1024)
    return CandidateResult(
        candidate=candidate,
        scores=scores,
        p50_ms=statistics.median(latencies_ms),
        p95_ms=statistics.quantiles(latencies_ms, n=100, method="inclusive")[94],
        load_s=load_s,
        rss_mb=rss_mb,
        artifact_mb=artifact_mb,
        sha256=sha256,
        revision=revision,
    )


def main() -> None:
    """Run all candidates, apply the gate, and write reproducible evidence."""
    pin_thread_env(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx-root", type=Path, required=True, help="Root containing candidate artifacts")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for JSON evidence")
    args = parser.parse_args()

    evaluated: list[tuple[CandidateResult, float, dict[str, float], bool]] = []
    for candidate in CANDIDATES:
        result = _measure_candidate(candidate, args.onnx_root)
        threshold, metrics = sweep_threshold(result)
        passes, _ = evaluate_gate(result, threshold, metrics)
        evaluated.append((result, threshold, metrics, passes))
    winner = pick_winner(evaluated)
    write_manifest(args.out, evaluated, winner)
    if winner is None:
        raise SystemExit("No eligible jailbreak candidate passed the pre-registered gate")


if __name__ == "__main__":
    main()
