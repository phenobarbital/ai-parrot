---
id: FG-003
query_id: Q050
type: git_log
intent: "Recent history of agentd."
executed_at: 2026-10-30T15:19:33Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-003 — integrations/agentd history, last 180 days

## Summary

14 commits (2026-08-16 → 2026-10-08) by Jesus, Jesus Lara and Javier León. The daemon was
built in Aug 2026 (`agent-cli-daemon` + `claude-agent-tool-bridge`). **The key identity commit is
`9599c44ff` (2026-08-20, TASK-2286): "agentd caller identity (SO_PEERCRED + service-identity
fallback)"** — it added ~100 lines to `agentd/config.py`, ~67 to `agentd/server.py` and a 163-line
`tests/agentd/test_caller_identity.py`. So agentd already identifies the UDS caller by OS peer
credentials, not by a Navigator user. Later commits: TASK-2290 bridge (`168633e02`), UDS buffer
sizing (`f760cf01c`, `5f271cece`), LLM tools from `exposed_*` (`71fc1bc97`), FEAT-573 post-turn
hooks in `cli.py`/`proxy.py` (TASK-3415, 2026-09-18), and the most recent: scheduler-manager-base
TASK-4162 on `config.py`/`service.py` (2026-10-08).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
  lines: 1-1
  symbol: `(caller identity, TASK-2286)`
  excerpt: |
    9599c44ff 2026-08-20 Jesus feat(claude-agent-tool-bridge): TASK-2286 — agentd caller identity
      (SO_PEERCRED + service-identity fallback)
      agentd/config.py +103, agentd/server.py +67, tests/agentd/test_caller_identity.py +163

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py`
  lines: 1-1
  symbol: `(config evolution)`
  excerpt: |
    cf7547187 2026-08-20 parrot serve daemon now supports expand variables (config.py)
    71fc1bc97 2026-08-20 Javier León feat(agentd): derive LLM tools from exposed_… (config.py, service.py, tools.py)
    05ba68eb6 / 7ffcf3c62 2026-10-08 Jesus Lara TASK-4162 scheduler-manager-base (config.py, service.py)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py`
  lines: 1-1
  symbol: `(bridge)`
  excerpt: |
    168633e02 2026-08-20 feat(claude-agent-tool-bridge): TASK-2290 — bridge… (service.py)
    336990001 2026-08-20 fix(claude-agent-tool-bridge): address code review (server.py, service.py)
    0eb48a0e6 2026-08-20 fix(cli): stop blaming optional extras for inner ImportError (service.py)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py`
  lines: 1-1
  symbol: `DaemonAgentProxy`
  excerpt: |
    ba104a841 2026-09-18 feat(new-ui-cli-agents): TASK-3415 — agentd post-turn… (cli.py, proxy.py)
    4fdcb0f93 2026-09-18 style TASK-3415 lint autofix

- path: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/client.py`
  lines: 1-1
  symbol: `(UDS client)`
  excerpt: |
    f760cf01c / 5f271cece 2026-08-20 — StreamReader buffers / UDS stream limit (client.py, server.py)

## Notes

- agentd's identity model is **process-level** (SO_PEERCRED uid/gid, service-identity fallback). There is no commit introducing a per-user Navigator principal; S-4 must map a peer identity → Navigator `user_id` or carry an explicit login token over the JSON-RPC envelope.
- [cross-lane: type=read, intent=Read agentd/server.py and agentd/config.py around the SO_PEERCRED caller-identity code added by 9599c44ff, and tests/agentd/test_caller_identity.py for the identity contract.]
