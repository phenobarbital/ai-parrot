# TASK-559: Add API authentication to handler endpoints

**Feature**: FEAT-080 formdesigner-package-fixes
**Status**: pending
**Priority**: critical
**Estimated effort**: medium

## Context

All 8 API routes in `handlers/api.py` are completely open with no authentication. The `POST /api/forms/from-db` endpoint executes live PostgreSQL queries, and `POST /api/forms` drives LLM calls at the operator's API key expense. This is a cost-amplification and data-enumeration attack vector.

## Tasks

### 1. Implement authentication check

**File**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`

Follow the AI-Parrot integration handler pattern (as used in Telegram/Slack/MS Teams handlers) where `_is_authorized()` is called before processing.

Options (discuss with team):
- **Option A**: Bearer token validation via middleware
- **Option B**: `_is_authorized(request)` method on `FormAPIHandler` checking a shared secret header
- **Option C**: Integration with existing AI-Parrot auth middleware

Minimum viable implementation — shared secret:
```python
import hmac

class FormAPIHandler:
    def __init__(self, *, registry, client=None, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("PARROT_FORM_API_KEY")

    def _is_authorized(self, request: web.Request) -> bool:
        if not self._api_key:
            return True  # No key configured = open (dev mode)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return hmac.compare_digest(token, self._api_key)
```

### 2. Guard all endpoints

Add to each handler method:
```python
if not self._is_authorized(request):
    return web.json_response({"error": "Unauthorized"}, status=401)
```

### 3. Wire API key through `setup_form_routes`

**File**: `handlers/routes.py`

Add `api_key` parameter:
```python
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: AbstractClient | None = None,
    api_key: str | None = None,
    prefix: str = "",
) -> None:
```

### 4. Return proper HTTP status codes

- `401 Unauthorized` when no credentials provided
- `403 Forbidden` when credentials are invalid
- Clear error messages in JSON response body

## Acceptance Criteria

- [ ] All 8 API routes check authorization before processing
- [ ] `POST /api/forms` (LLM cost) is protected
- [ ] `POST /api/forms/from-db` (DB access) is protected
- [ ] Auth can be disabled for development (no key = open)
- [ ] API key passed via environment variable, not hardcoded
- [ ] 401/403 responses with clear error messages
- [ ] `setup_form_routes` accepts and forwards auth config
