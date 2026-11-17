---
id: F028
query_id: Q049
type: grep
intent: "Existing hand-built domain agents in the tools package (contracts) — migration candidates."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FC-029-migration-candidates]
---

# F028 — Hand-built domain agents exist in ai-parrot-tools: `ContractsAgent(Agent)` + `ContractsAgentProducer` + `ContractsToolkit`, and `LegalLibrarianAgent(Agent)` (verbatim custom system_prompt, opts out of composable layers); no trading agent

## Summary

`parrot_tools/contracts/agent.py:232 ContractsAgent` ("ReAct agent over the contracts toolkit, gated by the shared service"), `:65 ContractsAgentProducer`, `contracts/toolkit.py:39 ContractsToolkit`; `parrot_tools/legal/librarian/agent.py:47 LegalLibrarianAgent` passes `system_prompt` explicitly, which the docstring says "opts out of the composable" prompt stack. Both are code-defined identities, not file bundles — concrete migration targets; "trading" has no match.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py`
  lines: 232-240
  symbol: `ContractsAgent`
  excerpt: |
    class ContractsAgent(Agent):
        """ReAct agent over the contracts toolkit, gated by the shared service.
            **kwargs: Forwarded to :class:`~parrot.bots.Agent`.

- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py`
  lines: 65
  symbol: `ContractsAgentProducer`
  excerpt: |
    class ContractsAgentProducer:

- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py`
  lines: 39
  symbol: `ContractsToolkit`
  excerpt: |
    class ContractsToolkit(AbstractToolkit):

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py`
  lines: 47-70
  symbol: `LegalLibrarianAgent`
  excerpt: |
    class LegalLibrarianAgent(Agent):
        """Initialise with the librarian system prompt (R1/R2/R5, verbatim).
        Passing ``system_prompt`` explicitly (rather than overriding ``system_prompt_template``) opts out of the composable

## Notes

Migrating LegalLibrarianAgent to a persona layer changes its prompt composition (currently fully controlled).
