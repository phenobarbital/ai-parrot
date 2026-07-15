---
type: Wiki Summary
title: parrot_tools.gvoice
id: mod:parrot_tools.gvoice
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Google Text-to-Speech Tool migrated to use AbstractTool framework with async
  support.
relates_to:
- concept: class:parrot_tools.gvoice.GoogleTTSArgs
  rel: defines
- concept: class:parrot_tools.gvoice.GoogleVoiceTool
  rel: defines
- concept: func:parrot_tools.gvoice.markdown_to_plain
  rel: defines
- concept: func:parrot_tools.gvoice.strip_markdown
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.gvoice`

Google Text-to-Speech Tool migrated to use AbstractTool framework with async support.

## Classes

- **`GoogleTTSArgs(BaseModel)`** — Arguments schema for GoogleTTSTool.
- **`GoogleVoiceTool(AbstractTool)`** — Tool for generating speech audio from text using Google Cloud Text-to-Speech.

## Functions

- `def strip_markdown(text: str) -> str` — Remove the most common inline Markdown markers.
- `def markdown_to_plain(md: str) -> str` — Convert Markdown to plain text via HTML parsing.
