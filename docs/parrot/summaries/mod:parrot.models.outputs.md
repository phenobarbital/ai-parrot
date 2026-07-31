---
type: Wiki Summary
title: parrot.models.outputs
id: mod:parrot.models.outputs
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.models.outputs
relates_to:
- concept: class:parrot.models.outputs.BoundingBox
  rel: defines
- concept: class:parrot.models.outputs.ImageGenerationPrompt
  rel: defines
- concept: class:parrot.models.outputs.MapColumn
  rel: defines
- concept: class:parrot.models.outputs.MapLayer
  rel: defines
- concept: class:parrot.models.outputs.MapQuery
  rel: defines
- concept: class:parrot.models.outputs.MapViewport
  rel: defines
- concept: class:parrot.models.outputs.ObjectDetectionResult
  rel: defines
- concept: class:parrot.models.outputs.OutputMode
  rel: defines
- concept: class:parrot.models.outputs.OutputType
  rel: defines
- concept: class:parrot.models.outputs.ProductReview
  rel: defines
- concept: class:parrot.models.outputs.SentimentAnalysis
  rel: defines
- concept: class:parrot.models.outputs.SpeakerConfig
  rel: defines
- concept: class:parrot.models.outputs.SpeechGenerationPrompt
  rel: defines
- concept: class:parrot.models.outputs.StructuredChartConfig
  rel: defines
- concept: class:parrot.models.outputs.StructuredMapConfig
  rel: defines
- concept: class:parrot.models.outputs.StructuredOutputConfig
  rel: defines
- concept: class:parrot.models.outputs.StructuredTableConfig
  rel: defines
- concept: class:parrot.models.outputs.TableColumn
  rel: defines
- concept: class:parrot.models.outputs.VideoGenerationPrompt
  rel: defines
- concept: mod:parrot.models.basic
  rel: references
---

# `parrot.models.outputs`

## Classes

- **`OutputType(str, Enum)`** — Types of outputs that can be rendered
- **`OutputMode(str, Enum)`** — Output mode enumeration
- **`StructuredOutputConfig`** — Configuration for structured output parsing.
- **`BoundingBox(BaseModel)`** — Represents a detected object with its location and details.
- **`ObjectDetectionResult(BaseModel)`** — A list of all prominent items detected in the image.
- **`ImageGenerationPrompt(BaseModel)`** — Input schema for generating an image.
- **`SpeakerConfig(BaseModel)`** — Configuration for a single speaker in speech generation.
- **`SpeechGenerationPrompt(BaseModel)`** — Input schema for generating speech from text.
- **`VideoGenerationPrompt(BaseModel)`** — Input schema for generating video content.
- **`SentimentAnalysis(BaseModel)`** — Structured sentiment analysis response.
- **`ProductReview(BaseModel)`** — Structured product review response.
- **`StructuredChartConfig(BaseModel)`** — Library-agnostic chart configuration mirroring the frontend AppChartConfig.
- **`TableColumn(BaseModel)`** — Per-column contract for a structured table output.
- **`StructuredTableConfig(BaseModel)`** — Framework-agnostic table configuration for FEAT-218.
- **`MapColumn(BaseModel)`** — Per-column contract for a map layer (same vocabulary as TableColumn).
- **`MapLayer(BaseModel)`** — One layer per dataset — data schema + presentation schema (FEAT-221).
- **`MapViewport(BaseModel)`** — Map viewport hints — computed from feature bounds (FEAT-221).
- **`MapQuery(BaseModel)`** — Echoed spatial filter query — carries the originating search parameters (FEAT-221).
- **`StructuredMapConfig(BaseModel)`** — Framework-agnostic map configuration for FEAT-221.
