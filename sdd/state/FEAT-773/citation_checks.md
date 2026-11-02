# Citation probe (§4d) — FEAT-773

Probe sheet: `probe_sheet.json` (282 checks: 160 file, 114 symbol, 8 absent), run as 8 `sdd-contract-probe` agents at HEAD `5fa785952`.

| Result | Count | Notes |
|---|---|---|
| verified | 268 | every cited file exists with cited line ≤ line count; every `def/class` symbol found once with signature |
| stale | 2 | F030 `_build_credential_sink` → actual `_build_jira_credential_sink` (integrations/manager.py:81); F076 `parrot/integrations/mcp/fireflies_a2a.py` lives in ai-parrot-integrations, not core |
| absent (expected) | 9 | NeedsAuthorizationError, WebOAuthManager, ConnectionManager, OAuthProviderRegistry, VaultCredentialResolver, CredentialVault, ConnectionChannel, AuthRequirement, parrot/connections/__init__.py — all absent in `packages/` |
| not-a-def (ignored) | 11 | attribute/alias/import citations probed as `symbol` (AuthKind, credential_provider, token_supplier, header_provider, user_id, EventBus, `module`, `import`) — spot-checked inline: EventBus used at orchestrator.py:30,240; credential_provider attr at toolkit.py:331 |
| directory (ignored) | 3 | tree citations (ui/src/lib/oauth, …/integrations, …/stores) |

Verdict: no `missing` claim; two `stale` claims tagged in the owning findings' Notes.
