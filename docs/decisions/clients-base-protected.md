---
id: ADR-SEED-0009
title: AbstractClient base changes require a decision
status: accepted
---

## Context

Source: `.agent/CONTEXT.md` § What NOT to Do and `.claude/rules/codebase-conventions.md` § Stack.

## Decision

`packages/ai-parrot/src/parrot/clients/base.py` is not modified without an explicit specification
decision.

## Consequences

Changes to the foundation shared by all LLM providers require an explicit architectural review and
recorded decision.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-clients-base-protected
entries:
  - id: rule
    statement: The AbstractClient base module is modified only under an explicit specification decision.
    relation: constrains
    about: [clients]
    targets: [file:packages/ai-parrot/src/parrot/clients/base.py]
    rationale: AbstractClient is the foundation shared by every provider integration.
```
