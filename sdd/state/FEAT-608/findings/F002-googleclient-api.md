---
id: F002
query_id: Q002
type: wiki_page
intent: Read GoogleClient API outline (auth modes, execute_api_call, get_drive_client)
executed_at: 2026-09-25T22:52:05Z
duration_ms: 700
parent_id: null
depth: 0
---

# F002 — `GoogleClient` is an aiogoogle discovery client with two auth types and no Drive helpers

## Summary

`GoogleClient(credentials, scopes, user_creds_cache_file)` loads service-account
JSON (file/dict/string) or OAuth client JSON (`installed`/`web`), exposes
`initialize()`, `execute_api_call(service, resource, method, version, **kw)`
(opens a fresh `Aiogoogle` per call and dispatches `as_service_account` /
`as_user`), `interactive_login(...)`, `ensure_interactive_session()`, `close()`
(only flips `_authenticated`). `get_drive_client()` returns a bare config dict
`{"service": "drive", "version": "v3"}` — there is no Drive wrapper analogous
to `CalendarClient`. The constructor eagerly creates an `aioredis` client for
user-credential caching. `DEFAULT_SCOPES["drive"]` already lists the three
Drive scopes.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 226-290
  symbol: `GoogleClient.__init__`
  excerpt: |
    self.auth_type: str = "service_account"  # or 'user'
    self.redis_url: str = kwargs.get("redis_url", REDIS_HISTORY_URL or "redis://localhost:6379/0")
    self.redis = aioredis.from_url(self.redis_url, ...)          # eager, in __init__
    self.scopes: List[str] = self._process_scopes(scopes or "all")
    self.user_creds_cache_file = BASE_DIR.joinpath("env", "google", "user_creds.json")

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 41-47
  symbol: `DEFAULT_SCOPES`
  excerpt: |
    "drive": [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ],

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 650-703
  symbol: `GoogleClient.initialize`
  excerpt: |
    if self.auth_type != "service_account":
        ... await self._load_user_creds_from_redis(...) or self._load_cached_user_creds()
        else: raise RuntimeError("Google: User credentials not available. Run interactive_login() first.")
    elif self.auth_type == "service_account":
        self._service_account_creds = ServiceAccountCreds(scopes=self.scopes, **creds_dict)

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 705-769
  symbol: `GoogleClient.execute_api_call`
  excerpt: |
    async with Aiogoogle(service_account_creds=self._service_account_creds, user_creds=self._user_creds) as aiogoogle:
        api = await aiogoogle.discover(service_name, version)
        method = getattr(getattr(api, api_name), method_chain)
        result = await aiogoogle.as_service_account(method(**kwargs))  # or as_user

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 771-772
  symbol: `GoogleClient.get_drive_client`
  excerpt: |
    async def get_drive_client(self, version: str = "v3") -> Dict[str, Any]:
        return {"service": "drive", "version": version}

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 827-836
  symbol: `GoogleClient.interactive_login`
  excerpt: |
    async def interactive_login(self, scopes=None, port=5050, redirect_uri=None, open_browser=True,
                                browser="system", login_callback=None, timeout=300) -> Dict[str, Any]:

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 1051-1054
  symbol: `GoogleClient.close`
  excerpt: |
    async def close(self) -> None:
        self._authenticated = False

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 1059-1075
  symbol: `GoogleClient.ensure_interactive_session`
  excerpt: |
    if not loaded and not self._load_cached_user_creds():
        raise RuntimeError("Google: no cached session; call interactive_login()")

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  lines: 160-224
  symbol: `CalendarClient`
  excerpt: |
    class CalendarClient:  # FEAT-453 — thin wrapper promoted from get_calendar_client()'s config dict
        async def insert_event(...): return await self._client.execute_api_call("calendar", "events", "insert", ...)

## Notes

`execute_api_call` discovers the API on **every** call (`aiogoogle.discover`),
which is fine for a few metadata calls but costly for a chunked upload or a
paginated listing — a Drive manager will want to hold one `Aiogoogle` session
+ discovered `drive` API per manager lifetime (see F013 for media kwargs).
`close()` does not close the Redis client.
