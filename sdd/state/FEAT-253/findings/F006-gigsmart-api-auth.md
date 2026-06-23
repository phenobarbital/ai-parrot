---
id: F006
slug: gigsmart-api-auth
query: "GigSmart API authentication mechanism"
type: web
---

## Finding: OAuth 2.1 with PKCE, NOT simple API key

### Auth endpoints:
- Authorize: `https://api.gigsmart.com/oauth/authorize`
- Token: `https://api.gigsmart.com/oauth/token`

### Two grant types:
1. **Authorization Code + PKCE** (user-facing): tokens expire 1 hour, refresh available
2. **Client Credentials** (server-to-server): tokens expire 15 minutes, no refresh

### Token request (client credentials):
```bash
curl -X POST https://api.gigsmart.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d "grant_type=client_credentials&scope=read:gigs"
```

### Response:
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "dGhpcyBpcyBhIHJlZnJl...",
  "scope": "read:gigs read:engagements"
}
```

### Rate limiting headers:
- `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

### Correction to SPEC:
- SPEC §3 assumes simple `Authorization: Bearer <api_key>` — WRONG
- Actual auth is OAuth 2.1 with client_id + client_secret → token exchange
- Need token refresh logic, expiry tracking, scope management
