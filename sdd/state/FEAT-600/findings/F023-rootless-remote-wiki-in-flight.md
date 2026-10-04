---
id: F023
query_id: (recursive from Q012/Q014)
type: read
intent: FEAT-569 wikitoolkit-http-mcp is in progress (17 tasks in-progress) and touches the exact seams the plane needs
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 1
---

# F023 — FEAT-569 wikitoolkit-http-mcp is in progress (17 tasks in-progress) and touches the exact seams the plane needs

## Summary

sdd/tasks/index/wikitoolkit-http-mcp.json: feature FEAT-569, spec sdd/specs/wikitoolkit-http-mcp.spec.md, completed_at null, TASK-3351…3367 all 'in-progress'. Directly relevant: TASK-3353 StructuralService(read_repair=False) rootless mode; TASK-3354 LedgerService.from_dir() (ledger without a git root); TASK-3355 ArangoDB symbol plane; TASK-3358 build_wiki_tools()/WikiToolBundle extraction; TASK-3362 remote_cli.py + @remote_aware; TASK-3364 ProxyStdioMCPServer; TASK-3367 tool-surface golden test. Implications: (a) the plane needs from_dir() and a read_repair switch from v1; (b) mcp_server.py/cli.py/tools bundle are being refactored concurrently — merge-order risk; (c) adding four wiki_schema_* tools will change the golden tool surface.

## Citations

- path: `sdd/tasks/index/wikitoolkit-http-mcp.json`
  lines: -
  excerpt: |
    feature_id FEAT-569; tasks TASK-3351..TASK-3367 status in-progress
- path: `sdd/specs/wikitoolkit-http-mcp.spec.md`
  lines: -
  excerpt: |
    wikitoolkit HTTP MCP / remote mode spec
- path: `sdd/tasks/active/TASK-3354-ledger-service-from-dir.md`
  lines: -
  excerpt: |
    LedgerService.from_dir() — ledger without a git root (M2c)
- path: `sdd/tasks/active/TASK-3353-structural-read-repair-flag.md`
  lines: -
  excerpt: |
    StructuralService(read_repair=False) rootless mode (M2b)
- path: `sdd/tasks/active/TASK-3362-cli-remote-proxy-commands.md`
  lines: -
  excerpt: |
    remote_cli.py + @remote_aware + proxied read/authoring/symbol/ledger commands (M6a)
