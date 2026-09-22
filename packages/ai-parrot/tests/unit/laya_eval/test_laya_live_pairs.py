"""FEAT-589 M4 — paired live calls: accounting, cap stop, provider errors, evidence and rubric per arm."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

from artifacts.laya.live import LiveCallBudget, rubric_pass, run_live_routing_pairs
from artifacts.laya.models import EvaluationCase, EvaluationConfig, RouteDecision


def _cfg(**kw) -> EvaluationConfig:
    base = dict(worker_python=Path("/bin/python3"), checkpoint_path=Path("/tmp/c"), checkpoint_revision="r", output_dir=Path("/tmp/o"),
                live=True, primary_api_model="P", cheap_api_model="C", max_live_calls=4)
    base.update(kw)
    return EvaluationConfig(**base)


def _case(i: str, expected: str = "cheap") -> EvaluationCase:
    return EvaluationCase(id=i, scenario="routing", language="en", split="evaluation", state=f"question {i}", expected=expected, bucket="simple", source="t")


class FakeAgent:
    def __init__(self, fail_for: str | None = None, raw: bool = True):
        self.calls, self.fail_for, self.raw = [], fail_for, raw

    async def ask_routed(self, question, decision, **kwargs):
        self.calls.append((question, decision.selected_model, kwargs))
        if self.fail_for and decision.selected_model == self.fail_for:
            raise RuntimeError("provider says no")
        return AIMessage(input=question, output="Paris", response="Paris", model=decision.selected_model, provider="claude",
                         raw_response={"model": f"{decision.selected_model}-real"} if self.raw else None,
                         usage=CompletionUsage(prompt_tokens=5, completion_tokens=1, total_tokens=6))


def test_rubric_pass_exact_and_facts():
    assert rubric_pass(" paris ", {"exact_answer": "Paris"}) is True
    assert rubric_pass("Paris is in France", {"required_facts": ["paris", "france"]}) is True
    assert rubric_pass("Rome", {"exact_answer": "Paris"}) is False and rubric_pass("x", None) is None


async def test_pair_uses_separate_sessions_matching_settings_and_both_arms_recorded():
    agent = FakeAgent()
    decisions = {"a": RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap")}
    samples = await run_live_routing_pairs(agent, [_case("a")], decisions, _cfg(), LiveCallBudget(4), {"a": {"exact_answer": "Paris"}})
    assert [s.arm for s in samples] == ["primary", "routed"] and [c[1] for c in agent.calls] == ["P", "C"]
    sessions = {c[2]["session_id"] for c in agent.calls}
    assert sessions == {"a:primary", "a:routed"} and all(c[2]["max_tokens"] == 256 and c[2]["temperature"] == 0.0 for c in agent.calls)
    assert all(s.quality_pass is True and s.actual_model == f"{s.selected_model}-real" for s in samples)


async def test_cap_stops_before_a_partial_pair_and_counts_both_arms():
    budget = LiveCallBudget(3)
    decisions = {i: RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap") for i in ("a", "b")}
    samples = await run_live_routing_pairs(FakeAgent(), [_case("a"), _case("b")], decisions, _cfg(), budget, {})
    assert [s.arm for s in samples[:2]] == ["primary", "routed"] and samples[2].error_code == "call_cap_reached" and budget.used == 2


async def test_provider_error_recorded_without_substitution_and_slot_consumed():
    budget = LiveCallBudget(2)
    decisions = {"a": RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap")}
    samples = await run_live_routing_pairs(FakeAgent(fail_for="C"), [_case("a")], decisions, _cfg(), budget, {})
    routed = samples[1]
    assert routed.status == "error" and routed.error_code == "provider_error" and routed.selected_model == "C" and budget.remaining == 0


async def test_missing_raw_model_marks_model_unverified_per_arm():
    agent = FakeAgent(raw=False)
    decisions = {"a": RouteDecision(choice="cheap", selected_model="C", confidence=0.9, reason="cheap")}
    samples = await run_live_routing_pairs(agent, [_case("a")], decisions, _cfg(), LiveCallBudget(4), {})
    assert len(samples) == 2
    assert all(s.status == "ok" for s in samples)
    assert all(s.actual_model is None for s in samples)
    assert all(s.error_code == "model_unverified" for s in samples)
