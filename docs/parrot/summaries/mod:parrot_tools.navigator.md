---
type: Wiki Summary
title: parrot_tools.navigator
id: mod:parrot_tools.navigator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Navigator Toolkit for AI-Parrot.
relates_to:
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.navigator`

Navigator Toolkit for AI-Parrot.

Manages Programs, Modules, Dashboards and Widgets
for the Navigator platform via an AI agent.

Uses PageIndex (vectorless, LLM-driven RAG) for widget documentation:
- Layer 1: Tree context in system prompt (compact node summaries)
- Layer 2: search_widget_docs() for detailed retrieval per query
- Layer 3: get_widget_schema() for exact DB lookups

Usage:
    from parrot_tools.navigator import NavigatorToolkit, NavigatorPageIndex

    page_index = NavigatorPageIndex()
    await page_index.build(adapter)

    toolkit = NavigatorToolkit(
        dsn="postgres://user:password@host:5432/navigator",
        user_id=123,
        page_index=page_index,
    )
    tools = toolkit.get_tools()
