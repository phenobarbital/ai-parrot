---
id: FC-008
query_id: Q021
type: grep
intent: "Host config writing for Claude Code / Codex"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-008 — Hosts: .mcp.json (Claude), .codex/config.toml (Codex), user-global (Google) via adapters

## Summary

`parrot/mcp/hosts.py` defines a `HostAdapter` protocol with `ClaudeAdapter` (repo `.mcp.json`, entries `parrot-<name>`, approvals sync), `CodexAdapter` (repo `.codex/config.toml`, managed marker block, tables `mcp_servers.parrot-<name>`) and `GoogleAdapter` (USER-GLOBAL `~/.gemini/config/mcp_config.json`). Entry writing is delegated to `parrot.knowledge.wiki.{claude_code,codex,google}.installer`; `toolkit_install.py` drives `sync_approvals` for Claude only.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/hosts.py`
  lines: 18-23, 58-64, 120-126, 176-177
  symbol: `HostKind / ClaudeAdapter / CodexAdapter / GoogleAdapter`
  excerpt: |
    class HostKind(str, Enum): CLAUDE = "claude"; CODEX = "codex"; GOOGLE = "google"
    class ClaudeAdapter:  # repo `.mcp.json`
        def config_paths(self, root): return (root / ".mcp.json",)
    class CodexAdapter:   # repo `.codex/config.toml`, managed marker block
        def config_paths(self, root): return (root / ".codex" / "config.toml",)
    class GoogleAdapter:  # USER-GLOBAL ~/.gemini/config/mcp_config.json

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_install.py`
  lines: 173-174, 208-209, 240-244
  symbol: `install/uninstall → sync_approvals`
  excerpt: |
    if HostKind.CLAUDE in resolved_hosts:
        message = get_adapter(HostKind.CLAUDE).sync_approvals(root)


## Notes

Server entries are `command: parrot mcp-local <name>` + `env` from ToolkitSection; a CLI principal/token for S-4 would have to travel as env or a file the server process reads.
