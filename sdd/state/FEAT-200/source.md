---
kind: inline
jira_key: null
fetched_at: 2026-05-28T18:00:00+02:00
summary_oneline: "Move outputs/formats to ai-parrot-visualizations with PEP 420 namespace merging"
---

# Source — ai-parrot-visualizations (enriched)

Move `outputs/formats` to a new package `ai-parrot-visualizations` with PEP 420
support as the existing new package `ai-parrot-embeddings`.

The concrete renderer backends (matplotlib, seaborn, plotly, altair, bokeh,
holoviews, d3, echarts, map, infographic, generators, mixins) should be extracted
to a satellite package that contributes to the `parrot.outputs.formats` namespace
via PEP 420 implicit namespace packages — the same pattern used by
`ai-parrot-embeddings` for `parrot.embeddings`, `parrot.stores`, and
`parrot.rerankers`. Import paths must remain unchanged.

## Decisions (resolved during proposal)

- **Discovery**: PEP 420 + extend_path(). No entry-points.
- **Core scope**: Only zero-dep renderers stay (json, yaml, html, table).
- **Phasing**: Big-bang single PR.
- **Namespace**: `parrot.outputs.formats` via PEP 420 (not `parrot_visualizations`).
