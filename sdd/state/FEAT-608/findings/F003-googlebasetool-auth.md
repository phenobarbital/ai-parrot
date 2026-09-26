---
id: F003
query_id: Q003
type: wiki_page
intent: Read GoogleBaseTool (auth_mode handling, client cache) — the analogue of O365Tool._get_client
executed_at: 2026-09-25T22:52:05Z
duration_ms: 600
parent_id: null
depth: 0
---

# F003 — `GoogleBaseTool._get_client` defines the three Google auth modes to reproduce

## Summary

`parrot_tools/google/base.py` mirrors `O365Tool` for Google: `GoogleAuthMode`
(`service_account` / `user` / `cached`), `GoogleToolArgsSchema` (per-call
`auth_mode`, `scopes` overrides) and `GoogleBaseTool._get_client(auth_mode,
scopes)` which builds a `GoogleClient`, then `initialize()` (service account),
`interactive_login()`+`initialize()` (user), or `initialize()` with fallback to
interactive login when the cached-session error is raised (cached). Clients are
cached per `auth_mode:scopes`. This is exactly the branch table the FEAT-603
spec copied from `O365Tool._get_client` into `GraphDriveFileManager.connect()`.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/google/base.py`
  lines: 15-20
  symbol: `GoogleAuthMode`
  excerpt: |
    class GoogleAuthMode:
        SERVICE_ACCOUNT = "service_account"
        USER = "user"
        CACHED = "cached"

- path: `packages/ai-parrot-tools/src/parrot_tools/google/base.py`
  lines: 23-33
  symbol: `GoogleToolArgsSchema`
  excerpt: |
    auth_mode: Optional[str] = Field(default=None, description="Authentication mode: 'service_account', 'user', or 'cached'.")
    scopes: Optional[Union[str, List[str]]] = Field(default=None, ...)

- path: `packages/ai-parrot-tools/src/parrot_tools/google/base.py`
  lines: 44-66
  symbol: `GoogleBaseTool.__init__`
  excerpt: |
    def __init__(self, credentials=None, default_auth_mode=GoogleAuthMode.SERVICE_ACCOUNT, scopes=None,
                 user_creds_cache_file=None, open_browser=True, login_callback=None,
                 interactive_login_kwargs=None, interactive_timeout=300, **kwargs)

- path: `packages/ai-parrot-tools/src/parrot_tools/google/base.py`
  lines: 82-135
  symbol: `GoogleBaseTool._get_client`
  excerpt: |
    if resolved_auth_mode == GoogleAuthMode.SERVICE_ACCOUNT:
        await client.initialize()
    elif resolved_auth_mode == GoogleAuthMode.USER:
        await client.interactive_login(scopes=..., open_browser=..., login_callback=..., timeout=..., **self.interactive_login_kwargs)
        await client.initialize()
    elif resolved_auth_mode == GoogleAuthMode.CACHED:
        try: await client.initialize()
        except RuntimeError as auth_error:
            if "User credentials not available" not in str(auth_error): raise
            await client.interactive_login(...); await client.initialize()

- path: `packages/ai-parrot-tools/src/parrot_tools/google/base.py`
  lines: 156-163
  symbol: `GoogleBaseTool._execute_google_operation`
  excerpt: |
    @abstractmethod
    async def _execute_google_operation(self, client: GoogleClient, **kwargs) -> Any: ...

## Notes

No tool currently subclasses `GoogleBaseTool` for Drive (F006). The Google
tools that exist (`GoogleSearchTool`, places, routes) bypass `GoogleClient`
and use `googleapiclient.discovery.build` / raw aiohttp instead
(`tools.py:15`).
