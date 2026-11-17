---
id: FG-004
query_id: Q063
type: git_log
intent: "History: MCP client/oauth2 config — any in-flight per-user token work."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 500
parent_id: null
depth: 0
---

# FG-004 — mcp/client.py + mcp/oauth2_config.py: zero commits in 120 days; last touch 2026-06-29 (TASK-1676 broker token injection)

## Summary

No commits in the 120-day window for `packages/ai-parrot/src/parrot/mcp/client.py` or `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`. A follow-up unbounded `git log -3` shows the last three commits: `793b3ca21` 2026-06-29 "feat(unified-credential-broker): TASK-1676 — MCP per-user token injection via broker", `4748de100` 2026-06-26 "fix(mcp-server-oauth2-support): address all code review issues", `f6aa04f6d` 2026-06-26 "feat(mcp-server-oauth2-support): TASK-1662 — MCPClientConfig Extension". So the MCP client auth surface has been frozen since FEAT-262 (MCP OAuth2 support) and FEAT-264 M9 (broker-fed per-user token) landed four months ago — there is no in-flight work and no regression risk from concurrent edits.

## Citations

- sha: `793b3ca21` · 2026-06-29 · Jesus Lara · feat(unified-credential-broker): TASK-1676 — MCP per-user token injection via broker
  files: `packages/ai-parrot/src/parrot/mcp/client.py` (and/or `oauth2_config.py`).
- sha: `4748de100` · 2026-06-26 · Jesus · fix(mcp-server-oauth2-support): address all code review issues
- sha: `f6aa04f6d` · 2026-06-26 · Jesus · feat(mcp-server-oauth2-support): TASK-1662 — MCPClientConfig Extension

## Notes

- Confirms (by history) the wiki hint that the old `OAuthManager` was removed (TASK-1665) and replaced by `MCPOAuth2Config` + broker-fed `token_supplier`/`header_provider` — the brainstorm's R3 "reuse OAuthManager PKCE" premise is moot.
- [cross-lane: type=read, intent=read `mcp/client.py` around `token_supplier`/`header_provider`/`user_id` to confirm whether `user_id` is still bound at config time after TASK-1676]
