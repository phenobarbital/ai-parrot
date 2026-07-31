---
type: Wiki Summary
title: parrot.loaders.splitters.semantic
id: mod:parrot.loaders.splitters.semantic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rust-backed semantic text splitter (thin wrapper over TextSplitter from semantic_text_splitter).
relates_to:
- concept: class:parrot.loaders.splitters.semantic.SemanticTextSplitter
  rel: defines
- concept: mod:parrot.loaders.splitters.base
  rel: references
---

# `parrot.loaders.splitters.semantic`

Rust-backed semantic text splitter (thin wrapper over TextSplitter from semantic_text_splitter).

## Classes

- **`SemanticTextSplitter(BaseTextSplitter)`** — Sentence/paragraph-aware splitter backed by the Rust crate. Never
