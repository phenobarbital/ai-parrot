---
id: ADR-SEED-0004
title: HTTP stack uses aiohttp
status: accepted
---

## Context

Source: `.claude/rules/codebase-conventions.md` § Stack and § Forbidden — and what to use instead.

## Decision

HTTP clients and servers use aiohttp, and application servers run through gunicorn's aiohttp worker.
ASGI stacks are not part of the repository architecture.

## Consequences

New HTTP work uses aiohttp handlers and clients. `uvicorn`, `starlette`, and `fastapi` are forbidden.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-http-stack-aiohttp
entries:
  - id: requires-aiohttp
    statement: HTTP clients and servers use aiohttp and application servers use gunicorn's aiohttp worker.
    relation: requires
    about: [server, integrations]
    targets: [dir:packages]
    rationale: The repository standardizes its HTTP surfaces on the asyncio and uvloop-compatible aiohttp stack.
  - id: forbids-asgi
    statement: ASGI stacks including uvicorn, starlette, and fastapi are forbidden.
    relation: forbids
    about: [server, integrations]
    targets: [dir:packages]
    rationale: A second server stack would violate the repository's aiohttp architecture.
```
