# Design research triage — FEAT-773 (model gpt-5.6-luna, codex-cli 0.164.0)

All `affected_paths` passed containment (`spec_tools check-path`) and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make principal binding explicit in OAuth state (architecture) | CONFIRM | Matches the U1 decision; `AbstractOAuth2Manager` binds a `Principal` into the nonce payload at start and verifies it at callback, failing closed. | §2 Overview, §3 M1/M2 |
| S2 | Do not silently succeed when durable persistence fails (risk) | CONFIRM | Verified: `_persist_token` swallows vault failures (oauth2_base.py:415-420) and the Jira sink failure is logged after Redis (jira_oauth.py:541-548). With the Identity Vault as owner, callback success now requires the durable write; Redis is written only after it. | §3 M2, §5 AC |
| S3 | Resolve account cardinality before changing keys (api) | CONFIRM | v1 is explicitly single-account-per-provider with replace-on-reconnect; `account_id` is carried on rows, status, events and the DELETE semantics are documented. | §2 Data Models, §7 |
| S4 | Enforce PBAC on connect and revoke (risk) | CONFIRM | Verified: `start_connect` (service.py:291) checks origin + registry only; `_check_pbac` (service.py:490) exists. `integration:connect` / `integration:disconnect` added, with requested scopes as context. | §3 M6, §5 AC |
| S5 | Separate connection ownership from agent capability enablement (architecture) | CONFIRM (modified) | U2 decided to drop per-agent enablement, so no separate capability mechanism is built; but the hydration path (`user_objects.py:218` reads `list_user_agent_toolkits`) switches to principal connections in the same module, and `/enable` stays as a compatibility no-op until S-3a removes the UI call. | §3 M6, §7 risks |
| S6 | Define cross-process notifier delivery explicitly (architecture) | CONFIRM (constraint) | U5 keeps the in-process registry load-bearing; the same-process constraint is recorded, notifier failures never fail a callback, bus publication covers out-of-process consumers, and the Redis-backed web delivery is S-3a scope. | §3 M4, §7 |
| S7 | Distinguish invalid refresh tokens from transient failures (risk) | CONFIRM | Verified at oauth2_base.py:543-550: any `PermissionError` from `_refresh_request` revokes; typed `InvalidGrantError` (revoke + `connection.refresh_failed`) vs `RefreshTransientError` (no revoke) added. | §3 M2 |
| S8 | Use a superset needs-auth contract (api) | CONFIRM | `AuthRequiredPayload` carries the union of `AuthorizationRequired` and `CredentialRequired` fields; ToolManager and AgentTalk serialize the same payload. | §3 M5 |
| S9 | Make MCP credential resolution genuinely per-call (architecture) | CONFIRM | Verified: `inject_broker_credential` (client.py:242, 282) gates injection and `create_oauth_mcp_server` drops `user_id`. Per-call supplier over the broker replaces add-time binding. | §3 M9 |
| S10 | Keep provider-specific behavior typed before introducing YAML hooks (alternative) | CONFIRM (modified) | Descriptor stays a typed Pydantic model for metadata/endpoints/scopes/PKCE/refresh policy; the standard RFC 6749 exchange/refresh is generic code; post-exchange hooks are a typed in-code registry (Atlassian only), never YAML-imported callables; O365 keeps its subclass. | §3 M3, §7 |
| S11 | Require a migration and isolation contract matrix before cutover (testing) | CONFIRM | Added as §4 tests: principal-keyed dual read, cross-channel reuse, unlinked-user rejection, legacy-key deletion, concurrent refresh, notifier failure isolation, durable-write-required callback, CredentialRequired serialization. | §4 |

Summary: **11** confirmed (3 with modifications) · **0** rejected · **0** escalated.
