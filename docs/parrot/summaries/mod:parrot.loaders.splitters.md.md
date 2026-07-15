---
type: Wiki Summary
title: parrot.loaders.splitters.md
id: mod:parrot.loaders.splitters.md
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Rust-backed Markdown splitter (thin wrapper over semantic_text_splitter.MarkdownSplitter).
relates_to:
- concept: class:parrot.loaders.splitters.md.MarkdownTextSplitter
  rel: defines
- concept: mod:parrot.loaders.splitters.base
  rel: references
- concept: mod:parrot.loaders.splitters.semantic
  rel: references
---

# `parrot.loaders.splitters.md`

Rust-backed Markdown splitter (thin wrapper over semantic_text_splitter.MarkdownSplitter).

Respects fenced code blocks, headers, lists, and blockquotes natively.

## Classes

- **`MarkdownTextSplitter(BaseTextSplitter)`** — Markdown-aware splitter backed by the Rust crate. Never cuts inside
