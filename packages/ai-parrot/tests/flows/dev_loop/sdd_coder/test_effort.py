"""Unit tests for sdd_coder.effort (HOTFIX-sdd-coder-seat-effort-2)."""

import logging

import pytest

from parrot.flows.dev_loop.models import (
    CodexCodeDispatchProfile,
    GoogleCompatCodeDispatchProfile,
    LLMCodeDispatchProfile,
    ZaiCodeDispatchProfile,
)
from parrot.flows.dev_loop.models.google_coding import GoogleCodingDispatchProfile
from parrot.flows.dev_loop.models.moonshot import MoonshotCodeDispatchProfile
from parrot.flows.dev_loop.sdd_coder.complexity_models import StrongModelIdentity
from parrot.flows.dev_loop.sdd_coder.effort import (
    apply_effort_to_profile,
    resolve_native_effort,
    resolve_seat_effort,
)
from parrot.flows.dev_loop.sdd_coder.models import RosterSeat

LOG = logging.getLogger("test_effort")
STRONG = (StrongModelIdentity(canonical_model="x", backend="codex", model="m", effort="high"),)


def _seat(effort="medium"):
    return RosterSeat(label="a", backend="codex", model="m", effort=effort)


@pytest.mark.parametrize("cls", ["complex", "unknown"])
def test_resolve_strong_override(cls):
    assert resolve_seat_effort(_seat(), cls, STRONG) == "high"


def test_resolve_seat_effort_for_standard():
    assert resolve_seat_effort(_seat(), "standard", STRONG) == "medium"


def test_resolve_none_when_unset():
    assert resolve_seat_effort(_seat(None), "complex", ()) is None


@pytest.mark.parametrize(
    "backend,cls,field",
    [
        ("codex", CodexCodeDispatchProfile, "reasoning_effort"),
        ("zai", ZaiCodeDispatchProfile, "reasoning_effort"),
        ("moonshot", MoonshotCodeDispatchProfile, "reasoning_effort"),
        ("google-compat", GoogleCompatCodeDispatchProfile, "reasoning_effort"),
        ("google_coding", GoogleCodingDispatchProfile, "effort"),
    ],
)
def test_apply_maps_each_backend(backend, cls, field):
    out = apply_effort_to_profile(cls(), backend, "high", seat_label="a", logger=LOG)
    assert getattr(out, field) == "high"


@pytest.mark.parametrize(
    "backend,cls,value",
    [("google-compat", GoogleCompatCodeDispatchProfile, "max"), ("codex", CodexCodeDispatchProfile, "none")],
)
def test_apply_rejects_unsupported_value_with_warning(caplog, backend, cls, value):
    profile = cls()
    with caplog.at_level("WARNING"):
        out = apply_effort_to_profile(profile, backend, value, seat_label="a", logger=LOG)
    assert out is profile and len(caplog.records) == 1


def test_apply_unsupported_backend_warns(caplog):
    profile = LLMCodeDispatchProfile()
    with caplog.at_level("WARNING"):
        out = apply_effort_to_profile(profile, "nova", "high", seat_label="a", logger=LOG)
    assert out is profile and len(caplog.records) == 1


def test_apply_none_returns_same_object(caplog):
    profile = CodexCodeDispatchProfile()
    with caplog.at_level("WARNING"):
        assert apply_effort_to_profile(profile, "codex", None, seat_label="a", logger=LOG) is profile
    assert not caplog.records


def _native(effort=None, model="sonnet"):
    return RosterSeat(label="sonnet", kind="native", model=model, effort=effort)


_NATIVE_STRONG = [StrongModelIdentity(canonical_model="sonnet-5", backend="native", model="sonnet", effort="max")]


@pytest.mark.parametrize("classification", ["complex", "unknown"])
def test_native_strong_override_matches_backend_native(classification):
    assert resolve_native_effort(_native("medium"), classification, _NATIVE_STRONG, logger=LOG) == "max"


def test_native_standard_uses_seat_effort():
    assert resolve_native_effort(_native("medium"), "standard", _NATIVE_STRONG, logger=LOG) == "medium"


def test_native_unset_is_none(caplog):
    with caplog.at_level("WARNING"):
        assert resolve_native_effort(_native(), "standard", [], logger=LOG) is None
    assert not caplog.records


@pytest.mark.parametrize("value", ["none", "minimal"])
def test_native_rejects_values_the_agent_tool_lacks(caplog, value):
    with caplog.at_level("WARNING"):
        assert resolve_native_effort(_native(value), "standard", [], logger=LOG) is None
    assert len(caplog.records) == 1
