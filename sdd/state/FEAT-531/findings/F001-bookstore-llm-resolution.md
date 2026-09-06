---
id: F001
query_id: Q001
type: grep
intent: Locate how the bookstore CLI/MCP server resolves its LLM configuration today
executed_at: 2026-09-06T03:09:28Z
duration_ms: 400
parent_id: null
depth: 0
---

# F001 — Bookstore LLM resolution lives in one shared helper

## Summary

`wikitoolkit query` ranked `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
(`resolve_adapter`) as the shared LLM-resolution entrypoint for both the `bookstore` CLI and
its MCP server. A sibling hit, `bookstore/cli.py`, is the CLI surface that calls it. No result
scored a hardcoded default-provider module.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
  symbol: `resolve_adapter`
  excerpt: |
    Shared LLM resolution for the bookstore CLI and MCP server.
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py`
  excerpt: |
    ``bookstore`` CLI — manage the personal indexed library.

## Notes

Confirms there is exactly one resolution seam for bookstore, not several duplicated ones —
good news for a low-blast-radius change.
