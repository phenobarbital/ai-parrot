# F011 — VaultTokenSync + per-user token persistence (EXISTS) + recent A2A/MS-SDK WIP

**Query**: Q009/Q015 (grep vault; git log a2a + oauth2)
**Verdict**: vault EXISTS; active in-flight work on A2A + MS Agent SDK.

- `parrot/services/vault_token_sync.py` → `VaultTokenSync.store_tokens(...)` for encrypted per-user token persistence; used by `integrations/telegram/post_auth_jira.py:227` (`_store_in_vault`, flat keys per user).
- git (a2a core): `6d9b8b3ed wip: a2a server + ms agent sdk`, `05885166d TASK-1370 Move A2A server files to satellite` (ai-parrot-server), `e7c97b7c3 TASK-1367 lazy __getattr__`.
- git (oauth2): `b865256f4 TASK-1342 OAuth2 Relocation to parrot/auth/oauth2/`, `ebe33d620 fix code review issues`.
- Related prior art (memory): `reference_copilot_a2a_agentcard` — Copilot card needs `preferredTransport` (now in code, F005); `FEAT-259 msagentsdk` tenant-auth work in flight.

**Implication**: Credential custody store exists (vault). A2A + MS Agent SDK are under active WIP (`6d9b8b3ed`), confirming this is continuation work, not greenfield. The spec must coordinate with the in-flight MS Agent SDK branch (FEAT-259) to avoid divergence.
