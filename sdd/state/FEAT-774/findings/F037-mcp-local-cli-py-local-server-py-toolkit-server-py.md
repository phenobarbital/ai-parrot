---
id: F037
query_id: Q049
type: git_log
intent: "Recent history of the local-MCP surface (mcp-local, stdio servers, hosts)."
executed_at: 2026-10-30T15:19:33Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FG-002]
---

# F037 — mcp/local_cli.py, local_server.py, toolkit_server.py, hosts.py history, last 180 days

## Summary

17 commits (2026-09-01 → 2026-10-28). Three themes: (1) FEAT-570 `expose-local-mcp-tools`
(2026-09-18) created `hosts.py` (`HostAdapter` contract + `detect_hosts`, TASK-3374, +236 lines) and
the builtin-toolkit `mcp-local` registration (TASK-3380); (2) `sdd-coder` / `sdd-research-lsp`
hardening of the stdio server (2026-09-19/24: concurrency, unwedge, mutation serialisation,
factory-close TASK-3506); (3) the most recent commits are CI / stdin-isolation fixes
(`dda9a3ed2` 2026-10-27, `b80ea3a98` 2026-10-28 HOTFIX). **No commit in this window mentions
credentials, identity, principal, OAuth or vault on these four files** — the local-MCP surface was
built for in-repo dev tooling (sdd-coder, LSP, wikitoolkit) and has no per-user auth history.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/hosts.py`
  lines: 1-236
  symbol: `HostAdapter`
  excerpt: |
    52aa35dcf 2026-09-18 feat(expose-local-mcp-tools): TASK-3374 — HostAdapter contract + detect_hosts
      hosts.py +236, tests/mcp/test_hosts.py +61
    da255457c / 27e541609 2026-09-18 — TASK-3374 lint + review fixes (hosts.py)
    e4361c074 2026-09-18 fix(expose-local-mcp-tools): code review fixes (hosts.py)
- path: `packages/ai-parrot/src/parrot/mcp/local_cli.py`
  lines: 1-1
  symbol: `(mcp-local command)`
  excerpt: |
    5fcbc842c 2026-09-18 feat(expose-local-mcp-tools): TASK-3380 — builtin-toolkit registration
    f2f551685 2026-09-18 style TASK-3380
    5ab817537 2026-09-19 feat(sdd-research-lsp): TASK-3506 — close factory (local_cli.py, toolkit_server.py)
    dda9a3ed2 2026-10-27 fix(ci): repair nightly setup and package registration
    b80ea3a98 2026-10-28 fix(sdd-coder-stdin-isolation): HOTFIX-995ad869e50 (local_cli.py, local_server.py)
    122e495dd 2026-09-01 Claude feat(dev_loop): wire FEAT-484/485/486 (local_cli.py)
- path: `packages/ai-parrot/src/parrot/mcp/local_server.py`
  lines: 1-1
  symbol: `StdioMCPServer`
  excerpt: |
    cdd7a4bb2 2026-09-24 fix(sdd-coder): concurrent stdio MCP server
    ba4eba573 2026-09-24 fix(sdd-coder): unwedge the stdio MCP server
    76311f92f 2026-09-24 fix(sdd-coder): review round — serialise mutations
    b80ea3a98 2026-10-28 HOTFIX stdin isolation
- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 1-1
  symbol: `(toolkit stdio server)`
  excerpt: |
    15472a6c0 2026-09-10 feat(tool-optimizations): TASK-3087 — Toolkit… (toolkit_server.py)
    5ab817537 / 3c0eac3df / 37e11180d 2026-09-19 — TASK-3506 factory close + FEAT-580 review fixes

## Notes

- Absence evidence: zero auth/identity-themed commits on the local-MCP surface in 180 days.
- Most recent change (`b80ea3a98`, 2026-10-28) is a hotfix on stdin isolation — the surface is actively maintained and in flight; S-4 edits to `local_cli.py`/`local_server.py` should rebase on it.
- [cross-lane: type=read, intent=Read hosts.py HostAdapter to see whether host config entries carry an env block (channel for passing a CLI principal/token to the stdio server process).]
