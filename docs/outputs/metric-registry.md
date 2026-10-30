# Metric Definition Registry (FEAT-756)

## What it is

The metric definition registry supplies tenant-scoped KPI definitions with identity,
matching vocabulary, semantics, a declared default display shape, and a source. A
tenant definition shadows the global definition with the same id or alias, so agents
and tools resolve the appropriate metric vocabulary for the active tenant.

## Defining metrics — `metrics.yaml`

Put global definitions in `AGENTS_DIR/<agent_id>/metrics.yaml`. Put tenant definitions
in `AGENTS_DIR/<agent_id>/tenants/<tenant>/metrics.yaml`; their tenant is forced,
`global_only` is stripped, and `visibility: public` is rejected.

```yaml
metrics:
  - id: worked_hours
    name: Worked Hours
    aliases: [hours worked, horas trabajadas, worked hrs]
    example_phrases: ["show me worked hours this month", "cuántas horas trabajamos este mes"]
    unit: h
    format: number
    higher_is_better: null          # tri-state; omit for true
    program: flex
    dimensions:
      - {name: cost center, column: cost_center, aliases: [cc]}
      - {name: pay code, column: pay_code}
    time: {grain: month, default_period: this_month, series_grain: day,
           binding: {start_placeholder: firstdate, end_placeholder: lastdate}}
    comparison: {mode: previous_period}
    default_shape: {component: KPICard, value_column: hours, aggregate: sum}
    source: {kind: query_slug, slug: flex_hours, tenant: null}
```

## Importing the Flex kpi-table

Import a Flex table with `import_kpi_table(markdown, recipe_name=..., recipe_owner=...,
tenant=..., program=..., period_param="month")`. It reads the header `KPI`,
`Transformer`, `Dataset alias(es)`, `Recipe path`, `Output mode`, and `Supported
filters`. KPI names are slugified into ids; recipe paths become `RecipeSource` values;
and transformer and dataset aliases are preserved in the description for lineage.

| kpi-table output mode | Metric default shape |
| --- | --- |
| `KPICard hero` | `KPICardShape(value_column="value", aggregate="none")` |
| `STRUCTURED_CHART` | `ChartShape(line, x="month", y=["value"])` |
| `STRUCTURED_TABLE` | `DataTableShape(columns=[])` |
| `STRUCTURED_MAP` | `MapShape(lat="lat", lon="lon")` |

Supported filters except the period parameter become dimensions. When the period
parameter is present, it becomes the start and end `TimeSpec` binding.

## Output-mode precedence

Output selection is, in order: explicit request, phrasing router, metric default
shape, then agent default. Use the cooperative MRO order below so an explicit phrasing
route can win before the metric fallback:

```python
class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent):
    pass
```

`MetricRoutingMixin` emits the matched metric's component through FEAT-755's
`set_output_shape` hint channel when the phrasing router abstains.

## Tools and MCP

`MetricsToolkit` exposes `list_metrics`, `describe_metric`, `query_metric`, and
`explain_metric`. Add the toolkit to `.parrot/mcp-toolkits.yaml`:

```yaml
metrics:
  class: parrot_tools.metrics.toolkit.MetricsToolkit
  enabled: true
```

Serve it with:

```bash
parrot mcp-local metrics --config .parrot/mcp-toolkits.yaml
```

## REST API

The authenticated REST lane provides `GET /api/v1/metrics` (optionally filtered by
`?program=`), `GET /api/v1/metrics/schema`, and `GET /api/v1/metrics/{metric_id}`.
The latter returns 404 when the metric is absent. `POST /api/v1/metrics` creates a
definition (201; 409 on duplicate); `PUT /api/v1/metrics/{metric_id}` replaces one
(200; 404 when absent). Writes return 401 without a user, 403 when authorization is
insufficient, and 422 for invalid bodies or server-set tenant/owner fields.

## Limitations

Only `query_slug` sources can produce linked surfaces; recipe sources produce baked
envelopes. `semantic_metric` is reserved for FEAT-704: it can be parsed, listed, and
described but is not executable here. The registry starts with the FEAT-224 routing
threshold of 0.85; the M3 Flex-vocabulary sweep result is to be recorded here when
available.
