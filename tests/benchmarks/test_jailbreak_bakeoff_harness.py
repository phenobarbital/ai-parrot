"""FEAT-761 TASK-4831 offline tests for the jailbreak bake-off harness."""

from __future__ import annotations

import json

import pytest

from benchmarks.injection_guardrail_latency import compare_jailbreak as cj
from benchmarks.injection_guardrail_latency import jailbreak_corpus as corpus
from benchmarks.injection_guardrail_latency.detectors import _resolve_injection_index


def _candidate(
    model_id: str = "example/model",
    *,
    license_name: str = "mit",
    eligible: bool = True,
) -> cj.Candidate:
    """Build a compact synthetic candidate."""
    return cj.Candidate(
        model_id=model_id,
        kind="classifier",
        license=license_name,
        eligible=eligible,
    )


def _scored_result(
    *,
    benign_es: list[float] | None = None,
    p50_ms: float = 10.0,
    candidate: cj.Candidate | None = None,
) -> cj.CandidateResult:
    """Build a fully aligned synthetic result without loading a model."""
    scores: dict[str, list[float]] = {}
    for bucket_name, (items, label, _) in corpus.BUCKETS.items():
        scores[bucket_name] = [0.8 if label else 0.1] * len(items)
    if benign_es is not None:
        scores["benign_es"] = benign_es
    return cj.CandidateResult(candidate=candidate or _candidate(), scores=scores, p50_ms=p50_ms)


def test_corpus_sizes_and_disjointness() -> None:
    """All preregistered buckets meet their minimums and remain disjoint."""
    assert len(corpus.BENIGN_EN) >= 25
    assert len(corpus.BENIGN_ES) >= 25
    assert len(corpus.JAILBREAK_EN) >= 25
    assert len(corpus.JAILBREAK_ES) >= 25
    assert len(corpus.LEAKAGE_ATTEMPT_EN) >= 10
    assert len(corpus.LEAKAGE_ATTEMPT_ES) >= 10
    assert any("olvida lo anterior" in prompt.casefold() for prompt in corpus.BENIGN_ES)
    assert any("actúa como profesor" in prompt.casefold() for prompt in corpus.BENIGN_ES)
    corpus.assert_buckets_disjoint()


def test_candidate_matrix_pins_eligible_shortlist_and_fp32_gravitee() -> None:
    """Only the four approved candidates are default-eligible."""
    eligible_ids = {candidate.model_id for candidate in cj.CANDIDATES if candidate.eligible}
    assert eligible_ids == {
        "vllm-sr/mmbert32k-jailbreak-detector-merged",
        "madhurjindal/Jailbreak-Detector-Large",
        "gravitee-io/Llama-Prompt-Guard-2-86M-onnx",
        "enguard/medium-guard-128m-xx-prompt-jailbreak-binary-in-the-wild",
    }
    gravitee = next(candidate for candidate in cj.CANDIDATES if candidate.model_id.startswith("gravitee-io/"))
    assert gravitee.graph_path == "model.onnx"
    assert "quant" not in gravitee.graph_path


def test_sweep_threshold_raises_threshold_to_avoid_spanish_false_positive() -> None:
    """A high benign-ES score forces selection above that score."""
    benign_es = [0.7] + [0.1] * (len(corpus.BENIGN_ES) - 1)
    threshold, metrics = cj.sweep_threshold(_scored_result(benign_es=benign_es))
    assert threshold == pytest.approx(0.8)
    assert metrics["es_benign_fp"] == 0
    assert metrics["f1_combined"] == pytest.approx(1.0)
    assert metrics["recall_jailbreak_es"] == pytest.approx(1.0)


def test_sweep_threshold_returns_reject_all_when_no_threshold_passes() -> None:
    """Scores beyond the reject-all sentinel fail closed."""
    threshold, metrics = cj.sweep_threshold(_scored_result(benign_es=[2.0] * len(corpus.BENIGN_ES)))
    assert threshold == pytest.approx(1.01)
    assert metrics["f1_combined"] == 0.0
    assert metrics["es_benign_fp"] == len(corpus.BENIGN_ES)


def test_evaluate_gate_reports_all_failures() -> None:
    """Eligibility, Spanish FP, and p50 gates produce stable reasons."""
    result = _scored_result(
        p50_ms=31.25,
        candidate=_candidate(license_name="none", eligible=False),
    )
    metrics = {"es_benign_fp": 2.0}
    passes, reasons = cj.evaluate_gate(result, 0.8, metrics)
    assert not passes
    assert reasons == ["not-eligible:none", "es-benign-fp:2", "p50:31.25"]


def test_pick_winner_ties_break_by_license_then_artifact_size() -> None:
    """Permissive licenses outrank llama4, then smaller artifacts win."""
    metrics = {"f1_combined": 0.9}
    llama = cj.CandidateResult(_candidate("llama", license_name="llama4"), artifact_mb=1.0)
    apache_large = cj.CandidateResult(_candidate("apache-large", license_name="apache-2.0"), artifact_mb=20.0)
    mit_small = cj.CandidateResult(_candidate("mit-small", license_name="mit"), artifact_mb=5.0)
    assert cj.pick_winner(
        [(llama, 0.5, metrics, True), (apache_large, 0.5, metrics, True)]
    ) is apache_large
    assert cj.pick_winner(
        [(apache_large, 0.5, metrics, True), (mit_small, 0.5, metrics, True)]
    ) is mit_small


def test_pick_winner_never_selects_noneligible_and_returns_none_without_pass() -> None:
    """The winner function independently enforces default eligibility."""
    metrics = {"f1_combined": 1.0}
    excluded = cj.CandidateResult(_candidate("excluded", eligible=False))
    assert cj.pick_winner([(excluded, 0.5, metrics, True)]) is None
    eligible = cj.CandidateResult(_candidate("eligible"))
    assert cj.pick_winner([(eligible, 0.5, metrics, False)]) is None


def test_manifest_contains_provenance_verdict_and_raw_scores(tmp_path) -> None:
    """Manifest output is complete and can be reproduced offline."""
    result = _scored_result()
    result.revision = "abc123"
    result.sha256 = "f" * 64
    threshold, metrics = cj.sweep_threshold(result)
    passes, _ = cj.evaluate_gate(result, threshold, metrics)
    cj.write_manifest(tmp_path, [(result, threshold, metrics, passes)], result)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    raw = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    entry = manifest["candidates"][0]
    assert manifest["winner"] == result.candidate.model_id
    assert entry["revision"] == "abc123"
    assert entry["sha256"] == "f" * 64
    assert entry["verdict"] == "pass"
    assert raw["candidates"][0]["scores"] == result.scores


def test_positive_label_resolution_preserves_injection_default() -> None:
    """Jailbreak labels resolve while the injection default stays unchanged."""
    assert _resolve_injection_index({0: "safe", 3: "JAILBREAK"}, ("jailbreak", "malicious")) == 3
    assert _resolve_injection_index({"0": "safe", "2": "malicious_request"}, ("jailbreak", "malicious")) == 2
    assert _resolve_injection_index({0: "safe", 4: "prompt_injection"}) == 4
    assert _resolve_injection_index({0: "LABEL_0", 1: "LABEL_1"}, ("jailbreak", "malicious")) == 1
