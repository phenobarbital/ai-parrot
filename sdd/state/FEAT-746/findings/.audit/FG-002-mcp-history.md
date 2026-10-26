---
id: FG-002
query_id: Q052
type: git_log
intent: "Recent history: MCP core + transports."
executed_at: 2026-10-25T22:40:29Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-002 — MCP history: very active, but on local-MCP/sdd-coder tooling, not transports

## Summary

25+ commits in 90 days on `parrot/mcp/` (core) and the server's `parrot/mcp/`. Dominant themes: the sdd-coder stdio MCP server (concurrency, serial server, seat roster — Sep/Oct), expose-local-mcp-tools FEAT (HostAdapter contract, install orchestration, packaged toolkit templates — 09-18), LSP toolkit template (FEAT-580), standalone HTTP MCP kept alive until shutdown (FEAT-581). No commit in the window touches transport plumbing (stdio/HTTP/Unix/QUIC) or adds a binary transport. Area is active; the transport layer is stable.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `b0455e0429` 2026-09-24 Jesus — fix(mcp): lazily re-export ChromeManager from parrot.mcp.integration
- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `cdd7a4bb2a` 2026-09-24 Jesus Lara — fix(sdd-coder): concurrent stdio MCP server, bounded engine subprocesses, core-only import
- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `b3c8b8b7dc` 2026-09-19 Jesus — feat(agentic-e2e-testing): TASK-3515 — keep standalone HTTP MCP alive until shutdown
- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `5ab817537f` 2026-09-19 Jesus — feat(sdd-research-lsp): TASK-3506 — close factory-owned toolkit resources on local MCP exit
- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `52aa35dcfc` 2026-09-18 Jesus — feat(expose-local-mcp-tools): TASK-3374 — HostAdapter contract + detect_hosts
- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `32f30643c2` 2026-09-18 Jesus — feat(expose-local-mcp-tools): TASK-3375 — install orchestration (inventory, install, uninstall, enable/disable)
- path: `packages/ai-parrot/src/parrot/mcp/`
  commit: `e21596b3f5` 2026-09-18 Jesus — feat(expose-local-mcp-tools): TASK-3370 — five packaged toolkit templates + requires_dist header

## Notes

"expose-local-mcp-tools" (install/uninstall/enable/disable of packaged toolkits, HostAdapter) is the closest existing lifecycle to the brainstorm's `catalog.mount/unmount` — but it operates at install time on an MCP host, not mid-conversation inside ToolManager. [cross-lane: type=grep, intent=locate the expose-local-mcp-tools inventory/enable/disable API to compare with catalog.mount semantics]
