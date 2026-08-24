# What-If Scenario Analysis

Simulate hypothetical changes to a dataset and measure their impact —
*"what happens if this client's expenses go up 15%?"*, *"how do I cut costs
without losing more than 1% of revenue?"* — through a small declarative DSL
instead of ad-hoc pandas code.

The DSL exists so an **agent** can answer those questions. An LLM writing raw
pandas produces a number you cannot audit, reproduce, or compare against
another scenario. The same question expressed as a scenario produces a named,
re-runnable object with a baseline, an explicit set of actions, a comparison
table, and a result DataFrame registered back in the catalog.

- **Engine + DSL**: `packages/ai-parrot-tools/src/parrot_tools/whatif.py`
- **Agent toolkit**: `packages/ai-parrot-tools/src/parrot_tools/whatif_toolkit.py`
- **Runnable verification**: `examples/data/whatif_scenario_e2e.py`

---

## Contents

1. [When to use it](#when-to-use-it)
2. [Mental model](#mental-model)
3. [Quick start](#quick-start)
4. [Derived metrics](#derived-metrics)
5. [Actions reference](#actions-reference)
6. [Objectives and constraints](#objectives-and-constraints)
7. [Solving a scenario](#solving-a-scenario)
8. [Reading the results](#reading-the-results)
9. [The agent toolkit — 6 tools](#the-agent-toolkit-6-tools)
10. [Wiring it into an agent](#wiring-it-into-an-agent)
11. [Recipes](#recipes)
12. [Semantics worth knowing](#semantics-worth-knowing)
13. [Trust boundary: formulas are code](#trust-boundary-formulas-are-code)
14. [Verifying your setup](#verifying-your-setup)

---

## When to use it

Reach for What-If when the question is **counterfactual** — about a state the
data is not in.

| Question | Fits? |
|---|---|
| "What is our total EBITDA by region?" | No — that is a plain query. Use the pandas REPL. |
| "What if Acme's expenses rise 15%?" | Yes — single-change impact. |
| "What if we drop the Initech account?" | Yes — entity exclusion. |
| "What if visits grow 20% — what happens to revenue?" | Yes — proportional propagation. |
| "How do I hit €2M expenses without revenue falling >5%?" | Yes — constrained optimization. |
| "Which of those two plans is better?" | Yes — scenario comparison. |

The dividing line is simple: **descriptive questions about actual data belong
to the REPL; hypothetical states belong here.** Mixing them is the single most
common integration mistake — see [Wiring it into an agent](#wiring-it-into-an-agent).

### What it gives you

- **A declarative DSL** — describe *what may change*, not how to mutate a frame.
- **Derived metrics** — `ebitda = revenue - payroll - expenses` is recomputed
  after every mutation, so it can never go stale.
- **Constrained optimization** — search for the best combination of changes
  subject to hard limits, via a greedy or exhaustive solver.
- **Named, comparable scenarios** — every run is addressable and can be put
  side by side with another.
- **A result DataFrame** published back to the `DatasetManager`, so follow-up
  questions can query the simulated world.

---

## Mental model

A scenario is five decisions, in order:

```
   dataset          which rows and columns we start from (the baseline)
      │
      ▼
   derived metrics  formulas recomputed after every change (ebitda, margin…)
      │
      ▼
   actions          the menu of changes that are ALLOWED to happen
      │
      ▼
   objectives       what "better" means   ─┐  optional: omit both and the
   constraints      what must never break ─┘  actions are simply applied
      │
      ▼
   solve            pick the combination and produce the result
```

Two properties of this model matter more than any individual method:

**Actions are a menu, not a script.** `can_adjust_metric("expenses", -30, 0)`
does not cut expenses by 30%. It says *"expenses may move anywhere between
-30% and 0%"*, and offers the solver ten candidate percentages for that one
decision. Which one gets used depends on the objectives.

**Without objectives there is nothing to optimize**, so the solver simply
applies the actions it was given, up to `max_actions`. That is the right mode
for a plain *"what if X happens?"* question.

---

## Quick start

### As an agent tool

```python
from parrot.bots.data import PandasAgent
from parrot.clients.factory import LLMFactory
from parrot_tools.whatif_toolkit import integrate_whatif_toolkit

agent = PandasAgent(
    llm=LLMFactory.create(llm="anthropic", model="claude-sonnet-4-5"),
    name="FinOpsAnalyst",
    df={"clients": clients_df},
)

# Registers all 6 tools AND injects the usage instructions into the prompt.
integrate_whatif_toolkit(agent)
await agent.configure()

answer = await agent.ask(
    "What if the client Acme increases its expenses by 15%? "
    "EBITDA is revenue - payroll - expenses."
)
```

### Programmatically, with the DSL

```python
from parrot_tools.whatif import WhatIfDSL

scenario = (
    WhatIfDSL(clients_df, name="acme_expenses_up_15")
    .register_derived_metric("ebitda", "revenue - payroll - expenses")
    .initialize_optimizer()
    .can_scale_entity(
        entity_column="customer",
        target_columns=["expenses"],
        entities=["Acme"],
        min_pct=15,
        max_pct=15,
    )
)
result = scenario.solve(max_actions=1)

print(result.visualize())
print(result.result_df)          # the mutated dataset
print(result.compare()["metrics"]["ebitda"])
```

> `initialize_optimizer()` must be called **after** registering derived
> metrics and **before** `solve()`. It snapshots the baseline that every
> later comparison is measured against.

---

## Derived metrics

A derived metric is a formula over the DataFrame's columns, recomputed from
scratch on every mutated frame. This is what keeps a simulation coherent: if
you scale `expenses`, `ebitda` follows automatically.

```python
dsl.register_derived_metric("ebitda", "revenue - payroll - expenses")
dsl.register_derived_metric("margin", "(revenue - expenses) / revenue")
dsl.register_derived_metric("cost_per_head", "expenses / headcount")
```

The formula is a Python expression evaluated with the DataFrame's columns in
scope (vectorised — each name is a `Series`), plus `np` for numpy functions.
Derived metrics appear in comparison tables and can be used as objectives and
constraints exactly like real columns.

**Model them rather than precomputing them.** A column you compute yourself
before building the scenario becomes stale the moment an action changes its
inputs, and nothing will warn you.

### The `_per_` naming convention

`can_scale_proportional` propagates a change from a base column to other
columns by looking up a derived metric named **`<affected>_per_<base>`**. The
name is the wiring — get it wrong and the affected columns silently do not move:

```python
dsl.register_derived_metric("revenue_per_visits",  "revenue / visits")
dsl.register_derived_metric("expenses_per_visits", "expenses / visits")

dsl.can_scale_proportional(
    base_column="visits",
    affected_columns=["revenue", "expenses"],   # revenue_per_visits, expenses_per_visits
    min_pct=20, max_pct=20,
)
```

Note the plural: the base column is `visits`, so the metric must be
`revenue_per_visits`, not `revenue_per_visit`.

---

## Actions reference

Five action families. Each `can_*` call registers a *menu of alternatives* for
**one decision**; the solver picks at most one entry per menu.

### `can_scale_entity` — change one entity's numbers

The workhorse for client/project/product questions.

```python
dsl.can_scale_entity(
    entity_column="customer",        # column identifying the entity
    target_columns=["expenses"],     # which numbers move
    entities=["Acme"],               # None = every unique value
    min_pct=15, max_pct=15,          # fixed 15%; a range offers alternatives
)
```

Scales only the matching rows. Different entities are independent decisions,
so "Acme +15% **and** Umbrella +15%" is two actions and both apply.

### `can_adjust_metric` — move a whole column, optionally per group

```python
dsl.can_adjust_metric("expenses", min_pct=-30, max_pct=0, group_by="customer")
```

Without `group_by` the whole column scales. With it, each group becomes its
own decision — which is what makes *"find the best per-client cut"* possible.

### `can_scale_proportional` — propagate a driver

```python
dsl.can_scale_proportional(
    base_column="visits",
    affected_columns=["revenue", "expenses"],
    min_pct=-50, max_pct=100,
    group_by=None,
)
```

Scales `base_column`, then recomputes each affected column as
`new_base × <affected>_per_<base>`. Requires those derived metrics — see above.

### `can_exclude_values` — drop rows

```python
dsl.can_exclude_values("customer", ["Initech"])     # None = offer every value
```

Each value is an **independent** action, so excluding two regions applies both.
The solver refuses an action that would empty the DataFrame.

### `can_close_regions` — exclusion, hardcoded to `region`

```python
dsl.can_close_regions(["North"])       # None = every region
```

Convenience wrapper that only works on a column literally named `region`. For
any other column use `can_exclude_values`, which is the general form.

---

## Objectives and constraints

Objectives say what "better" means. Constraints say what must never break.

```python
dsl.minimize("expenses", weight=1.0)
dsl.maximize("ebitda", weight=2.0)          # higher weight = more important
dsl.target("expenses", 2_000_000, weight=2.0)   # get as close as possible

dsl.constrain_change("revenue", max_pct=5.0)         # |Δ%| must stay ≤ 5%
dsl.constrain_min("headcount", 1500)                 # absolute floor
dsl.constrain_max("expenses", 4_500_000)             # absolute ceiling
dsl.constrain_ratio("expenses", "revenue", 0.60)     # expenses/revenue ≤ 0.60
```

Objectives and constraints accept **derived metrics** as freely as real
columns. All comparisons are on the **column sum** across the frame.

Constraints are hard: a candidate that violates one is discarded outright, not
penalised. If every candidate violates a constraint, the solver applies nothing
and returns the baseline — an empty action list is a meaningful answer meaning
*"no allowed change satisfies your requirements."*

---

## Solving a scenario

```python
result = dsl.solve(max_actions=3, algorithm="greedy")
```

| Parameter | Meaning |
|---|---|
| `max_actions` | Maximum number of **decisions** applied. Use `1` for a single-change what-if. |
| `algorithm` | `"greedy"` (default) or `"genetic"`. |

**`greedy`** adds one action at a time, each time taking the one that improves
the objective most, stopping when nothing improves. Fast; the default; good
enough for most questions.

**`genetic`** despite the name is an exhaustive search over all combinations up
to `max_actions`. It finds better optima but the cost grows combinatorially —
keep `max_actions` small and the action menu tight.

With **no objectives and no constraints**, both paths reduce to "apply the
actions given, up to `max_actions`", which is the plain what-if mode.

---

## Reading the results

`solve()` returns a `ScenarioResult`:

| Member | What it holds |
|---|---|
| `result_df` | The mutated DataFrame — the simulated world. |
| `base_df` | The untouched baseline. |
| `actions` | The actions actually applied (may be fewer than offered). |
| `compare()` | `dict` with per-metric `value`, `change`, `pct_change`. |
| `visualize()` | Human-readable before/after summary. |

```python
metrics = result.compare()["metrics"]
metrics["ebitda"]["value"]       # scenario total
metrics["ebitda"]["change"]      # absolute delta vs baseline
metrics["ebitda"]["pct_change"]  # percentage delta
```

Through the toolkit, `simulate` renders this as a markdown table:

```
| Metric   | Baseline     | Scenario     | Change      | % Change |
|----------|--------------|--------------|-------------|----------|
| revenue  | 7,195,000.00 | 7,195,000.00 | +0.00       | +0.00%   |
| expenses | 2,180,000.00 | 2,232,500.00 | +52,500.00  | +2.41%   |
| ebitda   | 2,565,000.00 | 2,512,500.00 | -52,500.00  | -2.05%   |
```

---

## The agent toolkit — 6 tools

`WhatIfToolkit` exposes the engine as six LLM-callable tools: one fast path and
a five-step workflow for anything that needs optimization.

```
quick_impact                                   ← one call, one change

describe_scenario → add_actions → set_constraints → simulate → compare_scenarios
                                   (optional)
```

### `quick_impact` — the fast path

One call, one change, immediate before/after. Use it for *"what if X?"* with no
optimization involved.

| Argument | Meaning |
|---|---|
| `df_name` | Dataset name **or alias** (`df1`). |
| `action_description` | Natural-language label for the output. |
| `action_type` | `scale_entity`, `adjust_metric`, `scale_proportional`, `exclude_values`, `close_region`. |
| `target` | Column or entity the action acts on. |
| `parameters` | Action-specific; may carry `derived_metrics` inline. |

```python
await toolkit.quick_impact(
    df_name="clients",
    action_description="Acme expenses +15%",
    action_type="scale_entity",
    target="customer",
    parameters={
        "entity_column": "customer",
        "entities": ["Acme"],
        "target_columns": ["expenses"],
        "min_pct": 15, "max_pct": 15,
        "derived_metrics": [
            {"name": "ebitda", "formula": "revenue - payroll - expenses"}
        ],
    },
)
```

### `describe_scenario` — open a scenario

Resolves the dataset, validates every derived-metric formula against it, and
returns a `scenario_id` plus a column inventory (types, sums, cardinalities) so
the model can plan its actions against something real instead of guessing.

Invalid formulas and unknown datasets raise here — early, with an error message
that lists what *is* available.

### `add_actions` — declare what may change

Takes `WhatIfAction` entries (`type`, `target`, `parameters`). Each is validated
against the frame's schema; invalid ones are reported individually with the
reason (`Column 'x' not found. Available: [...]`, `Column 'region' is not
numeric`) while the valid ones are still accepted. That feedback is what lets a
model correct itself without a round trip through an exception.

### `set_constraints` — optional; declare intent

Objectives and constraints, validated against columns and derived metrics.
Unknown metric names are reported as warnings rather than failing the call.

**Declaring objectives has a second effect**: it is the only thing that tells
`compare_scenarios` which direction is better for each metric.

### `simulate` — run it

Executes the scenario, renders the comparison table, describes the actions
applied in plain language, and registers the result DataFrame in the
`DatasetManager` under `whatif_<scenario_id>_result`.

> Pass `max_actions=1` for single-change questions. The default is `5`.

### `compare_scenarios` — put them side by side

```
| Metric              | sc_1         | sc_2           | Best |
|---------------------|--------------|----------------|------|
| revenue             | 7,195,000.00 | 7,195,000.00   | n/a  |
| expenses (minimize) | 2,232,500.00 | 2,145,000.00 ^ | sc_2 |
| ebitda (maximize)   | 2,512,500.00 | 2,637,000.00 ^ | sc_2 |
```

Ranking comes **only** from objectives declared via `set_constraints`. A metric
with no declared direction is shown but marked `n/a`, with a footnote saying so.
This is deliberate: a metric has no inherent polarity — more revenue is good,
more expenses is not — and guessing from the name would mis-rank anything
unusually named. If you want costs ranked, declare `minimize`.

---

## Wiring it into an agent

```python
from parrot_tools.whatif_toolkit import integrate_whatif_toolkit

toolkit = integrate_whatif_toolkit(agent)
```

One call does both halves: registers the six tools **and** injects
`WHATIF_TOOLKIT_SYSTEM_PROMPT` into the agent's system prompt.

Both halves matter. Tools without instructions are six terse docstrings with no
hint that `describe_scenario` chains into `add_actions` and `simulate`; a model
that cannot see the workflow falls back to whatever general-purpose tool it
already trusts — usually the pandas REPL.

### Prompt injection is not one mechanism

Agents assemble their system prompt in mutually exclusive ways, and they are
**not interchangeable**. `PandasAgent` renders from `PromptBuilder` layers via
`_build_prompt()`; it does not read `system_prompt_template`, and even the
`system_prompt=` constructor argument does not reach the rendered prompt.

`inject_whatif_system_prompt()` handles this by trying mechanisms in order of
specificity and **reporting which one applied**:

```python
from parrot_tools.whatif_toolkit import inject_whatif_system_prompt

mechanism = inject_whatif_system_prompt(agent, MY_PROMPT)
# "add_system_prompt" | "prompt_builder" | "system_prompt_template" | None
```

`None` means nothing was injected; `integrate_whatif_toolkit` logs a warning in
that case rather than returning a toolkit that looks wired up but is not.

> **If a model seems to ignore an instruction, assert the instruction is
> actually in the rendered prompt before concluding anything about the model.**
> Check `agent._build_prompt()`, not the attribute you assigned to.

### Routing: keeping the REPL out of hypotheticals

Inside a `PandasAgent` the toolkit competes with `python_repl_pandas`, which can
technically compute any scenario — badly, unauditably, and without producing a
comparable scenario object. An explicit routing rule settles it:

```python
ROUTING_POLICY = """
## MANDATORY ROUTING RULE FOR HYPOTHETICAL QUESTIONS

Any question about a hypothetical change to the data ("what if ...?",
"simulate ...", "impact of ...") MUST be answered with the what-if toolkit:

  * one single change              -> `quick_impact`
  * optimization under constraints -> `describe_scenario` -> `add_actions`
                                      -> `set_constraints` -> `simulate`

Do NOT reproduce a scenario with `python_repl_pandas`. The REPL is only for
descriptive questions about the data as it actually is.
"""

inject_whatif_system_prompt(
    agent, f"{WHATIF_TOOLKIT_SYSTEM_PROMPT}\n\n{ROUTING_POLICY}"
)
```

With the rule genuinely delivered, Claude Sonnet 4.5 routes every hypothetical
to the toolkit and does not touch the REPL — measured in
`examples/data/whatif_scenario_e2e.py --llm`.

### Datasets: names and aliases

`df_name` accepts the real dataset name, its `DatasetManager` alias (`df1`,
`df2` — the names `PandasAgent` advertises to the model), or a differently-cased
name. Resolution always returns the **canonical** name, so result datasets and
labels stay stable. An unknown name raises with the available names *and* their
aliases listed.

The toolkit finds its datasets through, in order: its own `DatasetManager`, the
parent agent's (including `PandasAgent`'s private `_dataset_manager`), and
finally the agent's `dataframes` registry.

---

## Recipes

### Single-change impact

```python
await toolkit.quick_impact(
    df_name="clients",
    action_description="Acme expenses +15%",
    action_type="scale_entity", target="customer",
    parameters={"entity_column": "customer", "entities": ["Acme"],
                "target_columns": ["expenses"], "min_pct": 15, "max_pct": 15,
                "derived_metrics": [{"name": "ebitda",
                                     "formula": "revenue - payroll - expenses"}]},
)
```

### Optimization under constraints

> *"Cut expenses per client to maximize EBITDA, without revenue falling >1%."*

```python
sid = parse_id(await toolkit.describe_scenario(
    "clients", "cut expenses, protect revenue",
    [DerivedMetric(name="ebitda", formula="revenue - payroll - expenses")],
))
await toolkit.add_actions(sid, [WhatIfAction(
    type="adjust_metric", target="expenses",
    parameters={"min_pct": -30, "max_pct": 0, "group_by": "customer"},
)])
await toolkit.set_constraints(
    sid,
    objectives=[WhatIfObjective(type="maximize", metric="ebitda", weight=2.0)],
    constraints=[WhatIfConstraint(type="max_change", metric="revenue", value=1.0)],
)
print(await toolkit.simulate(sid, max_actions=3))
```

The solver picks a percentage per client, never exceeding the declared -30%
floor, and discards any combination that moves revenue more than 1%.

### Losing an account

```python
parameters={"column": "customer", "values": ["Initech"]}   # action_type="exclude_values"
```

### Growth propagated from a driver

```python
# needs revenue_per_visits and expenses_per_visits registered
parameters={"affected_columns": ["revenue", "expenses"], "min_pct": 20, "max_pct": 20}
# action_type="scale_proportional", target="visits"
```

### Best-case vs worst-case

Build two scenarios, declare the same objectives on both, `simulate` each, then
`compare_scenarios([a, b])`. Without objectives the comparison shows values but
ranks nothing.

---

## Semantics worth knowing

Sharp edges that are easy to get wrong. Each is asserted in the test suite.

### `max_actions` counts decisions, not percent steps

The ten candidate percentages a `can_*` call generates are **alternatives for
one decision**, not steps that stack. The solver takes at most one per menu, so
a fixed `min_pct == max_pct` is applied exactly once regardless of `max_actions`,
and an optimizer working over a `-30%…0%` range can never compound two
candidates into `-48.7%`.

Independent decisions still stack: two different entities, two different groups,
or two `exclude_values` all apply together.

### An empty action list is an answer

If constraints rule out every candidate, `solve()` returns zero actions and the
baseline unchanged. That means *"nothing allowed satisfies this"* — not a bug.

### Comparisons are on sums

Every objective, constraint, and comparison uses the **column sum** across the
frame. `constrain_min("headcount", 1500)` is a floor on the total, not per row.

### "Best" needs a declared direction

`compare_scenarios` ranks only metrics with an objective. See
[compare_scenarios](#compare_scenarios-put-them-side-by-side).

### Result datasets

`simulate` registers `whatif_<scenario_id>_result`, and `quick_impact`
registers `whatif_quick_<action_type>_result`; both report the name only when
registration actually succeeded, so a name in the output is always queryable.
A catalog failure is logged and costs you the registration, never the analysis.

### `can_close_regions` is column-specific

It only works on a column literally named `region`. Use `can_exclude_values`
otherwise.

### Always pass `min_pct`/`max_pct` explicitly

Defaults differ between action types and between the DSL and the toolkit
(`scale_entity` defaults are not the same on both paths). Being explicit costs
one keyword and removes the question entirely.

---

## Trust boundary: formulas are code

Derived-metric formulas are evaluated with Python's `eval`. Builtins are
stripped, so `__import__(...)` fails — but `np` is deliberately in scope, and
attribute traversal from a module object can reach interpreter internals. **This
is a soft sandbox, not a hard one.**

In the normal setup this is acceptable: formulas come from your agent's LLM,
which you already trust to execute pandas code. It stops being acceptable when
formula strings can be influenced by an untrusted party — end users typing
directly into a scenario builder, or dataset contents that a prompt-injection
payload could steer.

If that is your situation, validate formulas against an allowlist of column
names and operators before they reach `register_derived_metric`, and treat the
scenario tools with the same care as the Python REPL tool.

---

## Verifying your setup

`examples/data/whatif_scenario_e2e.py` is an executable specification. Every
number it prints is checked against ground truth computed with plain pandas, so
it fails loudly if the engine regresses.

```bash
source .venv/bin/activate

# deterministic stages — no API key, no network
python examples/data/whatif_scenario_e2e.py

# add the natural-language round trip through a real LLM
python examples/data/whatif_scenario_e2e.py --llm
python examples/data/whatif_scenario_e2e.py --llm --provider google --model gemini-2.5-pro

# one stage at a time
python examples/data/whatif_scenario_e2e.py --stage dsl
```

It covers four layers: the DSL alone, the six tools called programmatically,
the integration edges (result registration, alias resolution, compounding,
ranking), and a live agent answering in natural language — asserting not just
that the answer is right but that the toolkit was the thing that produced it.

Exit code is 0 only when every check passes, so it works as a smoke test in CI.

### Unit tests

```bash
pytest packages/ai-parrot-tools/tests/test_whatif.py \
       packages/ai-parrot-tools/tests/test_whatif_resolution.py \
       packages/ai-parrot-tools/tests/test_whatif_compounding.py \
       packages/ai-parrot-tools/tests/test_whatif_compare.py \
       packages/ai-parrot-tools/tests/test_whatif_integration.py \
       packages/ai-parrot-tools/tests/test_whatif_result_registration.py
```

> `ai-parrot` and `ai-parrot-tools` both ship a `tests` package, so their test
> trees cannot be collected in a single pytest invocation. Run them separately.

---

## API summary

### `WhatIfDSL`

| Method | Purpose |
|---|---|
| `register_derived_metric(name, formula, description="")` | Add a recomputed metric. |
| `initialize_optimizer()` | Snapshot the baseline. After metrics, before solving. |
| `minimize(metric, weight=1.0)` / `maximize(...)` | Directional objective. |
| `target(metric, value, weight=1.0)` | Aim for a specific total. |
| `constrain_change(metric, max_pct)` | Limit percentage movement. |
| `constrain_min(metric, min_value)` / `constrain_max(...)` | Absolute bounds. |
| `constrain_ratio(metric, reference, max_ratio)` | Cap a ratio between metrics. |
| `can_scale_entity(entity_column, target_columns, entities=None, min_pct=-100, max_pct=100)` | Scale specific entities' numbers. |
| `can_adjust_metric(metric, min_pct=-50, max_pct=50, group_by=None)` | Move a column, optionally per group. |
| `can_scale_proportional(base_column, affected_columns, min_pct=-50, max_pct=100, group_by=None)` | Propagate from a driver. |
| `can_exclude_values(column, values=None)` | Drop rows by value. |
| `can_close_regions(regions=None)` | Exclusion on a `region` column. |
| `solve(max_actions=5, algorithm="greedy")` | Run it; returns `ScenarioResult`. |

### `WhatIfToolkit`

| Tool | Signature |
|---|---|
| `quick_impact` | `(df_name, action_description, action_type, target, parameters=None)` |
| `describe_scenario` | `(df_name, scenario_description, derived_metrics=None)` |
| `add_actions` | `(scenario_id, actions)` |
| `set_constraints` | `(scenario_id, objectives=None, constraints=None)` |
| `simulate` | `(scenario_id, algorithm="greedy", max_actions=5)` |
| `compare_scenarios` | `(scenario_ids)` |

### Type vocabulary

| Kind | Accepted values |
|---|---|
| Action `type` | `scale_entity`, `adjust_metric`, `scale_proportional`, `exclude_values`, `close_region` |
| Objective `type` | `minimize`, `maximize`, `target` |
| Constraint `type` | `max_change`, `min_value`, `max_value`, `ratio` |
| `algorithm` | `greedy`, `genetic` |

---

## See also

- `examples/data/whatif_scenario_e2e.py` — executable verification of everything above.
- [DatasetManager design](datasetmanager_design.md) — the catalog scenarios read from and write to.
- [PandasAgent capabilities](pandas-agent-capabilities.md) — the agent this toolkit most often plugs into.
