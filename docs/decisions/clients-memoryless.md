---
id: ADR-SEED-0001
title: Clients are memory-less
status: accepted
---

## Context

Source: `.agent/CONTEXT.md` § AbstractClient ("Memory-less (FEAT-524)") and § Conversation memory.

## Decision

`AbstractClient` subclasses neither load nor persist conversation history; they receive an already
rendered `history` per call.

## Consequences

`AbstractBot` is the sole owner of history. A client that reads or writes a memory backend violates
this rule.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-clients-memoryless
entries:
  - id: rule
    statement: AbstractClient subclasses neither load nor persist conversation history.
    relation: forbids
    about: [clients, memory]
    targets: [dir:packages/ai-parrot/src/parrot/clients]
    rationale: FEAT-524 made AbstractBot the single owner of conversation history.
```
