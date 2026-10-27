# G5 — Biscuit Attenuation Spike Report

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Date**: 2026-10-27
**Status**: PASS

---

## Summary

G5 demonstrates that biscuit-python can issue capability-scoped tokens, attenuate them to narrower scopes, and authorize requests against those tokens. The spike proves the three core cases required by spec §3 G5:

1. **Root token on `hr.reports.*`**: ALLOW
2. **Attenuated token on `hr.reports.headcount_by_dept`**: ALLOW
3. **Attenuated token on `hr.people.lookup`**: DENY

---

## Test Results

```
{
  "root_on_reports": true,
  "sub_on_headcount": true,
  "sub_on_people": false,
  "root_wrong_caller": false
}
```

All four cases match the expected table from spec G5.

---

## biscuit-python API

**Version**: Installed via `pip show biscuit-auth` (module name is `biscuit_auth`)

### Key Classes Used

- `KeyPair` — generates Ed25519 keypair for signing
- `BiscuitBuilder` — builds authority block with facts
- `BlockBuilder` — builds attenuation blocks with checks
- `Biscuit` — the token; `.append()` adds blocks, `.to_bytes()` serializes
- `AuthorizerBuilder` — builds authorization context with facts, checks, policies
- `Fact`, `Check`, `Policy` — Datalog primitives
- `AuthorizationError` — raised on authorization failure

### Datalog Features Used

- **Facts**: `capability_glob("hr.reports.*")`, `caller("external-agent")`, `expires(1793151635)`
- **Checks**: `check if caller($c), peer($c)` — verifies caller identity
- **Checks**: `check if expires($e), time($t), $t < $e` — verifies not expired
- **Checks**: `check if capability($c), capability_glob($g), $c.starts_with("hr.reports.")` — glob matching via string method
- **Policies**: `allow if true` — simple allow-all when checks pass

### Important Notes

1. **Glob prefix is a constant in the spike**: `spike.py` hardcodes `starts_with("hr.reports.")` and does not derive it from the token's `capability_glob` fact, so the authorizer does not yet prove glob-from-token matching. M10 MUST compute the prefix from the verified `capability_glob` fact (see M10 Implementation Notes, item 1) and add a regression for a second glob.

2. **Glob matching**: The installed `biscuit-python` does NOT support `.matches()` or `prefix()` in the way expected. Instead, we use the string method `$c.starts_with("hr.reports.")` to match the glob prefix. This is a pragmatic solution that works for the `*` glob pattern.

3. **Token facts extraction**: The authorizer must include facts from the token's authority block. We extract these by parsing `token.block_source(0)` with a regex and adding them as facts to the authorizer.

4. **Exception handling**: `AuthorizationError` is raised when any check fails or no policy matches.

---

## M10 Contract (Datalog)

The following is the exact Datalog that M10's `BiscuitVerifier.authorize` must implement:

### Authorizer Facts (from call)
```
capability("<requested_capability>")
peer("<caller_identity>")
time(<current_timestamp>)
```

### Token Authority Block Facts
```
capability_glob("<root_glob>")
caller("<original_caller>")
expires(<expiry_timestamp>)
```

### Checks
```
check if caller($c), peer($c)
check if expires($e), time($t), $t < $e
check if capability($c), capability_glob($g), $c.starts_with("<glob_prefix>")
```

### Attenuation Block Checks (from token blocks)
```
check if capability("<narrowed_capability>")
```

### Policy
```
allow if true
```

### M10 Implementation Notes

1. **Glob prefix extraction**: For globs ending in `.*`, extract the prefix (e.g., `"hr.reports.*"` → `"hr.reports."`) and use `$c.starts_with("<prefix>")`.

2. **Caller verification**: The token's `caller` fact must match the peer identity from the transport (mTLS). Record this as an M10 rule: "Token's caller fact must equal the authenticated peer identity."

3. **Attenuation enforcement**: The check `check if capability("<narrowed>")` in the attenuation block prevents widening — the token will only authorize if the requested capability matches the narrowed capability.

---

## navigator-auth Change Request

Per spec §8 Q4, the capability token issuance lives in `navigator-auth` (external). This spike generates tokens in-process for demonstration, but production requires the following changes to navigator-auth:

### Issue: Missing Biscuit/Macaroon Support in navigator-auth

**Current State**: navigator-auth 0.28.7 has no Biscuit or macaroon support. It only supports OAuth2 tokens.

**Required Changes**:

1. **Root Key Management**
   - Add Ed25519 key pair generation and storage for Biscuit root keys
   - Keys should be generated per-tenant or per-deployment, never hardcoded
   - Store private keys securely (KMS integration recommended)
   - API: `POST /api/v1/auth/biscuit/keys` — generate new key pair
   - API: `GET /api/v1/auth/biscuit/keys/{kid}` — retrieve public key

2. **Token Lifetime Configuration**
   - Add configuration for Biscuit token TTL (default: 24 hours)
   - Support short-lived tokens for high-security contexts
   - API: `POST /api/v1/auth/biscuit/token` — issue root token
   - Request body: `{ "capabilities": ["hr.reports.*"], "caller": "agent-123", "ttl_hours": 24 }`

3. **Attenuation Endpoint**
   - Add endpoint to create attenuated tokens from existing root tokens
   - API: `POST /api/v1/auth/biscuit/attenuate`
   - Request body: `{ "root_token": "<base64>", "narrowed_capability": "hr.reports.headcount_by_dept" }`
   - Response: `{ "token": "<base64>" }`

4. **Integration with Squawk**
   - Squawk will verify tokens using the public key from `GET /api/v1/auth/biscuit/keys/{kid}`
   - Add CORS and service-to-service auth for Squawk to access the key endpoint

### Change Request Text

> **Title**: Implement Biscuit Token Issuance and Attenuation for Inter-Agent Protocol
>
> **Description**: FEAT-746 introduces Squawk, a typed binary inter-agent protocol that uses Biscuit capability tokens for authorization. navigator-auth must provide token issuance and attenuation endpoints to support this protocol.
>
> **Requirements**:
> 1. Generate and store Ed25519 key pairs for signing Biscuit tokens
> 2. Issue root tokens with capability glob, caller, and expiry facts
> 3. Provide attenuation endpoint to narrow token capabilities
> 4. Expose public key endpoint for token verification by Squawk
>
> **Security Considerations**:
> - Root keys must be stored securely (KMS)
> - Token lifetime should be configurable with sensible defaults (24h)
> - Attenuation must only narrow (never widen) capabilities
> - Caller identity must be verified against transport (mTLS)

---

## References

- Spec: `sdd/specs/inter-agent-protocol.spec.md` §3 G5, §3 M10
- biscuit-python: https://github.com/biscuit-auth/biscuit-python
- Existing token integration: `packages/ai-parrot/src/parrot/auth/token_exchange.py`