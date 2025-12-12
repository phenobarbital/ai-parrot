# WhatIfTool Implementation - Complete Summary

## 📦 What Was Created

A complete What-If scenario analysis tool for AI-Parrot's PandasAgent with the following capabilities:

✅ **Domain Specific Language (DSL)** for defining scenarios
✅ **Derived Metrics** support (e.g., revenue_per_visit, profit_margin)
✅ **Constraint-based Optimization** (greedy & genetic algorithms)
✅ **Proportional Scaling** for rate-based changes
✅ **Natural Language Integration** with LLM triggers
✅ **Comparison Tables** (baseline vs scenario)
✅ **Scenario Caching** for comparing multiple scenarios

## 📁 Files Created

1. **`whatif_integration.py`** (Main Implementation)
   - Complete tool implementation
   - All classes: WhatIfTool, WhatIfDSL, MetricsCalculator, ScenarioOptimizer
   - Pydantic schemas for input validation
   - Integration helper function

2. **`example_usage.py`** (Usage Examples)
   - 5 comprehensive examples
   - Natural language queries
   - Direct tool calls
   - Manual DSL usage

3. **`README_WHATIF.md`** (Documentation)
   - Feature overview
   - Installation instructions
   - API documentation
   - Common scenarios
   - Troubleshooting guide

4. **`test_whatif.py`** (Test Suite)
   - Unit tests for all components
   - Integration tests
   - Error handling tests
   - Performance tests

## 🚀 Quick Start

### 1. Integration

```python
from aiparrot.agents.data import PandasAgent
from aiparrot.clients.factory import LLMFactory
from whatif_integration import integrate_whatif_tool

# Create your PandasAgent
client = LLMFactory.create_client(provider="anthropic")
agent = PandasAgent(
    client=client,
    name="Analyst",
    dataframes={'data': df}
)

# Integrate WhatIfTool (one line!)
whatif_tool = integrate_whatif_tool(agent)

# That's it! Now use it naturally:
response = await agent.ask(
    "What if we increase visits by 30%?"
)
```

### 2. Natural Language Examples

The LLM automatically detects what-if patterns:

```python
# Simple impact
await agent.ask("What if we close the West region?")

# Proportional scaling
await agent.ask("What if we increase visits by 30%?")

# Optimization
await agent.ask(
    "Reduce expenses to 500k without revenue dropping more than 5%"
)

# Multi-objective
await agent.ask(
    "Maximize profit while keeping headcount above 1000"
)
```

## 🎯 Key Features Explained

### 1. Derived Metrics

**Problem**: You want to increase visits, but how does that affect revenue and expenses?

**Solution**: Define derived metrics that calculate rates:

```python
# The tool automatically creates these when needed:
revenue_per_visit = revenue / visits
expenses_per_visit = expenses / visits

# When visits increase by 30%:
# - visits × 1.3
# - revenue = visits × revenue_per_visit (automatically adjusted)
# - expenses = visits × expenses_per_visit (automatically adjusted)
```

**Example Query**:
```python
"What if we do 20% more visits? How does that affect revenue and expenses?"
```

### 2. Constraint Optimization

**Problem**: You need to reduce expenses but can't let revenue drop too much.

**Solution**: Set objectives and constraints, let the optimizer find the best actions:

```python
# Objective: Reduce expenses to 500k
# Constraint: Revenue can't drop more than 5%
# Actions: Can close regions, adjust expenses by region
# → Optimizer finds: Close West, reduce expenses 15% in North
```

**Example Query**:
```python
"I need to cut expenses to 500k, but revenue can't drop more than 5%. What should I do?"
```

### 3. Regional Analysis

**Problem**: Changes should only apply to specific regions.

**Solution**: Actions can be regional:

```python
"What if we increase visits by 50% in the North region only?"

# The tool will:
# - Scale visits in North by 50%
# - Adjust revenue/expenses in North proportionally
# - Leave other regions unchanged
```

## 📊 Output Format

Every scenario returns:

1. **Visualization** - Text summary with actions and changes
2. **Comparison Table** - Markdown table showing before/after
3. **Actions Applied** - List of actions taken
4. **Verdict** - High-level assessment

Example output:
```
======================================================================
Scenario: increase_visits_30pct
======================================================================

Actions Taken:
  1. Scale visits by +30.0% (affects: revenue, expenses)

Metric Changes:
Metric               Baseline         Scenario           Change      % Change
--------------------------------------------------------------------------------
visits             25000.00        32500.00         7500.00        30.00%
revenue          8500000.00     11050000.00      2550000.00        30.00%
expenses         5200000.00      6760000.00      1560000.00        30.00%

| Metric | Baseline | Scenario | Change | % Change |
|--------|----------|----------|--------|----------|
| visits | 25,000.00 | 32,500.00 | +7,500.00 | +30.00% |
| revenue | 8,500,000.00 | 11,050,000.00 | +2,550,000.00 | +30.00% |
| expenses | 5,200,000.00 | 6,760,000.00 | +1,560,000.00 | +30.00% |
```

## 🔧 Advanced Usage

### Manual DSL (Without LLM)

For programmatic scenario building:

```python
from whatif_integration import WhatIfDSL

scenario = (
    WhatIfDSL(df, name="my_scenario")
    .register_derived_metric("profit", "revenue - expenses")
    .initialize_optimizer()
    .maximize("profit", weight=1.0)
    .constrain_change("revenue", max_pct=5.0)
    .can_close_regions()
    .solve(max_actions=3, algorithm="greedy")
)

print(scenario.visualize())
```

### Direct Tool Call

For complete control:

```python
from whatif_integration import WhatIfInput, WhatIfAction, DerivedMetric

result = await whatif_tool._execute(
    scenario_description="test_scenario",
    objectives=[{"type": "maximize", "metric": "profit", "weight": 1.0}],
    constraints=[{"type": "max_change", "metric": "revenue", "value": 5.0}],
    possible_actions=[
        {
            "type": "scale_proportional",
            "target": "visits",
            "parameters": {
                "min_pct": 20,
                "max_pct": 20,
                "affected_columns": ["revenue", "expenses"]
            }
        }
    ],
    derived_metrics=[
        {"name": "revenue_per_visit", "formula": "revenue / visits"}
    ],
    max_actions=1,
    algorithm="greedy"
)
```

## 🎓 How It Works

### Architecture

```
User Query: "What if we increase visits by 30%?"
    ↓
LLM detects "what if" trigger
    ↓
LLM constructs WhatIfInput:
  - scenario_description: "increase_visits_30pct"
  - derived_metrics: [revenue_per_visit, expenses_per_visit]
  - possible_actions: [scale_proportional visits by 30%]
    ↓
WhatIfTool._execute():
  - Creates WhatIfDSL instance
  - Registers derived metrics
  - Defines possible actions
  - Runs optimizer
    ↓
Optimizer finds best actions:
  - Evaluates each action
  - Checks constraints
  - Calculates objective scores
  - Returns best combination
    ↓
ScenarioResult:
  - Baseline DataFrame
  - Result DataFrame
  - Actions taken
  - Comparison metrics
    ↓
Returns to user:
  - Visualization
  - Comparison table
  - Actions list
  - Verdict
```

### Optimization Algorithms

**Greedy (Default)**:
- Fast and simple
- Evaluates actions one at a time
- Good for 1-5 actions
- Best for: Simple scenarios, quick results

**Genetic**:
- More thorough
- Explores combinations
- Better optimization
- Best for: Complex scenarios with many constraints

## 🔍 Common Use Cases

### 1. Regional Closure Analysis
```python
"What if we close the West and South regions?"
```

### 2. Scaling Operations
```python
"What if we increase visits by 25%?"
"What if we reduce headcount by 10%?"
```

### 3. Cost Optimization
```python
"How can I reduce expenses to 4.5M without revenue dropping more than 8%?"
```

### 4. Profit Maximization
```python
"Find the best way to maximize profit while keeping expenses under 5M"
```

### 5. Rate-Based Analysis
```python
"What if we do 30% more visits in high-revenue regions?"
"How do expenses change if we increase visits by 40%?"
```

## ⚠️ Important Notes

### Data Requirements
- DataFrame must have numeric columns for metrics
- For regional analysis, needs a 'region' column
- For rate-based analysis, needs base column (e.g., 'visits')

### Formula Safety
- Derived metrics use Python `eval()` with sandboxed context
- Only DataFrame columns and numpy are available
- No access to builtins or dangerous functions

### Performance
- Greedy: Very fast, handles 100+ actions
- Genetic: Slower, best with <50 actions
- Large DataFrames (>100k rows) may slow down optimization

## 🧪 Testing

Run the test suite:

```bash
python test_whatif.py
```

Expected output:
```
Running WhatIfTool Tests
======================================================================

1. Testing MetricsCalculator...
   ✅ MetricsCalculator tests passed

2. Testing ScenarioOptimizer...
   ✅ ScenarioOptimizer tests passed

3. Testing WhatIfDSL...
   ✅ WhatIfDSL tests passed

4. Testing Error Handling...
   ✅ Error handling tests passed

5. Testing Integration...
   ✅ Integration tests passed

6. Testing Performance...
   ✅ Performance tests passed

7. Testing WhatIfTool (async)...
   ✅ WhatIfTool tests passed

======================================================================
✅ All tests passed!
```

## 📝 Next Steps

1. **Try the Examples**:
   ```bash
   python example_usage.py
   ```

2. **Integrate with Your Agent**:
   ```python
   from whatif_integration import integrate_whatif_tool
   whatif_tool = integrate_whatif_tool(your_pandas_agent)
   ```

3. **Test with Your Data**:
   - Start with simple scenarios
   - Add derived metrics as needed
   - Use constraints for realistic scenarios

4. **Customize**:
   - Add custom actions in WhatIfDSL
   - Create domain-specific derived metrics
   - Tune optimization parameters

## 🐛 Troubleshooting

### Issue: "DataFrame not found"
**Solution**: Make sure DataFrame is loaded in agent.dataframes

### Issue: "No actions taken"
**Solution**: Constraints too strict or no valid actions. Try:
- Relaxing constraints
- Adding more possible actions
- Using genetic algorithm

### Issue: LLM not invoking tool
**Solution**:
- Check system prompt includes WHATIF_SYSTEM_PROMPT
- Use clear "what if" phrasing
- Verify DataFrames are loaded

### Issue: Slow optimization
**Solution**:
- Use greedy algorithm instead of genetic
- Reduce max_actions
- Reduce action granularity (fewer percentage steps)

## 📚 Additional Resources

- **README_WHATIF.md**: Complete documentation
- **example_usage.py**: Working examples
- **test_whatif.py**: Comprehensive tests
- **whatif_integration.py**: Full implementation with comments

## ✅ Summary

You now have a complete What-If analysis tool that:

1. ✅ Integrates seamlessly with PandasAgent
2. ✅ Responds to natural language queries
3. ✅ Handles derived metrics and rate-based changes
4. ✅ Optimizes with constraints
5. ✅ Provides clear visualizations and comparisons
6. ✅ Caches scenarios for comparison
7. ✅ Is production-ready with error handling and tests

**Start using it now**:
```python
from whatif_integration import integrate_whatif_tool

# One line to enable what-if analysis!
whatif_tool = integrate_whatif_tool(your_pandas_agent)

# Ask questions naturally
response = await your_pandas_agent.ask(
    "What if we increase visits by 30%?"
)
```

Enjoy your new What-If analysis capabilities! 🚀
