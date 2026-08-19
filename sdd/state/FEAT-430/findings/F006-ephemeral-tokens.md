# F006 — navigator-auth ephemeral tokens: exist, but are user-scoped, not dashboard-scoped

**Query:** Q011 (grep + read, navigator-auth)
**Citations:** `navigator-auth/navigator_auth/backends/idp/__init__.py`
  :: `create_ephemeral_token` (L265-269), `create_token` (L271-300);
  `navigator-auth/navigator_auth/auth.py` :: ephemeral-token endpoint (L321-336)
**Confidence:** high (direct source read)

## Confirmed

Ephemeral tokens exist and are JWTs:

```python
def create_ephemeral_token(self, data: dict = None, expiration: int = 1800) -> tuple:
    """Create an Ephemeral Token (short-lived) for accessing resources.
    default expiration: 30 minutes."""
    return self.create_token(data=data, expiration=expiration)
```

`create_token` builds `{"exp": ..., "iat": ..., "iss": AUTH_TOKEN_ISSUER, **data}` and
signs with `SECRET_KEY` / `AUTH_JWT_ALGORITHM`. **`data` is arbitrary**, so custom
claims are possible.

## Corrections to brainstorm §3.4

1. **"1-24h lifetime" is not a built-in property.** The default is `expiration=1800`
   (30 minutes). Any lifetime is achievable by passing `expiration` in seconds, so a
   1-24h TTL policy is implementable — but it is a decision SPEC-A must make and pass
   explicitly, not an existing capability to inherit.

2. **The existing token is user-scoped, not resource-scoped.** The HTTP endpoint mints
   a token for the *currently authenticated caller*:

   ```python
   if not request.get("authenticated", False):
       raise self.Unauthorized(reason="Access Denied")
   user = request.user
   payload = {"user_id": user.user_id, "username": user.username, "user": user.user_id}
   ```

   There is **no `dashboard_id` (or any resource) scope claim**. A token minted this way
   grants the recipient the *sender's* identity — strictly worse than the current
   `AMBASSADOR_ANONYM_USER_TOKEN` (F005), which is at least an anonymous identity.

## Consequences for SPEC-A (design work the brainstorm under-scopes)

Delivering HI-3 requires **two** pieces that do not exist today:

- **Minting:** a share token carrying a scope claim (e.g. `{"dashboard_id": ..., "scope":
  "share"}`) with an explicit TTL. Feasible via `create_token(data=...)` — but it must be
  called as a **library call from backend/scheduler context**, since the HTTP endpoint
  requires an authenticated request and the scheduler has no user session.
- **Enforcement:** the `/share/dashboard/<id>` path must validate that claim and refuse a
  token whose `dashboard_id` does not match the requested dashboard. Nothing found so far
  performs scope-claim enforcement; today the apikey is simply accepted.

Brainstorm §4.1.B treats sharing as "reuse Navigator's existing dashboard sharing".
That reuse is real for the **URL shape** (F005) but the **secure token model is new
construction**, and it is the single largest under-estimated item in SPEC-A's build delta.
