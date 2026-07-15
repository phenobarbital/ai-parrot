---
type: Wiki Summary
title: parrot_loaders.ocr.layout
id: mod:parrot_loaders.ocr.layout
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Heuristic layout analyzer for parrot_loaders.
relates_to:
- concept: class:parrot_loaders.ocr.layout.HeuristicLayoutAnalyzer
  rel: defines
- concept: func:parrot_loaders.ocr.layout.render_markdown
  rel: defines
- concept: mod:parrot_loaders.ocr.models
  rel: references
---

# `parrot_loaders.ocr.layout`

Heuristic layout analyzer for parrot_loaders.

Converts a flat list of :class:`OCRBlock` objects into a structured
:class:`LayoutResult` using pure geometry-based heuristics.

Stages
------
1. **Line grouping** — cluster blocks whose y-centres are within
   ``line_threshold`` pixels of each other.
2. **Header detection** — mark a line as a header when its text is
   significantly larger than average, or it is written in ALL CAPS.
3. **Table detection** — identify 3+ consecutive lines whose column
   x-positions are vertically aligned.
4. **Column detection** — count how many visual columns are present.

The :func:`render_markdown` function converts a :class:`LayoutResult` into
a clean Markdown string.

## Classes

- **`HeuristicLayoutAnalyzer`** — Geometry-based layout analyzer that requires no ML model.

## Functions

- `def render_markdown(layout: LayoutResult) -> str` — Convert a :class:`LayoutResult` into a Markdown string.
