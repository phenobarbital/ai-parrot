---
id: FG-001
query_id: Q051
type: git_log
intent: "Recent history: A2A package (is it active? streaming/artifact changes)."
executed_at: 2026-10-25T22:40:29Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-001 — A2A package history: v1.0 protocol complete (Jul 2026), maintenance since

## Summary

21 commits in the last 120 days on `packages/ai-parrot-server/src/parrot/a2a/`. The bulk landed 2026-07-10 as FEAT-272 (a2a-protocol-compatibility, 8/8 tasks done: v1.0 data models, AgentCard v1.0, REST routes + version negotiation, JSON-RPC methods + error codes, push-notification config store, A2AClient v1.0, mesh & router, integration tests). After that only maintenance: credential-broker gate (FEAT 06-29), A2A agent-card extension + inbound DataPart dispatch (FEAT-469, 08-29), identity/PBAC wiring via mcp-as-agent TASK-2610 (09-01), lazy imports (FEAT-668, 10-14). Active but feature-stable: a JSON-RPC/REST (HTTP) surface, no binary transport.

## Citations

- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `dc347e0dc0` 2026-10-14 Jesus Lara — feat(a2ui-lazy-imports): TASK-4292 — server handlers defer heavy imports
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `dcd09421aa` 2026-09-01 Jesus Lara — feat(mcp-as-agent): TASK-2610 — integration tests, SDK interop, docs, and identity/PBAC wiring
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `aa7ae59de7` 2026-08-29 Jesus — feat(a2ui-agent-functions): TASK-2572 A2A agent card extension, inbound DataPart dispatch, queued renderer calls
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `24e31cbedd` 2026-07-20 Claude — feat(outputs): OutputMode.TEXT plain-text mode; A2A serves plain text by default for Copilot
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `f2d210169f` 2026-07-10 Jesus — feat(a2a-protocol-compatibility): port JSON-RPC streaming + extra coverage from feat-272
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `094fda5278` 2026-07-10 Jesus — feat(a2a-protocol-compatibility): TASK-1715 — v1.0 JSON-RPC methods & error codes
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `764af73c07` 2026-07-10 Jesus — feat(a2a-protocol-compatibility): TASK-1713 — AgentCard v1.0 structure
- path: `packages/ai-parrot-server/src/parrot/a2a/`
  commit: `05bf98da5b` 2026-06-29 Jesus Lara — feat(unified-credential-broker): TASK-1672 — replace A2AServer credential gate with broker calls
- path: `sdd/tasks/index/a2a-protocol-compatibility.json`
  symbol: FEAT-272
  excerpt: |
    completed_at 2026-07-10; 8/8 done — TASK-1712 data models, TASK-1713 AgentCard v1.0,
    TASK-1714 A2AServer REST routes, TASK-1715 JSON-RPC methods, TASK-1716 push-notification
    store, TASK-1717 A2AClient v1.0, TASK-1718 Mesh & Router, TASK-1719 integration tests

## Notes

A2A already has: AgentCard, A2AClient, A2AServer, a "Mesh & Router" component, push-notification config store, identity/PBAC wiring and a credential-broker gate — all relevant reuse points for the inbound `kind=a2a` path and for the policy gate. [cross-lane: type=read, intent=read the A2A mesh/router module (TASK-1718) — it may already be a registry of remote agents with endpoints]
