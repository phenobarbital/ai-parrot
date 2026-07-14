---
type: Wiki Summary
title: parrot.models.infographic
id: mod:parrot.models.infographic
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured Infographic Output Models.
relates_to:
- concept: class:parrot.models.infographic.AccordionBlock
  rel: defines
- concept: class:parrot.models.infographic.AccordionItem
  rel: defines
- concept: class:parrot.models.infographic.BlockType
  rel: defines
- concept: class:parrot.models.infographic.BulletListBlock
  rel: defines
- concept: class:parrot.models.infographic.BulletListStyle
  rel: defines
- concept: class:parrot.models.infographic.CalloutBlock
  rel: defines
- concept: class:parrot.models.infographic.CalloutLevel
  rel: defines
- concept: class:parrot.models.infographic.ChartBlock
  rel: defines
- concept: class:parrot.models.infographic.ChartDataSeries
  rel: defines
- concept: class:parrot.models.infographic.ChartType
  rel: defines
- concept: class:parrot.models.infographic.ChecklistBlock
  rel: defines
- concept: class:parrot.models.infographic.ChecklistItem
  rel: defines
- concept: class:parrot.models.infographic.ColumnDef
  rel: defines
- concept: class:parrot.models.infographic.DividerBlock
  rel: defines
- concept: class:parrot.models.infographic.HeroCardBlock
  rel: defines
- concept: class:parrot.models.infographic.ImageBlock
  rel: defines
- concept: class:parrot.models.infographic.InfographicResponse
  rel: defines
- concept: class:parrot.models.infographic.JSBundle
  rel: defines
- concept: class:parrot.models.infographic.ProgressBlock
  rel: defines
- concept: class:parrot.models.infographic.ProgressItem
  rel: defines
- concept: class:parrot.models.infographic.QuoteBlock
  rel: defines
- concept: class:parrot.models.infographic.SummaryBlock
  rel: defines
- concept: class:parrot.models.infographic.TabPane
  rel: defines
- concept: class:parrot.models.infographic.TabViewBlock
  rel: defines
- concept: class:parrot.models.infographic.TableBlock
  rel: defines
- concept: class:parrot.models.infographic.TableStyle
  rel: defines
- concept: class:parrot.models.infographic.ThemeConfig
  rel: defines
- concept: class:parrot.models.infographic.ThemeRegistry
  rel: defines
- concept: class:parrot.models.infographic.TimelineBlock
  rel: defines
- concept: class:parrot.models.infographic.TimelineEvent
  rel: defines
- concept: class:parrot.models.infographic.TitleBlock
  rel: defines
- concept: class:parrot.models.infographic.TrendDirection
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.models.infographic`

Structured Infographic Output Models.

Defines block-based Pydantic models for infographic generation.
The LLM returns structured JSON using these models, and the frontend
is responsible for rendering each block type appropriately.

Block Types:
    - TitleBlock: Main title/subtitle header
    - HeroCardBlock: Key metric card with optional trend
    - SummaryBlock: Rich text summary paragraph
    - ChartBlock: Chart specification (bar, line, pie, etc.)
    - BulletListBlock: Ordered/unordered list of items
    - TableBlock: Tabular data with headers and rows
    - ImageBlock: Image reference with alt text
    - QuoteBlock: Highlighted quote or callout
    - CalloutBlock: Alert/info/warning box
    - DividerBlock: Visual separator
    - TimelineBlock: Chronological sequence of events
    - ProgressBlock: Progress/completion indicators
    - AccordionBlock: Collapsible sections with nested content
    - ChecklistBlock: Visual checkbox-style list
    - TabViewBlock: Tabbed navigation with nested content panes

## Classes

- **`BlockType(str, Enum)`** — Available infographic block types.
- **`ChartType(str, Enum)`** — Supported chart types for ChartBlock.
- **`TrendDirection(str, Enum)`** — Trend direction for hero card metrics.
- **`CalloutLevel(str, Enum)`** — Severity/type for callout blocks.
- **`TableStyle(str, Enum)`** — Visual style variants for TableBlock.
- **`BulletListStyle(str, Enum)`** — Visual style variants for BulletListBlock.
- **`ColumnDef(BaseModel)`** — Column definition for TableBlock with optional styling.
- **`AccordionItem(BaseModel)`** — A single collapsible item within an AccordionBlock.
- **`ChecklistItem(BaseModel)`** — A single item in a ChecklistBlock.
- **`TabPane(BaseModel)`** — A single tab pane within a TabViewBlock.
- **`TitleBlock(BaseModel)`** — Main title/subtitle header block.
- **`HeroCardBlock(BaseModel)`** — Key metric card with value, label, and optional trend indicator.
- **`SummaryBlock(BaseModel)`** — Rich text summary paragraph.
- **`ChartDataSeries(BaseModel)`** — A single data series for chart rendering.
- **`ChartBlock(BaseModel)`** — Chart specification block. Frontend renders using its preferred library.
- **`BulletListBlock(BaseModel)`** — Ordered or unordered list of items.
- **`TableBlock(BaseModel)`** — Tabular data block.
- **`ImageBlock(BaseModel)`** — Image reference block.
- **`QuoteBlock(BaseModel)`** — Highlighted quote or testimonial.
- **`CalloutBlock(BaseModel)`** — Alert/info/warning box.
- **`DividerBlock(BaseModel)`** — Visual separator between sections.
- **`TimelineEvent(BaseModel)`** — A single event in a timeline.
- **`TimelineBlock(BaseModel)`** — Chronological sequence of events.
- **`ProgressItem(BaseModel)`** — A single progress indicator.
- **`ProgressBlock(BaseModel)`** — Progress/completion indicators.
- **`AccordionBlock(BaseModel)`** — Collapsible accordion sections with optional nested block content.
- **`ChecklistBlock(BaseModel)`** — Visual checkbox-style list with optional checked/unchecked state.
- **`TabViewBlock(BaseModel)`** — Tabbed navigation block containing multiple content panes.
- **`InfographicResponse(BaseModel)`** — Structured infographic output returned by get_infographic().
- **`JSBundle(BaseModel)`** — Declarative JavaScript bundle attached to an InfographicTemplate.
- **`ThemeConfig(BaseModel)`** — CSS variable configuration for infographic HTML themes.
- **`ThemeRegistry`** — Registry for infographic HTML themes.
