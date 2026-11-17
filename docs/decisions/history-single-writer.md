---
id: ADR-SEED-0002
title: Conversation history has one writer
status: accepted
---

## Context

Source: `.agent/CONTEXT.md` § Conversation memory.

## Decision

Every conversation turn is persisted through `AbstractBot.save_conversation_turn()`; `AbstractBot`
is the only writer of conversation history.

## Consequences

Clients and other components may consume rendered history but must not independently persist turns.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-history-single-writer
entries:
  - id: rule
    statement: AbstractBot.save_conversation_turn() is the only writer of conversation history.
    relation: requires
    about: [memory, bots]
    targets: [file:packages/ai-parrot/src/parrot/bots/abstract.py]
    rationale: A single write path preserves conversation ownership and per-agent history identity.
```
