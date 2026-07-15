---
type: Wiki Summary
title: parrot_tools.multidb
id: mod:parrot_tools.multidb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-Tier Schema Metadata Caching System for AI-Parrot DatabaseTool
relates_to:
- concept: class:parrot_tools.multidb.EnhancedDatabaseTool
  rel: defines
- concept: class:parrot_tools.multidb.MetadataFormat
  rel: defines
- concept: class:parrot_tools.multidb.SchemaMetadataCache
  rel: defines
- concept: class:parrot_tools.multidb.TableMetadata
  rel: defines
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.multidb`

Multi-Tier Schema Metadata Caching System for AI-Parrot DatabaseTool

This system implements intelligent schema caching with three tiers:
1. In-memory cache for frequently accessed tables
2. Vector database for semantic discovery of related tables
3. Direct database extraction as last resort

The key insight: 90% of queries hit the same 10% of tables, so we optimize
for this common case while gracefully handling discovery of new tables.

## Classes

- **`MetadataFormat(str, Enum)`** — Supported metadata formats for schema representation.
- **`TableMetadata`** — Optimized table metadata structure designed for both caching efficiency
- **`SchemaMetadataCache`** — Multi-tier caching system for database schema metadata.
- **`EnhancedDatabaseTool(AbstractTool)`** — Enhanced DatabaseTool with intelligent multi-tier schema caching.
