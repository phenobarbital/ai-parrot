"""FEAT-589 M4 — live preflight, logical-call cap and model-evidence extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

from artifacts.laya.models import EvaluationConfig
from artifacts.laya.live import LiveCallBudget, LivePreflightError, extract_model_evidence, preflight_live


def _cfg(**kw) -> EvaluationConfig:
    base = dict(
        worker_python=Path("/bin/python3"),
        checkpoint_path=Path("/tmp/c"),
        checkpoint_revision="r",
        output_dir=Path("/tmp/o"),
    )
    base.update(kw)
    return EvaluationConfig(**base)


def _msg(model="req-model", raw=None, metadata=None) -> AIMessage:
    return AIMessage(
        input="q",
        output="a",
        model=model,
        provider="claude",
        raw_response=raw,
        metadata=metadata or {},
        usage=CompletionUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


def test_preflight_is_a_noop_without_live_flag():
    preflight_live(_cfg(live=False), env={})


def test_preflight_lists_every_missing_input_before_any_request():
    with pytest.raises(LivePreflightError) as ei:
        preflight_live(_cfg(live=True), env={})
    msg = str(ei.value)
    assert all(
        part in msg for part in ("--primary-api-model", "--cheap-api-model", "--max-live-calls", "ANTHROPIC_API_KEY")
    )
    assert ei.value.error_code == "live_config_missing"


def test_preflight_passes_with_all_inputs():
    preflight_live(
        _cfg(live=True, primary_api_model="p", cheap_api_model="c", max_live_calls=2), env={"ANTHROPIC_API_KEY": "k"}
    )


def test_budget_counts_both_arms_and_refuses_partial_pair():
    b = LiveCallBudget(3)
    assert b.reserve_pair() and b.remaining == 1
    assert not b.reserve_pair()  # one slot left: no partial pair
    assert b.reserve() and not b.reserve()


def test_failed_calls_still_consume_slots():
    b = LiveCallBudget(2)
    assert b.reserve()
    try:
        raise RuntimeError("simulated provider failure")
    except RuntimeError:
        pass  # no release() API exists — a failed call keeps its reserved slot
    assert b.used == 1
    assert b.remaining == 1


def test_raw_provider_model_is_preferred_and_mismatch_stays_visible():
    ev = extract_model_evidence(_msg(model="claude-x", raw={"model": "claude-x-20260101", "content": []}), "claude-x")
    assert ev.verified and ev.actual_model == "claude-x-20260101" and ev.reported_model == "claude-x"
    assert ev.mismatch and ev.error_code is None


def test_requested_only_metadata_cannot_establish_actual_execution():
    ev = extract_model_evidence(_msg(model="claude-x", raw=None), "claude-x")
    assert not ev.verified and ev.actual_model is None and ev.error_code == "model_unverified"


def test_fallback_metadata_is_recorded_separately():
    ev = extract_model_evidence(
        _msg(
            raw={"model": "fb"}, metadata={"used_fallback_model": True, "original_model": "a", "fallback_model": "fb"}
        ),
        "a",
    )
    assert (
        ev.fallback_metadata == {"used_fallback_model": True, "original_model": "a", "fallback_model": "fb"}
        and ev.actual_model == "fb"
    )
