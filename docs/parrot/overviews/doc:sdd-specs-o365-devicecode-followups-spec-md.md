---
type: Wiki Overview
title: 'Feature Specification: O365 Device-Code Follow-ups — CLI tenant/roles hardcoding
  + non-atomic token persistence'
id: doc:sdd-specs-o365-devicecode-followups-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The FEAT-266 code review surfaced two gaps in the newly-merged `device_code`
  O365 broker path
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: O365 Device-Code Follow-ups — CLI tenant/roles hardcoding + non-atomic token persistence

**Feature ID**: FEAT-267
**Date**: 2026-07-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x

> Input: code review of FEAT-266 (`sdd/specs/o365-auth-homologation.spec.md`), findings
> "Important Issues" #1 and #2. Both items were explicitly called out as non-blocking for the
> FEAT-266 merge but tracked here as fast follow-ups.

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-266 code review surfaced two gaps in the newly-merged `device_code` O365 broker path
that are dormant today but become real risks as adjacent work lands:

1. **CLI `PermissionContext` hardcodes tenant/roles.**
   `build_cli_permission_context()` (`packages/ai-parrot/src/parrot/cli/identity.py:80`) builds
   `UserSession(user_id=canonical, tenant_id=CLI_CHANNEL, roles=frozenset())` — i.e.
   `tenant_id="cli"` (the channel literal, not a real tenant/org id) and zero roles,
   unconditionally, for every CLI device-code user. `PermissionContext.tenant_id`/`.roles` feed
   directly into `to_eval_context()` (`parrot/auth/permission.py`) for PBAC policy evaluation.
   Today this is inert: no CLI path wires a `ToolManager._resolver`, and no tool in the repo
   declares `_required_permissions` via `@requires_permission`, so the gate at
   `tools/abstract.py:544` (`pctx is not None and resolver is not None`) short-circuits. The
   moment PBAC/role-gating is wired onto the CLI surface, every device-code CLI user silently
   collapses into tenant `"cli"` with no roles — breaking any tenant-scoped or role-scoped
   policy with no error, no log, no signal.

2. **`VaultTokenSync.store_tokens` is not atomic and a missing `expires_at` reads as "valid
   forever."**
   `store_tokens()` (`packages/ai-parrot-server/src/parrot/services/vault_token_sync.py:131-164`)
   writes each `tokens[key]` with an individual `await vault.set(...)` inside a loop, wrapped in
   a single broad `except Exception` that logs and swallows. A failure partway through the loop
   (e.g. `access_token` written, `expires_at` write fails/vault hiccup) leaves a token set with
   `access_token` present and `expires_at` absent. `O365DeviceCodeCredentialResolver.resolve()`'s
   cache-hit check (`o365_devicecode_provider.py:145`:
   `expires_at is None or expires_at > time.time() + _EXPIRY_SKEW_SECONDS`) treats a missing
   `expires_at` as **valid indefinitely** — the same fallback used deliberately in
   `is_connected()` (`o365_devicecode_provider.py:188`) for a legitimately-absent field on a
   fresh dict. FEAT-266 is the **first production writer** of `o365:*` keys (previously nothing
   wrote them, only `WorkIQOBOCredentialResolver` read them), so this is the first place the gap
   becomes exercised in practice: a stale/dead token could be trusted forever with no reactive
   re-validation path on a real 401 from Graph.

### Goals

- Make the CLI `PermissionContext` construction honest: either accept a real `tenant_id`
  distinct from the `"cli"` channel literal, or make the placeholder nature of `tenant_id="cli"`
  impossible to silently misuse once PBAC lands (fail loud, not fail silent).
- Make `VaultTokenSync.store_tokens` resilient to partial failure: either persist atomically
  (single multi-field vault write, if the vault backend supports it) or change the write order /
  validation so a partial write cannot leave a token set that reads as "permanently valid."
- Keep both fixes additive/backward-compatible — no behavior change for existing callers
  (Telegram/jira/fireflies/workiq paths) outside the two specific gaps described.

### Non-Goals (explicitly out of scope)

- Wiring PBAC/role-gating onto the CLI surface itself — that is separate, larger work tracked
  elsewhere; this feature only prevents the CLI identity seam from becoming a silent landmine
  for that future work.
- Building a reactive token-invalidation path (e.g. catching a live 401 from Graph and evicting
  the cached vault entry) — out of scope; this feature only closes the "missing `expires_at`
  written by a partial failure gets treated as forever-valid" gap at write/read time.
- Any change to the Gen 2/3 OAuth2 3LO flow, `O365OAuthManager.get_valid_token()`'s internal
  refresh, or any surface beyond the two files named above and their direct tests.

---

## 2. Architectural Design

### Module 1 — CLI identity: explicit tenant + fail-loud roles placeholder

`packages/ai-parrot/src/parrot/cli/identity.py`:

- Add an explicit `O365_TENANT_ID` (or reuse an existing tenant-id env var if one already exists
  in the codebase — verify during implementation) environment variable, distinct from
  `CLI_CHANNEL`. `build_cli_permission_context()` reads it and passes it as `tenant_id`,
  falling back to a clearly-named sentinel (e.g. `UNSET_CLI_TENANT = "unset-cli-tenant"`, NOT
  `CLI_CHANNEL`) when absent — so a future PBAC rule keyed on `tenant_id="cli"` cannot
  accidentally match a real tenant, and the sentinel value makes the gap visible in logs/traces
  rather than silently reusing a channel literal that looks like a plausible tenant id.
  - Do not attempt to resolve real per-user roles in this feature (no role source exists yet)
    — keep `roles=frozenset()`, but add a code comment at the call site making the risk explicit
    (today inert; will matter the moment a `ToolManager._resolver` is wired for CLI).

### Module 2 — VaultTokenSync: atomic-enough token persistence

`packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`:

- Change `store_tokens()` write order and validation so a partial failure cannot produce a
  trusted-forever token:
  - Prefer writing `expires_at` **first** (or as part of a single batch, if `vault.set()` has
    a bulk/transactional variant — check `vault`'s interface during implementation and use it if
    available), so that if the loop fails partway through, either `expires_at` is already
    present (and correctly reflects real expiry) or `access_token` was never written at all.
  - As a defense-in-depth backstop independent of write order: change the resolver's read-side
    interpretation so a **freshly-read** token set missing `expires_at` is treated as *expired*
    (triggers refresh-or-device-flow) rather than *valid forever*, UNLESS the caller can
    distinguish "field intentionally absent on this provider" from "write partially failed."
    Since `o365:*` is a fixed field contract per FEAT-266 spec §3 (`expires_at` is always part
    of a successful device-flow/refresh persist), a missing `expires_at` on read for the `o365`
    provider specifically is always anomalous — safe to treat as expired.
  - Log a distinguishable warning (not just the existing generic exception log) when a
    partial-write is detected (e.g. some but not all expected keys ended up persisted), so this
    failure mode is observable in production instead of silent.

---

## 3. Acceptance Criteria

- [ ] CLI `PermissionContext.tenant_id` is no longer the literal `"cli"` channel string reused
      as a tenant id — either a real `O365_TENANT_ID`-sourced value or an explicit,
      distinctly-named "unset" sentinel that cannot be confused with a real tenant.
- [ ] A code comment at the `UserSession(...)` construction site in `identity.py` documents that
      `roles=frozenset()` is a known gap until CLI role resolution exists.
- [ ] `VaultTokenSync.store_tokens` either persists atomically or is reordered so `expires_at`
      lands before/with `access_token`, closing the "partial write reads as forever-valid" gap.
- [ ] `O365DeviceCodeCredentialResolver`'s cache-hit path treats a missing `expires_at` on a
      read `o365:*` token set as expired (not valid-forever) — updated to match the new
      persistence contract.
- [ ] A distinguishable log line fires on detected partial-write in `store_tokens`.
- [ ] All existing FEAT-266 tests (`test_o365_devicecode_resolver.py`,
      `test_credentials_devicecode.py`, `test_broker_devicecode.py`, `test_o365_refresh.py`,
      `test_cli_devicecode_e2e.py`) continue to pass unmodified in behavior (only the
      missing-`expires_at` semantics test, if any, may need updating to match the new
      "missing = expired" contract).
- [ ] New unit tests cover: CLI tenant_id is not `"cli"`/is the new sentinel or real value;
      partial `store_tokens` failure does not produce a forever-valid cached token on next read.
- [ ] No behavior change for Telegram/jira/fireflies/workiq `VaultTokenSync` callers.

---

## 4. Worktree Strategy

- **Default isolation unit**: `per-spec` — both tasks are small and touch adjacent but disjoint
  files (`identity.py` vs. `vault_token_sync.py` + `o365_devicecode_provider.py`); run
  sequentially in one worktree.
- **Cross-feature dependencies**: builds directly on FEAT-266 (`o365-auth-homologation`), already
  merged to `dev`. No other in-flight feature is known to touch these files.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-01 | Jesus Lara | Initial draft from FEAT-266 code review follow-ups |
