---
id: FG-004
query_id: Q051
type: git_log
intent: "Recent history of the MCP client-side OAuth files (is the loopback / storage path alive or stale?)."
executed_at: 2026-10-30T15:19:33Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-004 — mcp/oauth.py, oauth2_storage.py, oauth2_config.py history, last 365 days

## Summary

10 commits (2026-03-23 → 2026-06-26), all by Jesus. `oauth.py` originated with the monorepo migration
(TASK-398, 2026-03-23), gained NetSuite support (TASK-922, 2026-04-29), was split/relocated for
ai-parrot-server (TASK-1366/1368, 2026-05-29). `oauth2_config.py` and `oauth2_storage.py` were
created by the `mcp-server-oauth2-support` feature on 2026-06-26 (TASK-1659 `MCPOAuth2Config`,
TASK-1660 **`VaultMCPTokenStorage` adapter** +171 lines with 235 lines of tests, TASK-1665 OAuth in
`oauth.py`, then review fixes `4748de100`). **Nothing has touched these three files in the four
months since 2026-06-26** — the MCP client-side OAuth path is stable/frozen, consistent with S-1's
note that `mcp/client.py` is frozen since 2026-06-29.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py`
  lines: 1-171
  symbol: `VaultMCPTokenStorage`
  excerpt: |
    bfce52ea7 2026-06-26 feat(mcp-server-oauth2-support): TASK-1660 — VaultMCPTokenStorage Adapter
      mcp/oauth2_storage.py +171, tests/mcp/test_oauth2_storage.py +235
    4748de100 2026-06-26 fix(mcp-server-oauth2-support): address all code review… (oauth2_config.py, oauth2_storage.py)

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 1-1
  symbol: `MCPOAuth2Config`
  excerpt: |
    44497f159 2026-06-26 feat(mcp-server-oauth2-support): TASK-1659 — MCPOAuth2Config

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 1-1
  symbol: `(client-side OAuth)`
  excerpt: |
    473625b39 2026-06-26 TASK-1665 — OAuth… (oauth.py)
    461d7a0a2 2026-05-29 TASK-1368 — Split mcp/oauth… (ai-parrot-server)
    2e83e51ea 2026-05-29 TASK-1366 — Relocate vault… (oauth.py)
    fa055259b 2026-05-04 new test agents (oauth.py)
    0e03a4e67 / d9db07f77 2026-04-29 TASK-922 netsuite-mcp-integration (oauth.py)
    495361104 2026-03-23 TASK-398 monorepo-migration workspace (oauth.py)

## Notes

- Test file for the storage adapter lives at the repo-root tree `tests/mcp/test_oauth2_storage.py`, not under `packages/ai-parrot/tests/`.
- The feature name `mcp-server-oauth2-support` suggests these files serve parrot-as-MCP-*client* talking to OAuth-protected remote MCP servers (NetSuite); whether a loopback redirect exists is for the codebase lane.
- [cross-lane: type=read, intent=Read oauth2_storage.py VaultMCPTokenStorage to see its key layout (user-keyed? channel-keyed?) — candidate CredentialStore precedent.]
