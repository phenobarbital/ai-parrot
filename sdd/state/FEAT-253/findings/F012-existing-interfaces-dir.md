---
id: F012
slug: existing-interfaces-dir
query: "parrot/interfaces/ directory and pattern"
type: read
---

## Finding: interfaces/ exists in core parrot package

**Directory:** `packages/ai-parrot/src/parrot/interfaces/`

### Key files:
- `http.py` — `HTTPService` class (central HTTP client with auth, proxy, retry)
- `soap.py` — `SOAPClient` for WSDL-based services with OAuth token refresh

### HTTPService pattern:
- Accepts credentials dict, auth_type, headers, timeout, proxy config
- `async_request()` method creates `aiohttp.ClientSession`
- Auth header injection in a single method
- Error handling: raises `ConnectionError` on 4xx/5xx

### Relevance:
- User requested placing interface at `parrot_tools/interfaces/gigsmart/api.py`
- But existing interfaces are at `parrot/interfaces/` (core package)
- The GigSmart aiohttp interface layer should follow HTTPService patterns
- The toolkit layer goes in `parrot_tools/gigsmart/`
