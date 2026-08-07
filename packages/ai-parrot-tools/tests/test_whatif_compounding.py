"""Tests that What-If actions are alternatives, not steps that stack.

Each ``can_*`` declaration offers a *menu* for one decision: ten candidate
percentages for "how much should this metric move". Nothing used to mark them
as mutually exclusive, so a solver allowed several actions would apply more
than one candidate from the same menu and compound them:

* ``min_pct == max_pct`` produced ten identical actions, so a "+15%" what-if
  run with the default ``max_actions=5`` came out as 1.15^5 (+75.9%);
* a range let the optimizer take -30% and then -27% on the same group, landing
  at -48.7% — outside the bound the caller declared.

Both are pinned here, along with the cases that must keep stacking (excluding
two different regions is two genuinely independent decisions).
"""
import numpy as np
import pandas as pd
import pytest
from parrot_tools.whatif import WhatIfDSL, _percentage_steps


@pytest.fixture
def clients_df() -> pd.DataFrame:
    """Two clients with revenue/payroll/expenses."""
    return pd.DataFrame(
        {
            "customer": ["Acme", "Umbrella"],
            "region": ["North", "West"],
            "revenue": [1_200_000.0, 2_100_000.0],
            "payroll": [400_000.0, 700_000.0],
            "expenses": [350_000.0, 640_000.0],
        }
    )


def value_for(df: pd.DataFrame, customer: str, column: str) -> float:
    """Read one client's value."""
    return float(df.loc[df["customer"] == customer, column].iloc[0])


# ── the percentage-candidate helper ──────────────────────────────────────


def test_fixed_percentage_yields_one_candidate():
    """A degenerate range is one decision, not ten identical ones."""
    assert _percentage_steps(15, 15) == [15.0]


def test_range_yields_distinct_candidates():
    """A real range still spreads candidates across it."""
    steps = _percentage_steps(-30, 0)

    assert len(steps) == len(set(steps))
    assert min(steps) == -30.0
    # 0% is a no-op and is never offered as an action.
    assert 0.0 not in steps


def test_zero_percent_is_never_a_candidate():
    """A 0%-only range produces no actions at all."""
    assert _percentage_steps(0, 0) == []


# ── scale_entity: the reported "+15% applied five times" bug ─────────────


def test_fixed_pct_entity_scaling_generates_one_action(clients_df):
    """min_pct == max_pct must not fan out into duplicates."""
    dsl = WhatIfDSL(clients_df, "acme_up_15")
    dsl.initialize_optimizer()
    dsl.can_scale_entity(
        entity_column="customer",
        target_columns=["expenses"],
        entities=["Acme"],
        min_pct=15,
        max_pct=15,
    )

    assert len(dsl.possible_actions) == 1


def test_default_max_actions_does_not_compound(clients_df):
    """The headline bug: simulate()'s default max_actions=5 applied 1.15^5."""
    dsl = WhatIfDSL(clients_df, "acme_up_15")
    dsl.initialize_optimizer()
    dsl.can_scale_entity(
        entity_column="customer",
        target_columns=["expenses"],
        entities=["Acme"],
        min_pct=15,
        max_pct=15,
    )

    # max_actions=5 is what WhatIfToolkit.simulate() passes by default.
    result = dsl.solve(max_actions=5, algorithm="greedy")

    assert len(result.actions) == 1
    assert np.isclose(
        value_for(result.result_df, "Acme", "expenses"),
        value_for(clients_df, "Acme", "expenses") * 1.15,
    )


# ── the optimizer must respect the declared bound ────────────────────────


def test_optimizer_does_not_exceed_declared_range(clients_df):
    """Greedy used to stack -30% and -27% on one group, reaching -48.7%."""
    dsl = WhatIfDSL(clients_df, "cut_expenses")
    dsl.register_derived_metric("ebitda", "revenue - payroll - expenses")
    dsl.initialize_optimizer()
    dsl.maximize("ebitda", weight=2.0)
    dsl.can_adjust_metric("expenses", min_pct=-30, max_pct=0, group_by="customer")

    result = dsl.solve(max_actions=5, algorithm="greedy")

    for customer in ("Acme", "Umbrella"):
        before = value_for(clients_df, customer, "expenses")
        after = value_for(result.result_df, customer, "expenses")
        change_pct = (after / before - 1) * 100
        assert change_pct >= -30.0 - 1e-6, (
            f"{customer} moved {change_pct:.1f}%, past the declared -30% floor"
        )


def test_optimizer_picks_one_action_per_group(clients_df):
    """At most one candidate per (metric, group) decision is selected."""
    dsl = WhatIfDSL(clients_df, "cut_expenses")
    dsl.register_derived_metric("ebitda", "revenue - payroll - expenses")
    dsl.initialize_optimizer()
    dsl.maximize("ebitda", weight=2.0)
    dsl.can_adjust_metric("expenses", min_pct=-30, max_pct=0, group_by="customer")

    result = dsl.solve(max_actions=5, algorithm="greedy")

    groups = [a.alternative_group for a in result.actions]
    assert len(groups) == len(set(groups))


def test_genetic_solver_also_respects_groups(clients_df):
    """The combinatorial solver must reject same-group combinations too."""
    dsl = WhatIfDSL(clients_df, "cut_expenses_genetic")
    dsl.register_derived_metric("ebitda", "revenue - payroll - expenses")
    dsl.initialize_optimizer()
    dsl.maximize("ebitda", weight=2.0)
    dsl.can_adjust_metric("expenses", min_pct=-30, max_pct=-30, group_by="customer")

    result = dsl.solve(max_actions=3, algorithm="genetic")

    groups = [a.alternative_group for a in result.actions]
    assert len(groups) == len(set(groups))
    for customer in ("Acme", "Umbrella"):
        before = value_for(clients_df, customer, "expenses")
        after = value_for(result.result_df, customer, "expenses")
        assert (after / before - 1) * 100 >= -30.0 - 1e-6


# ── independent decisions must still stack ───────────────────────────────


def test_different_entities_remain_independent(clients_df):
    """Scaling two different clients are two separate decisions."""
    dsl = WhatIfDSL(clients_df, "both_up_15")
    dsl.initialize_optimizer()
    dsl.can_scale_entity(
        entity_column="customer",
        target_columns=["expenses"],
        entities=["Acme", "Umbrella"],
        min_pct=15,
        max_pct=15,
    )

    result = dsl.solve(max_actions=5, algorithm="greedy")

    assert len(result.actions) == 2
    for customer in ("Acme", "Umbrella"):
        assert np.isclose(
            value_for(result.result_df, customer, "expenses"),
            value_for(clients_df, customer, "expenses") * 1.15,
        )


def test_excluding_several_values_still_stacks():
    """Excluding two regions is two independent actions, not alternatives."""
    # Three regions, so removing two still leaves rows behind: the solver
    # refuses an action that would empty the DataFrame, which would otherwise
    # mask whether exclusions stack.
    df = pd.DataFrame(
        {
            "customer": ["Acme", "Umbrella", "Stark"],
            "region": ["North", "West", "East"],
            "revenue": [1_200_000.0, 2_100_000.0, 975_000.0],
            "expenses": [350_000.0, 640_000.0, 300_000.0],
        }
    )
    dsl = WhatIfDSL(df, "drop_regions")
    dsl.initialize_optimizer()
    dsl.can_exclude_values("region", ["North", "West"])

    assert all(a.alternative_group is None for a in dsl.possible_actions)

    result = dsl.solve(max_actions=2, algorithm="greedy")

    assert len(result.actions) == 2
    assert result.result_df["region"].tolist() == ["East"]
