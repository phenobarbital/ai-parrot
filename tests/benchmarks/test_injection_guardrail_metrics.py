"""Unit tests for the injection-guardrail benchmark's pure helpers.

Covers only the dependency-free parts — metrics and corpus assembly — so
the suite runs without torch, onnxruntime, or any model download. The
measurement loop itself is exercised by running the harness.

Import strategy mirrors ``test_benchmark_metrics.py``: the modules are
loaded via ``importlib.util.spec_from_file_location`` because this
``tests/benchmarks/`` directory otherwise shadows the repo-root
``benchmarks/`` package on ``sys.path``.
"""
from __future__ import annotations

import hashlib
import importlib.util as _ilu
import json
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[2]
_BENCH_DIR = _REPO_ROOT / "benchmarks" / "injection_guardrail_latency"


def _ensure_package_stub(package_name: str, path: Path | None = None) -> None:
    """Register a namespace stub in ``sys.modules`` when absent."""
    if package_name in sys.modules:
        return
    stub = types.ModuleType(package_name)
    if path is not None:
        stub.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[package_name] = stub


def _load_bench_module(name: str):
    """Load a benchmark sub-module by stem, bypassing ``sys.path``.

    Args:
        name: Sub-module stem, e.g. ``"metrics"`` or ``"corpus"``.

    Returns:
        The loaded module object.
    """
    full_name = f"benchmarks.injection_guardrail_latency.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    _ensure_package_stub("benchmarks", _REPO_ROOT / "benchmarks")
    _ensure_package_stub("benchmarks.injection_guardrail_latency", _BENCH_DIR)
    spec = _ilu.spec_from_file_location(full_name, str(_BENCH_DIR / f"{name}.py"))
    module = _ilu.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_metrics = _load_bench_module("metrics")
corpus_mod = _load_bench_module("corpus")

best_threshold = _metrics.best_threshold
confusion = _metrics.confusion
effective_latency_ms = _metrics.effective_latency_ms
escalation_rate = _metrics.escalation_rate
latency_percentiles = _metrics.latency_percentiles
quality = _metrics.quality
sweep_thresholds = _metrics.sweep_thresholds


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


def test_latency_percentiles_ordering() -> None:
    """p50 <= p95 <= p99 <= max, and seconds are reported as milliseconds."""
    timings = [i / 1000 for i in range(1, 101)]  # 1 ms .. 100 ms
    stats = latency_percentiles(timings)
    assert stats["p50_ms"] <= stats["p95_ms"] <= stats["p99_ms"] <= stats["max_ms"]
    assert stats["n"] == 100
    assert stats["max_ms"] == pytest.approx(100.0)
    assert stats["mean_ms"] == pytest.approx(50.5)


def test_latency_percentiles_single_sample() -> None:
    """A single sample makes every percentile that same value."""
    stats = latency_percentiles([0.005])
    assert stats["p50_ms"] == pytest.approx(5.0)
    assert stats["p99_ms"] == pytest.approx(5.0)


def test_latency_percentiles_rejects_empty() -> None:
    with pytest.raises(ValueError):
        latency_percentiles([])


# ---------------------------------------------------------------------------
# Detection quality
# ---------------------------------------------------------------------------


def test_confusion_counts() -> None:
    scores = [0.9, 0.1, 0.8, 0.2]
    labels = [1, 0, 0, 1]
    counts = confusion(scores, labels, threshold=0.5)
    assert counts == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


def test_quality_perfect_separation() -> None:
    scores = [0.99, 0.98, 0.01, 0.02]
    labels = [1, 1, 0, 0]
    result = quality(scores, labels, threshold=0.5)
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0
    assert result["accuracy"] == 1.0


def test_quality_threshold_above_every_score_is_zero_recall() -> None:
    """The failure mode the 0.98 production threshold risks."""
    scores = [0.90, 0.85, 0.10]
    labels = [1, 1, 0]
    result = quality(scores, labels, threshold=0.98)
    assert result["recall"] == 0.0
    assert result["fn"] == 2.0
    # No positives predicted at all -> precision is defined as 0.0, not NaN.
    assert result["precision"] == 0.0


def test_sweep_and_best_threshold_prefers_higher_on_ties() -> None:
    """Ties break toward the higher threshold (fewer false positives)."""
    scores = [0.9, 0.9, 0.1, 0.1]
    labels = [1, 1, 0, 0]
    sweep = sweep_thresholds(scores, labels, [0.2, 0.5, 0.8])
    best = best_threshold(sweep)
    assert best is not None
    assert best["f1"] == 1.0
    assert best["threshold"] == 0.8


def test_best_threshold_empty_sweep() -> None:
    assert best_threshold([]) is None


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------


def test_escalation_rate() -> None:
    assert escalation_rate([True, True, False, False]) == 0.5
    assert escalation_rate([True, True]) == 0.0
    assert escalation_rate([]) == 0.0


def test_effective_latency_scales_with_escalation() -> None:
    """A rarely-run expensive tier costs little; an always-run one costs all."""
    cheap = [0.01, 1.0]
    never = effective_latency_ms(cheap, 0.0, 50.0)
    sometimes = effective_latency_ms(cheap, 0.1, 50.0)
    always = effective_latency_ms(cheap, 1.0, 50.0)
    assert never == pytest.approx(1.01)
    assert sometimes == pytest.approx(6.01)
    assert always == pytest.approx(51.01)
    assert never < sometimes < always


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def test_seed_corpus_is_disjoint_from_eval_set() -> None:
    """The benchmark's central methodological guarantee."""
    corpus_mod.assert_seed_disjoint()


def test_eval_set_is_aligned_and_labelled() -> None:
    texts, labels, buckets = corpus_mod.build_eval_set()
    assert len(texts) == len(labels) == len(buckets)
    assert set(labels) == {0, 1}
    assert set(buckets) == set(corpus_mod.BUCKETS)
    # Every attack bucket is labelled 1, every clean bucket 0.
    for text, label, bucket in zip(texts, labels, buckets):
        assert label == (1 if bucket.startswith("attack") else 0), text[:40]


def test_corpus_summary_totals_match() -> None:
    summary = corpus_mod.corpus_summary()
    bucket_sizes = [size for name, size in summary.items() if name not in {"total", "seed_corpus"}]
    assert summary["total"] == sum(bucket_sizes)
    assert summary["seed_corpus"] == len(corpus_mod.ATTACK_SEED_CORPUS)


def test_corpus_sample_order_is_pinned() -> None:
    """Freeze the per-sample order the committed ``results.json`` files assume.

    ``compare_runs.py`` aligns two runs' per-sample ``scores`` arrays **by
    corpus index**. Reordering or inserting a sample therefore silently
    mis-attributes every stored score instead of failing loudly, so the
    order is pinned here. If this test fails because samples were added on
    purpose, the stored runs are stale: re-run the harness (or re-derive
    them) and update the digest in the same commit.
    """
    texts, labels, buckets = corpus_mod.build_eval_set()
    blob = json.dumps([texts, labels, buckets], ensure_ascii=False).encode()
    assert hashlib.sha256(blob).hexdigest() == (
        "28eaa2e7db442b88310479603070d103ff54e8e563c1f1b2a0802d0f2576d759"
    )


def test_language_tags_are_aligned() -> None:
    """Every sample carries exactly one known language tag."""
    corpus_mod.assert_languages_aligned()
    texts, _, _ = corpus_mod.build_eval_set()
    languages = corpus_mod.build_eval_languages()
    assert len(languages) == len(texts)
    assert set(languages) <= {"en", "es", "mixed"}


def test_language_tags_follow_the_sublists() -> None:
    """The tags are derived from structure, not hand-maintained.

    Guards the property that makes the per-language table trustworthy: a
    sample appended to a language sub-list is tagged automatically, so the
    tags cannot drift out of alignment with the texts.
    """
    tags = corpus_mod.BUCKET_LANGUAGES["clean"]
    assert tags == ["en"] * 18 + ["es"] * 16
    for index, text in enumerate(corpus_mod.CLEAN):
        if tags[index] == "es":
            assert text in corpus_mod._CLEAN_ES
        else:
            assert text in corpus_mod._CLEAN_EN


def test_language_summary_matches_the_eval_set() -> None:
    summary = corpus_mod.language_summary()
    assert sum(summary.values()) == len(corpus_mod.build_eval_languages())
    # The Spanish benign bucket is the sample set the FEAT-439 follow-up
    # proposal's false-positive rate is computed over; n=16 is load-bearing
    # for those percentages.
    clean_es = sum(
        1
        for bucket, language in zip(
            corpus_mod.build_eval_set()[2],
            corpus_mod.build_eval_languages(),
            strict=True,
        )
        if bucket == "clean" and language == "es"
    )
    assert clean_es == 16


def test_framework_bucket_wraps_clean_prompts() -> None:
    """clean_framework must carry the real <user_context> wrapper."""
    for text in corpus_mod.CLEAN_FRAMEWORK:
        assert text.startswith("<user_context")
        assert text.rstrip().endswith("</user_context>")


# ---------------------------------------------------------------------------
# Parity gate (harness-level)
# ---------------------------------------------------------------------------

_harness = _load_bench_module("harness")


def _clf_result(tier: str, scores: list[float]) -> dict:
    """Minimal result stub carrying only what the parity gate reads."""
    return {"tier": tier, "scores": scores, "error": None, "n_samples": len(scores)}


def test_parity_gate_passes_on_identical_scores() -> None:
    """An exact re-export must not be flagged."""
    scores = [0.0, 0.5, 1.0, 0.97]
    report = _harness.analyse_parity(
        [_clf_result("clf-torch", scores), _clf_result("clf-onnx", list(scores))],
        threshold=0.98,
    )
    assert report["clf-onnx"]["parity_ok"] is True
    assert report["clf-onnx"]["flipped_verdicts"] == 0


def test_parity_gate_tolerates_numerical_noise() -> None:
    """Sub-tolerance float drift is expected, not a failure."""
    reference = [0.0, 0.5, 1.0]
    noisy = [0.001, 0.502, 0.999]
    report = _harness.analyse_parity(
        [_clf_result("clf-torch", reference), _clf_result("clf-onnx", noisy)],
        threshold=0.98,
    )
    assert report["clf-onnx"]["parity_ok"] is True


def test_parity_gate_catches_a_fast_but_wrong_backend() -> None:
    """The int8 failure mode: plausible-looking scores, flipped verdicts.

    This is the regression the gate exists for — a quantized graph whose
    latency looks like a win while its answers have collapsed.
    """
    reference = [1.0, 1.0, 0.0, 0.0]
    collapsed = [0.02, 0.03, 0.01, 0.01]
    report = _harness.analyse_parity(
        [_clf_result("clf-torch", reference), _clf_result("clf-onnx-int8", collapsed)],
        threshold=0.98,
    )
    entry = report["clf-onnx-int8"]
    assert entry["parity_ok"] is False
    assert entry["flipped_verdicts"] == 2
    assert entry["max_abs_delta"] == pytest.approx(0.98, abs=1e-6)


def test_parity_gate_flags_sample_count_mismatch() -> None:
    report = _harness.analyse_parity(
        [_clf_result("clf-torch", [0.1, 0.2]), _clf_result("clf-onnx", [0.1])],
        threshold=0.5,
    )
    assert report["clf-onnx"]["parity_ok"] is False
    assert "mismatch" in report["clf-onnx"]["error"]


def test_parity_gate_skips_without_reference() -> None:
    assert _harness.analyse_parity([_clf_result("clf-onnx", [0.1])], threshold=0.5) is None


def test_parity_gate_ignores_non_classifier_tiers() -> None:
    """`regex` and `embed-cosine-*` compute different functions by design."""
    report = _harness.analyse_parity(
        [
            _clf_result("clf-torch", [1.0, 0.0]),
            _clf_result("regex", [0.0, 0.0]),
            _clf_result("embed-cosine-torch", [0.3, 0.4]),
        ],
        threshold=0.98,
    )
    assert set(report) == set()


# ---------------------------------------------------------------------------
# Per-language quality (harness-level)
# ---------------------------------------------------------------------------


def test_per_language_quality_counts_fp_and_recall() -> None:
    """FP and recall are segmented per language at the production threshold."""
    labels = [0, 0, 1, 1]
    languages = ["en", "es", "en", "es"]
    #            en benign ok | es benign FP | en attack hit | es attack miss
    scores = [0.0, 1.0, 1.0, 0.0]
    output = _harness._per_language_quality(
        [_clf_result("clf-onnx", scores)], labels, languages
    )["clf-onnx"]

    assert output["en"]["benign_n"] == 1
    assert output["en"]["fp"] == 0
    assert output["en"]["fp_rate"] == 0.0
    assert output["en"]["recall"] == 1.0

    assert output["es"]["fp"] == 1
    assert output["es"]["fp_rate"] == 1.0
    assert output["es"]["fn"] == 1
    assert output["es"]["recall"] == 0.0


def test_per_language_quality_handles_a_language_with_no_benign_samples() -> None:
    """``mixed`` has attacks only — rates must be None, not a ZeroDivisionError."""
    output = _harness._per_language_quality(
        [_clf_result("clf-onnx", [1.0])], [1], ["mixed"]
    )["clf-onnx"]
    assert output["mixed"]["fp_rate"] is None
    assert output["mixed"]["recall"] == 1.0


def test_per_language_quality_skips_a_tier_that_failed() -> None:
    """A tier with no scores (load error) contributes no row."""
    assert _harness._per_language_quality(
        [{"tier": "clf-onnx", "scores": None, "error": "boom"}], [1], ["en"]
    ) == {}


def test_per_language_quality_rejects_misaligned_inputs() -> None:
    """Misalignment must fail loudly, not mis-attribute scores."""
    with pytest.raises(ValueError):
        _harness._per_language_quality(
            [_clf_result("clf-onnx", [1.0, 0.0])], [1], ["en"]
        )
