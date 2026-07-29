---
type: Wiki Summary
title: parrot_tools.correlationanalysis
id: mod:parrot_tools.correlationanalysis
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Correlation Analysis Tool - Analyze correlations between a key column and
  other columns.
relates_to:
- concept: class:parrot_tools.correlationanalysis.CorrelationAnalysisArgs
  rel: defines
- concept: class:parrot_tools.correlationanalysis.CorrelationAnalysisTool
  rel: defines
- concept: class:parrot_tools.correlationanalysis.CorrelationMethod
  rel: defines
- concept: class:parrot_tools.correlationanalysis.OutputFormat
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.correlationanalysis`

Correlation Analysis Tool - Analyze correlations between a key column and other columns.

## Classes

- **`CorrelationMethod(str, Enum)`** — Available correlation methods.
- **`OutputFormat(str, Enum)`** — Available output formats.
- **`CorrelationAnalysisArgs(BaseModel)`** — Arguments schema for Correlation Analysis.
- **`CorrelationAnalysisTool(AbstractTool)`** — Tool for analyzing correlations between a key column and other columns in a DataFrame.
