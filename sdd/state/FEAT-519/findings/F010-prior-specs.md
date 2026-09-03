---
id: F010
query_id: Q012,Q013
type: read
intent: Recover prior design intent so the proposal does not re-litigate settled decisions
executed_at: 2026-09-02T22:01:30Z
parent_id: null
depth: 0
---

# F010 — Two prior specs govern this surface: FEAT-168 (agent console) and devloop-cli-console

## Summary

`console-cli-agents.spec.md` (FEAT-168, status **draft**) is the spec that
created `parrot agent`; its Module 5 is literally "Response Renderer", so a Rich
renderer was the original intent — the streaming raw-write is a deviation from
it, not the design. `devloop-cli-console.spec.md` specifies the newer console
whose Module 3 is "Run Renderer (Rich Live envelope painter)" and Module 4 the
"Console Engine (session, slash commands, gates)" — the components F005 shows
solved the conflict. A third spec, `devloop-cli-homologation-v2`, shows
"homologation" is already an established framing in this repo.

## Citations

- path: `sdd/specs/console-cli-agents.spec.md`
  lines: 9-15
  symbol: header
  excerpt: |
    # Feature Specification: Console CLI Agents
    **Feature ID**: FEAT-168
    **Date**: 2026-05-13
    **Status**: draft

- path: `sdd/specs/console-cli-agents.spec.md`
  lines: 191-238
  symbol: Module breakdown
  excerpt: |
    ### Module 3: REPL Engine
    ### Module 4: Slash Commands
    ### Module 5: Response Renderer
    ### Module 6: Tests

- path: `sdd/specs/devloop-cli-console.spec.md`
  lines: 200-261
  symbol: Module breakdown
  excerpt: |
    ### Module 1: Generic Pydantic Wizard Engine
    ### Module 3: Run Renderer (Rich Live envelope painter)
    ### Module 4: Console Engine (session, slash commands, gates)

- path: `sdd/specs/devloop-cli-console.spec.md`
  lines: 172-180
  symbol: New Public Interfaces
  excerpt: |
    # parrot/cli/wizard.py — generic, reusable engine (G2)

- path: `sdd/specs/devloop-cli-homologation-v2.spec.md`
  symbol: precedent for "homologation" framing

## Notes

`parrot/cli/wizard.py` was specified as a **generic, reusable** engine (goal G2)
— it is a candidate for reuse by the agent console rather than a devloop-only
asset.
