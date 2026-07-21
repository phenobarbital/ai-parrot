---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.report
id: mod:parrot.outputs.a2ui.catalog.components.report
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI ``Report`` composite catalog component (Module 3).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.report.ReportComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.report`

A2UI ``Report`` composite catalog component (Module 3).

Report is a narrative, section-structured document: title/metadata, an ordered list
of sections (heading + rich text + optional embedded catalog components + tables),
and an optional summary. Vocabulary is inspired by the legacy
``TemplateReportRenderer`` (dict/dataclass context flattened into a narrative
template) — inspiration only, no code reuse. Display-only (``requires_actions=False``).

Nested catalog children are lowered through the registry (delegation), keeping the
composite lowering deterministic.

## Classes

- **`ReportComponent`** — The ``Report`` composite catalog component (display-only).
