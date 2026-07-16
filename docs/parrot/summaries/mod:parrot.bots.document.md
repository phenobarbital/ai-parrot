---
type: Wiki Summary
title: parrot.bots.document
id: mod:parrot.bots.document
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DocumentAgent - Specialized agent for document processing without Langchain.
relates_to:
- concept: class:parrot.bots.document.DocumentAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.bots.document`

DocumentAgent - Specialized agent for document processing without Langchain.

Migrated from NotebookAgent to use native Parrot architecture:
- Extends BasicAgent from parrot.bots.agent
- Uses AbstractTool-based tools (WordToMarkdownTool, GoogleVoiceTool, ExcelTool)
- Native conversation() and invoke() methods
- Async-first architecture
- Integrated with ToolManager

## Classes

- **`DocumentAgent(BasicAgent)`** — A specialized agent for document processing - converting Word docs to Markdown,
