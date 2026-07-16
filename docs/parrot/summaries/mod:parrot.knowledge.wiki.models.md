---
type: Wiki Summary
title: parrot.knowledge.wiki.models
id: mod:parrot.knowledge.wiki.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic data models for the LLM Wiki feature (FEAT-260).
relates_to:
- concept: class:parrot.knowledge.wiki.models.SourceManifestEntry
  rel: defines
- concept: class:parrot.knowledge.wiki.models.WikiConfig
  rel: defines
- concept: class:parrot.knowledge.wiki.models.WikiLintReport
  rel: defines
- concept: class:parrot.knowledge.wiki.models.WikiPageCategory
  rel: defines
- concept: class:parrot.knowledge.wiki.models.WikiSearchResult
  rel: defines
---

# `parrot.knowledge.wiki.models`

Pydantic data models for the LLM Wiki feature (FEAT-260).

Defines all shared data structures used across the wiki package:
- WikiPageCategory: Karpathy's wiki page type taxonomy
- WikiConfig: per-wiki-instance configuration
- SourceManifestEntry: tracks an ingested source document
- WikiSearchResult: unified result from combined search
- WikiLintReport: extended lint report with wiki-specific checks

Design notes:
- All models follow the same Pydantic v2 pattern used throughout ai-parrot.
- WikiConfig.search_weights is validated to ensure all values are in [0, 1]
  and their sum is approximately 1.0 (within 0.01 tolerance).

## Classes

- **`WikiPageCategory(str, Enum)`** — Karpathy's wiki page type taxonomy.
- **`WikiConfig(BaseModel)`** — Configuration for a single wiki instance.
- **`SourceManifestEntry(BaseModel)`** — Tracks an ingested source document in the wiki's source manifest.
- **`WikiSearchResult(BaseModel)`** — Unified wiki search result.
- **`WikiLintReport(BaseModel)`** — Extended lint report combining OKF checks with wiki-specific checks.
