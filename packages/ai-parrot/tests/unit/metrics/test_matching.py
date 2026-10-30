"""Tests for metric context, tenant resolution, and phrase matching."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.metrics.context import bind_metric_match, current_metric_match, reset_metric_match, resolve_metric_tenant
from parrot.metrics.matching import MetricMatcher, normalize
from parrot.metrics.models import MetricDefinition, MetricMatch
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant


class _ExplodingEncoder:
    """Encoder that proves the alias path performs no embedding work."""

    def encode(self, *args: object, **kwargs: object) -> None:
        """Fail if matching attempts to use the encoder."""
        raise AssertionError("encoder must not be called on the alias lane")


def test_normalize_strips_accents_punctuation_and_whitespace() -> None:
    """Normalization produces stable terms across punctuation and accents."""
    assert normalize("  ¿CUÁNTAS   Horas?! ") == "cuantas horas"


def test_matcher_alias_fast_path_no_encoder(worked_hours_def: MetricDefinition) -> None:
    """An alias match returns before constructing or using the encoder."""
    matcher = MetricMatcher(encoder=_ExplodingEncoder())
    matcher.configure({worked_hours_def.id: worked_hours_def.matching_terms()})

    assert matcher.match("worked hours this month") == ("worked_hours", 0.95, "alias", False)
    assert matcher._router is None


def test_matcher_alias_prefers_longest_and_reports_cross_metric_tie() -> None:
    """Contains matching chooses the longest term and flags equal cross-id terms."""
    matcher = MetricMatcher(enable_embeddings=False)
    matcher.configure({"hours": ["hours"], "worked": ["worked hours"], "duplicate": ["worked hours"]})

    assert matcher.match("show worked hours now") == ("worked", 0.95, "alias", True)
    assert matcher.match("worked hours") == ("worked", 1.0, "alias", True)


def test_matcher_embedding_lane_threshold_and_ambiguity(stub_encoder: object) -> None:
    """Embedding matching applies its own threshold and runner-up margin."""
    matcher = MetricMatcher(threshold=0.3, margin=0.2, encoder=stub_encoder)
    matcher.configure({"worked_hours": ["labor time"], "scheduled_hours": ["scheduled time"]})

    matched = matcher.match("show labor report please")
    assert matched is not None
    assert matched[0] == "worked_hours"
    assert matched[1] >= 0.3
    assert matched[2:] == ("embedding", False)

    matcher.threshold = 0.99
    assert matcher.match("show labor details please") is None

    matcher.threshold = 0.3
    close = matcher.match("compare labor scheduled reports")
    assert close is not None
    assert close[3] is True


def test_matcher_short_questions_abstain(stub_encoder: object) -> None:
    """Single tokens abstain and two tokens never reach the embedding lane."""
    matcher = MetricMatcher(threshold=0.0, encoder=stub_encoder)
    matcher.configure({"worked_hours": ["worked hours"], "other": ["other metric"]})

    assert matcher.match("hours") is None
    assert matcher.match("unrelated words") is None
    assert matcher._router is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("worked hours this month", "this_month"),
        ("horas este mes", "this_month"),
        ("last month", "last_month"),
        ("el mes pasado", "last_month"),
        ("today", "today"),
        ("ayer", "yesterday"),
        ("this week", "this_week"),
        ("semana pasada", "last_week"),
        ("year to date", "ytd"),
        ("en lo que va del año", "ytd"),
        ("month to date", "mtd"),
        ("qtd", "qtd"),
        ("últimos 30 días", "last_30d"),
        ("este año", "this_year"),
        ("año pasado", "last_year"),
        ("today and yesterday", None),
    ],
)
def test_matcher_parse_period(question: str, expected: str | None) -> None:
    """Period parsing recognizes the declared English and Spanish lexicon."""
    assert MetricMatcher.parse_period(question) == expected


def test_matcher_parse_dimension(worked_hours_def: MetricDefinition) -> None:
    """Dimension parsing accepts English/Spanish introducers and aliases."""
    dimensions = worked_hours_def.dimensions

    assert MetricMatcher.parse_dimension("worked hours by cost center this month", dimensions) == "cost center"
    assert MetricMatcher.parse_dimension("horas por cc este mes", dimensions) == "cost center"
    assert MetricMatcher.parse_dimension("worked hours by pay code", dimensions) == "pay code"
    assert MetricMatcher.parse_dimension("worked hours for cost center", dimensions) is None


def test_resolve_metric_tenant_order() -> None:
    """Tenant resolution observes explicit, context, bound, and default precedence."""
    token = bind_skill_tenant("bound")
    try:
        context = SimpleNamespace(kwargs={"tenant": "context"})
        assert resolve_metric_tenant("explicit", context, "default") == "explicit"
        assert resolve_metric_tenant(ctx=context, default="default") == "context"
        assert resolve_metric_tenant(default="default") == "bound"
    finally:
        reset_skill_tenant(token)

    assert resolve_metric_tenant(default="default") == "default"
    assert resolve_metric_tenant() is None
    with pytest.raises(ValueError):
        resolve_metric_tenant("invalid/name")


def test_metric_match_contextvar(worked_hours_def: MetricDefinition) -> None:
    """Metric match binding is reversible with its ContextVar token."""
    match = MetricMatch(metric=worked_hours_def, score=1.0, lane="alias")
    assert current_metric_match() is None

    token = bind_metric_match(match)
    try:
        assert current_metric_match() == match
    finally:
        reset_metric_match(token)

    assert current_metric_match() is None
