---
id: F008
query: "Check MSAgentSDKConfig for OAuth/OBO fields"
type: read
path: packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py
lines: 9-131
---

## Finding

MSAgentSDKConfig fields:
- `name`, `chatbot_id` — identity
- `client_id`, `client_secret`, `tenant_id` — Azure AD app auth
- `anonymous_auth: bool` — dev mode
- `api_key`, `api_key_header` — inbound API-key auth
- `app_type: str` — SingleTenant/MultiTenant
- `authority: Optional[str]` — custom authority URL

**Missing fields needed for auth/OBO**:
- No `oauth_connections: dict[tool→connection_name]`
- No `obo_scopes: dict`
- No user-facing OAuth configuration at all
