"""Regression tests for bridge node-ID normalization and the shared verdict helper."""

from __future__ import annotations

from parrot.e2e._verdict import evaluate_required_nodes
from parrot.e2e.models import ScenarioResult, ScenarioSpec
from parrot.e2e.runner import _bridge_results

PLAN_ID = "packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_a"


def _scenario(node_ids: list[str]) -> ScenarioSpec:
    return ScenarioSpec.model_construct(id="s1", node_ids=node_ids, tier="codified", required=True)


def _bridge(node_id: str, outcome: str = "passed") -> dict:
    return {"exit_status": 0, "results": [{"node_id": node_id, "outcome": outcome, "duration_s": 0.1}]}


def test_package_relative_key_matches_repo_relative_plan_id() -> None:
    results = _bridge_results(_scenario([PLAN_ID]), _bridge("tests/e2e/test_mcp_http.py::test_a"), [])
    assert [r.outcome for r in results] == ["passed"]
    assert results[0].node_id == PLAN_ID


def test_exact_key_still_matches() -> None:
    assert _bridge_results(_scenario([PLAN_ID]), _bridge(PLAN_ID), [])[0].outcome == "passed"


def test_non_boundary_suffix_does_not_match() -> None:
    results = _bridge_results(_scenario([PLAN_ID]), _bridge("sts/e2e/test_mcp_http.py::test_a"), [])
    assert results[0].outcome == "missing"


def test_unrelated_test_not_fabricated_as_pass() -> None:
    results = _bridge_results(_scenario([PLAN_ID]), _bridge("tests/e2e/test_mcp_http.py::test_b"), [])
    assert results[0].outcome == "missing"


def test_shared_helper_findings() -> None:
    ok = ScenarioResult.model_construct(
        scenario_id="s", setup_outcome=None, call_outcome=None, teardown_outcome=None, node_id="a", outcome="passed"
    )
    bad = ScenarioResult.model_construct(
        scenario_id="s", setup_outcome=None, call_outcome=None, teardown_outcome=None, node_id="b", outcome="failed"
    )
    blk = ScenarioResult.model_construct(
        scenario_id="s", setup_outcome=None, call_outcome=None, teardown_outcome=None, node_id="c", outcome="blocked"
    )
    ph = ScenarioResult.model_construct(
        scenario_id="s",
        setup_outcome=None,
        teardown_outcome=None,
        node_id="d",
        outcome="passed",
        call_outcome="failed",
    )
    found = evaluate_required_nodes("abcde", {"a": ok, "b": bad, "c": blk, "d": ph}, check_phases=True)
    assert [(f.node_id, f.kind) for f in found] == [
        ("b", "not_passed"),
        ("c", "blocked"),
        ("d", "phase_failure"),
        ("e", "missing"),
    ]
    assert evaluate_required_nodes(["a"], {"a": ok}) == []
