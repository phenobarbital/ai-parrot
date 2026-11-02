---
id: ADR-SEED-0008
title: LangChain is not part of the stack
status: accepted
---

## Context

Source: `.agent/CONTEXT.md` § What NOT to Do and `.claude/rules/codebase-conventions.md` § Forbidden — and what to use instead.

## Decision

Repository packages do not use `langchain`, `langchain_core`, `langchain_community`, `langgraph`, or
`langsmith`; they use Parrot primitives.

## Consequences

LLM integrations use `AbstractClient`; tools use `AbstractTool`; orchestration uses `AgentsFlow` and
`AgentCrew`.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-no-langchain
entries:
  - id: rule
    statement: LangChain, LangGraph, and LangSmith libraries are forbidden across repository packages.
    relation: forbids
    about: [clients, bots, flows, tools]
    targets: [dir:packages]
    rationale: Parrot primitives provide the repository's client, tool, and orchestration abstractions.
```
