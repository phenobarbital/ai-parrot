"""
What-If Scenario Analysis Tool for AI-Parrot
Supports derived metrics, constraints, and optimization
"""
from typing import Dict, List, Optional, Tuple, Type
from dataclasses import dataclass
from enum import Enum
from pydantic import BaseModel, Field
import pandas as pd
import numpy as np
import traceback
from .abstract import AbstractTool, ToolResult


# ===== Enums =====

class ObjectiveType(Enum):
    """Type of optimization objective"""
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    TARGET = "target"


class ConstraintType(Enum):
    """Type of constraint"""
    MAX_CHANGE = "max_change"  # Don't change more than X%
    MIN_VALUE = "min_value"    # Keep above X
    MAX_VALUE = "max_value"    # Keep below X
    RATIO = "ratio"            # Keep ratio between metrics


# ===== Core Data Classes =====

@dataclass
class Objective:
    """Defines an optimization objective"""
    metric: str
    type: ObjectiveType
    target_value: Optional[float] = None
    weight: float = 1.0


@dataclass
class Constraint:
    """Defines a constraint"""
    metric: str
    type: ConstraintType
    value: float
    reference_metric: Optional[str] = None  # For ratio constraints


@dataclass
class Action:
    """Defines a possible action"""
    name: str
    column: str
    operation: str  # 'exclude', 'scale', 'set', 'scale_proportional'
    value: any
    cost: float = 0.0
    affects_derived: bool = False


@dataclass
class ScenarioResult:
    """Result of an optimized scenario"""
    scenario_name: str
    base_df: pd.DataFrame
    result_df: pd.DataFrame
    actions: List[Action]
    optimizer: 'ScenarioOptimizer'
    calculator: 'MetricsCalculator'

    def compare(self) -> Dict:
        """Compare scenario with baseline"""
        metrics = self.optimizer.evaluate_scenario(self.result_df)

        comparison = {
            'scenario_name': self.scenario_name,
            'actions_taken': [
                {
                    'action': action.name,
                    'description': f"{action.operation} {action.column} = {action.value}"
                }
                for action in self.actions
            ],
            'metrics': metrics,
            'summary': {
                'total_actions': len(self.actions),
                'total_cost': sum(a.cost for a in self.actions)
            }
        }

        return comparison

    def visualize(self) -> str:
        """Generate visual summary of the scenario"""
        comparison = self.compare()

        output = [f"\n{'='*70}"]
        output.append(f"Scenario: {self.scenario_name}")
        output.append(f"{'='*70}\n")

        output.append("Actions Taken:")
        if self.actions:
            for i, action_info in enumerate(comparison['actions_taken'], 1):
                output.append(f"  {i}. {action_info['description']}")
        else:
            output.append("  No actions needed - current state meets objectives")

        output.append("\nMetric Changes:")
        output.append(f"{'Metric':<20} {'Baseline':>15} {'Scenario':>15} {'Change':>15} {'% Change':>12}")
        output.append("-" * 80)

        for metric, data in comparison['metrics'].items():
            base_value = data['value'] - data['change']
            output.append(
                f"{metric:<20} {base_value:>15.2f} "
                f"{data['value']:>15.2f} {data['change']:>15.2f} "
                f"{data['pct_change']:>11.2f}%"
            )

        # Add derived metrics info if any
        derived_metrics = [
            m for m in comparison['metrics'].keys() if m in self.calculator.formulas
        ]
        if derived_metrics:
            output.append(f"\nDerived Metrics: {', '.join(derived_metrics)}")

        return "\n".join(output)


# ===== Pydantic Schemas for Tool Input =====

class DerivedMetric(BaseModel):
    """Calculated/derived metric"""
    name: str = Field(description="Name of derived metric (e.g., 'revenue_per_visit')")
    formula: str = Field(description="Formula as string (e.g., 'revenue / visits')")
    description: Optional[str] = Field(None, description="Description of what it represents")


class WhatIfObjective(BaseModel):
    """Objective for scenario optimization"""
    type: str = Field(description="Type: minimize, maximize, or target")
    metric: str = Field(description="Column/metric name (can be derived)")
    target_value: Optional[float] = None
    weight: float = 1.0


class WhatIfConstraint(BaseModel):
    """Constraint for scenario"""
    type: str = Field(description="Type: max_change, min_value, max_value, or ratio")
    metric: str
    value: float
    reference_metric: Optional[str] = None


class WhatIfAction(BaseModel):
    """Possible action to take"""
    type: str = Field(description="Type: close_region, exclude_values, adjust_metric, set_value, scale_proportional")
    target: str
    parameters: Dict = Field(default_factory=dict)


class WhatIfInput(BaseModel):
    """Input schema for WhatIfTool"""
    scenario_description: str
    df_name: Optional[str] = None
    objectives: List[WhatIfObjective] = Field(default_factory=list)
    constraints: List[WhatIfConstraint] = Field(default_factory=list)
    possible_actions: List[WhatIfAction]
    derived_metrics: List[DerivedMetric] = Field(
        default_factory=list,
        description="Calculated metrics from existing columns"
    )
    max_actions: int = 5
    algorithm: str = "greedy"  # greedy or genetic


# ===== Metrics Calculator =====

class MetricsCalculator:
    """Calculates derived metrics on DataFrames"""

    def __init__(self):
        self.formulas: Dict[str, str] = {}
        self.descriptions: Dict[str, str] = {}

    def register_metric(self, name: str, formula: str, description: str = ""):
        """Register a derived metric"""
        self.formulas[name] = formula
        self.descriptions[name] = description

    def calculate(self, df: pd.DataFrame, metric_name: str) -> pd.Series:
        """Calculate a derived metric"""
        if metric_name not in self.formulas:
            # If not derived, return column directly
            if metric_name in df.columns:
                return df[metric_name]
            raise ValueError(f"Metric '{metric_name}' not found in DataFrame or formulas")

        formula = self.formulas[metric_name]

        # Evaluate formula safely
        # Create safe context with DataFrame columns
        context = {col: df[col] for col in df.columns}
        context['np'] = np  # Allow numpy functions

        try:
            result = eval(formula, {"__builtins__": {}}, context)
            return pd.Series(result, index=df.index)
        except Exception as e:
            raise ValueError(f"Error calculating '{metric_name}': {str(e)}")

    def add_to_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all derived metrics to DataFrame"""
        df_copy = df.copy()
        for metric_name in self.formulas:
            df_copy[metric_name] = self.calculate(df, metric_name)
        return df_copy

    def get_base_value(self, df: pd.DataFrame, metric_name: str) -> float:
        """Get total value of a metric (derived or not)"""
        if metric_name in df.columns:
            return df[metric_name].sum()

        series = self.calculate(df, metric_name)
        return series.sum()


# ===== Scenario Optimizer =====

class ScenarioOptimizer:
    """Optimizer with support for derived metrics"""

    def __init__(self, base_df: pd.DataFrame, calculator: MetricsCalculator):
        self.base_df = base_df.copy()
        self.calculator = calculator

        # Calculate base metrics (including derived)
        self.base_with_derived = calculator.add_to_dataframe(base_df)
        self.base_metrics = {}

        for col in self.base_with_derived.columns:
            if pd.api.types.is_numeric_dtype(self.base_with_derived[col]):
                self.base_metrics[col] = {
                    'sum': self.base_with_derived[col].sum(),
                    'mean': self.base_with_derived[col].mean(),
                }

    def evaluate_scenario(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Evaluate metrics of a scenario (including derived)"""
        # Add derived metrics
        df_with_derived = self.calculator.add_to_dataframe(df)

        scenario_metrics = {}
        for col in df_with_derived.columns:
            if pd.api.types.is_numeric_dtype(df_with_derived[col]):
                base_sum = self.base_metrics.get(col, {}).get('sum', 0)
                scenario_sum = df_with_derived[col].sum()

                scenario_metrics[col] = {
                    'value': scenario_sum,
                    'change': scenario_sum - base_sum,
                    'pct_change': (
                        (scenario_sum - base_sum) / base_sum * 100
                    ) if base_sum != 0 else 0
                }

        return scenario_metrics

    def check_constraints(
        self,
        df: pd.DataFrame,
        constraints: List[Constraint]
    ) -> Tuple[bool, List[str]]:
        """Check if scenario meets constraints"""
        violations = []
        scenario_metrics = self.evaluate_scenario(df)

        for constraint in constraints:
            metric_data = scenario_metrics.get(constraint.metric)
            if not metric_data:
                continue

            if constraint.type == ConstraintType.MAX_CHANGE:
                if abs(metric_data['pct_change']) > constraint.value:
                    violations.append(
                        f"{constraint.metric} changed by {metric_data['pct_change']:.2f}%, "
                        f"exceeds limit of {constraint.value}%"
                    )

            elif constraint.type == ConstraintType.MIN_VALUE:
                if metric_data['value'] < constraint.value:
                    violations.append(
                        f"{constraint.metric} = {metric_data['value']:.2f}, "
                        f"below minimum of {constraint.value}"
                    )

            elif constraint.type == ConstraintType.MAX_VALUE:
                if metric_data['value'] > constraint.value:
                    violations.append(
                        f"{constraint.metric} = {metric_data['value']:.2f}, "
                        f"exceeds maximum of {constraint.value}"
                    )

            elif constraint.type == ConstraintType.RATIO:
                if constraint.reference_metric:
                    ref_data = scenario_metrics.get(constraint.reference_metric)
                    if ref_data and ref_data['value'] != 0:
                        ratio = metric_data['value'] / ref_data['value']
                        if ratio > constraint.value:
                            violations.append(
                                f"Ratio {constraint.metric}/{constraint.reference_metric} = {ratio:.2f}, "
                                f"exceeds {constraint.value}"
                            )

        return len(violations) == 0, violations

    def objective_function(
        self,
        df: pd.DataFrame,
        objectives: List[Objective]
    ) -> float:
        """Calculate objective function value"""
        scenario_metrics = self.evaluate_scenario(df)
        total_score = 0.0

        for obj in objectives:
            metric_data = scenario_metrics.get(obj.metric)
            if not metric_data:
                continue

            value = metric_data['value']

            if obj.type == ObjectiveType.MINIMIZE:
                score = -value  # Negative because we minimize
            elif obj.type == ObjectiveType.MAXIMIZE:
                score = value
            elif obj.type == ObjectiveType.TARGET:
                score = -abs(value - obj.target_value)  # Penalize deviation

            total_score += score * obj.weight

        return total_score


# ===== What-If DSL =====

class WhatIfDSL:
    """Domain Specific Language for What-If analysis with optimization"""

    def __init__(self, df: pd.DataFrame, name: str = "scenario"):
        self.df = df.copy()
        self.base_df = df.copy()
        self.name = name

        # Calculator for derived metrics
        self.calculator = MetricsCalculator()
        self.optimizer = None  # Initialize after registering metrics

        self.objectives: List[Objective] = []
        self.constraints: List[Constraint] = []
        self.possible_actions: List[Action] = []
        self.applied_actions: List[Action] = []

    def register_derived_metric(self, name: str, formula: str, description: str = ""):
        """Register a derived metric"""
        self.calculator.register_metric(name, formula, description)
        return self

    def initialize_optimizer(self):
        """Initialize optimizer after registering metrics"""
        if self.optimizer is None:
            self.optimizer = ScenarioOptimizer(self.base_df, self.calculator)
        return self

    # ===== Objective Definition =====

    def minimize(self, metric: str, weight: float = 1.0) -> 'WhatIfDSL':
        """Minimize a metric"""
        self.objectives.append(
            Objective(metric=metric, type=ObjectiveType.MINIMIZE, weight=weight)
        )
        return self

    def maximize(self, metric: str, weight: float = 1.0) -> 'WhatIfDSL':
        """Maximize a metric"""
        self.objectives.append(
            Objective(metric=metric, type=ObjectiveType.MAXIMIZE, weight=weight)
        )
        return self

    def target(self, metric: str, value: float, weight: float = 1.0) -> 'WhatIfDSL':
        """Reach a target value"""
        self.objectives.append(
            Objective(
                metric=metric,
                type=ObjectiveType.TARGET,
                target_value=value,
                weight=weight
            )
        )
        return self

    # ===== Constraint Definition =====

    def constrain_change(self, metric: str, max_pct: float) -> 'WhatIfDSL':
        """Constraint: metric cannot change more than X%"""
        self.constraints.append(
            Constraint(metric=metric, type=ConstraintType.MAX_CHANGE, value=max_pct)
        )
        return self

    def constrain_min(self, metric: str, min_value: float) -> 'WhatIfDSL':
        """Constraint: metric must stay above X"""
        self.constraints.append(
            Constraint(metric=metric, type=ConstraintType.MIN_VALUE, value=min_value)
        )
        return self

    def constrain_max(self, metric: str, max_value: float) -> 'WhatIfDSL':
        """Constraint: metric must stay below X"""
        self.constraints.append(
            Constraint(metric=metric, type=ConstraintType.MAX_VALUE, value=max_value)
        )
        return self

    def constrain_ratio(self, metric: str, reference: str, max_ratio: float) -> 'WhatIfDSL':
        """Constraint: ratio between two metrics"""
        self.constraints.append(
            Constraint(
                metric=metric,
                type=ConstraintType.RATIO,
                value=max_ratio,
                reference_metric=reference
            )
        )
        return self

    # ===== Possible Actions Definition =====

    def can_close_regions(self, regions: Optional[List[str]] = None) -> 'WhatIfDSL':
        """Define that regions can be closed"""
        if regions is None:
            if 'region' in self.df.columns:
                regions = self.df['region'].unique().tolist()
            else:
                return self

        for region in regions:
            self.possible_actions.append(
                Action(
                    name=f"close_{region}",
                    column="region",
                    operation="exclude",
                    value=region,
                    cost=1.0  # Cost of closing a region
                )
            )
        return self

    def can_exclude_values(
        self,
        column: str,
        values: Optional[List[str]] = None
    ) -> 'WhatIfDSL':
        """Define that specific values can be excluded from a column (generic version of can_close_regions)"""
        if values is None:
            if column in self.df.columns:
                values = self.df[column].unique().tolist()
            else:
                return self

        for value in values:
            self.possible_actions.append(
                Action(
                    name=f"exclude_{column}_{value}",
                    column=column,
                    operation="exclude",
                    value=value,
                    cost=1.0  # Cost of excluding a value
                )
            )
        return self

    def can_adjust_metric(
        self,
        metric: str,
        min_pct: float = -50,
        max_pct: float = 50,
        by_region: bool = False
    ) -> 'WhatIfDSL':
        """Define that a metric can be adjusted"""
        if by_region and 'region' in self.df.columns:
            regions = self.df['region'].unique()
            for region in regions:
                for pct in np.linspace(min_pct, max_pct, 10):
                    if pct != 0:
                        self.possible_actions.append(
                            Action(
                                name=f"adjust_{metric}_{region}_{pct:.0f}pct",
                                column=metric,
                                operation="scale_region",
                                value={'region': region, 'scale': 1 + pct / 100},
                                cost=abs(pct) / 100  # Cost proportional to change
                            )
                        )
        else:
            for pct in np.linspace(min_pct, max_pct, 10):
                if pct != 0:
                    self.possible_actions.append(
                        Action(
                            name=f"adjust_{metric}_{pct:.0f}pct",
                            column=metric,
                            operation="scale",
                            value=1 + pct / 100,
                            cost=abs(pct) / 100
                        )
                    )
        return self

    def can_scale_proportional(
        self,
        base_column: str,
        affected_columns: List[str],
        min_pct: float = -50,
        max_pct: float = 100,
        by_region: bool = False
    ) -> 'WhatIfDSL':
        """
        Allow scaling a base metric and adjust others proportionally.

        Example: Increase 'visits' and have 'revenue' and 'expenses' scale
        according to revenue_per_visit and expenses_per_visit.

        Args:
            base_column: Base column to scale (e.g., 'visits')
            affected_columns: Columns that adjust proportionally (e.g., ['revenue', 'expenses'])
            min_pct: Minimum % change
            max_pct: Maximum % change
            by_region: Whether to apply by region
        """
        if by_region and 'region' in self.df.columns:
            regions = self.df['region'].unique()
            for region in regions:
                for pct in np.linspace(min_pct, max_pct, 10):
                    if pct != 0:
                        self.possible_actions.append(
                            Action(
                                name=f"scale_{base_column}_{region}_{pct:.0f}pct",
                                column=base_column,
                                operation="scale_proportional_region",
                                value={
                                    'region': region,
                                    'scale': 1 + pct / 100,
                                    'affected': affected_columns
                                },
                                cost=abs(pct) / 50,
                                affects_derived=True
                            )
                        )
        else:
            for pct in np.linspace(min_pct, max_pct, 10):
                if pct != 0:
                    self.possible_actions.append(
                        Action(
                            name=f"scale_{base_column}_{pct:.0f}pct",
                            column=base_column,
                            operation="scale_proportional",
                            value={
                                'scale': 1 + pct / 100,
                                'affected': affected_columns
                            },
                            cost=abs(pct) / 50,
                            affects_derived=True
                        )
                    )
        return self

    # ===== Apply Actions =====

    def _apply_action(self, action: Action, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Apply an action to the dataframe"""
        df = self.df.copy() if df is None else df.copy()

        if action.operation == "exclude":
            df = df[df[action.column] != action.value]

        elif action.operation == "scale":
            df[action.column] = df[action.column].astype(float)
            df[action.column] = df[action.column] * action.value

        elif action.operation == "scale_region":
            region = action.value['region']
            scale = action.value['scale']
            mask = df['region'] == region
            # Convert column to float first to avoid dtype warnings
            df[action.column] = df[action.column].astype(float)
            df.loc[mask, action.column] = df.loc[mask, action.column] * scale

        elif action.operation == "scale_proportional":
            # Scale base column
            scale = action.value['scale']
            df[action.column] = df[action.column].astype(float)
            df[action.column] = df[action.column] * scale

            # Calculate derived metrics before the change
            df_with_derived = self.calculator.add_to_dataframe(self.base_df)

            # Adjust affected columns proportionally
            for affected_col in action.value['affected']:
                # Look for related derived metric (e.g., revenue_per_visit)
                derived_metric = f"{affected_col}_per_{action.column}"

                if derived_metric in self.calculator.formulas:
                    # Calculate value per base unit
                    per_unit = df_with_derived[derived_metric].values
                    # Apply to new base column values
                    df[affected_col] = df[action.column].values * per_unit

        elif action.operation == "scale_proportional_region":
            region = action.value['region']
            scale = action.value['scale']
            mask = df['region'] == region

            # Scale base column in region
            # Convert column to float first to avoid dtype warnings
            df[action.column] = df[action.column].astype(float)
            df.loc[mask, action.column] = df.loc[mask, action.column] * scale

            # Calculate derived metrics
            df_with_derived = self.calculator.add_to_dataframe(self.base_df)

            # Adjust affected columns in region
            for affected_col in action.value['affected']:
                derived_metric = f"{affected_col}_per_{action.column}"

                if derived_metric in self.calculator.formulas:
                    per_unit = df_with_derived.loc[mask, derived_metric].values
                    df.loc[mask, affected_col] = df.loc[mask, action.column].values * per_unit

        elif action.operation == "set_value":
            df[action.column] = action.value

        return df

    # ===== Optimization =====

    def solve(
        self,
        max_actions: int = 5,
        algorithm: str = "greedy"
    ) -> ScenarioResult:
        """
        Find best combination of actions that meets constraints.

        Args:
            max_actions: Maximum number of actions to take
            algorithm: 'greedy' or 'genetic'
        """

        if algorithm == "greedy":
            return self._solve_greedy(max_actions)
        elif algorithm == "genetic":
            return self._solve_genetic(max_actions)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

    def _solve_greedy(self, max_actions: int) -> ScenarioResult:
        """Greedy algorithm: evaluate actions one by one"""
        # SPECIAL CASE: If no objectives, just apply actions directly
        if len(self.objectives) == 0 and len(self.constraints) == 0:
            selected_actions = []
            current_df = self.df.copy()

            for action in self.possible_actions[:max_actions]:
                test_df = self._apply_action(action, current_df)
                if not test_df.empty:
                    selected_actions.append(action)
                    current_df = test_df
                    if len(selected_actions) >= max_actions:
                        break

            self.applied_actions = selected_actions
            return ScenarioResult(
                scenario_name=self.name,
                base_df=self.base_df,
                result_df=current_df,
                actions=selected_actions,
                optimizer=self.optimizer,
                calculator=self.calculator
            )
        best_df = self.df.copy()
        best_score = self.optimizer.objective_function(best_df, self.objectives)
        selected_actions = []

        for _ in range(max_actions):
            best_action = None
            best_action_score = best_score
            best_action_df = None

            # Try each possible action
            for action in self.possible_actions:
                if action in selected_actions:
                    continue

                # Apply action
                test_df = self._apply_action(action, best_df)

                # Check constraints
                valid, violations = self.optimizer.check_constraints(
                    test_df, self.constraints
                )

                if not valid:
                    continue

                # Calculate score
                score = self.optimizer.objective_function(test_df, self.objectives)
                score -= action.cost * 10  # Penalize by action cost

                if score > best_action_score:
                    best_action = action
                    best_action_score = score
                    best_action_df = test_df

            # If we found an improvement, apply it
            if best_action:
                selected_actions.append(best_action)
                best_df = best_action_df
                best_score = best_action_score
            else:
                break  # No more improvements possible

        self.applied_actions = selected_actions
        return ScenarioResult(
            scenario_name=self.name,
            base_df=self.base_df,
            result_df=best_df,
            actions=selected_actions,
            optimizer=self.optimizer,
            calculator=self.calculator
        )

    def _solve_genetic(self, max_actions: int) -> ScenarioResult:
        """Genetic algorithm to explore solution space"""
        from itertools import combinations

        best_score = float('-inf')
        best_actions = []
        best_df = self.df.copy()

        # Explore combinations of actions
        for r in range(1, min(max_actions + 1, len(self.possible_actions) + 1)):
            for action_combo in combinations(self.possible_actions, r):
                # Apply combination of actions
                test_df = self.base_df.copy()
                for action in action_combo:
                    test_df = self._apply_action(action, test_df)

                # Check constraints
                valid, violations = self.optimizer.check_constraints(
                    test_df, self.constraints
                )

                if not valid:
                    continue

                # Calculate score
                score = self.optimizer.objective_function(test_df, self.objectives)
                score -= sum(a.cost for a in action_combo) * 10

                if score > best_score:
                    best_score = score
                    best_actions = list(action_combo)
                    best_df = test_df

        self.applied_actions = best_actions
        return ScenarioResult(
            scenario_name=self.name,
            base_df=self.base_df,
            result_df=best_df,
            actions=best_actions,
            optimizer=self.optimizer,
            calculator=self.calculator
        )


# ===== What-If Tool Implementation =====

class WhatIfTool(AbstractTool):
    """
    What-If Analysis Tool with support for derived metrics and optimization.

    Allows LLM to execute hypothetical scenarios on DataFrames,
    optimize metrics under constraints, and compare results.
    """
    args_schema: Type[BaseModel] = WhatIfInput

    def __init__(self):
        super().__init__(
            name="whatif_scenario",
            description=self._get_description()
        )
        self.scenarios_cache: Dict[str, ScenarioResult] = {}
        self._parent_agent = None  # Reference to PandasAgent

    def _get_description(self) -> str:
        return """
Execute what-if scenario analysis on DataFrames with optimization and derived metrics support.

This tool allows you to:
- Test hypothetical scenarios (e.g., "what if we close region X?")
- Optimize metrics under constraints (e.g., "reduce expenses without revenue dropping >5%")
- Handle derived metrics (e.g., revenue_per_visit, expenses_per_visit)
- Simulate proportional changes (e.g., "what if we increase visits by 20%?")

DERIVED METRICS:
You can define calculated metrics using formulas:
- revenue_per_visit = revenue / visits
- expenses_per_visit = expenses / visits
- profit_margin = (revenue - expenses) / revenue
- cost_per_employee = expenses / headcount

These metrics are automatically recalculated when base columns change.

PROPORTIONAL SCALING:
When you scale a base metric (like 'visits'), you can specify affected columns
that should scale proportionally based on derived metrics.

Example: "What if we increase visits by 20%?"
- visits increases by 20%
- revenue = visits * revenue_per_visit (automatically adjusted)
- expenses = visits * expenses_per_visit (automatically adjusted)

TRIGGER PATTERNS:
- "What if we close region X?" or "What if we close project Y?"
- "What if we exclude department Z?"
- "What if we reduce expenses to Y?"
- "What if we increase visits by Z%?"
- "How can I reduce costs without affecting revenue?"
- "Find the best way to maximize profit"

COMMON SCENARIOS:

1. Simple Impact Analysis:
   "What if we close the North region?" or "What if we close the Belkin project?"
   → Removes entity from the specified column, shows impact on all metrics

2. Constraint Optimization:
   "Reduce expenses to 500k without revenue dropping more than 5%"
   → Finds optimal actions to hit target while respecting constraints

3. Proportional Changes:
   "What if we increase visits by 30%?"
   → Scales visits and adjusts revenue/expenses proportionally

4. Multi-Objective:
   "Maximize profit while keeping headcount above 100"
   → Optimizes multiple goals with constraints

IMPORTANT:
- Always define derived_metrics when dealing with per-unit calculations
- Use scale_proportional actions for scenarios involving rate-based changes
- Constraints are hard limits - scenarios violating them are rejected
- Objectives can have weights (higher = more important)
        """.strip()

    def set_parent_agent(self, agent):
        """Set reference to parent PandasAgent"""
        self._parent_agent = agent

    def get_input_schema(self) -> type[BaseModel]:
        return WhatIfInput

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute what-if analysis - FIXED VERSION"""

        self.logger.debug(
            f"WhatIfTool kwargs keys: {list(kwargs.keys())}"
        )

        # Validate input
        try:
            input_data = WhatIfInput(**kwargs)
            self.logger.info(f"  Input validated: {input_data.scenario_description}")
        except Exception as e:
            self.logger.error(f"  Input validation failed: {str(e)}")
            return ToolResult(
                success=False,
                result={},
                error=f"Invalid input: {str(e)}"
            )

        # Check parent agent
        if not self._parent_agent:
            self.logger.error("  Parent agent not set!")
            return ToolResult(
                success=False,
                result={},
                error="Tool not initialized with parent agent"
            )

        # CRITICAL FIX: Access dataframes correctly
        if not hasattr(self._parent_agent, 'dataframes'):
            return ToolResult(
                success=False,
                result={},
                error="Parent agent missing 'dataframes' attribute"
            )

        self.logger.info(
            f"::  Available DataFrames: {list(self._parent_agent.dataframes.keys())}"
        )

        df = None
        if input_data.df_name:
            df = self._parent_agent.dataframes.get(input_data.df_name)
            if df is None:
                self.logger.error(f"  DataFrame '{input_data.df_name}' not found")
                return ToolResult(
                    success=False,
                    result={},
                    error=f"DataFrame '{input_data.df_name}' not found. Available: {list(self._parent_agent.dataframes.keys())}"
                )
        else:
            # Get first DataFrame
            if self._parent_agent.dataframes:
                df_name = list(self._parent_agent.dataframes.keys())[0]
                df = self._parent_agent.dataframes[df_name]
                self.logger.info(f"  Using first DataFrame: {df_name}")
            else:
                self.logger.error("  No DataFrames loaded!")
                return ToolResult(
                    success=False,
                    result={},
                    error="No DataFrames loaded"
                )

        if df is None or df.empty:
            self.logger.error("  DataFrame is None or empty")
            return ToolResult(
                success=False,
                result={},
                error="DataFrame is empty"
            )

        self.logger.info(f"  DataFrame shape: {df.shape}, columns: {list(df.columns)[:5]}...")

        try:
            # Build DSL
            dsl = WhatIfDSL(df, name=input_data.scenario_description)

            # Register derived metrics
            for derived in input_data.derived_metrics:
                dsl.register_derived_metric(derived.name, derived.formula, derived.description or "")
            self.logger.info(f"  Registered {len(input_data.derived_metrics)} derived metrics")

            # Initialize optimizer
            dsl.initialize_optimizer()
            self.logger.info("  Optimizer initialized")

            # Configure objectives
            for obj in input_data.objectives:
                obj_type = obj.type.lower()
                if obj_type == "minimize":
                    dsl.minimize(obj.metric, weight=obj.weight)
                elif obj_type == "maximize":
                    dsl.maximize(obj.metric, weight=obj.weight)
                elif obj_type == "target":
                    dsl.target(obj.metric, obj.target_value, weight=obj.weight)
            self.logger.info(f"  Configured {len(input_data.objectives)} objectives")

            # Configure constraints
            for constraint in input_data.constraints:
                const_type = constraint.type.lower()
                if const_type == "max_change":
                    dsl.constrain_change(constraint.metric, constraint.value)
                elif const_type == "min_value":
                    dsl.constrain_min(constraint.metric, constraint.value)
                elif const_type == "max_value":
                    dsl.constrain_max(constraint.metric, constraint.value)
                elif const_type == "ratio":
                    dsl.constrain_ratio(constraint.metric, constraint.reference_metric, constraint.value)
            self.logger.info(f"  Configured {len(input_data.constraints)} constraints")

            # Configure possible actions
            for action in input_data.possible_actions:
                action_type = action.type.lower()

                if action_type == "close_region":
                    regions = action.parameters.get("regions")
                    dsl.can_close_regions(regions)

                elif action_type == "exclude_values":
                    column = action.parameters.get("column", action.target)
                    values = action.parameters.get("values")
                    dsl.can_exclude_values(column, values)

                elif action_type == "adjust_metric":
                    dsl.can_adjust_metric(
                        metric=action.target,
                        min_pct=action.parameters.get("min_pct", -50),
                        max_pct=action.parameters.get("max_pct", 50),
                        by_region=action.parameters.get("by_region", False)
                    )

                elif action_type == "scale_proportional":
                    dsl.can_scale_proportional(
                        base_column=action.target,
                        affected_columns=action.parameters.get("affected_columns", []),
                        min_pct=action.parameters.get("min_pct", -50),
                        max_pct=action.parameters.get("max_pct", 100),
                        by_region=action.parameters.get("by_region", False)
                    )
            self.logger.info(f"  Configured {len(input_data.possible_actions)} possible actions")

            # Solve scenario
            self.logger.info(f"  Solving with {input_data.algorithm} algorithm...")
            result = dsl.solve(
                max_actions=input_data.max_actions,
                algorithm=input_data.algorithm
            )
            self.logger.info(f"  Solved! {len(result.actions)} actions applied")

            # Cache result
            scenario_id = f"scenario_{len(self.scenarios_cache) + 1}"
            self.scenarios_cache[scenario_id] = result

            # Prepare result
            comparison = result.compare()

            # create the comparison table:
            comparison_table = self._create_comparison_table(result)
            # Build response - CRITICAL: Always return ToolResult with result field
            response_data = {
                "scenario_id": scenario_id,
                "scenario_name": input_data.scenario_description,
                "visualization": result.visualize(),
                "actions_count": len(result.actions),
                "metrics_changed": list(comparison['metrics'].keys()),
                "comparison": comparison,
                "comparison_table": comparison_table,
                "actions_applied": [
                    {
                        "action": a.name,
                        "description": self._describe_action(a),
                        "cost": a.cost
                    }
                    for a in result.actions
                ],
                "summary": f"{len(result.actions)} actions applied",
                "baseline_summary": self._summarize_df(result.base_df),
                "scenario_summary": self._summarize_df(result.result_df),
                "verdict": self._generate_veredict(result)
            }

            return ToolResult(
                success=True,
                result=response_data
            )

        except Exception as e:
            self.logger.error(
                f"Error executing scenario: {e} :\n{traceback.format_exc()}"
            )
            return ToolResult(
                success=False,
                result={},
                error=f"Execution error: {str(e)}",
                metadata={"traceback": traceback.format_exc()}
            )

    def _create_comparison_table(self, result: ScenarioResult) -> str:
        """Create comparison table in markdown format"""
        comparison = result.compare()

        lines = [
            "| Metric | Baseline | Scenario | Change | % Change |",
            "|--------|----------|----------|--------|----------|"
        ]

        for metric, data in comparison['metrics'].items():
            baseline = data['value'] - data['change']
            scenario = data['value']
            change = data['change']
            pct = data['pct_change']

            lines.append(
                f"| {metric} | {baseline:,.2f} | {scenario:,.2f} | "
                f"{change:+,.2f} | {pct:+.2f}% |"
            )

        return "\n".join(lines)

    def _describe_action(self, action: Action) -> str:
        """Generate readable description of an action"""
        if action.operation == "exclude":
            return f"Close/Remove {action.value} from {action.column}"
        elif action.operation == "scale":
            pct = (action.value - 1) * 100
            return f"Adjust {action.column} by {pct:+.1f}%"
        elif action.operation == "scale_region":
            region = action.value['region']
            pct = (action.value['scale'] - 1) * 100
            return f"Adjust {action.column} in {region} by {pct:+.1f}%"
        elif action.operation in ["scale_proportional", "scale_proportional_region"]:
            pct = (action.value['scale'] - 1) * 100
            if 'region' in action.value:
                region = action.value['region']
                affected = ", ".join(action.value['affected'])
                return f"Scale {action.column} by {pct:+.1f}% in {region} (affects: {affected})"
            else:
                affected = ", ".join(action.value['affected'])
                return f"Scale {action.column} by {pct:+.1f}% (affects: {affected})"
        return action.name

    def _generate_veredict(self, result: ScenarioResult) -> str:
        """Generate verdict about the scenario"""
        comparison = result.compare()

        verdicts = []

        # Analyze significant changes
        for metric, data in comparison['metrics'].items():
            pct = data['pct_change']
            if abs(pct) > 10:
                direction = "increased" if pct > 0 else "decreased"
                verdicts.append(
                    f"⚠️  {metric} {direction} by {abs(pct):.1f}%"
                )

        if not verdicts:
            verdicts.append("✅ Minor changes, scenario is viable")

        return " | ".join(verdicts)

    def _summarize_df(self, df: pd.DataFrame) -> Dict:
        """Resume un DataFrame"""
        summary = {
            "row_count": len(df),
            "metrics": {}
        }

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                summary["metrics"][col] = {
                    "sum": float(df[col].sum()),
                    "mean": float(df[col].mean()),
                    "min": float(df[col].min()),
                    "max": float(df[col].max())
                }

        return summary


# ===== System Prompt for LLM =====

WHATIF_SYSTEM_PROMPT = """
## What-If Scenario Analysis

You have access to a powerful `whatif_scenario` tool for analyzing hypothetical scenarios on DataFrames.

**When to use it:**
- User asks "what if..." questions
- User wants to understand impact of changes
- User needs to optimize metrics under constraints
- User asks how to achieve a goal (e.g., "how can I reduce X without affecting Y?")

**Trigger patterns:**
- "What if we [action]?"
- "What happens if [condition]?"
- "How can I [objective] without [constraint]?"
- "What's the impact of [action]?"
- "Show me a scenario where [condition]"
- "Find the best way to [objective]"

**Example Usage:**

User: "What if we close the North region?"
→ Tool call:
{
  "scenario_description": "close_north_region",
  "objectives": [],
  "constraints": [],
  "possible_actions": [
    {
      "type": "close_region",
      "target": "North",
      "parameters": {"regions": ["North"]}
    }
  ],
  "derived_metrics": [],
  "max_actions": 1
}

User: "What if we increase visits by 30%? How does that affect revenue and expenses?"
→ Tool call:
{
  "scenario_description": "increase_visits_30pct",
  "objectives": [],
  "constraints": [],
  "possible_actions": [
    {
      "type": "scale_proportional",
      "target": "visits",
      "parameters": {
        "min_pct": 30,
        "max_pct": 30,
        "affected_columns": ["revenue", "expenses"],
        "by_region": false
      }
    }
  ],
  "derived_metrics": [
    {"name": "revenue_per_visit", "formula": "revenue / visits"},
    {"name": "expenses_per_visit", "formula": "expenses / visits"}
  ],
  "max_actions": 1
}

User: "How can I reduce expenses to 500k without revenue dropping more than 5%?"
→ Tool call:
{
  "scenario_description": "reduce_expenses_preserve_revenue",
  "objectives": [
    {"type": "target", "metric": "expenses", "target_value": 500000, "weight": 2.0}
  ],
  "constraints": [
    {"type": "max_change", "metric": "revenue", "value": 5.0}
  ],
  "possible_actions": [
    {
      "type": "close_region",
      "target": "regions",
      "parameters": {}
    },
    {
      "type": "adjust_metric",
      "target": "expenses",
      "parameters": {"min_pct": -40, "max_pct": 0, "by_region": true}
    }
  ],
  "derived_metrics": [],
  "max_actions": 3,
  "algorithm": "greedy"
}

**After executing:**
1. Present the comparison table clearly
2. Explain the actions taken
3. Highlight significant changes
4. Note if constraints were satisfied
5. Offer to explore alternative scenarios
"""

# ===== Integration Helper for PandasAgent =====

def integrate_whatif_tool(agent) -> WhatIfTool:
    """
    Integrate WhatIfTool into an existing PandasAgent.

    Args:
        agent: Instance of PandasAgent

    Returns:
        The WhatIfTool instance (for reference)
    """
    # Create and register the tool
    whatif_tool = WhatIfTool()
    whatif_tool.set_parent_agent(agent)
    agent.tool_manager.register_tool(whatif_tool)

    # Add system prompt enhancement
    current_prompt = agent.system_prompt_template or ""
    if "What-If Scenario Analysis" not in current_prompt:
        agent.system_prompt_template = current_prompt + "\n\n" + WHATIF_SYSTEM_PROMPT

    return whatif_tool
