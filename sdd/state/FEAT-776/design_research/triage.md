## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (the FEAT-773 proposal,
> S-2 row). Model: `gpt-5.6-luna` · Status: completed · Transcript: `sdd/state/FEAT-776/design_research/`.
> The reviewer answered at the scale of the whole FEAT-773 initiative; suggestions that belong to S-1 are
> rejected here as out of scope (FEAT-773's own §9 already disposed of the same points).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make Jira persistence an explicit principal-aware store adapter (architecture) | REJECT | S-1 scope; FEAT-773 M2/M7/M8 adopt `CredentialStore` with durable-first writes. | — |
| S2 | Resolve a typed principal once; keep channel identity separately (architecture) | CONFIRM | Commands, needs-auth prompts and post-auth build one `Principal` from the session; `chat_id`/`bot_id` are delivery data only. | §2 M4/M6, §7 |
| S3 | Specify migration semantics, metric and rollback before cutover (risk) | CONFIRM (partly) / ESCALATE | Date gate, dry run, counts, channel-only patterns and exclusive relink adopted; "don't make forced reconnect the only recovery" rejected (U3 resolved); rollback backup escalated. | §2 M10, M4; §8 Q2 |
| S4 | FEAT-144 reversal is a session-hydration migration (architecture) | REJECT | S-1 scope (FEAT-773 M6 hydration from connections). | — |
| S5 | Don't expose the whole OAuth registry through channel commands (api) | CONFIRM | Connectable filter (manager present, not `mcp:*`, allowlist), PBAC before state, server-owned scopes. | §2 M5, AC-4 |
| S6 | Centralize needs-auth mapping, keep device-code fields (api) | CONFIRM | Mapping stays FEAT-773 M5; the Telegram renderer consumes `AuthRequiredPayload` incl. device-code fields. | §2 M8, AC-9 |
| S7 | Adapt JiraToolkit to the broker seam as client construction (architecture) | REJECT | Owned by FEAT-773 M7. | — |
| S8 | Keep provider behaviour in subclasses until stable (alternative) | REJECT | S-1 decision (FEAT-773 §9 S10); S-2 consumes whatever the registry holds. | — |
| S9 | Request-scoped MCP credential resolution (risk) | REJECT | S-1 / S-4 scope. | — |
| S10 | Event ordering and delivery failure semantics (risk) | CONFIRM | Telegram notifier logs, never raises, idempotent; event emission order stays FEAT-773's. | §2 M7, §7 |
| S11 | Cross-channel migration matrix before deleting legacy routes (testing) | CONFIRM | Telegram rows of the matrix: link/unlink, unlinked forced reconnect, cross-channel reuse, purge isolation. | §4 Integration Tests |

Summary: **6** confirmed (one partly) · **5** rejected · **1** escalated.
