---
id: F009
query_id: Q016
type: read
intent: OpenAPIToolkit auth surface, HTTP client and the httpx ban.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — OpenAPIToolkit transports through aiohttp HTTPService (cookies supported) but only knows bearer/apikey/basic — no cookie-session login, and it is TID251-exempt for a sync httpx spec fetch

## Summary

Constructor `OpenAPIToolkit(spec, service, base_url=None, api_key=None, auth_type="bearer"|"apikey"|"basic", auth_header, api_key_location, api_key_name, credentials, use_proxy, timeout, debug, **kwargs)`; builds `HTTPService(accept='application/json', headers=..., credentials=creds, ...)` (lines 136-158) and every generated tool calls `await self_ref.http_service._request(url, method, params, headers, use_json, data, full_response=False, raise_for_status=False)` (lines 695-770), so the request path is aiohttp. `httpx` is imported (line 29) and used synchronously only to fetch a spec URL (line 255); `ruff.toml` bans httpx repo-wide (TID251, line 127) and per-file-exempts this file (161) and `interfaces/http.py` (156). `HTTPService.__init__` accepts `cookies` (line 191) and `session()` forwards `cookies`/`headers` (277, 351) — a session cookie (`sid`) can be injected but nothing performs a login handshake. File untouched since 2026-03-23 (monorepo migration).

## Citations


- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  lines: 62-93
  symbol: `OpenAPIToolkit.__init__`
  excerpt: |
    auth_type: str = "bearer",  # "bearer", "apikey", "basic"
    credentials: Optional[Dict[str, str]] = None,  # username/password for basic auth

- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  lines: 136-158
  symbol: `HTTPService wiring`
  excerpt: |
    self.http_service = HTTPService(accept='application/json', headers=headers, credentials=creds, use_proxy=use_proxy, timeout=timeout, debug=debug, **kwargs)

- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  lines: 29, 255
  symbol: `httpx usage`
  excerpt: |
    import httpx  # 29
    response = httpx.get(spec, timeout=30)  # 255 (sync spec fetch)

- path: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py`
  lines: 695-770
  symbol: `_create_operation_method`
  excerpt: |
    result, error = await self_ref.http_service._request(**request_kwargs, full_response=False, use_proxy=False, raise_for_status=False)

- path: `packages/ai-parrot/src/parrot/interfaces/http.py`
  lines: 140-191, 272-351
  symbol: `HTTPService`
  excerpt: |
    class HTTPService(CredentialsInterface, PandasDataframe):  # 140
    self.cookies = kwargs.get('cookies', {})  # 191
    async def session(self, ..., cookies: dict = None, headers: dict = None, ...)  # 272-277
    args = {"timeout": timeout, "headers": headers, "cookies": cookies}  # 351

- path: `ruff.toml`
  lines: 113, 125-127, 156, 161
  symbol: `TID251 banned-api`
  excerpt: |
    "httpx".msg = "Use aiohttp — httpx is banned in this repository."
    "packages/ai-parrot/src/parrot/interfaces/http.py" = ["TID251"]
    "packages/ai-parrot/src/parrot/tools/openapitoolkit.py" = ["TID251"]

## Notes

git log (Q035): only 4953611047 2026-03-23 TASK-398 workspace scaffolding in the last year.

