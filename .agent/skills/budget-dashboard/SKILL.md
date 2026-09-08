---
name: budget-dashboard
description: >
  Render a published, deterministic budget-variance profile — the
  `budget-variance-dashboard` (visual KPIs) or `budget-variance-report`
  (narrative-first executive summary) recipe — through the
  `refresh_dashboard` agent function. Bare `/dashboard` renders the
  dashboard profile.
triggers: ["/dashboard"]
category: domain
version: "1.0"
---

# /dashboard — Render a Published Budget-Variance Profile

You are asked to render THE dashboard — one of the two profiles this agent
already declares in `agents/finance_reporter.py` and publishes as recipes:

| Profile | Recipe name | What it is |
|---|---|---|
| `dashboard` (default) | `budget-variance-dashboard` | Visual-first `Infographic`: KPI cards and variance charts. |
| `report` | `budget-variance-report` | Narrative-first `Report`: executive summary prose over the same facts. |

This is a deterministic replay of a published recipe, NOT an authoring
task: you do not choose sections, you do not choose charts, and you do not
compute any number yourself.

## How to use this skill

1. **Pick the profile** from the user's words. Default to `"dashboard"`.
   Route to `"report"` only when the user explicitly asks for the report,
   the executive summary, or the narrative version.
2. **Call `refresh_dashboard(profile=...)` exactly once.** That is the whole
   job. The tool replays the recipe server-side and returns
   `{"profile": "…", "recipe": "…", "artifact_id": "…", "bytes": N}`.
3. **Report the result** to the user: which profile was rendered and the
   `artifact_id`. One short sentence — the artifact is the answer, not your
   prose.

Examples of correct calls:

- `/dashboard` → `refresh_dashboard(profile="dashboard")`
- `/dashboard report` → `refresh_dashboard(profile="report")`
- `/dashboard give me the executive summary` →
  `refresh_dashboard(profile="report")`

## There are no filters

`refresh_dashboard` takes `profile` and nothing else, by design: neither
finance recipe declares any `RecipeParam`, so there is nothing to filter
on. A bare re-run is still meaningful — every data source replays with
`force_refresh=True`, so it pulls fresh rows from
`troc.finance_projection`.

If the user asks to scope the dashboard (one division, one project, a date
range), do NOT invent a filter argument and do NOT pre-filter a dataset
yourself. Say plainly that the published profiles are unscoped, render the
full profile, and offer the scoped figures as a separate, ordinary
data question.

## Hard rules

1. **Never recompute anything.** Do not open `python_repl_pandas`, do not
   fetch `snapshots`, do not call a transformer directly. The recipe replay
   computes every figure through the registered finance transformers
   already.
2. **Never hand-assemble the layout.** Do not call the `InfographicToolkit`
   render tools (`infographic_build_block`, `infographic_render_template`,
   …) for this skill — the published recipe owns the layout verbatim.
3. **Never call `refresh_dashboard` more than once per request.** If the
   user wants both profiles, render them as two explicit, separate turns.
4. **`refresh_dashboard` returns an artifact reference, not a renderable
   envelope.** Do not try to inline its bytes. Hand the `artifact_id` back;
   the frontend re-fetches the surface (or uses the ui_surfaces refresh
   route) to display it. Persisting a bookmarkable surface row is a
   separate backend call (`publish_profile_surface`), not yours to make.
5. **If `refresh_dashboard` is not among your available tools, say so
   plainly and stop.** Do not fall back to an ad-hoc pandas aggregation or
   a hand-built infographic — an approximation of the published profile is
   worse than a clear "not available", because it looks like the real
   thing. The tool is registered only when the backend calls
   `agent.build_refresh_tool(pctx)` with a real `PermissionContext`, and
   the profile's recipe must have been published
   (`publish_dashboard_recipe()` / `publish_report_recipe()`). Report which
   of the two is missing if you can tell.
