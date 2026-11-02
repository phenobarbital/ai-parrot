---
id: ADR-SEED-0007
title: Concrete tools live in ai-parrot-tools
status: accepted
---

## Context

Source: `CLAUDE.md` § Tool-Centric Architecture and `.claude/rules/codebase-conventions.md` § Repository layout.

## Decision

Concrete external API and service tools live in `packages/ai-parrot-tools/src/parrot_tools`; core
`parrot/tools` contains only base machinery.

## Consequences

New concrete toolkits use the `parrot_tools` namespace. Core retains `AbstractTool`, `AbstractToolkit`,
the `@tool` decorator, `ToolManager`, and working-memory machinery.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-tools-live-in-parrot-tools
entries:
  - id: rule
    statement: Concrete tool implementations live in the ai-parrot-tools distribution.
    relation: requires
    about: [tools]
    targets: [dir:packages/ai-parrot-tools/src/parrot_tools]
    rationale: Keeping implementations in parrot_tools preserves the core package boundary.
```
