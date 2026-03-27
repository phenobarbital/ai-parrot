# Feature Specification: WhatIf Toolkit Decomposition & Statistical Analysis Tools

**Feature ID**: FEAT-065
**Date**: 2026-03-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `WhatIfTool` is a **single monolithic tool** with a complex `WhatIfInput` schema containing ~10 fields (objectives, constraints, possible_actions, derived_metrics, algorithm). LLMs — especially Gemini — consistently fail with multi-purpose tools because they:

1. **Default to minimal parameters**: When a tool has many optional fields, LLMs pick the simplest configuration and ignore advanced features (constraints, derived metrics, optimization objectives).
2. **Cannot construct complex JSON in one shot**: Building a complete scenario with actions, constraints, objectives, and derived metrics in a single tool call exceeds the reliable structured-output capacity of most models.
3. **Lack intermediate validation**: The LLM gets no feedback until the entire scenario executes — if a column name is wrong or a metric formula is invalid, the whole call fails.
4. **Cannot iterate**: There is no way to refine a scenario incrementally. The user must re-describe everything from scratch.

Additionally, the WhatIf tool accesses DataFrames through the parent agent (`self._parent_agent.dataframes`) instead of using the `DatasetManager` directly, creating tight coupling and preventing use outside of `PandasAgent`.

Finally, the ecosystem lacks complementary statistical tools that would make what-if analysis truly powerful: sensitivity analysis (which variable matters most?), Monte Carlo simulation (what's the range of outcomes?), regression modeling (what's the relationship?), statistical tests (is this change significant?), and break-even analysis (where's the threshold?).

### Goals

1. **Decompose `WhatIfTool` into a `WhatIfToolkit`** with 6 focused tools that guide LLMs through a step-by-step workflow
2. **Add a `quick_impact` fast-path** for the 70% of queries that are simple ("what if we remove X?")
3. **Integrate directly with `DatasetManager`** for dataset resolution, metadata, and result persistence
4. **Register simulation results as DataFrames** accessible via `PythonPandasTool` for custom follow-up analysis
5. **Create 5 new statistical analysis tools** that complement the WhatIf workflow: `SensitivityAnalysisTool`, `MonteCarloSimulationTool`, `StatisticalTestsTool`, `RegressionAnalysisTool`, `BreakEvenAnalysisTool`
6. **Maintain backward compatibility** with the existing `WhatIfTool` API during transition

### Non-Goals (explicitly out of scope)

- Exposing the `WhatIfDSL` class directly to LLMs (it remains internal)
- Real-time streaming of simulation progress
- GPU-accelerated Monte Carlo (numpy is sufficient for current scale)
- Bayesian inference or probabilistic programming frameworks (e.g., PyMC)
- Time-series-specific what-if (Prophet handles forecasting; WhatIf is for tabular scenarios)
- UI/dashboard integration (tools return structured data; visualization is downstream)

---

## 2. Architectural Design

### Overview

The feature introduces two packages of changes:

**Package A — WhatIf Toolkit Decomposition**: Convert the monolithic `WhatIfTool` into a `WhatIfToolkit` (extends `AbstractToolkit`) with 6 async methods that become individual tools. The toolkit holds scenario state internally and integrates directly with `DatasetManager`.

**Package B — Statistical Analysis Tools**: 5 new tools in `parrot_tools/` that operate on DataFrames and complement the WhatIf workflow. Each is a standalone `AbstractTool` with focused schema.

```
                    ┌──────────────────────────────┐
                    │       DatasetManager         │
                    │  (dataset resolution + state) │
                    └──────────┬───────────────────┘
                               │
              ┌────────────────┼────────────────────┐
              │                │                    │
    ┌─────────▼──────────┐     │          ┌─────────▼──────────┐
    │  WhatIfToolkit      │     │          │  PythonPandasTool  │
    │  (6 focused tools)  │     │          │  (custom analysis) │
    │                     │     │          └────────────────────┘
    │  describe_scenario  │     │
    │  add_actions        │     │
    │  set_constraints    │     │
    │  simulate           │     │
    │  quick_impact       │     │
    │  compare_scenarios  │     │
    └─────────────────────┘     │
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
    ┌────▼─────────┐   ┌──────▼──────┐   ┌──────────▼─────────┐
    │ Sensitivity  │   │ MonteCarlo  │   │ StatisticalTests   │
    │ Analysis     │   │ Simulation  │   │                    │
    └──────────────┘   └─────────────┘   └────────────────────┘
         │                     │
    ┌────▼─────────┐   ┌──────▼──────┐
    │ Regression   │   │ BreakEven   │
    │ Analysis     │   │ Analysis    │
    └──────────────┘   └─────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | `WhatIfToolkit` inherits; each async method = one tool |
| `DatasetManager` | constructor dependency | Direct dataset resolution via `dm.get_dataframe()`, `dm.get_metadata()` |
| `PythonPandasTool` | result publishing | Simulation results registered as temporary DataFrames via DatasetManager |
| `WhatIfDSL` | internal (no change) | DSL remains the execution engine; toolkit methods configure it |
| `MetricsCalculator` | internal (no change) | Derived metrics engine unchanged |
| `ScenarioOptimizer` | internal (no change) | Optimization algorithms unchanged |
| `TOOL_REGISTRY` | modifies | Add new toolkit and 5 new tools |
| `integrate_whatif_tool()` | deprecates | Replaced by toolkit constructor pattern |
| Existing `WhatIfTool` | preserves (wrapper) | Thin wrapper that delegates to toolkit for backward compat |

### Data Models

#### Scenario State (internal, not exposed to LLM)

```python
@dataclass
class ScenarioState:
    """Internal state for a scenario being built incrementally."""
    id: str                                    # e.g., "sc_1"
    description: str
    df_name: str
    df: pd.DataFrame                          # snapshot at creation
    derived_metrics: List[DerivedMetric]       # registered formulas
    actions: List[WhatIfAction]               # configured actions
    objectives: List[WhatIfObjective]          # optimization goals
    constraints: List[WhatIfConstraint]        # limits
    result: Optional[ScenarioResult] = None   # populated after simulate()
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_ready(self) -> bool:
        """Scenario has at least actions defined."""
        return len(self.actions) > 0

    @property
    def is_solved(self) -> bool:
        return self.result is not None
```

#### Tool Input Schemas (one per tool — simple, focused)

```python
class DescribeScenarioInput(BaseModel):
    """Input for describe_scenario tool."""
    df_name: str = Field(description="Name or alias of the dataset to analyze")
    scenario_description: str = Field(description="Natural language description of the scenario")
    derived_metrics: List[DerivedMetric] = Field(
        default_factory=list,
        description="Calculated metrics (e.g., ebitda = revenue - expenses)"
    )

class AddActionsInput(BaseModel):
    """Input for add_actions tool."""
    scenario_id: str = Field(description="Scenario ID from describe_scenario")
    actions: List[WhatIfAction] = Field(description="Actions to add to the scenario")

class SetConstraintsInput(BaseModel):
    """Input for set_constraints tool."""
    scenario_id: str = Field(description="Scenario ID from describe_scenario")
    objectives: List[WhatIfObjective] = Field(
        default_factory=list,
        description="Optimization objectives (minimize, maximize, target)"
    )
    constraints: List[WhatIfConstraint] = Field(
        default_factory=list,
        description="Constraints to respect (max_change, min_value, max_value, ratio)"
    )

class SimulateInput(BaseModel):
    """Input for simulate tool."""
    scenario_id: str = Field(description="Scenario ID from describe_scenario")
    algorithm: str = Field(default="greedy", description="Algorithm: 'greedy' or 'genetic'")
    max_actions: int = Field(default=5, description="Maximum actions to apply")

class QuickImpactInput(BaseModel):
    """Input for quick_impact tool — the simple fast-path."""
    df_name: str = Field(description="Name or alias of the dataset")
    action_description: str = Field(
        description="Natural language: 'remove Belkin', 'increase visits by 30%', 'close North region'"
    )
    action_type: str = Field(
        description="Type: exclude_values, scale_entity, adjust_metric, scale_proportional, close_region"
    )
    target: str = Field(description="Column or entity to act on")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters"
    )

class CompareScenariosInput(BaseModel):
    """Input for compare_scenarios tool."""
    scenario_ids: List[str] = Field(
        description="Two or more scenario IDs to compare side by side",
        min_length=2
    )
```

---

## 3. Component Specifications

### 3.1 WhatIfToolkit (Package A)

**File**: `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py`
**Class**: `WhatIfToolkit(AbstractToolkit)`

#### Constructor

```python
class WhatIfToolkit(AbstractToolkit):
    name = "whatif"
    description = "What-If scenario analysis toolkit for simulating hypothetical changes on datasets"

    exclude_tools = ("start", "stop", "cleanup")  # lifecycle methods excluded

    def __init__(
        self,
        dataset_manager: Optional['DatasetManager'] = None,
        pandas_tool: Optional['PythonPandasTool'] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._dm = dataset_manager
        self._pandas = pandas_tool
        self._scenarios: Dict[str, ScenarioState] = {}
        self._counter = 0
```

#### Tool 1: `describe_scenario`

**Purpose**: Create and validate a scenario configuration. Returns scenario ID + dataset metadata so the LLM can make informed decisions about actions and constraints.

**Behavior**:
1. Resolve dataset from DatasetManager by name or alias
2. Materialize if not loaded (lazy loading)
3. Auto-detect numeric columns, categorical columns, and suggest possible metrics
4. Register any derived metrics and validate formulas against actual columns
5. Create `ScenarioState`, store in `_scenarios`
6. Return: scenario_id, column list with types, row count, numeric summary stats, registered derived metrics, suggested actions based on data shape

**Return example**:
```
Scenario sc_1 created for dataset 'pokemon_financials'
Columns: Project(categorical, 8 unique), Region(categorical, 4 unique),
         Revenue(numeric, sum=2.3M), Expenses(numeric, sum=1.8M),
         kiosks(numeric, sum=450), warehouses(numeric, sum=12)
Derived metrics registered: ebitda = revenue - expenses (validated OK)
Suggested actions: exclude_values(Project), close_region(Region),
                   adjust_metric(Revenue, Expenses, kiosks, warehouses)
```

#### Tool 2: `add_actions`

**Purpose**: Add possible actions to an existing scenario. Validates each action against the DataFrame schema.

**Behavior**:
1. Look up scenario by ID
2. For each action: validate column exists, validate parameters, validate entity values exist (for scale_entity)
3. Append valid actions, report invalid ones with specific error messages
4. Return: summary of added actions, validation status per action

#### Tool 3: `set_constraints`

**Purpose**: Define optimization objectives and constraints for a scenario.

**Behavior**:
1. Look up scenario by ID
2. Validate metric names (must be columns or registered derived metrics)
3. Validate constraint values are reasonable (e.g., max_change > 0)
4. Store objectives and constraints
5. Return: summary of configured optimization

#### Tool 4: `simulate`

**Purpose**: Execute the scenario using the WhatIfDSL engine. Registers results as a DataFrame.

**Behavior**:
1. Look up scenario by ID, verify it has actions
2. Build WhatIfDSL from ScenarioState (derived metrics, objectives, constraints, actions)
3. Run solver (greedy or genetic)
4. Store result in ScenarioState
5. **Register result DataFrame in DatasetManager** as `whatif_{scenario_id}_result`
6. Return: comparison table (markdown), actions applied, verdict, scenario_id for comparison

**DatasetManager integration**:
```python
# After solving:
if self._dm:
    self._dm.add_dataframe(
        name=f"whatif_{scenario.id}_result",
        df=result.result_df,
        description=f"WhatIf result: {scenario.description}"
    )
    if self._pandas:
        self._pandas.sync_from_manager()
```

#### Tool 5: `quick_impact`

**Purpose**: Fast-path for simple what-if queries that don't need optimization. Handles ~70% of user queries.

**Behavior**:
1. Resolve dataset from DatasetManager
2. Parse the action (single action, no optimization)
3. Apply action directly via WhatIfDSL (no solver)
4. Return before/after comparison table
5. Optionally register result if DatasetManager available

**Key difference from full workflow**: No scenario_id needed, no multi-step process. One call in, one result out.

**Supported action types**:
- `exclude_values`: Remove rows matching criteria ("remove Belkin", "close North")
- `scale_entity`: Scale specific entity values ("reduce Belkin by 50%")
- `adjust_metric`: Scale a column globally ("increase visits by 30%")
- `scale_proportional`: Scale base column and adjust derived proportionally
- `close_region`: Remove all rows for a region value

#### Tool 6: `compare_scenarios`

**Purpose**: Side-by-side comparison of multiple simulated scenarios.

**Behavior**:
1. Look up all scenario IDs, verify all are solved
2. Build comparison matrix: one row per metric, one column per scenario
3. Highlight best/worst scenario per metric
4. Return: markdown comparison table + recommendation

### 3.2 System Prompt Update

**File**: `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py`

The system prompt must guide the LLM through the tool selection:

```python
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
- "What if we remove X?" → quick_impact
- "What if we increase X by Y%?" → quick_impact
- "How can we optimize X without hurting Y?" → full workflow (describe → add_actions → set_constraints → simulate)
- "Compare scenario A vs B" → compare_scenarios
"""
```

### 3.3 Backward Compatibility Wrapper

**File**: `packages/ai-parrot-tools/src/parrot_tools/whatif.py` (existing)

The existing `WhatIfTool` class is preserved but delegates to `WhatIfToolkit`:

```python
class WhatIfTool(AbstractTool):
    """Legacy wrapper — delegates to WhatIfToolkit for backward compatibility."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._toolkit = WhatIfToolkit()
        # ... existing init preserved

    async def _execute(self, **kwargs) -> ToolResult:
        # Map WhatIfInput to quick_impact or full workflow
        input_data = WhatIfInput(**kwargs)
        if not input_data.objectives and not input_data.constraints:
            # Simple scenario → quick_impact path
            return await self._toolkit.quick_impact(...)
        else:
            # Complex scenario → full workflow in one shot
            ...
```

### 3.4 SensitivityAnalysisTool (Package B — Tool 1)

**File**: `packages/ai-parrot-tools/src/parrot_tools/sensitivity_analysis.py`
**Class**: `SensitivityAnalysisTool(AbstractTool)`
**Dependencies**: `numpy`, `pandas` (already in project)

**Purpose**: Determine which input variables have the greatest impact on a target metric. Generates tornado charts and spider plots.

**Input Schema**:
```python
class SensitivityAnalysisInput(BaseModel):
    df_name: str = Field(description="Name or alias of the dataset")
    target_metric: str = Field(description="Target column or derived metric to analyze")
    input_variables: Optional[List[str]] = Field(
        default=None,
        description="Columns to vary. If None, uses all numeric columns except target"
    )
    variation_range: float = Field(
        default=20.0,
        description="Percentage variation to test (e.g., 20 means ±20%)"
    )
    derived_metrics: List[DerivedMetric] = Field(
        default_factory=list,
        description="Formulas for computed metrics"
    )
    method: str = Field(
        default="one_at_a_time",
        description="Method: 'one_at_a_time' (tornado) or 'all_at_once' (spider)"
    )
```

**Behavior**:
1. For each input variable, vary it by ±`variation_range`% while holding others constant
2. Measure the change in `target_metric`
3. Rank variables by absolute impact
4. Return: ranked impact table, tornado chart data, elasticity coefficients

**Output**:
```
Sensitivity Analysis for 'ebitda' (±20% variation):

| Variable    | -20% Impact | +20% Impact | Range    | Elasticity |
|-------------|-------------|-------------|----------|------------|
| revenue     | -$460K      | +$460K      | $920K    | 1.00       |
| expenses    | +$360K      | -$360K      | $720K    | -0.78      |
| kiosks      | -$120K      | +$120K      | $240K    | 0.26       |
| warehouses  | +$45K       | -$45K       | $90K     | -0.10      |

Top driver: 'revenue' has the highest impact on ebitda.
```

### 3.5 MonteCarloSimulationTool (Package B — Tool 2)

**File**: `packages/ai-parrot-tools/src/parrot_tools/montecarlo.py`
**Class**: `MonteCarloSimulationTool(AbstractTool)`
**Dependencies**: `numpy`, `pandas`, `scipy.stats` (already in project via statsmodels)

**Purpose**: Run stochastic simulations to provide probability distributions of outcomes instead of single-point estimates.

**Input Schema**:
```python
class VariableDistribution(BaseModel):
    column: str = Field(description="Column name to vary")
    distribution: str = Field(
        default="normal",
        description="Distribution: 'normal', 'uniform', 'triangular', 'lognormal'"
    )
    params: Dict[str, float] = Field(
        description="Distribution params: normal={mean_pct, std_pct}, uniform={min_pct, max_pct}, triangular={min_pct, mode_pct, max_pct}"
    )

class MonteCarloInput(BaseModel):
    df_name: str = Field(description="Name or alias of the dataset")
    target_metrics: List[str] = Field(description="Metrics to measure (columns or derived)")
    variables: List[VariableDistribution] = Field(description="Variables to randomize")
    n_simulations: int = Field(default=10000, description="Number of simulations (1000-100000)")
    derived_metrics: List[DerivedMetric] = Field(default_factory=list)
    confidence_levels: List[float] = Field(
        default=[0.05, 0.25, 0.50, 0.75, 0.95],
        description="Percentiles to report"
    )
```

**Behavior**:
1. For each simulation: sample random variations for each variable from its distribution
2. Apply variations to the DataFrame
3. Calculate target metrics (including derived)
4. Collect results across all simulations
5. Return: percentile distribution, histogram data, probability of exceeding/falling below thresholds

**Output**:
```
Monte Carlo Simulation (10,000 runs):
Variables: kiosks (normal, mean=+1000, std=200), warehouses (uniform, +3 to +5)

| Metric  | P5         | P25        | P50 (Median) | P75        | P95        |
|---------|------------|------------|--------------|------------|------------|
| revenue | $2.45M     | $2.62M     | $2.71M       | $2.80M     | $2.98M     |
| expenses| $1.92M     | $2.01M     | $2.06M       | $2.11M     | $2.20M     |
| ebitda  | $380K      | $545K      | $650K        | $755K      | $890K      |

Probability ebitda > $500K: 72.3%
Probability ebitda < $0: 2.1%
```

### 3.6 StatisticalTestsTool (Package B — Tool 3)

**File**: `packages/ai-parrot-tools/src/parrot_tools/statistical_tests.py`
**Class**: `StatisticalTestsTool(AbstractTool)`
**Dependencies**: `scipy.stats`, `numpy`, `pandas`

**Purpose**: Validate whether observed differences between scenarios or groups are statistically significant.

**Input Schema**:
```python
class StatisticalTestInput(BaseModel):
    df_name: str = Field(description="Name or alias of the dataset")
    test_type: str = Field(
        description="Test type: 'ttest' (compare two groups), 'anova' (compare multiple groups), "
                    "'chi_square' (categorical association), 'mann_whitney' (non-parametric), "
                    "'kruskal_wallis' (non-parametric ANOVA), 'normality' (check distribution)"
    )
    target_column: str = Field(description="Numeric column to test")
    group_column: Optional[str] = Field(
        default=None,
        description="Categorical column defining groups (required for ttest, anova, etc.)"
    )
    groups: Optional[List[str]] = Field(
        default=None,
        description="Specific group values to compare (default: all groups)"
    )
    alpha: float = Field(default=0.05, description="Significance level")
    alternative: str = Field(
        default="two-sided",
        description="Alternative hypothesis: 'two-sided', 'less', 'greater'"
    )
```

**Behavior**:
1. Extract groups from DataFrame based on `group_column`
2. Run appropriate statistical test
3. Return: test statistic, p-value, effect size, confidence interval, plain-language interpretation

**Output**:
```
T-Test: Revenue by Region (North vs South)
  t-statistic: 2.45
  p-value: 0.018
  Effect size (Cohen's d): 0.72 (medium-large)
  95% CI for difference: [$12,300, $45,600]

Interpretation: The difference in revenue between North and South regions
is statistically significant (p=0.018 < 0.05). North generates significantly
more revenue with a medium-large effect size.
```

### 3.7 RegressionAnalysisTool (Package B — Tool 4)

**File**: `packages/ai-parrot-tools/src/parrot_tools/regression_analysis.py`
**Class**: `RegressionAnalysisTool(AbstractTool)`
**Dependencies**: `numpy`, `pandas`, `scipy.stats` (or `sklearn` if available)

**Purpose**: Model quantitative relationships between variables. Answer "how does X affect Y?" and "if we add 1000 kiosks, what's the expected revenue increase?"

**Input Schema**:
```python
class RegressionInput(BaseModel):
    df_name: str = Field(description="Name or alias of the dataset")
    target: str = Field(description="Dependent variable (Y) to predict")
    predictors: List[str] = Field(description="Independent variables (X1, X2, ...)")
    model_type: str = Field(
        default="linear",
        description="Model: 'linear', 'polynomial' (degree 2-3), 'log'"
    )
    predict_at: Optional[Dict[str, float]] = Field(
        default=None,
        description="Optional: predict Y for given X values (e.g., {'kiosks': 1450, 'warehouses': 16})"
    )
    include_diagnostics: bool = Field(
        default=True,
        description="Include R-squared, residual analysis, significance tests"
    )
```

**Behavior**:
1. Fit regression model using numpy/scipy (no sklearn dependency required)
2. Calculate R-squared, adjusted R-squared, coefficients with p-values
3. If `predict_at` provided, generate prediction with confidence interval
4. Return: model equation, coefficients table, fit diagnostics, prediction (if requested)

**Output**:
```
Linear Regression: ebitda ~ kiosks + warehouses

Model: ebitda = 1,250 * kiosks - 45,000 * warehouses + 125,000
R-squared: 0.87 (87% of variance explained)
Adjusted R-squared: 0.85

| Predictor   | Coefficient | Std Error | t-stat | p-value | Significant |
|-------------|-------------|-----------|--------|---------|-------------|
| kiosks      | 1,250       | 180       | 6.94   | <0.001  | Yes         |
| warehouses  | -45,000     | 12,000    | -3.75  | 0.004   | Yes         |
| intercept   | 125,000     | 35,000    | 3.57   | 0.006   | Yes         |

Prediction at kiosks=1450, warehouses=16:
  Expected ebitda: $1,812,500 ± $145,000 (95% CI: [$1,667,500, $1,957,500])
  Each additional kiosk adds ~$1,250 to ebitda.
  Each additional warehouse reduces ebitda by ~$45,000.
```

### 3.8 BreakEvenAnalysisTool (Package B — Tool 5)

**File**: `packages/ai-parrot-tools/src/parrot_tools/breakeven.py`
**Class**: `BreakEvenAnalysisTool(AbstractTool)`
**Dependencies**: `numpy`, `pandas`, `scipy.optimize`

**Purpose**: Find threshold values — "how many kiosks do we need to cover the cost of 4 new warehouses?" or "at what revenue level does the project break even?"

**Input Schema**:
```python
class BreakEvenInput(BaseModel):
    df_name: str = Field(description="Name or alias of the dataset")
    target_metric: str = Field(
        description="Metric that must reach the threshold (e.g., 'ebitda', 'profit')"
    )
    target_value: float = Field(
        default=0.0,
        description="Target value for break-even (default: 0 for true break-even)"
    )
    variable: str = Field(
        description="Variable to solve for (e.g., 'kiosks')"
    )
    variable_range: Optional[List[float]] = Field(
        default=None,
        description="Search range [min, max] for the variable. If None, uses 0 to 10x current value"
    )
    fixed_changes: Dict[str, float] = Field(
        default_factory=dict,
        description="Fixed changes to apply before solving (e.g., {'warehouses': 4} adds 4 warehouses)"
    )
    derived_metrics: List[DerivedMetric] = Field(default_factory=list)
```

**Behavior**:
1. Apply fixed changes (e.g., add 4 warehouses)
2. Binary search or root-finding (`scipy.optimize.brentq`) for the variable value where target_metric = target_value
3. Generate sensitivity curve around break-even point
4. Return: break-even value, margin of safety from current position, sensitivity curve data

**Output**:
```
Break-Even Analysis:
  Question: "How many kiosks needed to maintain ebitda >= $0 after adding 4 warehouses?"

  Current state: 450 kiosks, 12 warehouses, ebitda = $500K
  After adding 4 warehouses: ebitda drops to $320K
  Break-even point: 594 kiosks (need +144 kiosks)
  Current margin of safety: -144 kiosks (below break-even after warehouse expansion)

  Sensitivity:
  | Kiosks | ebitda    |
  |--------|-----------|
  | 500    | -$117K    |
  | 550    | $62K      |
  | 594    | $0        | ← break-even
  | 650    | $70K      |
  | 700    | $132K     |
```

---

## 4. Tool Registry Updates

**File**: `packages/ai-parrot-tools/src/parrot_tools/__init__.py`

```python
TOOL_REGISTRY = {
    # ... existing entries ...

    # WhatIf Toolkit (replaces single "whatif" entry)
    "whatif_toolkit": "parrot_tools.whatif_toolkit.WhatIfToolkit",
    "whatif": "parrot_tools.whatif.WhatIfTool",  # preserved for backward compat

    # New Statistical Analysis Tools
    "sensitivity_analysis": "parrot_tools.sensitivity_analysis.SensitivityAnalysisTool",
    "montecarlo": "parrot_tools.montecarlo.MonteCarloSimulationTool",
    "statistical_tests": "parrot_tools.statistical_tests.StatisticalTestsTool",
    "regression_analysis": "parrot_tools.regression_analysis.RegressionAnalysisTool",
    "breakeven": "parrot_tools.breakeven.BreakEvenAnalysisTool",
}
```

---

## 5. Integration Helper Update

**File**: `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py`

```python
def integrate_whatif_toolkit(
    agent,
    dataset_manager: Optional['DatasetManager'] = None,
    pandas_tool: Optional['PythonPandasTool'] = None
) -> WhatIfToolkit:
    """
    Integrate WhatIfToolkit into an agent.

    Resolves DatasetManager and PythonPandasTool from agent if not provided.
    Registers all 6 tools + adds system prompt.
    """
    # Auto-detect DatasetManager from agent
    if dataset_manager is None:
        dataset_manager = getattr(agent, 'dataset_manager', None)

    # Auto-detect PythonPandasTool from agent
    if pandas_tool is None:
        pandas_tool = getattr(agent, 'pandas_tool', None)

    toolkit = WhatIfToolkit(
        dataset_manager=dataset_manager,
        pandas_tool=pandas_tool
    )

    # Register all tools from toolkit
    for tool in toolkit.get_tools():
        agent.tool_manager.register(tool)

    # Add system prompt
    if hasattr(agent, 'add_system_prompt'):
        agent.add_system_prompt(WHATIF_TOOLKIT_SYSTEM_PROMPT)

    return toolkit
```

---

## 6. End-to-End User Flows

### Flow 1: Simple Query (quick_impact)

```
User: "What if we remove Belkin from the Pokemon dataset?"

LLM → quick_impact(
    df_name="pokemon_financials",
    action_description="remove Belkin",
    action_type="exclude_values",
    target="Project",
    parameters={"values": ["Belkin"]}
)

← Returns: comparison table showing impact on all metrics
```

### Flow 2: Complex Optimization (full workflow)

```
User: "In Pokemon, I want to add 1000 kiosks and 4 warehouses.
       What happens to expenses, revenue, and ebitda?
       Make sure ebitda margin stays above 15%."

LLM → describe_scenario(
    df_name="pokemon_financials",
    scenario_description="add 1000 kiosks and 4 warehouses",
    derived_metrics=[{"name": "ebitda", "formula": "revenue - expenses"},
                     {"name": "ebitda_margin", "formula": "(revenue - expenses) / revenue * 100"}]
)
← sc_1 created, columns listed, metrics validated

LLM → add_actions(
    scenario_id="sc_1",
    actions=[
        {"type": "adjust_metric", "target": "kiosks", "parameters": {"min_pct": 222, "max_pct": 222}},
        {"type": "scale_proportional", "target": "kiosks", "parameters": {
            "affected_columns": ["revenue"], "min_pct": 222, "max_pct": 222
        }},
        {"type": "adjust_metric", "target": "warehouses", "parameters": {"min_pct": 33, "max_pct": 33}}
    ]
)
← 3 actions validated and added

LLM → set_constraints(
    scenario_id="sc_1",
    objectives=[{"type": "maximize", "metric": "ebitda"}],
    constraints=[{"type": "min_value", "metric": "ebitda_margin", "value": 15.0}]
)
← Optimization configured

LLM → simulate(scenario_id="sc_1")
← Comparison table + result registered as 'whatif_sc_1_result' DataFrame
```

### Flow 3: Statistical Deep-Dive (complement WhatIf)

```
User: "Which variable has the biggest impact on EBITDA?"

LLM → sensitivity_analysis(
    df_name="pokemon_financials",
    target_metric="ebitda",
    derived_metrics=[{"name": "ebitda", "formula": "revenue - expenses"}]
)
← Tornado chart: revenue is #1 driver, then expenses, then kiosks

User: "If we add between 800 and 1200 kiosks, what's the range of outcomes?"

LLM → montecarlo(
    df_name="pokemon_financials",
    target_metrics=["ebitda"],
    variables=[{"column": "kiosks", "distribution": "uniform", "params": {"min_pct": 178, "max_pct": 267}}],
    derived_metrics=[{"name": "ebitda", "formula": "revenue - expenses"}]
)
← P10-P90 range with 72% probability of ebitda > $500K

User: "How many kiosks do we need to break even after adding 4 warehouses?"

LLM → breakeven(
    df_name="pokemon_financials",
    target_metric="ebitda",
    variable="kiosks",
    fixed_changes={"warehouses": 4},
    derived_metrics=[{"name": "ebitda", "formula": "revenue - expenses"}]
)
← Need 594 kiosks (+144 from current 450)
```

---

## 7. Testing Strategy

### Unit Tests

| Test File | Scope | Key Assertions |
|---|---|---|
| `tests/tools/test_whatif_toolkit.py` | WhatIfToolkit | Each tool method independently, scenario state management, DatasetManager integration |
| `tests/tools/test_whatif_quick_impact.py` | quick_impact | All 5 action types, edge cases (empty df, missing columns) |
| `tests/tools/test_whatif_backward_compat.py` | WhatIfTool wrapper | Existing tests still pass via legacy wrapper |
| `tests/tools/test_sensitivity_analysis.py` | SensitivityAnalysisTool | Tornado ranking, elasticity calculation, derived metrics |
| `tests/tools/test_montecarlo.py` | MonteCarloSimulationTool | Distribution sampling, percentile accuracy, convergence |
| `tests/tools/test_statistical_tests.py` | StatisticalTestsTool | t-test, ANOVA, chi-square, normality, p-value correctness |
| `tests/tools/test_regression.py` | RegressionAnalysisTool | Linear fit, R-squared, prediction with CI |
| `tests/tools/test_breakeven.py` | BreakEvenAnalysisTool | Root finding accuracy, fixed changes, edge cases |

### Integration Tests

| Test | What it validates |
|---|---|
| `test_toolkit_with_dataset_manager` | Scenario resolves datasets from DM, results registered back |
| `test_result_accessible_in_pandas_tool` | After simulate, result DataFrame available via PythonPandasTool |
| `test_full_workflow_end_to_end` | describe → add_actions → set_constraints → simulate → compare |
| `test_legacy_whatif_delegates_to_toolkit` | Existing WhatIfTool API produces same results via delegation |

---

## 8. Migration Plan

### Phase 1: Create WhatIfToolkit alongside WhatIfTool
- Implement `WhatIfToolkit` with all 6 methods
- Existing `WhatIfTool` continues to work unchanged
- Both registered in `TOOL_REGISTRY`

### Phase 2: Implement Statistical Tools
- Each tool is independent; can be implemented in parallel
- Priority order: SensitivityAnalysis > MonteCarlo > BreakEven > Regression > StatisticalTests

### Phase 3: Wire backward compatibility
- Modify `WhatIfTool._execute` to delegate to `WhatIfToolkit` internally
- Modify `integrate_whatif_tool()` to use toolkit under the hood
- Existing agents using `WhatIfTool` continue working without changes

### Phase 4: Update system prompts and documentation
- Replace `WHATIF_SYSTEM_PROMPT` with `WHATIF_TOOLKIT_SYSTEM_PROMPT` in agent configurations
- Update `docs/whatif_tool.md`

---

## 9. Dependencies

### Existing (no new dependencies)
- `numpy` — all numerical computation
- `pandas` — DataFrame operations
- `scipy.stats` — statistical tests, distributions (already available via statsmodels dependency)
- `scipy.optimize` — root finding for break-even (already available)

### Optional (for enhanced visualization)
- `matplotlib` — tornado charts, histograms (already in project)
- `seaborn` — enhanced statistical plots (already in project)

---

## 10. Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| LLM still fails to use multi-step workflow | Medium | `quick_impact` handles 70% of cases in one call; system prompt provides clear decision guide |
| Scenario state lost between conversation turns | Low | Scenarios stored in toolkit instance; same lifecycle as agent |
| Monte Carlo too slow for large DataFrames | Low | Default 10K simulations; operates on aggregated metrics, not row-level |
| Breaking existing WhatIfTool integrations | High | Wrapper preserved; existing API unchanged; delegation is internal |
| Statistical tools misinterpreted by LLM | Medium | Each tool has focused schema with clear descriptions; one purpose per tool |

---

## 11. Success Criteria

1. Gemini successfully completes a full WhatIf workflow (describe → actions → simulate) without falling back to defaults
2. `quick_impact` resolves simple queries in a single tool call
3. Simulation results appear as DataFrames in PythonPandasTool for follow-up analysis
4. All 5 statistical tools produce correct results validated against known scipy/numpy outputs
5. Existing `WhatIfTool` tests pass without modification via the backward-compat wrapper
6. The Pokemon scenario ("add 1000 kiosks and 4 warehouses → impact on ebitda") works end-to-end through both quick_impact and full workflow paths
