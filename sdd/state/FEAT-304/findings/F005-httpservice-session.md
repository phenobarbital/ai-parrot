---
id: F005
query_id: Q005
type: read
intent: Confirm HTTPService.session signature used by flowtask LeadIQ
executed_at: 2026-07-13T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — HTTPService is available in-repo (async GraphQL POST)

## Summary

`parrot.interfaces.http.HTTPService` provides the exact `session(...)`
coroutine flowtask's LeadIQ already calls, plus `request`, `_get`. So the
GraphQL POST logic ports with zero API change: build the payload, call
`await self.http_service.session(method="post", url=..., data=json.dumps(...),
headers=...)`, unpack `(result, error)`. No `requests`/`httpx` needed —
satisfies the async-first, aiohttp-only convention.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/http.py`
  lines: 126, 258, 670, 956
  symbol: `HTTPService`
  excerpt: |
    class HTTPService(CredentialsInterface, PandasDataframe):
        async def session(self, ...): ...
        async def request(self, ...): ...
        async def _get(self, ...): ...

## Notes

FRED (F003) already wires `HTTPService(base_url=..., **kwargs)` as a member —
the recommended composition. Flowtask's `session(**args)` returning
`(result, error)` matches this interface.
