# F001 — CredentialResolver IS the link-out seam (EXISTS)

**Query**: Q001 (grep `class CredentialResolver`)
**Verdict**: VERIFIED EXISTS — brainstorm §7 ⚠️VERIFY resolved.

- `packages/ai-parrot/src/parrot/auth/credentials.py:27` — `class CredentialResolver(ABC)`.
- API: `async resolve(channel, user_id) -> creds | None`, `async get_auth_url(channel, user_id) -> str`, `async is_connected(...)`.
- `OAuthCredentialResolver` (l.49) delegates to a manager exposing `get_valid_token` / `create_authorization_url` (ref impl `JiraOAuthManager`; docstring explicitly anticipates O365/GitHub managers).
- `StaticCredentialResolver` (l.81) for legacy basic/token auth.
- Referenced from `tools/manager.py`, `auth/oauth2/registry.py`, `auth/oauth2/jira_provider.py`, `bots/jira_specialist.py`, `bots/github_reviewer.py`.

**Implication**: The brainstorm's "resolve → None → emit consent link" flow is *already the contract*. `resolve()==None` is the documented signal to surface `get_auth_url()`.
