---
name: infographic
description: >
  Compose a user-requested descriptive infographic from the currently
  registered Flex datasets using InfographicToolkit's render tools,
  quoting only figures actually computed from the data.
triggers: ["/infographic"]
category: domain
version: "1.0"
---

# /infographic — Descriptive Flex Infographic

You are asked to build a one-off, descriptive infographic (NOT the
published, deterministic `flex-program-dashboard` recipe — that is the
`refresh_dashboard` tool's job). Use the agent's `InfographicToolkit`
render tools directly.

## How to use this skill

1. **Scope the request** — which datasets/KPIs does the user want
   summarized? (e.g. "an infographic of this month's payroll picture",
   "summarize proximity coverage for the CA region").
2. **Gather the data** via the agent's normal tools
   (`python_repl_pandas` over the registered datasets, cleaned through
   `agents/flex_dashboard/normalize.py`, or the registered
   `agents/flex_dashboard/transformers.py` functions when the request
   matches a known KPI — reuse them instead of recomputing).
3. **Render** via one of the `InfographicToolkit` tools:
   - `infographic_render_data_template` / `infographic_render_template` —
     when a registered template fits (list available ones first with
     `infographic_list_templates`).
   - `infographic_build_block` — to assemble ad-hoc structured blocks
     (KPI cards, tables, charts) when no template matches.
   - `infographic_validate_blocks` — validate before rendering to catch
     shape issues early.
4. **Return the render result** (artifact id / URL) to the user along
   with a short caption.

## Hard rules

1. **Quote only figures you actually computed** from the currently loaded
   data for this request — never copy a number from a prior turn or from
   the published dashboard recipe without recomputing it for the current
   scope.
2. **This is tier-1, ad-hoc authoring** — it does NOT publish or modify
   the `flex-program-dashboard` recipe. If the user wants a persistent,
   refreshable dashboard, point them at the recipe/refresh lane instead.
3. Prefer an existing registered `agents/flex_dashboard/transformers.py`
   function over hand-rolled pandas aggregation whenever the request maps
   to a known KPI (same figures, already tested).
