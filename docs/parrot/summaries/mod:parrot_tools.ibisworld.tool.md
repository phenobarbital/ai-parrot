---
type: Wiki Summary
title: parrot_tools.ibisworld.tool
id: mod:parrot_tools.ibisworld.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: IBISWorld Tool for AI-Parrot
relates_to:
- concept: class:parrot_tools.ibisworld.tool.IBISWorldSearchArgs
  rel: defines
- concept: class:parrot_tools.ibisworld.tool.IBISWorldTool
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.google.tools
  rel: references
---

# `parrot_tools.ibisworld.tool`

IBISWorld Tool for AI-Parrot
Search and extract content from IBISWorld industry research articles.

## Classes

- **`IBISWorldSearchArgs(BaseModel)`** — Arguments schema for IBISWorld Search Tool.
- **`IBISWorldTool(GoogleSiteSearchTool)`** — IBISWorld search and content extraction tool.
