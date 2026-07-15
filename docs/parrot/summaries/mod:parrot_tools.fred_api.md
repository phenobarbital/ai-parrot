---
type: Wiki Summary
title: parrot_tools.fred_api
id: mod:parrot_tools.fred_api
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FredAPITool for interacting with Federal Reserve Economic Data (FRED) API.
relates_to:
- concept: class:parrot_tools.fred_api.FredAPITool
  rel: defines
- concept: class:parrot_tools.fred_api.FredToolArgsSchema
  rel: defines
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.cache
  rel: references
---

# `parrot_tools.fred_api`

FredAPITool for interacting with Federal Reserve Economic Data (FRED) API.

## Classes

- **`FredToolArgsSchema(AbstractToolArgsSchema)`** — Schema for FredAPITool arguments.
- **`FredAPITool(AbstractTool)`** — Tool for fetching economic data from the Federal Reserve Economic Data (FRED) API.
