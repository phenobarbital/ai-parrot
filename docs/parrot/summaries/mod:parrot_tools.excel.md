---
type: Wiki Summary
title: parrot_tools.excel
id: mod:parrot_tools.excel
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MS Excel Tool migrated to use AbstractDocumentTool framework.
relates_to:
- concept: class:parrot_tools.excel.DataFrameToExcelTool
  rel: defines
- concept: class:parrot_tools.excel.ExcelArgs
  rel: defines
- concept: class:parrot_tools.excel.ExcelTool
  rel: defines
- concept: mod:parrot_tools.document
  rel: references
---

# `parrot_tools.excel`

MS Excel Tool migrated to use AbstractDocumentTool framework.

## Classes

- **`ExcelArgs(DocumentGenerationArgs)`** — Arguments schema for Excel/ODS Document generation.
- **`ExcelTool(AbstractDocumentTool)`** — Microsoft Excel/OpenDocument Spreadsheet Generation Tool.
- **`DataFrameToExcelTool(ExcelTool)`** — Simplified Excel tool that focuses purely on DataFrame export.
