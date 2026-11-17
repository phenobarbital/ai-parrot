# Design research triage — FEAT-777 connections-web-slack (S-3a of FEAT-773)

Model: gpt-5.6-luna (codex-cli 0.164.0) · Status: completed · 12 suggestions.
Every `affected_paths` entry passed containment (`spec_tools check-path`) and existence (`test -e`).

The brief was built from the parent proposal (FEAT-773, accepted) scoped to the S-3a row. Several
suggestions target contracts that the S-1 spec (`sdd/specs/delegated-auth-connections.spec.md`) already
fixes; those are REJECTED here as "owned by S-1", with the S-1 anchor named, not as wrong.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make durable persistence a required completion outcome (risk) | REJECT | Owned by S-1: durable-first `_persist_token` + `CredentialPersistenceError` (S-1 M2, AC-5). S-3a's O365 device-code path reuses that method instead of writing its own store. | — (S-1 AC-5); §3 M3 reuses it |
| S2 | Resolve and bind the Navigator principal before OAuth starts (architecture) | CONFIRM | Slack `/connect` refuses without a resolved principal; the link is created only by an authenticated web session consuming a signed one-time nonce; no principal is ever read from client-supplied state. | §2 Overview, §3 M2, AC-5/AC-6 |
| S3 | Choose and enforce multi-account semantics (api) | REJECT | Decided in S-1 (S3): single account per provider in v1, replace on reconnect, `account_id` carried everywhere. The panel shows one account per provider. | — |
| S4 | Remove agent enablement as a complete contract migration (architecture) | CONFIRM | S-3a removes `/enable` (route, handler branch, `EnableResponse`, `confirmIntegrationEnable`) and moves the menu + pill to `/api/v1/connections` in the same module. | §3 M5, AC-9 |
| S5 | Persist the metadata the Connections API promises (api) | REJECT | S-1 M6 adds `scopes_granted`, `expires_at`, `channels`, `canonical_identity` to the row/descriptor. S-3a only renders them (AC-1). | — (S-1 M6) |
| S6 | Apply PBAC to connect and revoke (risk) | REJECT | S-1 AC-8 (`integration:connect` / `integration:disconnect`, fail closed). S-3a's new link-confirm route is session-authenticated and binds only the caller's own id. | — (S-1 AC-8) |
| S7 | Route push events by principal with cross-process delivery semantics (architecture) | CONFIRM (modified) | User chose SSE over WebSocket (FEAT-476 non-goal kept). Streams keyed by Navigator `user_id`, Redis pub/sub across workers; reconnect = client backoff + full refetch; duplicates harmless (panel refetches state); offline = no buffering, `GET` is authoritative. | §2 Overview, §3 M1, AC-2/AC-3 |
| S8 | Define connection events separately from usage fanout (architecture) | REJECT | S-1 M4 owns `ConnectionEvent` (token-free) and `setup_connection_fanout`. S-3a adds a test that an SSE frame carries only `ConnectionEvent` fields. | — (S-1 M4); §4 test |
| S9 | Specify an idempotent retry contract for the UI (api) | CONFIRM | Auto-retry keyed by the `auth_required` message id: at most once, only when the completion's provider matches, only if no newer user message exists; otherwise a Retry button. | §3 M4, AC-7 |
| S10 | Normalize needs-auth at a shared boundary, keep native details (alternative) | REJECT | S-1 M5 (`AuthRequiredPayload` superset). S-3a's streaming `auth_required` trailer carries the full payload, device-code fields included. | — (S-1 M5); §3 M4 |
| S11 | Keep provider-specific store capabilities explicit during O365 migration (alternative) | CONFIRM (modified) | User chose full consolidation, so device-code and 3LO share one principal-keyed record. The concern is kept: the record carries `grant_origin`, and both flows already refresh through `O365OAuthManager.refresh_access_token` (o365_devicecode_provider.py:159-176), so one refresh path is safe. | §3 M3, §7 risks |
| S12 | Make migration correctness a cross-channel acceptance gate (testing) | CONFIRM | Tests: multi-worker SSE delivery, Slack linked/unlinked, O365 legacy `o365:*` migrated exactly once. The Telegram legacy-key matrix stays in S-1/S-2. | §4, AC-12 |

Summary: 6 confirmed (2 modified) · 6 rejected (all "owned by S-1") · 0 escalated.
