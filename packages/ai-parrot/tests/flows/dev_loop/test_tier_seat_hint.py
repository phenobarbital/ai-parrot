"""Tests for expert tier -> seat hint (FEAT-890 AC11)."""

from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy, StrongModelIdentity
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.roster import eligible_seats_for_tier

STRONG = RosterSeat(label="strong", kind="mcp", backend="codex", model="gpt-x")
WEAK = RosterSeat(label="weak", kind="mcp", backend="codex", model="mini")
NATIVE = RosterSeat(label="haiku", kind="native", model="haiku")


def _policy() -> ComplexityPolicy:
    return ComplexityPolicy(
        strong_models=[StrongModelIdentity(canonical_model="gpt-x", backend="codex", model="gpt-x")]
    )


def _config() -> RosterConfig:
    return RosterConfig(seats=[WEAK, STRONG, NATIVE])


def test_default_map() -> None:
    assert _config().expert_tier_seats == {"judgment": "complex", "balanced": "standard", "templated": "cheap"}


def test_judgment_only_strong() -> None:
    out = eligible_seats_for_tier("judgment", [WEAK, STRONG, NATIVE], _policy(), _config())
    assert [s.label for s in out] == ["strong"]


def test_balanced_unchanged() -> None:
    out = eligible_seats_for_tier("balanced", [WEAK, STRONG, NATIVE], _policy(), _config())
    assert [s.label for s in out] == ["weak", "strong", "haiku"]


def test_unknown_tier_is_standard() -> None:
    out = eligible_seats_for_tier("mystery", [STRONG, WEAK], _policy(), _config())
    assert [s.label for s in out] == ["strong", "weak"]


def test_templated_cheapest_first() -> None:
    out = eligible_seats_for_tier("templated", [STRONG, WEAK, NATIVE], _policy(), _config())
    assert [s.label for s in out] == ["weak", "haiku", "strong"]
