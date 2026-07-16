---
type: Wiki Summary
title: parrot_loaders.extractors.base
id: mod:parrot_loaders.extractors.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class and data models for structured data extraction.
relates_to:
- concept: class:parrot_loaders.extractors.base.ExtractDataSource
  rel: defines
- concept: class:parrot_loaders.extractors.base.ExtractedRecord
  rel: defines
- concept: class:parrot_loaders.extractors.base.ExtractionResult
  rel: defines
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
---

# `parrot_loaders.extractors.base`

Abstract base class and data models for structured data extraction.

ExtractDataSource provides a generic contract for extracting structured records
(list[dict]) from various data sources (CSV, JSON, SQL, APIs, in-memory).
Unlike AI-Parrot's Loaders (which produce text chunks for RAG), extractors
produce structured records for ontology graph ingestion, data pipelines, and ETL.

## Classes

- **`ExtractedRecord(BaseModel)`** — A single extracted record with its raw data and metadata.
- **`ExtractionResult(BaseModel)`** — Result of an extraction operation.
- **`ExtractDataSource(ABC)`** — Abstract base class for structured data extraction.
