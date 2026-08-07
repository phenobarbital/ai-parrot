"""Tests for the "Best" column of ``compare_scenarios``.

A metric has no inherent direction: more revenue is good, more expenses is
not. The comparison used to pick the winner with ``max()`` for *every* metric,
so the scenario with the HIGHEST costs was labelled best — the exact opposite
of the truth, presented to the LLM as a recommendation.

Ranking now comes from the objectives the caller declared through
``set_constraints``. Metrics with no declared direction are shown but left
unranked rather than guessed at.
"""
import pandas as pd
import pytest
from parrot_tools.whatif import DerivedMetric, WhatIfAction, WhatIfObjective
from parrot_tools.whatif_toolkit import WhatIfToolkit

EBITDA = DerivedMetric(name="ebitda", formula="revenue - payroll - expenses")


@pytest.fixture
def clients_df() -> pd.DataFrame:
    """Two clients with revenue/payroll/expenses."""
    return pd.DataFrame(
        {
            "customer": ["Acme", "Umbrella"],
            "revenue": [1_200_000.0, 2_100_000.0],
            "payroll": [400_000.0, 700_000.0],
            "expenses": [350_000.0, 640_000.0],
        }
    )


class Host:
    """Minimal parent agent exposing a `dataframes` registry."""

    def __init__(self, dataframes: dict) -> None:
        self.dataframes = dataframes


def scenario_id(described: str) -> str:
    """Pull the scenario id out of describe_scenario output."""
    return next(token for token in described.split() if token.startswith("sc_"))


async def make_scenario(
    toolkit: WhatIfToolkit,
    description: str,
    pct: float,
    objectives=None,
) -> str:
    """Build and simulate a scenario that moves expenses by *pct*."""
    sid = scenario_id(
        await toolkit.describe_scenario("clients", description, [EBITDA])
    )
    await toolkit.add_actions(
        sid,
        [
            WhatIfAction(
                type="adjust_metric",
                target="expenses",
                parameters={"min_pct": pct, "max_pct": pct, "group_by": "customer"},
            )
        ],
    )
    if objectives:
        await toolkit.set_constraints(sid, objectives=objectives)
    await toolkit.simulate(sid, max_actions=2)
    return sid


@pytest.fixture
def toolkit(clients_df: pd.DataFrame) -> WhatIfToolkit:
    """A toolkit wired to the client dataset."""
    tk = WhatIfToolkit()
    tk._parent_agent = Host({"clients": clients_df})
    return tk


# ── polarity resolution ──────────────────────────────────────────────────


def test_best_scenario_minimizes_when_declared():
    """The regression: for a minimized metric, the LOWER value wins."""
    values = {"sc_1": 1_138_500.0, "sc_2": 891_000.0}

    assert WhatIfToolkit._best_scenario(values, ("minimize", None)) == "sc_2"


def test_best_scenario_maximizes_when_declared():
    """A maximized metric still picks the higher value."""
    values = {"sc_1": 1_061_500.0, "sc_2": 1_309_000.0}

    assert WhatIfToolkit._best_scenario(values, ("maximize", None)) == "sc_2"


def test_best_scenario_targets_closest_value():
    """A target objective wins on proximity, not magnitude."""
    values = {"sc_1": 900_000.0, "sc_2": 1_400_000.0}

    assert WhatIfToolkit._best_scenario(values, ("target", 1_000_000.0)) == "sc_1"


def test_best_scenario_is_none_without_polarity():
    """No declared direction means no winner is invented."""
    assert WhatIfToolkit._best_scenario({"sc_1": 1.0, "sc_2": 2.0}, None) is None


def test_best_scenario_is_none_on_a_tie():
    """Identical values across scenarios produce no winner."""
    values = {"sc_1": 5.0, "sc_2": 5.0}

    assert WhatIfToolkit._best_scenario(values, ("maximize", None)) is None


# ── the full comparison ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_costs_are_not_ranked_without_an_objective(toolkit):
    """Without objectives no metric is marked best, and the table says why."""
    up = await make_scenario(toolkit, "expenses up 15", 15)
    down = await make_scenario(toolkit, "expenses down 10", -10)

    table = await toolkit.compare_scenarios([up, down])

    # The old behaviour marked the higher-expenses scenario as best.
    expenses_row = next(
        line for line in table.splitlines() if line.startswith("| expenses")
    )
    assert expenses_row.rstrip().endswith("| n/a |")
    assert "^" not in expenses_row
    assert "Not ranked" in table
    assert "Lower is NOT assumed for costs" in table


@pytest.mark.asyncio
async def test_declared_objectives_rank_the_metrics(toolkit):
    """With objectives, the lower-cost / higher-ebitda scenario wins."""
    objectives = [
        WhatIfObjective(type="minimize", metric="expenses"),
        WhatIfObjective(type="maximize", metric="ebitda"),
    ]
    up = await make_scenario(toolkit, "expenses up 15", 15, objectives)
    down = await make_scenario(toolkit, "expenses down 10", -10, objectives)

    table = await toolkit.compare_scenarios([up, down])

    expenses_row = next(
        line for line in table.splitlines() if line.startswith("| expenses")
    )
    ebitda_row = next(
        line for line in table.splitlines() if line.startswith("| ebitda")
    )
    assert expenses_row.rstrip().endswith(f"| {down} |")
    assert ebitda_row.rstrip().endswith(f"| {down} |")
    # The direction is spelled out so the reader knows how it was ranked.
    assert "expenses (minimize)" in table
    assert "ebitda (maximize)" in table


@pytest.mark.asyncio
async def test_contradictory_objectives_leave_the_metric_unranked(toolkit):
    """One scenario minimizing what another maximizes is not resolved."""
    up = await make_scenario(
        toolkit,
        "expenses up 15",
        15,
        [WhatIfObjective(type="maximize", metric="expenses")],
    )
    down = await make_scenario(
        toolkit,
        "expenses down 10",
        -10,
        [WhatIfObjective(type="minimize", metric="expenses")],
    )

    table = await toolkit.compare_scenarios([up, down])

    expenses_row = next(
        line for line in table.splitlines() if line.startswith("| expenses")
    )
    assert expenses_row.rstrip().endswith("| n/a |")


@pytest.mark.asyncio
async def test_unranked_metrics_are_still_shown(toolkit):
    """Metrics without an objective keep their values in the table."""
    objectives = [WhatIfObjective(type="minimize", metric="expenses")]
    up = await make_scenario(toolkit, "expenses up 15", 15, objectives)
    down = await make_scenario(toolkit, "expenses down 10", -10, objectives)

    table = await toolkit.compare_scenarios([up, down])

    # revenue has no objective but must remain visible for context.
    revenue_row = next(
        line for line in table.splitlines() if line.startswith("| revenue")
    )
    assert "3,300,000.00" in revenue_row
    assert revenue_row.rstrip().endswith("| n/a |")
