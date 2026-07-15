---
type: Wiki Summary
title: parrot_tools.powerbi
id: mod:parrot_tools.powerbi
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.powerbi
relates_to:
- concept: class:parrot_tools.powerbi.PowerBIDatasetClient
  rel: defines
- concept: class:parrot_tools.powerbi.PowerBIQueryArgs
  rel: defines
- concept: class:parrot_tools.powerbi.PowerBIQueryTool
  rel: defines
- concept: class:parrot_tools.powerbi.PowerBITableInfoArgs
  rel: defines
- concept: class:parrot_tools.powerbi.PowerBITableInfoTool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.powerbi`

## Classes

- **`PowerBIDatasetClient(BaseModel)`** — Client for executing DAX queries against a Power BI dataset.
- **`PowerBIQueryArgs(_BasePowerBIToolArgs)`** — Arguments for PowerBIQueryTool.
- **`PowerBIQueryTool(AbstractTool)`** — Tool for executing DAX queries against a Power BI dataset.
- **`PowerBITableInfoArgs(_BasePowerBIToolArgs)`**
- **`PowerBITableInfoTool(AbstractTool)`** — Tool for previewing table info (sample rows) from a Power BI dataset.
