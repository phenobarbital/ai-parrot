---
type: Wiki Summary
title: parrot.tools.excel_intelligence
id: mod:parrot.tools.excel_intelligence
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ExcelIntelligenceToolkit — LLM-callable tools for Excel file analysis.
relates_to:
- concept: class:parrot.tools.excel_intelligence.ExcelIntelligenceToolkit
  rel: defines
- concept: mod:parrot.tools.dataset_manager.excel_analyzer
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.excel_intelligence`

ExcelIntelligenceToolkit — LLM-callable tools for Excel file analysis.

Wraps :class:`ExcelStructureAnalyzer` and exposes three async tools:

* ``inspect_workbook`` — structural map of sheets and tables
* ``extract_table`` — clean tabular data for a specific table
* ``query_cells`` — raw cell values for arbitrary ranges

## Classes

- **`ExcelIntelligenceToolkit(AbstractToolkit)`** — Toolkit for intelligent Excel file analysis.
