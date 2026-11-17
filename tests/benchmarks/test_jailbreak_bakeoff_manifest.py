"""FEAT-761 TASK-4832 — the committed bake-off manifest satisfies the pre-registered gate."""

import json
from pathlib import Path

from benchmarks.injection_guardrail_latency import compare_jailbreak as cj

RESULTS_DIR = Path(__file__).resolve().parents[2] / "benchmarks/injection_guardrail_latency/results-jailbreak"
MANIFEST = RESULTS_DIR / "manifest.json"
RESULTS = RESULTS_DIR / "results.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_exists_and_lists_every_candidate():
    data = _manifest()
    measured = {c["model_id"]: c for c in data["candidates"]}
    skipped = {c["model_id"]: c for c in data.get("skipped", [])}
    for candidate in cj.CANDIDATES:
        model_id = candidate.model_id
        assert model_id in measured or model_id in skipped, f"{model_id} missing from manifest"
        if model_id in measured:
            entry = measured[model_id]
            assert entry["revision"], model_id
            assert entry["license"], model_id
            assert entry["verdict"] in {"pass", "fail"}, model_id
            if candidate.kind != "static":
                assert len(entry["sha256"]) == 64, model_id
        else:
            assert skipped[model_id]["eligible"] is False, f"eligible candidate {model_id} was skipped"
            assert skipped[model_id]["reason"], model_id
    assert not (set(measured) & set(skipped))


def test_no_eligible_candidate_is_skipped():
    eligible = {c.model_id for c in cj.CANDIDATES if c.eligible}
    assert not eligible & {c["model_id"] for c in _manifest().get("skipped", [])}


def test_winner_meets_the_gate_or_is_null():
    data = _manifest()
    winner = data["winner"]
    if winner is None:
        return
    entry = next(c for c in data["candidates"] if c["model_id"] == winner)
    candidate = next(c for c in cj.CANDIDATES if c.model_id == winner)
    raw = next(c for c in json.loads(RESULTS.read_text(encoding="utf-8"))["candidates"] if c["model_id"] == winner)

    assert candidate.eligible and entry["eligible"]
    assert entry["verdict"] == "pass" and entry["reasons"] == []
    assert entry["metrics"]["es_benign_fp"] <= cj.ES_BENIGN_MAX_FP
    assert raw["p50_ms"] <= cj.P50_BUDGET_MS
    assert 0.0 < entry["threshold"] < 1.0
    assert candidate.graph_path, "winner graph_path must be recorded"
    # Fail-closed against a degenerate "detects nothing" winner (F1 0 / threshold above 1.0).
    assert entry["metrics"]["f1_combined"] > 0.0
    assert entry["metrics"]["recall_jailbreak_es"] > 0.0


def test_manifest_gate_is_reproducible_from_raw_results():
    """Re-applying the live gate to results.json reproduces every committed verdict and the winner."""
    data = _manifest()
    raw = {c["model_id"]: c for c in json.loads(RESULTS.read_text(encoding="utf-8"))["candidates"]}
    by_id = {c.model_id: c for c in cj.CANDIDATES}
    evaluated = []
    for entry in data["candidates"]:
        r = raw[entry["model_id"]]
        result = cj.CandidateResult(
            candidate=by_id[entry["model_id"]],
            scores=r["scores"],
            p50_ms=r["p50_ms"],
            p95_ms=r["p95_ms"],
            artifact_mb=r["artifact_mb"],
        )
        threshold, metrics = cj.sweep_threshold(result)
        passes, _ = cj.evaluate_gate(result, threshold, metrics)
        assert ("pass" if passes else "fail") == entry["verdict"], entry["model_id"]
        evaluated.append((result, threshold, metrics, passes))
    expected = cj.pick_winner(evaluated)
    assert (expected.candidate.model_id if expected else None) == data["winner"]
