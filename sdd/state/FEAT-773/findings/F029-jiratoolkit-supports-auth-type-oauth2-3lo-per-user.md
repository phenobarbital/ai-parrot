---
id: F029
query_id: Q049
type: grep
intent: "R2: JiraToolkit credential wiring — CredentialResolver / credential_provider / per-user client cache."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-030]
---

# F029 — JiraToolkit supports auth_type oauth2_3lo (per-user via CredentialResolver in _pre_execute, client cache keyed '{channel}:{user_id}' → (client, token_hash)), oauth2_local (file resolver), and static basic_auth/token_auth/oauth(1)

## Summary

`parrot_tools/jiratoolkit.py`: imports `AuthorizationRequired` (:61) and `FileTokenCredentialResolver` (:67); `auth_type` doc 'basic_auth | token_auth | oauth' (:213) plus `oauth2_3lo` / `oauth2_local` (:927-930). For `oauth2_3lo` the client is deferred to `_pre_execute` (:1054-1061) with `self._client_cache: Dict[str, tuple] = {}` keyed `"{channel}:{user_id}"` → `(client, token_hash)`. `_pre_execute` (:1316-1345) raises `AuthorizationRequired` when the resolver returns None. Tools stay registered in all modes (:919-920 comment). No `credential_provider` declared on JiraToolkit (grep: 0 hits for `credential_provider`).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 927-936
  symbol: `JiraToolkit.__init__ (oauth2_local -> oauth2_3lo)`
  excerpt: |
    if self.auth_type == "oauth2_local":
        credential_resolver = FileTokenCredentialResolver.from_env()
        self.auth_type = "oauth2_3lo"
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1054-1061
  symbol: `JiraToolkit.__init__ (3LO cache)`
  excerpt: |
    if self.auth_type == "oauth2_3lo":
        self.jira = None  # resolved per-call in _pre_execute
        # Per-user JIRA client cache: {"{channel}:{user_id}": (client, token_hash)}
        self._client_cache: Dict[str, tuple] = {}
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1316-1345
  symbol: `JiraToolkit._pre_execute`
  excerpt: |
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
        if self.auth_type != "oauth2_3lo": return
        ... raise AuthorizationRequired(...)

## Notes

R2 confirmed: `(user_id, token_hash)` client cache exists. JiraToolkit does NOT declare `credential_provider`, so it is NOT routed through the FEAT-264 broker seam — unlike Office365Toolkit. Hot-swap placeholder (`jira_connect_tool.py`) still exists for AgentTalk sessions (FC-041).
