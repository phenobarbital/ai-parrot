---
type: Wiki Summary
title: parrot.tools.dataset_manager.excel_analyzer
id: mod:parrot.tools.dataset_manager.excel_analyzer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Excel Structure Analysis Engine.
relates_to:
- concept: class:parrot.tools.dataset_manager.excel_analyzer.CellRegion
  rel: defines
- concept: class:parrot.tools.dataset_manager.excel_analyzer.DetectedTable
  rel: defines
- concept: class:parrot.tools.dataset_manager.excel_analyzer.ExcelStructureAnalyzer
  rel: defines
- concept: class:parrot.tools.dataset_manager.excel_analyzer.SheetAnalysis
  rel: defines
---

# `parrot.tools.dataset_manager.excel_analyzer`

Excel Structure Analysis Engine.

Scans complex Excel workbooks using openpyxl and discovers table structures
via header-row heuristics. Produces SheetAnalysis and DetectedTable data models
describing the structural layout.

## Classes

- **`CellRegion`** — A rectangular region within a sheet.
- **`DetectedTable`** — A table discovered within a sheet.
- **`SheetAnalysis`** — Complete structural analysis of one sheet.
- **`ExcelStructureAnalyzer`** — Core analysis engine for Excel workbooks.
