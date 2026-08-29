# A2UI dashboards from an agent

A layer-by-layer walkthrough of how an AI-Parrot agent answers with an
**A2UI v1.0** dashboard surface: `InfographicToolkit` produces the envelope,
`OutputMode.A2UI` routes it, and the A2UI renderers turn it into HTML.

Everything runs on seeded synthetic data — no database, no network, no LLM by
default, no API key. One run takes a few seconds, and because the data is seeded
and the block-to-component mapping is pure, the surface *content* is identical
on every run — only `surfaceId` varies, since it is derived from the id of the
artifact persisted that run. That makes this usable as a smoke test for the wire
format as well as a teaching example.

```bash
source .venv/bin/activate

python examples/agents/a2ui/a2ui_dashboard_walkthrough.py           # the walkthrough
python examples/agents/a2ui/a2ui_dashboard_walkthrough.py --open    # + serve and open it
python examples/agents/a2ui/a2ui_dashboard_walkthrough.py --live    # let the LLM drive
```

## Files

| File | What it is |
|---|---|
| `a2ui_dashboard_walkthrough.py` | The walkthrough. Read it top to bottom. |
| `deterministic_refresh_dashboard.py` | The companion sample: deterministic recipe replay + FEAT-469 inline filtering/refresh (see below). |
| `synthetic_data.py` | Seeded synthetic SaaS revenue-ops data (`numpy` + `pandas` only). |

Output lands in `artifacts/a2ui_dashboard/`:

| Artifact | What it shows |
|---|---|
| `01_infographic_template.html` | The template lane — HTML rendered by the infographic template. |
| `02_envelope_v1.json` | The A2UI v1.0 wire envelope. **This is the interesting file.** |
| `03_baked_components.json` | The same surface lowered to Basic primitives and baked flat. |
| `04_surface_static.html` | `ssr_html` — no JavaScript, charts/tables degraded to text. |
| `05_surface_interactive.html` | `interactive-html` — real Chart.js charts, sortable table. |
| `06_live_envelope.json` | `--live` only: the envelope the LLM's own render produced. |

## The eight steps

1. **The agent** — `PandasAgent` + `InfographicToolkit(emit_a2ui=True)`.
2. **The contract** — the `dashboard` template's *positional* block contract.
3. **The blocks** — six typed, semantic blocks built from a DataFrame.
4. **The render** — one call, two surfaces: an HTML artifact **and** an envelope.
5. **The wire** — the A2UI v1.0 envelope-by-key (FEAT-470).
6. **Lowering** — the Parrot `Infographic` composite becomes 53 Basic primitives.
7. **Baking** — `{"path": ...}` bindings resolve; 53 components become 119.
8. **Renderers** — the same surface rendered two different ways.

## What makes an agent emit A2UI

Two things, and you need both:

```python
# 1. the toolkit must be built with emit_a2ui=True — and passed in explicitly.
#    InfographicAuthoringMixin will build one for you from artifact_store=,
#    but that auto-built toolkit defaults to emit_a2ui=False.
toolkit = InfographicToolkit(artifact_store=store, emit_a2ui=True)
agent = A2UIDashboardAgent(name="…", df=frames, infographic_toolkit=toolkit)

# 2. the caller must ask in A2UI mode.
response = await agent.ask(question, output_mode=OutputMode.A2UI)
response.a2ui_envelope   # the declarative surface
response.output_mode     # OutputMode.A2UI
```

`BaseBot` spots the `InfographicRenderResult` among the turn's tool calls, sees
it carries an `a2ui_envelope`, and hands it to `finalize_a2ui_response`
(`parrot/outputs/a2ui/emission.py`), which bypasses the legacy `OutputFormatter`
entirely. If the LLM answers in prose without rendering anything, the mode is
downgraded to `DEFAULT` rather than dispatched to a renderer with nothing to
render.

The A2UI lane is **additive**: if envelope construction fails, the toolkit logs
it and returns `a2ui_envelope=None`, and you still get the HTML artifact.

## The envelope is the wire

`InfographicRenderResult.a2ui_envelope` — and therefore `response.a2ui_envelope` —
is the finished A2UI v1.0 envelope: `{"version": "v1.0", "createSurface": {...}}`
with camelCase aliases. Hand it straight to `Artifact.from_a2ui_envelope` or an
external renderer; no re-shaping at the boundary. Step 5 asserts exactly that.

> Before this example landed, both toolkits emitted a bare
> `model_dump(mode="json")` (snake_case, no `version` wrapper), which
> `Artifact.from_a2ui_envelope` rejected outright — so any agent putting one of
> these surfaces on A2A was broken. Fixed in `infographic_toolkit.py` /
> `interactive_toolkit.py`, along with the doubled surface id
> (`infographic-infographic-<hex>`) and `PandasAgent`'s missing A2UI routing.

## If the LLM gets the blocks wrong

The template contract (step 2) declares block *types* and counts, but not each
block model's *fields*. A model handed a DataFrame writes **row records**, not
the column-oriented `labels` + `series[].values` / `columns` + `rows` that
`ChartBlock` and `TableBlock` declare. Three things now keep that from costing
you the render:

- **Record shapes are accepted.** `ChartBlock` and `TableBlock` normalize
  `data`/`rows` records into their canonical form (`ChartBlock` also accepts
  `series[].data` for `series[].values`, and honours an explicit `x_field`).
  So `{"type": "chart", "data": [{"month": "Dec", "mrr": 1.2}]}` just works.
- **`infographic_build_block` is still the reliable path.** It derives chart and
  table blocks from a DataFrame in the REPL (`label_column`, `value_columns`,
  `table_columns`), so the field names cannot be wrong at all. `--live`'s prompt
  spells out all six calls.
- **Errors are actionable.** A block that is genuinely unusable comes back as
  `{"ok": false, "code": "BLOCK_SCHEMA_INVALID", "detail": {...}}` naming the
  offending field, which the model can retry against — it used to escape as a
  raw pydantic `ValidationError` that failed the tool call outright.

## The companion sample: deterministic refresh + inline filtering

`deterministic_refresh_dashboard.py` picks up where this walkthrough stops:
instead of a display-only surface, it publishes a **deterministic recipe**
(FEAT-324/326 — the lane that grew out of the standalone
`documents/flex_program_report.html` report) and then drives the **FEAT-469
RPC leg** against it:

```bash
python examples/agents/a2ui/deterministic_refresh_dashboard.py           # all lanes
python examples/agents/a2ui/deterministic_refresh_dashboard.py --serve   # + open in browser
```

Its seven lanes: (1) `publish_recipe` maps sections onto registered
`@infographic_transformer`s and declares the `window`/`plan` filter params;
(2) `RecipeRunner.run()` replays twice — identical content (the deterministic-
refresh guarantee, with undeclared-override typo protection); (3) an `action`
envelope pushes the surface's inline filter state as `dataModel`; (4)
`callAgentFunction` invokes the agent's `refresh_dashboard` tool for a
filtered re-render; (5) the same tool refreshes *from the persisted surface
state* via `current_a2ui_surface_state()`; (6) `callRendererFunction` /
`rendererFunctionResponse` round-trips an agent-initiated call; (7)
`export_functions` / `agent_capabilities` show the discovery documents,
including the `a2ui_hidden = True` opt-out.

Output lands in `artifacts/a2ui_deterministic_refresh/`.

## See also

- `docs/outputs/a2ui-v1.md` — the v1.0 wire, the two catalogs, `lower()`, baking.
- `docs/migration/feat-273-a2ui-deprecations.md` — the dialect → v1.0 migration.
- `docs/toolkits/infographic_toolkit.md` — the toolkit's full tool surface.
- `examples/simple_infographic_agent.py` — the recipe / deterministic-replay
  lane (`publish_recipe` + `RecipeRunner`) this example deliberately skips.
