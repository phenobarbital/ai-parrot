---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-integrations, parrot-formdesigner]
tags: [msteams, formdesigner, security, tenant-isolation, hmac]
---

# Feature Specification: MS Teams submit envelope — fail-closed tenant isolation

**Feature ID**: FEAT-733
**Date**: 2026-10-23
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.3.0

> Closes ledger `issue:bcd04b2170a0` (`vulnerability`, filed `minor` on
> 2026-09-15, `discovered_from: spec:FEAT-551`). Folds in ledger
> `issue:89f47e08b13a` (missing private-form `403`-then-bearer test), whose
> fixture is the one this feature needs anyway.
>
> **Real-world severity is higher than the filed `minor`.** The secret is not
> configured in the deployment a live prospect would see, and that prospect
> runs on Teams. Treat as blocking before any demo in that environment.

---

## 1. Motivation & Business Requirements

### Problem Statement

`verify_envelope()` is the SSRF/tenant guard for every FormDesigner submission
that arrives through the MS Teams bot. It checks, in order: https → host
allowlist → that the URL path matches `{api_base_path}/{tenant}/forms/{form_uid}/data`
→ signature. The first three checks are unconditional. **The fourth is not:**

```python
# formdesigner_submit.py:56 — verified at c9c6a1ba5
if secret is not None and not env.verify(secret):
    raise EnvelopeRejected("Submission envelope signature is invalid.")
```

With `secret=None` the HMAC check does not run at all. The path check does not
compensate for it, because `env.tenant` and `env.form_uid` are **client-supplied
Adaptive Card data**: the attacker controls both sides of the comparison and can
simply craft a `submit_url` that agrees with the `tenant`/`form_uid` they chose.
Everything the guard still enforces (https, allowed host) is satisfied by a
legitimate host.

The bot then forwards that payload **with its own bearer token**
(`post_submission(..., bearer_token=self.config.formdesigner_submit_token)`,
`wrapper.py:1080`). So any Teams user who can reach the bot can write a
submission into **another tenant's form** on an allowed host, authenticated as
the bot. The precondition is exactly: `formdesigner_allowed_hosts` set,
`formdesigner_submit_token` set, `formdesigner_submit_secret` unset.

Nothing warns about this. The dangerous configuration is silent, undocumented,
and — critically — **it is the default**, for a reason that was not in the
original ledger issue:

> **The producing side cannot be configured through the documented entry point.**
> `setup_form_api()` calls `register_teams_renderer()` (`routes.py:316`) without
> a `signing_secret` argument and has no parameter for one, while
> `register_teams_renderer()` does accept one (`render.py:122`). So a host that
> wires Teams the documented way gets `TeamsFormRenderer(signing_secret=None)`,
> every envelope is emitted with `sig: null`, and configuring
> `formdesigner_submit_secret` on the bot would then reject **every** legitimate
> submission. The only escape today is for the host to build a
> `TeamsFormRenderer` by hand and pass it as `teams_renderer=`.

That asymmetry is why "just set the secret" is not a fix, and why this is a spec
rather than a configuration change.

### Goals

- **Fail closed at startup, not at request time.** A `MSTeamsAgentConfig` that
  enables the FormDesigner branch with a bearer token but no signing secret is
  refused when it is constructed, naming the missing variable.
- **Make skipping the signature an explicit choice, never a default.**
  `verify_envelope()` gains a keyword-only `require_signature` that defaults to
  refusing an unsigned envelope.
- **Make the secret configurable on the producing side**, so the two halves can
  actually be paired: a `teams_signing_secret` parameter on `setup_form_api()`
  plus an environment fallback, forwarded to `register_teams_renderer()`.
- **One documented escape hatch** for local development, loud and deliberate —
  never reachable by omission.
- **Stop trusting the envelope's `tenant` as the only source.** Derive it from
  the Bot Framework-asserted Teams tenant when a mapping exists, falling back to
  the envelope otherwise — a second line of defence behind the signature, never
  a replacement for it (see §2 "Why derivation does not replace the signature").
- **Document the pairing** in `docs/formdesigner-msteams-renderer.md`, which
  today describes `sig` as optional without stating the consequence.
- Close `issue:bcd04b2170a0` and `issue:89f47e08b13a`.

### Non-Goals (explicitly out of scope)

- Changing the envelope wire format, `canonical_payload()`, or the HMAC
  algorithm. `TeamsSubmitEnvelope.sign()`/`verify()` are correct as written
  (`verify()` already returns `False` for `sig=None`, `teams.py:76-81`); the
  defect is in the caller, not the primitive.
- Key rotation, multiple active secrets, or asymmetric signatures.
- Replacing the host allowlist or the SSRF guard around `submit_url`.
- Auto-discovering the AAD-tenant → FormDesigner-tenant mapping. M6 consumes a
  mapping the operator configures; building it from Graph or a directory sync is
  a separate problem.
- Deriving `form_uid` from anything but the envelope. Only `tenant` has a
  server-asserted counterpart in the activity; `form_uid` stays envelope-only
  and signature-protected.
- Teams upload support. Adaptive Cards cannot upload; the renderer already
  degrades to an `Action.OpenUrl` plus a `RenderWarning`.

---

## 2. Architectural Design

### Overview

Three independent gates, each of which alone closes the hole, layered so that a
misconfiguration is caught as early as possible:

1. **Construction time** — `MSTeamsAgentConfig.__post_init__` refuses the unsafe
   combination outright. A deployment cannot start in the vulnerable state.
2. **Request time** — `verify_envelope()` refuses an unsigned envelope unless
   the caller explicitly passed `require_signature=False`. Defence in depth for
   any caller that builds the config some other way.
3. **Emission time** — `setup_form_api(teams_signing_secret=...)` lets the
   producing side sign, which is what makes gate 1 satisfiable at all.

The escape hatch (`allow_unsigned_submissions`) is a single flag that relaxes
gates 1 and 2 together, logs a `WARNING` on every startup, and is never set by
default.

A fourth change, **M6**, narrows the blast radius rather than closing a gate: the
bot prefers a Bot Framework-asserted tenant over the one the card claims.

### Why derivation does not replace the signature

Teams asserts an **Azure AD tenant GUID** (`activity.channel_data["tenant"]["id"]`,
`TeamsChannelData.tenant.id` — verified against the installed `botbuilder.schema.teams`).
FormDesigner routes on a **tenant slug** (`navigator`), the `{tenant}` segment of
`…/{tenant}/forms/{form_uid}/data`. These are different namespaces, so derivation
needs an operator-configured mapping: `{aad_tenant_guid: formdesigner_tenant_slug}`.

That mapping cannot be exhaustive, and the fallback is what makes it safe to
deploy — but also what keeps it from being a gate:

> A caller whose AAD tenant is **not** in the mapping falls back to the envelope's
> `tenant`. An attacker reaching the bot from an unmapped tenant is therefore back
> to the original situation. **M6 constrains mapped tenants; only the signature
> constrains everyone.** M1, M2 and M3 remain mandatory, and M6 is not a reason to
> relax any of them.

What M6 does buy: for every mapped tenant — the configured, production case — a
valid signature is no longer sufficient to write into *another* tenant. A leaked
or replayed signing secret stops being a cross-tenant write primitive. That is a
real reduction in blast radius, and the reason it is worth doing here rather than
deferring.

### Component Diagram

```
FormDesigner side                             MS Teams bot side
─────────────────                             ─────────────────
setup_form_api(teams_signing_secret=…)   [M3]
        │
        ▼
register_teams_renderer(signing_secret=…)
        │
        ▼
TeamsFormRenderer(signing_secret=…)
        │  build_envelope() → TeamsSubmitEnvelope.sign(secret)
        │
        └──→ Adaptive Card  ──(Action.Submit)──→  MSTeamsAgentWrapper
                                                          │
                                   MSTeamsAgentConfig  [M1]  ← refuses at __post_init__
                                                          │
                                                  parse_envelope()
                                                          │
                                   verify_envelope(require_signature=…)  [M2]
                                                          │  ← refuses unsigned
                                   resolve_submit_tenant()  [M6]
                                     channel_data.tenant.id → mapping
                                     hit  → authoritative; rewrite submit_url
                                     miss → fall back to env.tenant
                                                          │
                                                  post_submission(bearer)
                                                          │
                                                          ▼
                                       POST …/{tenant}/forms/{uid}/data
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MSTeamsAgentConfig` | extends | one new field + a validation branch in `__post_init__` |
| `verify_envelope()` | signature change | new keyword-only `require_signature` |
| `MSTeamsAgentWrapper._handle_formdesigner_submit` | modifies | passes the new argument |
| `setup_form_api()` | extends | new `teams_signing_secret` parameter, forwarded |
| `register_teams_renderer()` | uses | already accepts `signing_secret` — unchanged |
| `TeamsSubmitEnvelope.sign/verify` | uses | unchanged |
| `Activity.channel_data["tenant"]["id"]` | reads | M6 — server-asserted AAD tenant GUID |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:
    formdesigner_allowed_hosts: Optional[List[str]] = None
    formdesigner_submit_token: Optional[str] = None
    formdesigner_submit_secret: Optional[str] = None
    formdesigner_allow_unsigned_submissions: bool = False  # NEW — escape hatch (M1)
    formdesigner_tenant_map: Optional[Dict[str, str]] = None  # NEW — {aad_guid: fd_slug} (M6)
```

### New Public Interfaces

```python
class UnsignedSubmitConfigError(ValueError):
    """The FormDesigner Teams branch is enabled with a bearer token but no signing secret."""
```

Raised from `MSTeamsAgentConfig.__post_init__`. A `ValueError` subclass so a host
that already guards config construction keeps working.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: config fail-closed | yes | field name, env var name, exception type and message shape all fixed below | — |
| M2: `require_signature` | yes | keyword-only, defaults `True`; reuses `EnvelopeRejected` | — |
| M3: `teams_signing_secret` wiring | yes | parameter name, env var, forwarding call site fixed | — |
| M6: tenant derivation | yes | helper is pure; mapping shape, precedence and fallback all fixed below | — |
| M4: documentation | yes | target file and section fixed | — |
| M5: tests | yes | test names and assertions enumerated in §4 | — |

### Module 1: Config-level fail-closed validation
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py`
- **Responsibility**: refuse the vulnerable configuration at construction time.
- **Depends on**: nothing in this spec.
- **Behaviour**: after the existing FormDesigner env fallbacks resolve
  (`models.py:87-99`), raise when **all** hold: `formdesigner_allowed_hosts` is
  truthy, `formdesigner_submit_token` is truthy, `formdesigner_submit_secret` is
  falsy, and `formdesigner_allow_unsigned_submissions` is `False`. When the hatch
  is `True`, log one `WARNING` instead. Order matters: the check runs **after**
  the env fallbacks, or a secret supplied only through the environment would be
  invisible to it.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
  # (modifies models.py:64 field block and models.py:91 __post_init__ tail)

  class UnsignedSubmitConfigError(ValueError):
      """The FormDesigner Teams branch is enabled with a bearer token but no signing secret."""

  @dataclass
  class MSTeamsAgentConfig:  # verified: models.py:30
      formdesigner_allow_unsigned_submissions: bool = False
      """Opt out of signature enforcement. Development only; logs a WARNING on every startup."""

      def __post_init__(self):  # verified: models.py:68
          """Resolve credentials from env, then refuse an unsigned-but-authenticated FormDesigner branch."""
  ```

### Module 2: `require_signature` on the request-time guard
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py`
- **Responsibility**: make an unsigned envelope a refusal by default.
- **Depends on**: nothing (M1 and M2 are independent gates).
- **Behaviour**: the final branch becomes — refuse when `require_signature` is
  `True` and `secret` is `None` (misconfiguration reaching request time); refuse
  when `secret` is not `None` and `env.verify(secret)` is `False` (existing
  behaviour); skip only when `require_signature` is `False`. The user-facing
  message must not disclose which of the two conditions failed.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
  # (modifies formdesigner_submit.py:44)
  def verify_envelope(
      env: TeamsSubmitEnvelope,
      *,
      allowed_hosts: list[str],
      secret: str | None,
      api_base_path: str = "/api/v1",
      require_signature: bool = True,
  ) -> None:
      """SSRF guard (spec S3). Order: https -> host allowlist -> path/tenant/uid -> signature.

      Raises EnvelopeRejected when ``require_signature`` and no secret is configured:
      tenant/form_uid are client-supplied, so an unsigned envelope is unauthenticated routing.
      """
  ```
- **Call site** (`wrapper.py:1065`) passes
  `require_signature=not self.config.formdesigner_allow_unsigned_submissions`.

### Module 3: `teams_signing_secret` on the producing side
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
- **Responsibility**: let the documented entry point configure signing, so the
  bot-side secret is satisfiable.
- **Depends on**: nothing. **Blocks nothing** — but without it M1 turns every
  documented deployment into a hard startup failure, so it ships together.
- **Behaviour**: `setup_form_api()` gains `teams_signing_secret: str | None = None`,
  falling back to env `FORMDESIGNER_TEAMS_SIGNING_SECRET`, forwarded to
  `register_teams_renderer(signing_secret=...)`. `register_teams_renderer()`
  already accepts the argument (`render.py:122`) and needs no change. When a
  pre-built `teams_renderer=` is passed it still wins, unchanged.
- **Interface Skeleton**:
  ```python
  # packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
  # (modifies routes.py:215 signature block and routes.py:316 call)
  def setup_form_api(
      ...,
      public_base_url: str | None = None,          # verified: routes.py:214
      teams_renderer: "AbstractFormRenderer | None" = None,  # verified: routes.py:215
      teams_signing_secret: str | None = None,
  ) -> None:
      """``teams_signing_secret`` falls back to env ``FORMDESIGNER_TEAMS_SIGNING_SECRET``.

      Without it the ``teams`` renderer emits ``sig: null`` and a bot configured with
      ``formdesigner_submit_secret`` rejects every submission.
      """
  ```

### Module 6: Bot-asserted tenant derivation
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py`
  (pure helper) + `.../wrapper.py` (call site) + `.../models.py` (config field)
- **Responsibility**: prefer the Bot Framework-asserted tenant over the card's
  claim when a mapping exists; fall back to the envelope otherwise.
- **Depends on**: M2 — derivation runs **after** `verify_envelope()`, never
  instead of it. Order is load-bearing: a rewritten `submit_url` must not be
  able to launder an envelope past the SSRF/path guard.
- **Behaviour**:
  - Read the AAD tenant GUID from `activity.channel_data["tenant"]["id"]`
    (a plain dict on a raw activity; absent on non-Teams channels and in many
    test activities → treat as a miss, never an error).
  - Look it up in `formdesigner_tenant_map`. **Hit** → that slug is
    authoritative; when it differs from `env.tenant`, rewrite both `env.tenant`
    and the `{tenant}` segment of `env.submit_url`, and log at `INFO` that a
    claim was overridden. **Miss, or no map configured** → keep `env.tenant`
    unchanged (today's behaviour).
  - The helper is pure and takes the GUID, not the activity, so it stays
    testable without `botbuilder` — preserving the module's no-botbuilder rule
    (`formdesigner_submit.py:3`). The wrapper does the extraction.
  - Rewriting `submit_url` must rebuild the path from `api_base_path`, the
    resolved tenant and `env.form_uid` — never string-replace the old slug,
    which would corrupt a URL whose host or path contains it.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py (new symbols)
  def resolve_submit_tenant(
      env: TeamsSubmitEnvelope,
      *,
      asserted_tenant_id: str | None,
      tenant_map: dict[str, str] | None,
      api_base_path: str = "/api/v1",
  ) -> tuple[TeamsSubmitEnvelope, bool]:
      """Return (envelope, overridden). A mapped ``asserted_tenant_id`` wins over ``env.tenant``.

      Rebuilds ``submit_url`` from ``api_base_path``/tenant/``form_uid`` on override.
      Returns the envelope unchanged with ``False`` when the id is None or unmapped.
      """
  ```
- **Call site** (`wrapper.py:1065`, immediately after `verify_envelope`):
  ```python
  tenant_info = (getattr(turn_context.activity, "channel_data", None) or {}).get("tenant") or {}
  env, overridden = resolve_submit_tenant(
      env,
      asserted_tenant_id=tenant_info.get("id"),
      tenant_map=self.config.formdesigner_tenant_map,
      api_base_path=getattr(self.config, "formdesigner_api_base_path", FORMDESIGNER_API_BASE_PATH),
  )
  ```

### Module 4: Documentation
- **Path**: `docs/formdesigner-msteams-renderer.md`
- **Responsibility**: state the pairing requirement where the `sig` field is
  introduced.
- **Depends on**: M1, M2, M3, M6 (documents their final names).
- **Content**: replace the bare *"`sig` is omitted (`null`) when no secret is
  configured"* with the rule — the two secrets are one setting in two places
  (`teams_signing_secret` on the FormDesigner side, `formdesigner_submit_secret`
  on the bot side) and must be equal; a bearer token without a secret is refused
  at startup; the escape hatch and why it is development-only; a short
  "Configuring Teams submissions securely" section with all three env vars; and
  a "Tenant resolution" subsection stating the AAD-GUID → slug mapping, the
  fallback, and — explicitly — that the mapping does **not** remove the need for
  the signature.

### Module 5: Tests
- **Path**: `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py`,
  `.../test_formdesigner_wrapper.py`, `.../test_formdesigner_roundtrip.py`,
  `packages/parrot-formdesigner/tests/unit/api/` (new file for M3)
- **Responsibility**: regression coverage per §4; update the existing calls that
  pass `secret=None` (`test_formdesigner_submit.py:56`) now that the default
  refuses.
- **Depends on**: M1, M2, M3, M6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_rejects_token_without_secret` | M1 | hosts + token, no secret → `UnsignedSubmitConfigError` naming the env var |
| `test_config_allows_token_with_secret` | M1 | hosts + token + secret → constructs cleanly |
| `test_config_allows_no_token_no_secret` | M1 | hosts, no token, no secret → constructs (nothing to escalate with) |
| `test_config_hatch_allows_unsigned_and_warns` | M1 | hatch `True` → constructs, emits exactly one `WARNING` |
| `test_config_secret_from_env_satisfies_check` | M1 | secret supplied only via `<NAME>_FORMDESIGNER_SUBMIT_SECRET` → no raise (ordering guard) |
| `test_verify_envelope_rejects_unsigned_by_default` | M2 | `secret=None`, default args → `EnvelopeRejected` |
| `test_verify_envelope_skips_when_not_required` | M2 | `secret=None, require_signature=False` → passes |
| `test_verify_envelope_rejects_bad_sig` | M2 | existing behaviour preserved with a secret set |
| `test_verify_envelope_accepts_valid_sig` | M2 | round-trip through `TeamsSubmitEnvelope.sign()` |
| `test_verify_envelope_message_does_not_leak_cause` | M2 | unsigned and bad-signature produce the same user-facing text |
| `test_setup_form_api_forwards_signing_secret` | M3 | the registered renderer carries the secret |
| `test_setup_form_api_signing_secret_from_env` | M3 | `FORMDESIGNER_TEAMS_SIGNING_SECRET` fallback |
| `test_setup_form_api_explicit_renderer_still_wins` | M3 | `teams_renderer=` takes precedence, unchanged |
| `test_resolve_tenant_mapped_guid_overrides_envelope` | M6 | mapped GUID ≠ `env.tenant` → tenant and `submit_url` rewritten, `overridden is True` |
| `test_resolve_tenant_mapped_guid_matching_is_noop` | M6 | mapped GUID == `env.tenant` → unchanged, `overridden is False` |
| `test_resolve_tenant_unmapped_guid_falls_back` | M6 | GUID absent from the map → envelope untouched |
| `test_resolve_tenant_no_asserted_id_falls_back` | M6 | `asserted_tenant_id=None` (non-Teams channel) → envelope untouched, no raise |
| `test_resolve_tenant_rebuilds_url_not_string_replace` | M6 | a tenant slug that also appears in the host survives the rewrite intact |
| `test_hatch_env_fallback_sets_allow_unsigned` | M1 | `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED=1` → hatch on (Q1) |

### Integration Tests

| Test | Description |
|---|---|
| `test_cross_tenant_envelope_is_refused` | **The vulnerability.** Signed-mode bot; a card whose envelope names another tenant with a self-consistent `submit_url` on an allowed host → refused, and `post_submission` is never called |
| `test_teams_card_roundtrip_signed` | render `teams` with a signing secret → bot verifies → `POST …/data` → `200` reply card |
| `test_teams_card_roundtrip_private_form_403_then_bearer` | private form without token → `403` card; with an accepted bearer → `200`. **Closes `issue:89f47e08b13a`** |
| `test_unsigned_renderer_against_signed_bot_is_refused` | the misconfiguration M3 exists to prevent: `sig: null` meets a bot with a secret → refused, not silently accepted |
| `test_mapped_tenant_overrides_validly_signed_cross_tenant_claim` | M6's reason to exist: a **correctly signed** envelope claiming another tenant, from a mapped AAD tenant → the POST goes to the mapped slug, not the claimed one |
| `test_derivation_runs_after_verification` | a rewritten `submit_url` cannot launder an envelope past the SSRF/path guard — an envelope that fails `verify_envelope` never reaches `resolve_submit_tenant` |

### Validation Contract

tests:
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def signing_secret() -> str:
    return "test-secret-not-a-real-key"

@pytest.fixture
def signed_envelope(signing_secret):
    """A valid envelope for tenant 'navigator', signed — the happy path."""

@pytest.fixture
def cross_tenant_envelope():
    """Unsigned envelope naming tenant 'victim' with a self-consistent submit_url
    on an allowed host — the attack payload. `sig` is None."""
```

---

## 5. Acceptance Criteria

- [ ] A `MSTeamsAgentConfig` with `formdesigner_allowed_hosts` and
      `formdesigner_submit_token` set and `formdesigner_submit_secret` unset
      raises `UnsignedSubmitConfigError`, and the message names
      `<NAME>_FORMDESIGNER_SUBMIT_SECRET`.
- [ ] That check runs **after** the env fallbacks, so a secret provided only
      through the environment satisfies it.
- [ ] `formdesigner_allow_unsigned_submissions=True` permits it and logs exactly
      one `WARNING` per startup; `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED` sets it
      through the environment like every other FormDesigner field (Q1).
- [ ] `verify_envelope()` refuses an unsigned envelope by default; the skip
      requires an explicit `require_signature=False`.
- [ ] The refusal text is identical for "no secret configured" and "bad
      signature" — no oracle.
- [ ] `_handle_formdesigner_submit` derives `require_signature` from the hatch,
      and a refused envelope never reaches `post_submission`.
- [ ] `setup_form_api(teams_signing_secret=...)` and
      `FORMDESIGNER_TEAMS_SIGNING_SECRET` reach
      `TeamsFormRenderer.signing_secret`; an explicit `teams_renderer=` still
      wins.
- [ ] `test_cross_tenant_envelope_is_refused` fails against the pre-fix code
      (it is the regression test for the vulnerability).
- [ ] A mapped AAD tenant GUID overrides a conflicting `env.tenant`, rewriting
      both the tenant and the `{tenant}` segment of `submit_url` by rebuilding
      the path — never by string replacement.
- [ ] An absent or unmapped AAD tenant GUID leaves the envelope untouched and
      raises nothing (non-Teams channels must keep working).
- [ ] `resolve_submit_tenant()` runs strictly **after** `verify_envelope()`; an
      envelope that fails verification never reaches it.
- [ ] `resolve_submit_tenant()` is importable and testable without `botbuilder`
      installed.
- [ ] `docs/formdesigner-msteams-renderer.md` documents the pairing, all three
      env vars, the hatch, and that tenant derivation does **not** replace the
      signature.
- [ ] Full contract suite green; `ruff check` clean on every changed file.
- [ ] `issue:bcd04b2170a0` and `issue:89f47e08b13a` closed with
      `--resolved-by` pointing at the merge commit.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot_formdesigner.renderers.teams import (  # verified: formdesigner_submit.py:22
    ENVELOPE_KEY, RESERVED_CONTROL_KEYS, TeamsSubmitEnvelope,
)
from parrot.integrations.msteams.formdesigner_submit import (  # verified: wrapper.py:36
    EnvelopeRejected, parse_envelope, verify_envelope, post_submission,
    extract_answers, build_reply_card, RecentActivityCache, SubmitOutcome,
)
from parrot_formdesigner.api.render import register_teams_renderer  # verified: api/render.py:117
```

### Existing Class Signatures

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
class EnvelopeRejected(Exception): ...                                    # line 28
def parse_envelope(submitted_data: dict[str, Any]) -> TeamsSubmitEnvelope: ...   # line 32
def verify_envelope(                                                      # line 44
    env: TeamsSubmitEnvelope, *, allowed_hosts: list[str],
    secret: str | None, api_base_path: str = "/api/v1",
) -> None: ...
#   line 49  https check
#   line 51  host allowlist check
#   line 53  expected_path = f"{api_base_path.rstrip('/')}/{env.tenant}/forms/{env.form_uid}/data"
#   line 56  if secret is not None and not env.verify(secret):   ← THE DEFECT
async def post_submission(                                                # line 73
    session, env, answers, *, bearer_token: str | None,
    timeout: float, max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> SubmitOutcome: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
class TeamsSubmitEnvelope(BaseModel):                                     # line 52
    v: Literal[1] = 1                                                     # line 55
    form_uid: uuid.UUID                                                   # line 57
    tenant: str = Field(min_length=1)                                     # line 58
    submit_url: HttpUrl                                                   # line 61
    sig: str | None = None                                                # line 63
    def canonical_payload(self) -> bytes: ...                             # line 65
    def sign(self, secret: str) -> "TeamsSubmitEnvelope": ...             # line 71
    def verify(self, secret: str) -> bool: ...                            # line 76 — False when sig is None

class TeamsFormRenderer(AdaptiveCardRenderer):                            # line 88
    RENDERER_NAME = "teams"                                               # line 91
    def __init__(self, public_base_url=None, *, api_base_path="/api/v1",
                 ui_base_path="", signing_secret: str | None = None,
                 version=None) -> None: ...                               # line 94

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
class MSTeamsAgentConfig:
    formdesigner_allowed_hosts: Optional[List[str]] = None                # line 62
    formdesigner_submit_token: Optional[str] = None                       # line 63
    formdesigner_submit_secret: Optional[str] = None                      # line 64
    formdesigner_submit_timeout: float = 15.0                             # line 65
    formdesigner_api_base_path: str = "/api/v1"                           # line 66
    def __post_init__(self): ...                                          # line 68
    #   line 87-91  FormDesigner env fallbacks (token, then secret)
    #   line 92-95  allowed-hosts env fallback

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
def register_teams_renderer(                                              # line 117
    *, public_base_url=None, api_base_path="/api/v1", ui_base_path="",
    signing_secret: str | None = None,                                    # line 122 — already accepted
    renderer: AbstractFormRenderer | None = None,
) -> bool: ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `UnsignedSubmitConfigError` | `MSTeamsAgentConfig.__post_init__` | raise after env fallbacks | `models.py:91` |
| `require_signature` | `verify_envelope()` | keyword-only parameter | `formdesigner_submit.py:44` |
| `require_signature` call site | `_handle_formdesigner_submit` | argument | `wrapper.py:1065` |
| `teams_signing_secret` | `register_teams_renderer()` | `signing_secret=` | `routes.py:316` → `render.py:122` |

### Does NOT Exist (Anti-Hallucination)

- ~~`setup_form_api(signing_secret=...)`~~ — **not** a parameter today. The
  renderer registration at `routes.py:316` passes only `public_base_url`,
  `api_base_path`, `ui_base_path` and `renderer`. This is M3's whole point.
- ~~`FORMDESIGNER_TEAMS_SIGNING_SECRET`~~ — no such environment variable exists
  yet; M3 introduces it. The existing `PUBLIC_URL_ENV`
  (`FORMDESIGNER_PUBLIC_URL`, `renderers/teams.py`) is unrelated.
- ~~`MSTeamsAgentConfig.formdesigner_require_signature`~~ — does not exist. The
  new field is `formdesigner_allow_unsigned_submissions` (inverted on purpose:
  the safe value is the falsy default).
- ~~`TeamsSubmitEnvelope.require_signature`~~ / ~~`.is_signed`~~ — not model
  fields. Signedness is `env.sig is not None`.
- ~~`verify_envelope(..., strict=...)`~~ — no such parameter; the name is
  `require_signature`.
- ~~A shared constant for the two secrets~~ — they are two independent settings
  in two distributions that must be given the same value by the operator. There
  is no code path that compares or synchronizes them.
- ~~`TeamsInfo.get_tenant_id()`~~ / ~~`teams_get_tenant_id()`~~ — no such helper.
  `botbuilder.core.teams` exposes only `teams_get_channel_id` and
  `teams_get_selected_channel_id` (verified against the installed package). Read
  `activity.channel_data["tenant"]["id"]` directly.
- ~~`MSTeamsAgentConfig.app_tenantid` as the FormDesigner tenant~~ — it is the
  **AAD tenant GUID** for `app_type: SingleTenant` bot authentication
  (`models.py:37`, `models.py:79`), a different namespace from the FormDesigner
  tenant slug. Never pass it as `{tenant}`.
- ~~`channel_data` being read anywhere today~~ — it is not. M6 is the first
  reader in the `msteams` package.
- ~~`TenantInfo` carrying a name or slug~~ — its only field is `id`
  (verified: `botbuilder.schema.teams.TenantInfo._attribute_map`).

### Edit Sites (Blueprint Anchors)

Verified against: `c9c6a1ba5`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `    formdesigner_submit_secret: Optional[str] = None  # HMAC secret; envelopes must carry a valid sig when set` | `models.py:64` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `            self.formdesigner_submit_secret = config.get(f"{self.name.upper()}_FORMDESIGNER_SUBMIT_SECRET")` | `models.py:91` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` | MODIFY | `def verify_envelope(` | `formdesigner_submit.py:44` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `            verify_envelope(` | `wrapper.py:1065` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `    render_module.register_teams_renderer(` | `routes.py:316` | 1 |
| `docs/formdesigner-msteams-renderer.md` | MODIFY | `` `sig` is the HMAC-SHA256 hex digest of the envelope's canonical JSON (every field except `sig`, `` | `docs/formdesigner-msteams-renderer.md:67` | 1 |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py` | MODIFY | `        verify_envelope(_env(**over), allowed_hosts=["forms.test"], secret=None)` | `test_formdesigner_submit.py:56` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `formdesigner_submit.py` deliberately imports no `botbuilder` symbol so it
  stays unit-testable without the `msteams` extra (`formdesigner_submit.py:3`).
  **Do not break that** — M2 adds no imports.
- Config env fallbacks use `config.get(f"{self.name.upper()}_<SUFFIX>")`
  (`models.py:87-99`). M1's new field follows the same shape; the validation
  goes **after** that block.
- `_handle_formdesigner_submit` "never raises; never continues the dialog"
  (`wrapper.py:1058`). `EnvelopeRejected` is already caught and rendered as text
  (`wrapper.py:1085`); M2 needs no new handling there.
- Logging is `self.logger` / module `logger`, never `print`.

### Known Risks / Gotchas

- **M2's default is a behaviour change for external callers.** Anyone calling
  `verify_envelope(..., secret=None)` and expecting it to pass now gets
  `EnvelopeRejected`. That is the fix, and it is why the target version is a
  minor bump. The in-repo call sites are exactly two: `wrapper.py:1065` and
  `test_formdesigner_submit.py:56`.
- **M1 without M3 bricks the documented wiring.** A host that upgrades, sets the
  bot secret and keeps using plain `setup_form_api()` would emit unsigned
  envelopes against a signature-requiring bot — every submission refused. The
  two must land in the same release; neither is independently shippable.
- **Do not compare the two secrets in code.** They live in different
  distributions and may be deployed separately; a cross-check would create a
  coupling that does not exist today.
- **The error message must not be an oracle.** "No secret configured" and "bad
  signature" are distinguishable to an attacker if the user-facing text differs.
  Log the distinction; do not return it.
- **The hatch must be hard to reach by accident.** `False` default, explicit
  field, `WARNING` on every startup. It does get an env fallback (§8 Q1), so the
  `WARNING` is the only thing standing between a stray cluster-wide variable and
  a silently unsigned deployment — do not downgrade it to `INFO` or emit it
  once per process-group.
- **M6 is not a gate, and the spec must keep saying so.** It is tempting to read
  "the bot derives the tenant itself" as making the signature redundant. It does
  not: an unmapped caller falls straight back to the envelope. Any future change
  that relaxes M1/M2 on the grounds that M6 exists reopens `bcd04b2170a0`.
- **Order M2 → M6, never the reverse.** `resolve_submit_tenant()` can rewrite
  `submit_url`; running it before `verify_envelope()` would let a crafted
  envelope be rewritten into a shape that then passes the host/path guard.
- **`channel_data` is not always a dict.** It is absent on non-Teams channels
  and in most hand-built test activities. Treat anything that is not a dict with
  a `tenant.id` as a miss; never raise from the extraction.
- **No live deployment relies on unsigned envelopes** (§8 Q3), so M1 may fail
  closed from day one with no migration path.

### External Dependencies

None. `hmac` and `hashlib` are stdlib and already imported in
`renderers/teams.py`.

---

## 8. Open Questions

- [x] **Q1** — Env fallback for the escape hatch? — *Resolved: **yes***.
      `formdesigner_allow_unsigned_submissions` gets
      `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED`, consistent with every other
      FormDesigner config field (`models.py:87-99`). The `WARNING` on every
      startup is what keeps it from being silent. Landed in M1 and §5.
- [x] **Q2** — Derive `tenant` from the Bot Framework identity? — *Resolved:
      **yes — derive from the tenant, falling back to the envelope***. Promoted
      out of Non-Goals into **M6**. Note the consequence recorded in §2 "Why
      derivation does not replace the signature": because the fallback is
      reachable by any unmapped caller, M6 narrows blast radius for mapped
      tenants but gates nothing — M1/M2/M3 stay mandatory.
- [x] **Q3** — Does any live deployment rely on unsigned envelopes? — *Resolved:
      **no***. No migration path and no breaking-upgrade release note needed;
      M1 can fail closed from day one.

### Remaining

- [ ] **Q4** — Where does `formdesigner_tenant_map` come from operationally? A
      dict on the agent config is enough for the first deployment, but FieldSync
      already owns tenant identity (tenant-per-schema, `fieldsync.projects`), so
      a second hand-maintained copy will drift. Decide before the map grows past
      a handful of entries. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — this spec was
> raised directly from ledger `issue:bcd04b2170a0`, so §3b's precondition was
> never met) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-733-msteams-submit-envelope-fail-closed`,
  branched from `origin/dev`. The `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M1, M2 and M3 are **independent** — three different files in two
    distributions, no shared symbol. Expected to run concurrently.
  - M6 → M2 (adds a symbol to `formdesigner_submit.py` and a call right after
    `verify_envelope`; the ordering is a correctness requirement, not a
    convenience).
  - M4 → M1, M2, M3, M6 (documents their final names).
  - M5 → M1, M2, M3, M6 (tests their behaviour).
- **Shared files** — two, and both serialize:
  - `models.py`: M1 (field + env fallback + validation) and M6
    (`formdesigner_tenant_map` field + env fallback). Same two anchor regions.
  - `formdesigner_submit.py`: M2 (`verify_envelope` signature) and M6
    (`resolve_submit_tenant`).
  - `wrapper.py`: M2 and M6 both edit the `verify_envelope(` call site at
    `:1065`.
- **Exclusive resources**: none. No migration, no lockfile change, no extension
  rebuild.
- **Cross-feature dependencies**: none. Touches no file in flight on
  `feat-FEAT-728-formbuilder-llm-validation-enforcement` or FEAT-732.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-23 | Jesus Lara | Initial draft from ledger `issue:bcd04b2170a0`; adds the `setup_form_api` signing-secret gap (M3) found during §4 verification |
| 0.2 | 2026-10-23 | Jesus Lara | Resolved Q1–Q3. Q2 promoted tenant derivation out of Non-Goals into **M6** (AAD GUID → slug map, envelope fallback), with §2 recording why it narrows blast radius without gating. Q1 adds the hatch's env fallback; Q3 removes the migration path. New Q4 on where the tenant map lives |
