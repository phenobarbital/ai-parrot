---
id: F007
query_id: Q007
type: read
intent: Recent history and conventions
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F007 — Recent history and conventions

## Summary

Recent commits: 14b548483 (2026-09-05 formatting); 7f7f6f165, a0471ded2, 77b599141 (2026-09-04 provider split); 434423d45 (2026-05-29 handler satellite). These establish layout history, not proven defect causality. Core models must not import provider enums; keep new HTTP fields provider-neutral strings validated by capabilities.

## Citations

- AGENTS.md — async-first, provider separation, file safety.
- .agent/CONTEXT.md — workspace architecture.
- packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py:1-16 — public exports.
- git log scoped to provider generation and handler.
