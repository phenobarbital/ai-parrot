"""
WhatIf Toolkit — Decomposed What-If Scenario Analysis.

Provides 6 focused tools for incremental scenario building:
  1. describe_scenario — create & validate a scenario
  2. add_actions — add possible actions to a scenario
  3. set_constraints — set optimization objectives/constraints
  4. simulate — execute the scenario via WhatIfDSL
  5. quick_impact — fast-path for simple single-action queries
  6. compare_scenarios — side-by-side comparison of solved scenarios
"""
from typing import Dict, List, Optional, Any, Tuple, Type
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

from parrot_tools.toolkit import AbstractToolkit
from parrot_tools.whatif import (
    DerivedMetric,
    WhatIfObjective,
    WhatIfConstraint,
    WhatIfAction,
    WhatIfDSL,
    MetricsCalculator,
    ScenarioOptimizer,
    ScenarioResult,
)


# ===== Internal State =====


@dataclass
class ScenarioState:
    """Internal state for a scenario being built incrementally."""

    id: str
    description: str
    df_name: str
    df: pd.DataFrame
    derived_metrics: List[DerivedMetric]
    actions: List[Any]
    objectives: List[Any]
    constraints: List[Any]
    result: Optional[ScenarioResult] = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_ready(self) -> bool:
        """Scenario has at least one action defined."""
        return len(self.actions) > 0

    @property
    def is_solved(self) -> bool:
        """Scenario has been simulated."""
        return self.result is not None


# ===== Pydantic Input Schemas =====


class DescribeScenarioInput(BaseModel):
    """Input for describe_scenario tool."""

    df_name: str = Field(description="Name or alias of the dataset to analyze")
    scenario_description: str = Field(
        description="Natural language description of the scenario"
    )
    derived_metrics: List[DerivedMetric] = Field(
        default_factory=list,
        description="Calculated metrics (e.g., ebitda = revenue - expenses)",
    )


class AddActionsInput(BaseModel):
    """Input for add_actions tool."""

    scenario_id: str = Field(description="Scenario ID from describe_scenario")
    actions: List[WhatIfAction] = Field(
        description="Actions to add to the scenario"
    )


class SetConstraintsInput(BaseModel):
    """Input for set_constraints tool."""

    scenario_id: str = Field(description="Scenario ID from describe_scenario")
    objectives: List[WhatIfObjective] = Field(
        default_factory=list,
        description="Optimization objectives (minimize, maximize, target)",
    )
    constraints: List[WhatIfConstraint] = Field(
        default_factory=list,
        description="Constraints to respect (max_change, min_value, max_value, ratio)",
    )


class SimulateInput(BaseModel):
    """Input for simulate tool."""

    scenario_id: str = Field(description="Scenario ID from describe_scenario")
    algorithm: str = Field(
        default="greedy", description="Algorithm: 'greedy' or 'genetic'"
    )
    max_actions: int = Field(default=5, description="Maximum actions to apply")


class QuickImpactInput(BaseModel):
    """Input for quick_impact tool -- the simple fast-path."""

    df_name: str = Field(description="Name or alias of the dataset")
    action_description: str = Field(
        description="Natural language: 'remove Belkin', 'increase visits by 30%', 'close North region'"
    )
    action_type: str = Field(
        description="Type: exclude_values, scale_entity, adjust_metric, scale_proportional, close_region"
    )
    target: str = Field(description="Column or entity to act on")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Action-specific parameters"
    )


class CompareScenariosInput(BaseModel):
    """Input for compare_scenarios tool."""

    scenario_ids: List[str] = Field(
        description="Two or more scenario IDs to compare side by side",
        min_length=2,
    )


# ===== System Prompt =====


WHATIF_TOOLKIT_SYSTEM_PROMPT = """
## What-If Scenario Analysis Toolkit

You have access to a what-if scenario analysis toolkit with these tools:

### Quick Analysis (use for simple questions):
- **quick_impact**: For simple "what if we remove/change X?" questions.
  One call, immediate result. No setup needed.

### Full Scenario Analysis (use for complex optimization):
1. **describe_scenario**: Start here. Provide dataset name and description.
   Returns scenario_id and dataset info for planning.
2. **add_actions**: Add possible actions to the scenario.
3. **set_constraints**: (Optional) Add objectives and constraints for optimization.
4. **simulate**: Run the simulation. Returns comparison table.
5. **compare_scenarios**: Compare two or more simulated scenarios.

### Decision Guide:
- "What if we remove X?" -> quick_impact
- "What if we increase X by Y%?" -> quick_impact
- "How can we optimize X without hurting Y?" -> full workflow (describe -> add_actions -> set_constraints -> simulate)
- "Compare scenario A vs B" -> compare_scenarios
""".strip()


# ===== Toolkit =====


class WhatIfToolkit(AbstractToolkit):
    """What-If scenario analysis toolkit for simulating hypothetical changes on datasets."""

    name = "whatif"
    description = "What-If scenario analysis toolkit"
    exclude_tools = ("start", "stop", "cleanup")

    def __init__(
        self,
        dataset_manager: Optional[Any] = None,
        pandas_tool: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._dm = dataset_manager
        self._pandas = pandas_tool
        self._scenarios: Dict[str, ScenarioState] = {}
        self._counter: int = 0
        self._parent_agent: Optional[Any] = None

    def _generate_id(self) -> str:
        """Generate a unique scenario ID."""
        self._counter += 1
        return f"sc_{self._counter}"

    # ------------------------------------------------------------------
    # Helper: resolve DataFrame from DM or parent agent
    # ------------------------------------------------------------------

    async def _resolve_dataframe(self, df_name: str) -> Tuple[str, pd.DataFrame]:
        """Resolve DataFrame by name or alias from DatasetManager or parent agent."""
        if self._dm:
            try:
                result = await self._dm.get_dataframe(df_name)
                if result and isinstance(result, dict) and "dataframe" in result:
                    return df_name, result["dataframe"]
                if isinstance(result, pd.DataFrame):
                    return df_name, result
            except Exception:
                pass  # fall through to parent agent
        # Fallback to parent agent
        if self._parent_agent and hasattr(self._parent_agent, "dataframes"):
            df = self._parent_agent.dataframes.get(df_name)
            if df is not None:
                return df_name, df
        raise ValueError(f"Dataset '{df_name}' not found")

    # ------------------------------------------------------------------
    # Helper: formatting
    # ------------------------------------------------------------------

    def _create_comparison_table(self, result: ScenarioResult) -> str:
        """Create comparison table in markdown format."""
        comparison = result.compare()
        lines = [
            "| Metric | Baseline | Scenario | Change | % Change |",
            "|--------|----------|----------|--------|----------|",
        ]
        for metric, data in comparison["metrics"].items():
            baseline = data["value"] - data["change"]
            scenario = data["value"]
            change = data["change"]
            pct = data["pct_change"]
            lines.append(
                f"| {metric} | {baseline:,.2f} | {scenario:,.2f} | "
                f"{change:+,.2f} | {pct:+.2f}% |"
            )
        return "\n".join(lines)

    def _describe_action(self, action) -> str:
        """Generate readable description of an action."""
        if action.operation == "exclude":
            return f"Remove {action.value} from {action.column}"
        elif action.operation == "scale":
            pct = (action.value - 1) * 100
            return f"Adjust {action.column} by {pct:+.1f}%"
        elif action.operation == "scale_group":
            group = action.value["group_val"]
            pct = (action.value["scale"] - 1) * 100
            return f"Adjust {action.column} in {group} by {pct:+.1f}%"
        elif action.operation in ("scale_proportional", "scale_proportional_group"):
            pct = (action.value["scale"] - 1) * 100
            affected = ", ".join(action.value["affected"])
            return f"Scale {action.column} by {pct:+.1f}% (affects: {affected})"
        elif action.operation == "scale_by_value":
            entity = action.value["filter_value"]
            pct = (action.value["scale"] - 1) * 100
            return f"Scale {entity} by {pct:+.1f}%"
        return str(action.name)

    def _generate_verdict(self, result: ScenarioResult) -> str:
        """Generate verdict about the scenario."""
        comparison = result.compare()
        verdicts = []
        for metric, data in comparison["metrics"].items():
            pct = data["pct_change"]
            if abs(pct) > 10:
                direction = "increased" if pct > 0 else "decreased"
                verdicts.append(f"{metric} {direction} by {abs(pct):.1f}%")
        if not verdicts:
            return "Minor changes, scenario is viable"
        return " | ".join(verdicts)

    # ------------------------------------------------------------------
    # Tool 1: describe_scenario
    # ------------------------------------------------------------------

    async def describe_scenario(
        self,
        df_name: str,
        scenario_description: str,
        derived_metrics: Optional[List[DerivedMetric]] = None,
    ) -> str:
        """Create and validate a what-if scenario on a dataset.
        Returns scenario ID, column inventory, derived metrics status, and suggested actions.
        Use this as the first step of a multi-step what-if analysis.
        """
        derived_metrics = derived_metrics or []
        name, df = await self._resolve_dataframe(df_name)

        # Validate derived metric formulas
        calculator = MetricsCalculator()
        for dm in derived_metrics:
            calculator.register_metric(dm.name, dm.formula, dm.description or "")
        # Validate each formula by attempting calculation
        for dm in derived_metrics:
            try:
                calculator.calculate(df, dm.name)
            except Exception as exc:
                raise ValueError(
                    f"Invalid formula for derived metric '{dm.name}': {exc}"
                ) from exc

        # Auto-detect column types
        numeric_cols = []
        categorical_cols = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                numeric_cols.append(
                    f"{col}(numeric, sum={df[col].sum():,.0f})"
                )
            else:
                categorical_cols.append(
                    f"{col}(categorical, {df[col].nunique()} unique)"
                )

        # Create scenario state
        scenario_id = self._generate_id()
        state = ScenarioState(
            id=scenario_id,
            description=scenario_description,
            df_name=name,
            df=df.copy(),
            derived_metrics=derived_metrics,
            actions=[],
            objectives=[],
            constraints=[],
        )
        self._scenarios[scenario_id] = state

        # Build suggested actions
        suggestions = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                suggestions.append(f"adjust_metric({col})")
            else:
                suggestions.append(f"exclude_values({col})")

        # Format response
        dm_status = []
        for dm in derived_metrics:
            dm_status.append(f"{dm.name} = {dm.formula} (validated OK)")

        lines = [
            f"Scenario {scenario_id} created for dataset '{name}'",
            f"Rows: {len(df)}",
            f"Columns: {', '.join(numeric_cols + categorical_cols)}",
        ]
        if dm_status:
            lines.append(f"Derived metrics registered: {'; '.join(dm_status)}")
        lines.append(f"Suggested actions: {', '.join(suggestions)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool 2: add_actions
    # ------------------------------------------------------------------

    async def add_actions(
        self,
        scenario_id: str,
        actions: List[WhatIfAction],
    ) -> str:
        """Add possible actions to an existing scenario.
        Validates each action against the DataFrame schema and reports invalid ones.
        """
        if scenario_id not in self._scenarios:
            raise ValueError(
                f"Scenario '{scenario_id}' not found. "
                f"Available: {list(self._scenarios.keys())}"
            )
        scenario = self._scenarios[scenario_id]
        df = scenario.df

        valid_count = 0
        invalid_msgs: List[str] = []

        for action in actions:
            ok, msg = self._validate_action(action, df)
            if ok:
                scenario.actions.append(action)
                valid_count += 1
            else:
                invalid_msgs.append(f"  - {action.type}({action.target}): {msg}")

        lines = [f"Actions update for {scenario_id}:"]
        lines.append(f"  {valid_count} action(s) added successfully")
        if invalid_msgs:
            lines.append(f"  {len(invalid_msgs)} action(s) invalid:")
            lines.extend(invalid_msgs)
        lines.append(f"  Total actions: {len(scenario.actions)}")
        lines.append(f"  Scenario ready: {scenario.is_ready}")
        return "\n".join(lines)

    def _validate_action(
        self, action: WhatIfAction, df: pd.DataFrame
    ) -> Tuple[bool, str]:
        """Validate a single action against the DataFrame schema."""
        action_type = action.type.lower()
        if action_type == "exclude_values":
            col = action.parameters.get("column", action.target)
            if col not in df.columns:
                return False, f"Column '{col}' not found. Available: {list(df.columns)}"
            values = action.parameters.get("values", [])
            if values:
                actual = set(df[col].unique())
                missing = set(str(v) for v in values) - set(str(v) for v in actual)
                if missing:
                    return False, f"Values {missing} not found in '{col}'"
        elif action_type == "adjust_metric":
            if action.target not in df.columns:
                return (
                    False,
                    f"Column '{action.target}' not found. Available: {list(df.columns)}",
                )
            if not pd.api.types.is_numeric_dtype(df[action.target]):
                return False, f"Column '{action.target}' is not numeric"
        elif action_type == "scale_entity":
            entity_col = action.parameters.get("entity_column", action.target)
            if entity_col not in df.columns:
                return (
                    False,
                    f"Column '{entity_col}' not found. Available: {list(df.columns)}",
                )
        elif action_type == "scale_proportional":
            if action.target not in df.columns:
                return (
                    False,
                    f"Column '{action.target}' not found. Available: {list(df.columns)}",
                )
        elif action_type == "close_region":
            # Accepts region-like columns
            pass
        return True, "OK"

    # ------------------------------------------------------------------
    # Tool 3: set_constraints
    # ------------------------------------------------------------------

    async def set_constraints(
        self,
        scenario_id: str,
        objectives: Optional[List[WhatIfObjective]] = None,
        constraints: Optional[List[WhatIfConstraint]] = None,
    ) -> str:
        """Define optimization objectives and constraints for a scenario.
        Validates metric names against columns and registered derived metrics.
        """
        if scenario_id not in self._scenarios:
            raise ValueError(
                f"Scenario '{scenario_id}' not found. "
                f"Available: {list(self._scenarios.keys())}"
            )
        scenario = self._scenarios[scenario_id]
        objectives = objectives or []
        constraints = constraints or []

        # Build set of valid metric names
        valid_metrics = set(scenario.df.columns)
        for dm in scenario.derived_metrics:
            valid_metrics.add(dm.name)

        invalid_msgs: List[str] = []

        # Validate and store objectives
        for obj in objectives:
            if obj.metric not in valid_metrics:
                invalid_msgs.append(
                    f"Objective metric '{obj.metric}' not found in columns or derived metrics"
                )
            else:
                scenario.objectives.append(obj)

        # Validate and store constraints
        for con in constraints:
            if con.metric not in valid_metrics:
                invalid_msgs.append(
                    f"Constraint metric '{con.metric}' not found in columns or derived metrics"
                )
            else:
                scenario.constraints.append(con)

        lines = [f"Optimization configured for {scenario_id}:"]
        lines.append(f"  Objectives: {len(scenario.objectives)}")
        lines.append(f"  Constraints: {len(scenario.constraints)}")
        if invalid_msgs:
            lines.append("  Warnings:")
            for msg in invalid_msgs:
                lines.append(f"    - {msg}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool 4: simulate
    # ------------------------------------------------------------------

    async def simulate(
        self,
        scenario_id: str,
        algorithm: str = "greedy",
        max_actions: int = 5,
    ) -> str:
        """Execute a configured scenario using the WhatIfDSL optimization engine.
        Registers the result DataFrame in DatasetManager for follow-up analysis.
        """
        if scenario_id not in self._scenarios:
            raise ValueError(
                f"Scenario '{scenario_id}' not found. "
                f"Available: {list(self._scenarios.keys())}"
            )
        scenario = self._scenarios[scenario_id]

        if not scenario.is_ready:
            raise ValueError(
                f"Scenario '{scenario_id}' has no actions defined. "
                "Use add_actions first."
            )

        # Build WhatIfDSL
        dsl = WhatIfDSL(scenario.df, name=scenario.description)

        # Register derived metrics
        for dm in scenario.derived_metrics:
            dsl.register_derived_metric(dm.name, dm.formula, dm.description or "")

        # Initialize optimizer
        dsl.initialize_optimizer()

        # Configure objectives
        for obj in scenario.objectives:
            obj_type = obj.type.lower()
            if obj_type == "minimize":
                dsl.minimize(obj.metric, weight=obj.weight)
            elif obj_type == "maximize":
                dsl.maximize(obj.metric, weight=obj.weight)
            elif obj_type == "target":
                dsl.target(obj.metric, obj.target_value, weight=obj.weight)

        # Configure constraints
        for con in scenario.constraints:
            con_type = con.type.lower()
            if con_type == "max_change":
                dsl.constrain_change(con.metric, con.value)
            elif con_type == "min_value":
                dsl.constrain_min(con.metric, con.value)
            elif con_type == "max_value":
                dsl.constrain_max(con.metric, con.value)
            elif con_type == "ratio":
                dsl.constrain_ratio(con.metric, con.reference_metric, con.value)

        # Configure actions
        self._configure_dsl_actions(dsl, scenario.actions)

        # Solve
        result = dsl.solve(max_actions=max_actions, algorithm=algorithm)
        scenario.result = result

        # Register result in DatasetManager
        result_name = f"whatif_{scenario.id}_result"
        if self._dm:
            try:
                await self._dm.add_dataframe(
                    name=result_name,
                    df=result.result_df,
                    description=f"WhatIf result: {scenario.description}",
                )
            except Exception:
                pass  # graceful degradation
            if self._pandas:
                try:
                    self._pandas.sync_from_manager()
                except Exception:
                    pass

        # Format output
        comparison_table = self._create_comparison_table(result)
        actions_desc = []
        for i, a in enumerate(result.actions, 1):
            actions_desc.append(f"  {i}. {self._describe_action(a)}")

        verdict = self._generate_verdict(result)

        lines = [
            f"Simulation complete for {scenario_id} ({algorithm} algorithm):",
            "",
            comparison_table,
            "",
            f"Actions applied ({len(result.actions)}):",
        ]
        lines.extend(actions_desc)
        lines.append("")
        lines.append(f"Verdict: {verdict}")
        lines.append(f"Result DataFrame registered as: '{result_name}'")
        return "\n".join(lines)

    def _configure_dsl_actions(
        self, dsl: WhatIfDSL, actions: List[Any]
    ) -> None:
        """Map WhatIfAction list to DSL method calls."""
        for action in actions:
            # Support both WhatIfAction objects and plain dicts
            if isinstance(action, dict):
                action_type = action.get("type", "").lower()
                params = action.get("parameters", {})
                target = action.get("target", "")
            else:
                action_type = action.type.lower()
                params = action.parameters if hasattr(action, "parameters") else {}
                target = action.target if hasattr(action, "target") else ""

            if action_type == "close_region":
                regions = params.get("regions")
                dsl.can_close_regions(regions)
            elif action_type == "exclude_values":
                column = params.get("column", target)
                values = params.get("values")
                dsl.can_exclude_values(column, values)
            elif action_type == "adjust_metric":
                dsl.can_adjust_metric(
                    metric=target,
                    min_pct=params.get("min_pct", -50),
                    max_pct=params.get("max_pct", 50),
                    group_by=params.get("group_by"),
                )
            elif action_type == "scale_proportional":
                dsl.can_scale_proportional(
                    base_column=target,
                    affected_columns=params.get("affected_columns", []),
                    min_pct=params.get("min_pct", -50),
                    max_pct=params.get("max_pct", 100),
                    group_by=params.get("group_by"),
                )
            elif action_type == "scale_entity":
                dsl.can_scale_entity(
                    entity_column=params.get("entity_column", target),
                    target_columns=params.get("target_columns", []),
                    entities=params.get("entities"),
                    min_pct=params.get("min_pct", -100),
                    max_pct=params.get("max_pct", 0),
                )

    # ------------------------------------------------------------------
    # Tool 5: quick_impact
    # ------------------------------------------------------------------

    async def quick_impact(
        self,
        df_name: str,
        action_description: str,
        action_type: str,
        target: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Fast-path for simple what-if queries. Resolves dataset, applies a single action,
        and returns before/after comparison -- all in one call.
        Use for questions like 'what if we remove X?' or 'what if we increase Y by Z%?'.
        """
        parameters = parameters or {}
        try:
            _, df = await self._resolve_dataframe(df_name)
        except ValueError as e:
            return f"Error: {e}"

        dsl = WhatIfDSL(df, name=action_description)

        # Register derived metrics if provided
        for dm_dict in parameters.get("derived_metrics", []):
            if isinstance(dm_dict, dict):
                dsl.register_derived_metric(dm_dict["name"], dm_dict["formula"])
            elif isinstance(dm_dict, DerivedMetric):
                dsl.register_derived_metric(dm_dict.name, dm_dict.formula)

        dsl.initialize_optimizer()

        action_type_lower = action_type.lower()
        try:
            if action_type_lower == "exclude_values":
                column = parameters.get("column", target)
                values = parameters.get("values", [target])
                if column not in df.columns:
                    return (
                        f"Error: Column '{column}' not found. "
                        f"Available: {list(df.columns)}"
                    )
                dsl.can_exclude_values(column, values)
            elif action_type_lower == "scale_entity":
                dsl.can_scale_entity(
                    entity_column=parameters.get("entity_column", target),
                    target_columns=parameters.get("target_columns", []),
                    entities=parameters.get("entities", []),
                    min_pct=parameters.get("min_pct", -50),
                    max_pct=parameters.get("max_pct", -50),
                )
            elif action_type_lower == "adjust_metric":
                if target not in df.columns:
                    return (
                        f"Error: Column '{target}' not found. "
                        f"Available: {list(df.columns)}"
                    )
                dsl.can_adjust_metric(
                    metric=target,
                    min_pct=parameters.get("min_pct", -50),
                    max_pct=parameters.get("max_pct", 50),
                )
            elif action_type_lower == "scale_proportional":
                dsl.can_scale_proportional(
                    base_column=target,
                    affected_columns=parameters.get("affected_columns", []),
                    min_pct=parameters.get("min_pct", -50),
                    max_pct=parameters.get("max_pct", 100),
                )
            elif action_type_lower == "close_region":
                regions = parameters.get("regions", [target])
                # close_region uses can_exclude_values on the target column
                # because can_close_regions hardcodes 'region' column name
                region_col = parameters.get("column", target)
                dsl.can_exclude_values(region_col, regions)
            else:
                return f"Error: Unknown action type '{action_type}'"
        except Exception as exc:
            return f"Error configuring action: {exc}"

        # Solve with single action
        try:
            result = dsl.solve(max_actions=1, algorithm="greedy")
        except Exception as exc:
            return f"Error during simulation: {exc}"

        # Register result
        if self._dm:
            try:
                await self._dm.add_dataframe(
                    name=f"whatif_quick_{action_type_lower}_result",
                    df=result.result_df,
                    description=f"Quick impact: {action_description}",
                )
            except Exception:
                pass

        # Format
        comparison_table = self._create_comparison_table(result)
        verdict = self._generate_verdict(result)
        actions_desc = [
            f"  {i}. {self._describe_action(a)}"
            for i, a in enumerate(result.actions, 1)
        ]

        lines = [
            f"Quick Impact Analysis: {action_description}",
            "",
            comparison_table,
            "",
        ]
        if actions_desc:
            lines.append("Actions applied:")
            lines.extend(actions_desc)
            lines.append("")
        lines.append(f"Verdict: {verdict}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool 6: compare_scenarios
    # ------------------------------------------------------------------

    async def compare_scenarios(
        self,
        scenario_ids: List[str],
    ) -> str:
        """Compare two or more simulated scenarios side by side.
        All scenarios must have been simulated (is_solved=True).
        Returns a comparison matrix with best/worst highlighting per metric.
        """
        if len(scenario_ids) < 2:
            raise ValueError("At least 2 scenario IDs are required for comparison")

        scenarios: List[ScenarioState] = []
        for sid in scenario_ids:
            if sid not in self._scenarios:
                raise ValueError(f"Scenario '{sid}' not found")
            if not self._scenarios[sid].is_solved:
                raise ValueError(
                    f"Scenario '{sid}' has not been simulated yet. "
                    "Run simulate first."
                )
            scenarios.append(self._scenarios[sid])

        # Collect metrics from each scenario
        all_metrics: Dict[str, Dict[str, float]] = {}
        for scenario in scenarios:
            comparison = scenario.result.compare()
            for metric, data in comparison["metrics"].items():
                if metric not in all_metrics:
                    all_metrics[metric] = {}
                all_metrics[metric][scenario.id] = data["value"]

        # Build comparison table
        header_ids = [s.id for s in scenarios]
        header = "| Metric | " + " | ".join(header_ids) + " | Best |"
        separator = "|--------|" + "|".join(["--------"] * len(header_ids)) + "|------|"

        rows = []
        for metric, values in all_metrics.items():
            best_id = max(values, key=values.get)
            row_vals = []
            for sid in header_ids:
                val = values.get(sid, 0)
                marker = " ^" if sid == best_id else ""
                row_vals.append(f"{val:,.2f}{marker}")
            rows.append(f"| {metric} | " + " | ".join(row_vals) + f" | {best_id} |")

        lines = [
            "Scenario Comparison:",
            "",
            header,
            separator,
        ]
        lines.extend(rows)
        lines.append("")

        # Summary
        for scenario in scenarios:
            lines.append(
                f"  {scenario.id}: {scenario.description} "
                f"({len(scenario.result.actions)} actions)"
            )

        return "\n".join(lines)


# ===== Integration Helper =====


def integrate_whatif_toolkit(
    agent,
    dataset_manager: Optional[Any] = None,
    pandas_tool: Optional[Any] = None,
) -> WhatIfToolkit:
    """Integrate WhatIfToolkit into an agent.

    Resolves DatasetManager and PythonPandasTool from agent if not provided.
    Registers all 6 tools and adds system prompt.

    Args:
        agent: The agent to integrate with.
        dataset_manager: Optional DatasetManager instance.
        pandas_tool: Optional PythonPandasTool instance.

    Returns:
        The configured WhatIfToolkit instance.
    """
    if dataset_manager is None:
        dataset_manager = getattr(agent, "dataset_manager", None)
    if pandas_tool is None:
        pandas_tool = getattr(agent, "pandas_tool", None)

    toolkit = WhatIfToolkit(
        dataset_manager=dataset_manager,
        pandas_tool=pandas_tool,
    )
    toolkit._parent_agent = agent

    # Register all tools from toolkit
    for tool in toolkit.get_tools():
        if hasattr(agent, "tool_manager"):
            agent.tool_manager.register(tool)

    # Add system prompt
    if hasattr(agent, "add_system_prompt"):
        agent.add_system_prompt(WHATIF_TOOLKIT_SYSTEM_PROMPT)

    return toolkit
