---
id: FC-011
query_id: Q024
type: glob
intent: "agentd package layout"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-011 — agentd package: cli, client, config, mcp_server, protocol, proxy, server, service, tools

## Summary

`packages/ai-parrot-integrations/src/parrot/integrations/agentd/` contains `__init__.py`, `cli.py` (12.3K), `client.py` (14.7K), `config.py` (16.2K), `mcp_server.py` (7.0K), `protocol.py` (10.7K), `proxy.py` (14.7K), `server.py` (18.8K), `service.py` (32.7K), `tools.py` (7.8K). Identity lives in `server.py` (peercred) and `config.py` (`ServiceIdentityConfig`); `mcp_server.py` is the `parrot mcp-serve` stdio proxy.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/`
  lines: dir
  symbol: `agentd package`
  excerpt: |
    __init__.py cli.py client.py config.py mcp_server.py protocol.py proxy.py server.py service.py tools.py


## Notes

Q040 resolved to server.py (read as FC-026).
