"""End-to-end verification of the What-If Scenario toolkit (``WhatIfToolkit``).

The toolkit lets an LLM answer *"what if ...?"* questions by mutating a base
dataset through a small DSL (:mod:`parrot_tools.whatif`) instead of writing
ad-hoc pandas code. This example exercises the whole stack on a financial
dataset of clients (``revenue`` / ``payroll`` / ``expenses`` / ``visits``,
with ``ebitda`` as a derived metric) and checks every result against ground
truth computed with plain pandas.

Four stages, each independently runnable::

    Stage 1 — DSL          WhatIfDSL directly (no toolkit, no LLM)
    Stage 2 — Toolkit      the 6 tools, called programmatically (no LLM)
    Stage 3 — Diagnostics  known integration gaps, reported not asserted
    Stage 4 — Agent        PandasAgent + LLM answering in natural language

Stages 1 and 2 assert exact numbers, so they fail loudly if the simulation
maths regresses. Stage 3 covers the integration edges that a pure-maths test
would miss, and that this example originally found broken: action compounding
in ``simulate``, the polarity-blind "Best" column in ``compare_scenarios``,
the multi-step tools rejecting the dict payloads an LLM actually sends, the
DatasetManager wiring, and dataset alias resolution. All of those are fixed
and asserted here so they stay fixed. Anything still open is printed as a
``[NOTE]`` rather than failing the run, so the script stays usable as a smoke
test while the finding stays visible.

Usage::

    source .venv/bin/activate

    # deterministic stages only (no API key needed, no network)
    python examples/data/whatif_scenario_e2e.py

    # add the LLM round-trip
    python examples/data/whatif_scenario_e2e.py --llm
    python examples/data/whatif_scenario_e2e.py --llm --provider google \\
        --model gemini-2.5-pro

Exit code is 0 when every check passes, 1 otherwise, so the script doubles as
a smoke test in CI.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import pandas as pd
from parrot_tools.whatif import (
    DerivedMetric,
    WhatIfAction,
    WhatIfConstraint,
    WhatIfDSL,
    WhatIfObjective,
)
from parrot_tools.whatif_toolkit import (
    WHATIF_TOOLKIT_SYSTEM_PROMPT,
    WhatIfToolkit,
    inject_whatif_system_prompt,
)

# Tolerance for float comparisons on monetary aggregates.
TOL = 0.01

# The client we mutate in the headline scenario, and by how much.
TARGET_CLIENT = "Acme"
EXPENSE_BUMP_PCT = 15.0

# ``ebitda`` is NOT a column: it is recomputed by the DSL after every mutation.
# This is the whole point of derived metrics — the simulation cannot go stale.
EBITDA = DerivedMetric(
    name="ebitda",
    formula="revenue - payroll - expenses",
    description="Operating result: revenue minus payroll and other expenses",
)

# Per-unit metrics enabling `scale_proportional`: the DSL looks up a derived
# metric literally named "<affected>_per_<base>" to propagate a change in the
# base column to the affected columns.
REVENUE_PER_VISIT = DerivedMetric(
    name="revenue_per_visits",
    formula="revenue / visits",
    description="Revenue generated per visit",
)
EXPENSES_PER_VISIT = DerivedMetric(
    name="expenses_per_visits",
    formula="expenses / visits",
    description="Cost incurred per visit",
)


# ======================================================================
# Base dataset + ground truth
# ======================================================================


def build_clients_dataset() -> pd.DataFrame:
    """Build the base client P&L dataset used by every stage.

    Returns:
        A DataFrame with one row per client and the columns ``customer``,
        ``region``, ``revenue``, ``payroll``, ``expenses`` and ``visits``.
        Values are hardcoded (not random) so the expected numbers printed by
        this example are reproducible run after run.
    """
    return pd.DataFrame(
        {
            "customer": [
                "Acme",
                "Globex",
                "Initech",
                "Umbrella",
                "Stark",
                "Wayne",
            ],
            "region": ["North", "South", "North", "West", "East", "West"],
            "revenue": [
                1_200_000.0,
                850_000.0,
                430_000.0,
                2_100_000.0,
                975_000.0,
                1_640_000.0,
            ],
            "payroll": [
                400_000.0,
                300_000.0,
                180_000.0,
                700_000.0,
                350_000.0,
                520_000.0,
            ],
            "expenses": [
                350_000.0,
                260_000.0,
                150_000.0,
                640_000.0,
                300_000.0,
                480_000.0,
            ],
            "visits": [
                1_200.0,
                980.0,
                610.0,
                2_400.0,
                1_100.0,
                1_750.0,
            ],
        }
    )


def ebitda_series(df: pd.DataFrame) -> pd.Series:
    """Compute EBITDA per row with plain pandas (the ground-truth oracle)."""
    return df["revenue"] - df["payroll"] - df["expenses"]


def expected_expense_bump(
    df: pd.DataFrame,
    customer: str,
    pct: float,
) -> dict[str, float]:
    """Ground truth for 'client X increases its expenses by pct%'.

    Args:
        df: Base dataset.
        customer: Client whose ``expenses`` grow.
        pct: Percentage increase (15.0 means +15%).

    Returns:
        Expected post-scenario totals for ``expenses`` and ``ebitda``, plus the
        absolute delta, all computed without touching the What-If code.
    """
    row = df.loc[df["customer"] == customer]
    delta = float(row["expenses"].iloc[0]) * pct / 100.0
    return {
        "delta": delta,
        "expenses": float(df["expenses"].sum()) + delta,
        "ebitda": float(ebitda_series(df).sum()) - delta,
        "revenue": float(df["revenue"].sum()),  # unchanged
    }


# ======================================================================
# Check recorder
# ======================================================================


class Checks:
    """Collects pass/fail results so one run reports every failure at once."""

    def __init__(self) -> None:
        self.passed: int = 0
        self.failed: int = 0
        self.notes: list[str] = []

    def ok(self, label: str, condition: bool, detail: str = "") -> bool:
        """Record a boolean assertion without aborting the run."""
        if condition:
            self.passed += 1
            print(f"  [PASS] {label}")
        else:
            self.failed += 1
            print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))
        return condition

    def close(self, label: str, actual: float, expected: float) -> bool:
        """Record a float comparison against ground truth."""
        delta = abs(float(actual) - float(expected))
        return self.ok(
            f"{label}: {actual:,.2f} == {expected:,.2f}",
            delta <= TOL,
            f"off by {delta:,.4f}",
        )

    def note(self, message: str) -> None:
        """Record a diagnostic that is reported but never fails the run."""
        self.notes.append(message)
        print(f"  [NOTE] {message}")

    def report(self) -> int:
        """Print the summary and return the process exit code."""
        print("\n" + "=" * 72)
        print(f"RESULT: {self.passed} passed, {self.failed} failed")
        if self.notes:
            print(f"\nDiagnostics ({len(self.notes)}):")
            for note in self.notes:
                print(f"  - {note}")
        print("=" * 72)
        return 1 if self.failed else 0


def banner(title: str) -> None:
    """Print a stage header."""
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def total(df: pd.DataFrame, column: str) -> float:
    """Sum a column as a float."""
    return float(df[column].sum())


def value_for(df: pd.DataFrame, customer: str, column: str) -> float:
    """Read a single client's value for a column."""
    return float(df.loc[df["customer"] == customer, column].iloc[0])


def parse_scenario_id(described: str) -> str:
    """Extract the scenario id from ``describe_scenario`` output.

    The id must be read back rather than assumed: the toolkit's counter only
    advances on a successful call, so a rejected formula or an unknown dataset
    leaves the numbering unchanged.

    Args:
        described: Raw text returned by ``describe_scenario``.

    Returns:
        The scenario id (for example ``"sc_1"``).

    Raises:
        ValueError: If no scenario id is present in the text.
    """
    for token in described.split():
        if token.startswith("sc_"):
            return token
    raise ValueError(f"No scenario id found in: {described!r}")


# ======================================================================
# Stage 1 — the DSL itself
# ======================================================================


def stage_dsl(df: pd.DataFrame, checks: Checks) -> None:
    """Verify the DSL primitives the toolkit is built on.

    Covers the three action families that matter for client-level financial
    what-ifs: per-entity scaling, entity exclusion and proportional scaling
    driven by derived per-unit metrics. Also verifies that a hard constraint
    actually rejects a scenario.

    Args:
        df: Base dataset.
        checks: Result recorder.
    """
    banner("STAGE 1 -- WhatIfDSL (no toolkit, no LLM)")
    expected = expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)

    # --- 1.1 scale one entity's expenses by +15% -----------------------
    print(f"\n1.1 scale_entity: {TARGET_CLIENT} expenses +{EXPENSE_BUMP_PCT}%")
    dsl = WhatIfDSL(df, name="acme_expenses_up_15")
    dsl.register_derived_metric(EBITDA.name, EBITDA.formula)
    dsl.initialize_optimizer()
    dsl.can_scale_entity(
        entity_column="customer",
        target_columns=["expenses"],
        entities=[TARGET_CLIENT],
        min_pct=EXPENSE_BUMP_PCT,
        max_pct=EXPENSE_BUMP_PCT,
    )
    # max_actions=1 is deliberate: see the compounding note in stage 3.
    result = dsl.solve(max_actions=1, algorithm="greedy")
    mutated = result.result_df

    checks.ok(
        "exactly one action applied",
        len(result.actions) == 1,
        f"got {len(result.actions)}",
    )
    checks.close(
        f"{TARGET_CLIENT} expenses",
        value_for(mutated, TARGET_CLIENT, "expenses"),
        value_for(df, TARGET_CLIENT, "expenses") * (1 + EXPENSE_BUMP_PCT / 100),
    )
    checks.close("total expenses", total(mutated, "expenses"), expected["expenses"])
    checks.close("total revenue untouched", total(mutated, "revenue"), expected["revenue"])
    checks.close(
        "derived ebitda recomputed",
        float(ebitda_series(mutated).sum()),
        expected["ebitda"],
    )
    others = df["customer"] != TARGET_CLIENT
    checks.ok(
        "other clients untouched",
        bool((mutated.loc[others, "expenses"].values == df.loc[others, "expenses"].values).all()),
    )

    # The optimizer's own metric view must agree with the pandas oracle —
    # this is what the LLM ultimately reads in the comparison table.
    metrics = result.compare()["metrics"]
    checks.close("optimizer view: expenses", metrics["expenses"]["value"], expected["expenses"])
    checks.close("optimizer view: ebitda", metrics["ebitda"]["value"], expected["ebitda"])

    # --- 1.2 drop a client entirely -----------------------------------
    print("\n1.2 exclude_values: drop client Initech")
    dsl_drop = WhatIfDSL(df, name="drop_initech")
    dsl_drop.register_derived_metric(EBITDA.name, EBITDA.formula)
    dsl_drop.initialize_optimizer()
    dsl_drop.can_exclude_values("customer", ["Initech"])
    dropped = dsl_drop.solve(max_actions=1, algorithm="greedy").result_df

    checks.ok("row removed", len(dropped) == len(df) - 1, f"got {len(dropped)} rows")
    checks.close(
        "revenue loses exactly Initech",
        total(dropped, "revenue"),
        total(df, "revenue") - value_for(df, "Initech", "revenue"),
    )

    # --- 1.3 proportional scaling via per-unit derived metrics ---------
    print("\n1.3 scale_proportional: Umbrella visits +20% drags revenue/expenses")
    dsl_prop = WhatIfDSL(df, name="umbrella_visits_up_20")
    dsl_prop.register_derived_metric(REVENUE_PER_VISIT.name, REVENUE_PER_VISIT.formula)
    dsl_prop.register_derived_metric(EXPENSES_PER_VISIT.name, EXPENSES_PER_VISIT.formula)
    dsl_prop.initialize_optimizer()
    dsl_prop.can_scale_proportional(
        base_column="visits",
        affected_columns=["revenue", "expenses"],
        min_pct=20,
        max_pct=20,
        group_by="customer",
    )
    umbrella_action = next(
        (a for a in dsl_prop.possible_actions if "Umbrella" in a.name), None
    )
    if checks.ok("Umbrella proportional action generated", umbrella_action is not None):
        scaled = dsl_prop._apply_action(umbrella_action)
        checks.close(
            "Umbrella visits +20%",
            value_for(scaled, "Umbrella", "visits"),
            value_for(df, "Umbrella", "visits") * 1.2,
        )
        checks.close(
            "Umbrella revenue follows visits",
            value_for(scaled, "Umbrella", "revenue"),
            value_for(df, "Umbrella", "revenue") * 1.2,
        )
        checks.close(
            "Stark revenue unaffected",
            value_for(scaled, "Stark", "revenue"),
            value_for(df, "Stark", "revenue"),
        )

    # --- 1.4 a hard constraint must veto the scenario -----------------
    print("\n1.4 constraint enforcement: revenue may not move at all")
    dsl_c = WhatIfDSL(df, name="cut_revenue_but_forbidden")
    dsl_c.register_derived_metric(EBITDA.name, EBITDA.formula)
    dsl_c.initialize_optimizer()
    dsl_c.minimize("expenses")
    dsl_c.constrain_change("revenue", max_pct=0.0)  # revenue is frozen
    dsl_c.can_scale_entity(
        entity_column="customer",
        target_columns=["revenue", "expenses"],  # touching revenue violates it
        entities=[TARGET_CLIENT],
        min_pct=-20,
        max_pct=-20,
    )
    vetoed = dsl_c.solve(max_actions=3, algorithm="greedy")
    checks.ok(
        "constraint rejected every candidate action",
        len(vetoed.actions) == 0,
        f"applied {len(vetoed.actions)} actions despite frozen revenue",
    )
    checks.close("revenue really unchanged", total(vetoed.result_df, "revenue"), total(df, "revenue"))


# ======================================================================
# Stage 2 — the 6 toolkit tools
# ======================================================================


class DataframeHost:
    """Minimal stand-in for the parent agent's DataFrame registry.

    ``WhatIfToolkit._resolve_dataframe`` falls back to ``parent.dataframes``
    when no DatasetManager yields a DataFrame, so this is all the toolkit
    needs to run outside a full PandasAgent.
    """

    def __init__(self, dataframes: dict[str, pd.DataFrame]) -> None:
        self.dataframes = dataframes


async def stage_toolkit(df: pd.DataFrame, checks: Checks) -> None:
    """Exercise all 6 tools the LLM can call, and their validation paths.

    Args:
        df: Base dataset.
        checks: Result recorder.
    """
    banner("STAGE 2 -- WhatIfToolkit tools (no LLM)")
    expected = expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)

    toolkit = WhatIfToolkit()
    toolkit._parent_agent = DataframeHost({"clients": df})

    tool_names = sorted(toolkit.list_tool_names())
    print(f"\nExposed tools: {tool_names}")
    checks.ok(
        "all 6 tools exposed to the LLM",
        tool_names
        == [
            "add_actions",
            "compare_scenarios",
            "describe_scenario",
            "quick_impact",
            "set_constraints",
            "simulate",
        ],
    )

    # --- 2.1 quick_impact: the one-shot fast path ----------------------
    print("\n2.1 quick_impact -- 'what if Acme increases expenses by 15%?'")
    quick = await toolkit.quick_impact(
        df_name="clients",
        action_description=f"{TARGET_CLIENT} expenses +{EXPENSE_BUMP_PCT}%",
        action_type="scale_entity",
        target="customer",
        parameters={
            "entity_column": "customer",
            "entities": [TARGET_CLIENT],
            "target_columns": ["expenses"],
            "min_pct": EXPENSE_BUMP_PCT,
            "max_pct": EXPENSE_BUMP_PCT,
            # quick_impact accepts derived metrics inline
            "derived_metrics": [{"name": EBITDA.name, "formula": EBITDA.formula}],
        },
    )
    print(quick)
    checks.ok("quick_impact reports ebitda", "ebitda" in quick)
    checks.ok(
        "quick_impact expenses total is exact",
        f"{expected['expenses']:,.2f}" in quick,
        f"expected {expected['expenses']:,.2f} in the comparison table",
    )
    checks.ok(
        "quick_impact ebitda total is exact",
        f"{expected['ebitda']:,.2f}" in quick,
        f"expected {expected['ebitda']:,.2f} in the comparison table",
    )

    # --- 2.2 describe_scenario ----------------------------------------
    print("\n2.2 describe_scenario -- create + validate the scenario")
    described = await toolkit.describe_scenario(
        df_name="clients",
        scenario_description=f"{TARGET_CLIENT} expenses +{EXPENSE_BUMP_PCT}%",
        derived_metrics=[EBITDA],
    )
    print(described)
    bump_id = parse_scenario_id(described)
    checks.ok("scenario id returned", bump_id.startswith("sc_"))
    checks.ok("ebitda formula validated", "validated OK" in described)
    checks.ok("column inventory surfaced for planning", "revenue(numeric" in described)

    print("\n    describe_scenario rejects an invalid formula")
    try:
        await toolkit.describe_scenario(
            df_name="clients",
            scenario_description="bad formula",
            derived_metrics=[DerivedMetric(name="broken", formula="revenue / nope")],
        )
        checks.ok("invalid derived metric raises", False, "no error raised")
    except ValueError as exc:
        checks.ok("invalid derived metric raises", "broken" in str(exc))

    print("\n    describe_scenario rejects an unknown dataset")
    try:
        await toolkit.describe_scenario(df_name="ghost", scenario_description="x")
        checks.ok("unknown dataset raises", False, "no error raised")
    except ValueError as exc:
        checks.ok("unknown dataset raises", "not found" in str(exc))

    # --- 2.3 add_actions (valid + invalid) -----------------------------
    print("\n2.3 add_actions -- schema validation feedback for the LLM")
    added = await toolkit.add_actions(
        scenario_id=bump_id,
        actions=[
            WhatIfAction(
                type="scale_entity",
                target="customer",
                parameters={
                    "entity_column": "customer",
                    "entities": [TARGET_CLIENT],
                    "target_columns": ["expenses"],
                    "min_pct": EXPENSE_BUMP_PCT,
                    "max_pct": EXPENSE_BUMP_PCT,
                },
            ),
            # Hallucinated column: must be rejected, not silently accepted.
            WhatIfAction(type="adjust_metric", target="ebit_margin", parameters={}),
            # Non-numeric column for a numeric action: also rejected.
            WhatIfAction(type="adjust_metric", target="region", parameters={}),
        ],
    )
    print(added)
    checks.ok("1 valid action accepted", "1 action(s) added successfully" in added)
    checks.ok("2 bogus actions rejected", "2 action(s) invalid" in added)
    checks.ok("rejection explains why", "not numeric" in added or "not found" in added)

    # --- 2.4 simulate --------------------------------------------------
    print("\n2.4 simulate -- run the scenario through the optimizer")
    simulated = await toolkit.simulate(bump_id, algorithm="greedy", max_actions=1)
    print(simulated)
    checks.ok(
        "simulate expenses total is exact",
        f"{expected['expenses']:,.2f}" in simulated,
        f"expected {expected['expenses']:,.2f}",
    )
    checks.ok(
        "simulate ebitda total is exact",
        f"{expected['ebitda']:,.2f}" in simulated,
        f"expected {expected['ebitda']:,.2f}",
    )
    checks.ok(
        "action described in plain language",
        f"Scale {TARGET_CLIENT} by +15.0%" in simulated,
    )

    print("\n    simulate refuses a scenario with no actions")
    empty_id = parse_scenario_id(
        await toolkit.describe_scenario("clients", "empty scenario", [EBITDA])
    )
    try:
        await toolkit.simulate(empty_id)
        checks.ok("empty scenario raises", False, "no error raised")
    except ValueError as exc:
        checks.ok("empty scenario raises", "no actions" in str(exc), str(exc))

    # --- 2.5 set_constraints + optimization ----------------------------
    print("\n2.5 set_constraints + simulate -- 'cut expenses, keep revenue flat'")
    opt_id = parse_scenario_id(
        await toolkit.describe_scenario(
            df_name="clients",
            scenario_description="cut expenses without touching revenue",
            derived_metrics=[EBITDA],
        )
    )
    await toolkit.add_actions(
        scenario_id=opt_id,
        actions=[
            WhatIfAction(
                type="adjust_metric",
                target="expenses",
                parameters={"min_pct": -30, "max_pct": 0, "group_by": "customer"},
            )
        ],
    )
    constrained = await toolkit.set_constraints(
        scenario_id=opt_id,
        objectives=[WhatIfObjective(type="maximize", metric="ebitda", weight=2.0)],
        constraints=[
            WhatIfConstraint(type="max_change", metric="revenue", value=1.0),
            # Deliberately unknown metric: must be reported, not crash.
            WhatIfConstraint(type="min_value", metric="cashflow", value=0.0),
        ],
    )
    print(constrained)
    checks.ok("valid objective stored", "Objectives: 1" in constrained)
    checks.ok("unknown constraint metric flagged", "cashflow" in constrained)

    optimized = await toolkit.simulate(opt_id, algorithm="greedy", max_actions=3)
    print(optimized)
    opt_state = toolkit._scenarios[opt_id]
    opt_metrics = opt_state.result.compare()["metrics"]
    checks.ok(
        "optimizer improved ebitda",
        opt_metrics["ebitda"]["change"] > 0,
        f"change was {opt_metrics['ebitda']['change']:,.2f}",
    )
    checks.ok(
        "optimizer reduced expenses",
        opt_metrics["expenses"]["change"] < 0,
        f"change was {opt_metrics['expenses']['change']:,.2f}",
    )
    checks.ok(
        "revenue constraint respected (<=1%)",
        abs(opt_metrics["revenue"]["pct_change"]) <= 1.0,
        f"revenue moved {opt_metrics['revenue']['pct_change']:.2f}%",
    )
    # The action declared expenses may fall by AT MOST 30%. The optimizer must
    # not reach further by stacking two of the candidate percentages it was
    # offered for the same client.
    opt_result_df = opt_state.result.result_df
    worst_client, worst_pct = "", 0.0
    for client in df["customer"]:
        before = value_for(df, client, "expenses")
        after = value_for(opt_result_df, client, "expenses")
        pct = (after / before - 1) * 100
        if pct < worst_pct:
            worst_client, worst_pct = client, pct
    checks.ok(
        "no client exceeds the declared -30% expense floor",
        worst_pct >= -30.0 - 1e-6,
        f"{worst_client} moved {worst_pct:.1f}%",
    )

    # --- 2.6 compare_scenarios -----------------------------------------
    print("\n2.6 compare_scenarios -- pessimistic vs optimization side by side")
    comparison = await toolkit.compare_scenarios([bump_id, opt_id])
    print(comparison)
    checks.ok(
        "both scenarios in the matrix",
        bump_id in comparison and opt_id in comparison,
    )
    checks.ok("ebitda row present", "ebitda" in comparison)

    print("\n    compare_scenarios refuses unsimulated scenarios")
    try:
        await toolkit.compare_scenarios([bump_id, empty_id])
        checks.ok("unsimulated scenario raises", False, "no error raised")
    except ValueError as exc:
        checks.ok("unsimulated scenario raises", "not been simulated" in str(exc))

    # --- 2.7 the same workflow driven the way an LLM drives it ---------
    print("\n2.7 full workflow through tool.execute() with raw JSON payloads")
    # Everything above passed real DerivedMetric / WhatIfAction objects. An LLM
    # cannot: it emits JSON, so the tool layer receives plain dicts and must
    # coerce them into the declared models before the method body runs. This is
    # the exact path that used to fail with
    # "'dict' object has no attribute 'name'".
    await stage_llm_payloads(df, checks)


async def stage_llm_payloads(df: pd.DataFrame, checks: Checks) -> None:
    """Drive the multi-step workflow with the payload shape an LLM emits.

    Tools are invoked through ``tool.execute(**payload)`` rather than by
    calling the bound methods, because that is the path an agent takes: the
    tool layer validates the raw JSON against the generated schema and must
    hand the method the declared model instances, not plain dicts.

    Args:
        df: Base dataset.
        checks: Result recorder.
    """
    toolkit = WhatIfToolkit()
    toolkit._parent_agent = DataframeHost({"clients": df})
    expected = expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)

    async def call(tool_name: str, **payload: Any) -> str:
        """Invoke a toolkit tool exactly as the agent runtime would."""
        result = await toolkit.get_tool(tool_name).execute(**payload)
        if getattr(result, "status", None) == "error" or getattr(result, "error", None):
            raise RuntimeError(f"{tool_name}: {result.error}")
        return str(result.result)

    described = await call(
        "describe_scenario",
        df_name="clients",
        scenario_description="llm-shaped call",
        # raw JSON, exactly as a model emits it
        derived_metrics=[{"name": EBITDA.name, "formula": EBITDA.formula}],
    )
    scenario_id = parse_scenario_id(described)
    checks.ok("describe_scenario accepts raw JSON derived_metrics", "validated OK" in described)

    added = await call(
        "add_actions",
        scenario_id=scenario_id,
        actions=[
            {
                "type": "scale_entity",
                "target": "customer",
                "parameters": {
                    "entity_column": "customer",
                    "entities": [TARGET_CLIENT],
                    "target_columns": ["expenses"],
                    "min_pct": EXPENSE_BUMP_PCT,
                    "max_pct": EXPENSE_BUMP_PCT,
                },
            }
        ],
    )
    checks.ok(
        "add_actions accepts raw JSON actions",
        "1 action(s) added successfully" in added,
        added,
    )

    # set_constraints is exercised on its own scenario: attaching an
    # optimization objective changes what simulate() is allowed to do (greedy
    # would rightly refuse a +15% expense action while maximizing ebitda), so
    # the numeric assertion below runs on the plain what-if scenario instead.
    opt_id = parse_scenario_id(
        await call(
            "describe_scenario",
            df_name="clients",
            scenario_description="llm-shaped optimization",
            derived_metrics=[{"name": EBITDA.name, "formula": EBITDA.formula}],
        )
    )
    await call(
        "add_actions",
        scenario_id=opt_id,
        actions=[
            {
                "type": "adjust_metric",
                "target": "expenses",
                "parameters": {"min_pct": -30, "max_pct": 0, "group_by": "customer"},
            }
        ],
    )
    constrained = await call(
        "set_constraints",
        scenario_id=opt_id,
        objectives=[{"type": "maximize", "metric": "ebitda", "weight": 1.0}],
        constraints=[{"type": "max_change", "metric": "revenue", "value": 1.0}],
    )
    checks.ok(
        "set_constraints accepts raw JSON objectives/constraints",
        "Objectives: 1" in constrained and "Constraints: 1" in constrained,
        constrained,
    )

    simulated = await call("simulate", scenario_id=scenario_id, max_actions=1)
    checks.ok(
        "the LLM-driven workflow produces the exact same numbers",
        f"{expected['expenses']:,.2f}" in simulated
        and f"{expected['ebitda']:,.2f}" in simulated,
        simulated,
    )


# ======================================================================
# Stage 3 — known integration gaps (reported, never asserted)
# ======================================================================


async def stage_diagnostics(df: pd.DataFrame, checks: Checks) -> None:
    """Probe integration edges that behave surprisingly today.

    These are reported as diagnostics rather than failures so that this
    example keeps passing while the findings stay visible; if any of them is
    fixed, the corresponding note simply stops printing.

    Args:
        df: Base dataset.
        checks: Result recorder.
    """
    banner("STAGE 3 -- integration diagnostics")

    # --- 3.1 max_actions compounds a fixed-percentage action -----------
    print("\n3.1 simulate(max_actions=N) with a fixed-percentage action")
    toolkit = WhatIfToolkit()
    toolkit._parent_agent = DataframeHost({"clients": df})
    probe_id = parse_scenario_id(
        await toolkit.describe_scenario("clients", "compounding probe", [EBITDA])
    )
    await toolkit.add_actions(
        probe_id,
        [
            WhatIfAction(
                type="scale_entity",
                target="customer",
                parameters={
                    "entity_column": "customer",
                    "entities": [TARGET_CLIENT],
                    "target_columns": ["expenses"],
                    "min_pct": EXPENSE_BUMP_PCT,
                    "max_pct": EXPENSE_BUMP_PCT,
                },
            )
        ],
    )
    # simulate() defaults to max_actions=5. A fixed-percentage action must
    # still be applied exactly once: the ten candidate percentages a `can_*`
    # call generates are alternatives for one decision, not steps that stack.
    compounded = await toolkit.simulate(probe_id)
    applied = len(toolkit._scenarios[probe_id].result.actions)
    once = expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)["expenses"]
    got = float(toolkit._scenarios[probe_id].result.result_df["expenses"].sum())
    checks.ok(
        "default max_actions applies a fixed-percentage action only once",
        applied == 1,
        f"applied {applied} actions",
    )
    checks.close("expenses after the default-max_actions run", got, once)
    print(f"  {compounded.splitlines()[0]}")

    # --- 3.2 compare_scenarios 'Best' column polarity -------------------
    print("\n3.2 compare_scenarios 'Best' column semantics")
    cut_id = parse_scenario_id(
        await toolkit.describe_scenario("clients", "mild expense cut", [EBITDA])
    )
    await toolkit.add_actions(
        cut_id,
        [
            WhatIfAction(
                type="adjust_metric",
                target="expenses",
                parameters={"min_pct": -10, "max_pct": -10, "group_by": "customer"},
            )
        ],
    )
    await toolkit.simulate(cut_id, max_actions=1)

    # probe_id has the HIGHER expenses of the two. Neither scenario declared
    # an objective, so nothing defines which direction is "better" and the
    # table must not crown either one.
    matrix = await toolkit.compare_scenarios([probe_id, cut_id])
    expenses_row = next(
        (line for line in matrix.splitlines() if line.startswith("| expenses")), ""
    )
    checks.ok(
        "costs are left unranked when no objective declares a direction",
        expenses_row.strip().endswith("| n/a |"),
        expenses_row.strip(),
    )
    checks.ok(
        "the table explains why nothing was ranked",
        "Not ranked" in matrix,
    )
    print(f"  {expenses_row}")

    # Declare the direction and the ranking becomes meaningful.
    await toolkit.set_constraints(
        probe_id, objectives=[WhatIfObjective(type="minimize", metric="expenses")]
    )
    await toolkit.set_constraints(
        cut_id, objectives=[WhatIfObjective(type="minimize", metric="expenses")]
    )
    ranked = await toolkit.compare_scenarios([probe_id, cut_id])
    ranked_row = next(
        (line for line in ranked.splitlines() if line.startswith("| expenses")), ""
    )
    checks.ok(
        "with 'minimize expenses' declared, the cheaper scenario wins",
        ranked_row.strip().endswith(f"| {cut_id} |"),
        ranked_row.strip(),
    )
    print(f"  {ranked_row}")

    # --- 3.3 simulate() registering its result back --------------------
    print("\n3.3 simulate() registering its result in the DatasetManager")
    try:
        from parrot.tools.dataset_manager import DatasetManager
    except ImportError:  # pragma: no cover - optional dependency path
        print("  DatasetManager unavailable, skipping")
        return

    manager = DatasetManager()
    manager.add_dataframe(name="clients", df=df, description="client P&L")
    dm_toolkit = WhatIfToolkit(dataset_manager=manager)
    result_id = parse_scenario_id(
        await dm_toolkit.describe_scenario("clients", "registration probe", [EBITDA])
    )
    await dm_toolkit.add_actions(
        result_id,
        [
            WhatIfAction(
                type="scale_entity",
                target="customer",
                parameters={
                    "entity_column": "customer",
                    "entities": [TARGET_CLIENT],
                    "target_columns": ["expenses"],
                    "min_pct": EXPENSE_BUMP_PCT,
                    "max_pct": EXPENSE_BUMP_PCT,
                },
            )
        ],
    )
    announced = await dm_toolkit.simulate(result_id, max_actions=1)
    result_name = f"whatif_{result_id}_result"
    catalog = manager.get_active_dataframes()
    checks.ok(
        "the result dataset really exists in the catalog",
        result_name in catalog,
        f"catalog holds {sorted(catalog)}",
    )
    checks.ok(
        "simulate() announces where it stored the result",
        f"registered as: '{result_name}'" in announced,
    )
    if result_name in catalog:
        stored = catalog[result_name]
        checks.close(
            "the stored dataset carries the scenario's values, not the baseline",
            float(stored["expenses"].sum()),
            expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)["expenses"],
        )
    print(f"  result registered as {result_name!r}")

    # A catalog that refuses the result must not make simulate() lie about it,
    # and must not cost the caller their analysis either.
    class RefusingManager:
        """DatasetManager stand-in whose writes always fail."""

        def get_active_dataframes(self) -> dict:
            """Expose the source dataset so the scenario can be built."""
            return {"clients": df}

        def _resolve_name(self, identifier: str) -> str:
            """Names only."""
            return identifier

        def add_dataframe(self, **kwargs):
            """Always fail."""
            raise RuntimeError("catalog unavailable")

    refusing = WhatIfToolkit(dataset_manager=RefusingManager())
    refused_id = parse_scenario_id(
        await refusing.describe_scenario("clients", "refused probe", [EBITDA])
    )
    await refusing.add_actions(
        refused_id,
        [
            WhatIfAction(
                type="scale_entity",
                target="customer",
                parameters={
                    "entity_column": "customer",
                    "entities": [TARGET_CLIENT],
                    "target_columns": ["expenses"],
                    "min_pct": EXPENSE_BUMP_PCT,
                    "max_pct": EXPENSE_BUMP_PCT,
                },
            )
        ],
    )
    refused = await refusing.simulate(refused_id, max_actions=1)
    checks.ok(
        "a failed registration is not announced",
        "Result DataFrame registered as" not in refused,
    )
    checks.ok(
        "a failed registration still returns the analysis",
        "Simulation complete" in refused and "ebitda" in refused,
    )

    # --- 3.4 dataset aliases -------------------------------------------
    print("\n3.4 dataset alias resolution")
    # Every what-if tool documents df_name as "Name or alias", and PandasAgent
    # actively tells the LLM to refer to datasets by their alias (df1, df2...),
    # so alias lookups have to work or the LLM is told the dataset is missing.
    alias_map = manager._get_alias_map()
    alias = alias_map.get("clients")
    aliased = WhatIfToolkit(dataset_manager=manager)
    aliased._parent_agent = DataframeHost({"clients": df})
    checks.ok(
        "the real dataset name resolves",
        (await aliased._resolve_dataframe("clients"))[0] == "clients",
    )
    if alias:
        resolved, _ = await aliased._resolve_dataframe(alias)
        checks.ok(
            f"the advertised alias {alias!r} resolves to the canonical name",
            resolved == "clients",
            f"got {resolved!r}",
        )
    checks.ok(
        "a differently-cased name resolves",
        (await aliased._resolve_dataframe("CLIENTS"))[0] == "clients",
    )
    # A DatasetManager on its own (no parent agent) must also work: that is how
    # the toolkit is wired when it is not hosted by a PandasAgent.
    standalone = WhatIfToolkit(dataset_manager=manager)
    checks.ok(
        "a DatasetManager alone can serve the dataset",
        (await standalone._resolve_dataframe("clients"))[1].shape == df.shape,
    )
    try:
        await aliased._resolve_dataframe("ghost")
        checks.ok("an unknown dataset raises", False, "no error raised")
    except ValueError as exc:
        checks.ok(
            "an unknown dataset lists the names and aliases available",
            "clients" in str(exc) and (not alias or alias in str(exc)),
            str(exc),
        )


# ======================================================================
# Stage 4 — natural-language round trip through an LLM
# ======================================================================


class InstrumentedWhatIfToolkit(WhatIfToolkit):
    """WhatIfToolkit that records which tools the LLM actually invoked.

    Without this, an agent can answer a what-if question *correctly* while
    never calling the toolkit (for example by computing it in the pandas
    REPL), which would make the end-to-end check meaningless.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.invocations: list[tuple[str, dict[str, Any]]] = []

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Record the call, then defer to the standard hook."""
        self.invocations.append((tool_name, kwargs))
        return await super()._pre_execute(tool_name, **kwargs)

    @property
    def tools_used(self) -> list[str]:
        """Names of the toolkit tools invoked so far, in order."""
        return [name for name, _ in self.invocations]


ROUTING_POLICY = """
## MANDATORY ROUTING RULE FOR HYPOTHETICAL QUESTIONS

Any question about a hypothetical change to the data ("what if ...?",
"que pasa si ...?", "simulate ...", "impact of ...") MUST be answered by
calling the what-if toolkit:

  * one single change  -> `quick_impact`
  * optimization under constraints ->
    `describe_scenario` -> `add_actions` -> `set_constraints` -> `simulate`

Do NOT reproduce a scenario with `python_repl_pandas`. The REPL is only for
descriptive questions about the data as it actually is. Scenario simulation
belongs to the what-if toolkit so that results are reproducible, comparable
across scenarios and stored under a scenario id.

Dataset notes: `ebitda` is not a column. It is a derived metric,
`revenue - payroll - expenses`, and must be passed as a derived metric so the
toolkit recomputes it after the mutation.
""".strip()


async def stage_agent(
    df: pd.DataFrame,
    checks: Checks,
    provider: str,
    model: str,
) -> None:
    """Ask a real LLM the what-if questions in natural language.

    Args:
        df: Base dataset.
        checks: Result recorder.
        provider: LLM provider name for ``LLMFactory.create``.
        model: Model id for the provider.
    """
    banner(f"STAGE 4 -- PandasAgent + LLM ({provider}:{model})")

    from parrot.bots.data import PandasAgent
    from parrot.clients.factory import LLMFactory

    expected = expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)

    client = LLMFactory.create(llm=provider, model=model)
    agent = PandasAgent(
        llm=client,
        name="WhatIfAnalyst",
        description="Financial analyst running client-level what-if scenarios",
        df={"clients": df},
        enable_cache=False,
    )

    # `integrate_whatif_toolkit(agent)` does exactly this, in one call; it is
    # inlined here only so the instrumented subclass can be used.
    toolkit = InstrumentedWhatIfToolkit()
    toolkit._parent_agent = agent
    for tool in toolkit.get_tools():
        agent.tool_manager.register(tool)
    mechanism = inject_whatif_system_prompt(
        agent, f"{WHATIF_TOOLKIT_SYSTEM_PROMPT}\n\n{ROUTING_POLICY}"
    )
    checks.ok(
        "the toolkit's instructions were injected into the agent",
        mechanism is not None,
        "no injection mechanism available",
    )
    print(f"  injected via: {mechanism}")

    await agent.configure()

    # Injecting is not the same as arriving. PandasAgent renders from
    # PromptBuilder layers and ignores system_prompt / system_prompt_template,
    # so this asserts against the prompt the model is actually handed.
    rendered = agent._build_prompt()
    rendered_text = (
        rendered if isinstance(rendered, str)
        else "".join(str(segment) for segment in rendered)
    )
    checks.ok(
        "the instructions reach the prompt the model actually receives",
        "What-If Scenario Analysis Toolkit" in rendered_text,
        "the toolkit section is absent from the rendered prompt",
    )
    checks.ok(
        "the routing rule reaches the model too",
        "MANDATORY ROUTING RULE" in rendered_text,
    )

    registered = [
        getattr(t, "name", "") for t in agent.tool_manager.get_tools()
    ]
    checks.ok(
        "toolkit tools reached the agent's tool list",
        all(
            name in registered
            for name in ("quick_impact", "describe_scenario", "simulate")
        ),
        f"registered: {sorted(n for n in registered if n)}",
    )

    question = (
        "Usando el dataset 'clients': ¿Que pasa si el cliente Acme incrementa "
        "sus expenses en un 15%? Muestra la tabla comparativa de revenue, "
        "expenses y ebitda antes y despues, y el impacto total en ebitda."
    )
    print(f"\nQ: {question}")
    answer = await agent.ask(question)
    text = str(getattr(answer, "response", answer))
    print(f"\nA: {text}")

    print(f"\nToolkit tools invoked: {toolkit.tools_used or '(none)'}")
    used_toolkit = checks.ok(
        "the LLM routed the what-if question to the toolkit",
        bool(toolkit.tools_used),
        "the agent answered without calling any what-if tool "
        "(most likely it used python_repl_pandas instead)",
    )
    if not used_toolkit:
        checks.note(
            "Tool-selection gap: with PandasAgent's full tool set, the LLM "
            "prefers python_repl_pandas over the what-if tools even with an "
            "explicit routing rule in the system prompt. The toolkit itself "
            "computes correctly (stages 1-2); what fails is the routing."
        )

    checks.ok(
        "answer quotes the expected ebitda impact",
        f"{expected['delta']:,.0f}" in text or f"{expected['delta']:,.2f}" in text,
        f"expected a delta of {expected['delta']:,.2f} to appear in the answer",
    )

    # Optimization phrasing: this one should take the multi-step path.
    question2 = (
        "Ahora encuentra la mejor combinacion de recortes de expenses por "
        "cliente para maximizar el ebitda total, sin que el revenue total "
        "caiga mas de 1%. Compara ese escenario con el anterior."
    )
    print(f"\nQ: {question2}")
    answer2 = await agent.ask(question2)
    print(f"\nA: {getattr(answer2, 'response', answer2)!s}")
    print(f"\nToolkit tools invoked (cumulative): {toolkit.tools_used or '(none)'}")


# ======================================================================
# Entrypoint
# ======================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="End-to-end verification of the What-If Scenario toolkit",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="also run stage 4 (needs an LLM API key and network access)",
    )
    parser.add_argument(
        "--provider",
        default="anthropic",
        help="LLM provider for stage 4 (default: anthropic)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-5",
        help="model id for stage 4 (default: claude-sonnet-4-5)",
    )
    parser.add_argument(
        "--stage",
        choices=("dsl", "toolkit", "diagnostics", "all"),
        default="all",
        help="run only one deterministic stage (default: all)",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    """Run the selected stages and return the process exit code."""
    args = parse_args(argv)
    checks = Checks()
    df = build_clients_dataset()

    banner("BASE DATASET -- client P&L")
    print(df.to_string(index=False))
    print(
        f"\nTotals: revenue={total(df, 'revenue'):,.2f} "
        f"payroll={total(df, 'payroll'):,.2f} "
        f"expenses={total(df, 'expenses'):,.2f} "
        f"ebitda={float(ebitda_series(df).sum()):,.2f}"
    )
    expected = expected_expense_bump(df, TARGET_CLIENT, EXPENSE_BUMP_PCT)
    print(
        f"\nGround truth for '{TARGET_CLIENT} expenses +{EXPENSE_BUMP_PCT}%': "
        f"expenses -> {expected['expenses']:,.2f}, "
        f"ebitda -> {expected['ebitda']:,.2f} "
        f"(delta {expected['delta']:,.2f})"
    )

    if args.stage in ("dsl", "all"):
        stage_dsl(df, checks)
    if args.stage in ("toolkit", "all"):
        await stage_toolkit(df, checks)
    if args.stage in ("diagnostics", "all"):
        await stage_diagnostics(df, checks)
    if args.llm:
        await stage_agent(df, checks, args.provider, args.model)

    return checks.report()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
