---
id: F005
query: "Verify inbound auth (JWT + API-key) in msagentsdk wrapper"
type: read
path: packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py
lines: 251-360
---

## Finding

`handle_request()` implements two inbound auth schemes:
1. Bot Framework JWT via `JwtTokenValidator` (Authorization header)
2. API Key via configurable header (default `x-api-key`)

Both populate `request["claims_identity"]`. Anonymous mode supported for dev.

Outbound auth uses `MsalConnectionManager` with a single `SERVICE_CONNECTION`
entry — this is the bot↔connector service auth only. No user-facing OAuth
connection is configured or referenced.

`_AnonymousConnectionManager` (lines 22-59) provides a dev-only path that
skips real token acquisition. Explicitly warned "Do NOT use in production."
