---
id: ADR-SEED-0003
title: Async code remains non-blocking
status: accepted
---

## Context

Source: `.agent/CONTEXT.md` § What NOT to Do and `.claude/rules/codebase-conventions.md` § Stack.

## Decision

Async code must not perform blocking I/O. It must not use `requests`, `time.sleep`, or synchronous
database drivers in an async execution path.

## Consequences

I/O paths use async APIs throughout. The project standardizes on aiohttp, asyncio, and uvloop.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-non-blocking-async-stack
entries:
  - id: rule
    statement: Async code must not perform blocking I/O through requests, time.sleep, or synchronous database drivers.
    relation: forbids
    about: [server, integrations, tools, clients]
    targets: [dir:packages]
    rationale: httpx is excluded for stack consistency, not because it blocks; it supports async, while this project standardizes on aiohttp, asyncio, and uvloop.
```
