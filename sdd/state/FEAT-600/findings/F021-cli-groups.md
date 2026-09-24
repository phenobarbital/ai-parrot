---
id: F021
query_id: Q019
type: read
intent: wikitoolkit CLI has groups symbols, ns, ledger, sync (and adr); `schema` is unused
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F021 — wikitoolkit CLI has groups symbols, ns, ledger, sync (and adr); `schema` is unused

## Summary

cli.py: def symbols() L2277, def ns() L2479, def ledger() L2765, def sync() L3958; TASK-3496 added `wikitoolkit adr`. cli.py is ~6.5K tokens as a wiki page and is a hot file (F024). TASK-3362 (FEAT-569) is adding remote_cli.py + @remote_aware proxies for read/authoring/symbol/ledger commands — a `schema` group landing concurrently must decide whether its read verbs are remote-aware.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 2277,2479,2765,3958
  symbol: `symbols / ns / ledger / sync`
  excerpt: |
    def ledger() -> None:
- path: `sdd/tasks/completed/TASK-3496-adr-cli-and-post-ingest-refresh.md`
  lines: -
  excerpt: |
    `wikitoolkit adr` CLI group
