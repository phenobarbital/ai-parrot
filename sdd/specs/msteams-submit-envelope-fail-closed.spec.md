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
- **Document the pairing** in `docs/formdesigner-msteams-renderer.md`, which
  today describes `sig` as optional without stating the consequence.
- Close `issue:bcd04b2170a0` and `issue:89f47e08b13a`.

### Non-Goals (explicitly out of scope)

- Changing the envelope wire format, `canonical_payload()`, or the HMAC
  algorithm. `TeamsSubmitEnvelope.sign()`/`verify()` are correct as written
  (`verify()` already returns `False` for `sig=None`, `teams.py:76-81`); the
  defect is in the caller, not the primitive.
- Key rotation, multiple active secrets, or asymmetric signatures.
- Server-side re-derivation of `tenant` from the Bot Framework identity. That
  would be a stronger design, but it changes the trust model of FEAT-551's
  envelope and belongs to its own feature — see §8 Q2.
- Replacing the host allowlist or the SSRF guard around `submit_url`.
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

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:
    formdesigner_allowed_hosts: Optional[List[str]] = None
    formdesigner_submit_token: Optional[str] = None
    formdesigner_submit_secret: Optional[str] = None
    formdesigner_allow_unsigned_submissions: bool = False  # NEW — escape hatch
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

### Module 4: Documentation
- **Path**: `docs/formdesigner-msteams-renderer.md`
- **Responsibility**: state the pairing requirement where the `sig` field is
  introduced.
- **Depends on**: M1, M2, M3 (documents their final names).
- **Content**: replace the bare *"`sig` is omitted (`null`) when no secret is
  configured"* with the rule — the two secrets are one setting in two places
  (`teams_signing_secret` on the FormDesigner side, `formdesigner_submit_secret`
  on the bot side) and must be equal; a bearer token without a secret is refused
  at startup; the escape hatch and why it is development-only; a short
  "Configuring Teams submissions securely" section with both env vars.

### Module 5: Tests
- **Path**: `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py`,
  `.../test_formdesigner_wrapper.py`, `.../test_formdesigner_roundtrip.py`,
  `packages/parrot-formdesigner/tests/unit/api/` (new file for M3)
- **Responsibility**: regression coverage per §4; update the existing calls that
  pass `secret=None` (`test_formdesigner_submit.py:56`) now that the default
  refuses.
- **Depends on**: M1, M2, M3.

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

### Integration Tests

| Test | Description |
|---|---|
| `test_cross_tenant_envelope_is_refused` | **The vulnerability.** Signed-mode bot; a card whose envelope names another tenant with a self-consistent `submit_url` on an allowed host → refused, and `post_submission` is never called |
| `test_teams_card_roundtrip_signed` | render `teams` with a signing secret → bot verifies → `POST …/data` → `200` reply card |
| `test_teams_card_roundtrip_private_form_403_then_bearer` | private form without token → `403` card; with an accepted bearer → `200`. **Closes `issue:89f47e08b13a`** |
| `test_unsigned_renderer_against_signed_bot_is_refused` | the misconfiguration M3 exists to prevent: `sig: null` meets a bot with a secret → refused, not silently accepted |

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
      one `WARNING` per startup.
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
- [ ] `docs/formdesigner-msteams-renderer.md` documents the pairing, both env
      vars and the hatch.
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
  field, `WARNING` on every startup. Do not add an env fallback that could be
  set cluster-wide by mistake — see §8 Q1.

### External Dependencies

None. `hmac` and `hashlib` are stdlib and already imported in
`renderers/teams.py`.

---

## 8. Open Questions

- [ ] **Q1** — Should `formdesigner_allow_unsigned_submissions` get an env
      fallback (`<NAME>_FORMDESIGNER_ALLOW_UNSIGNED`) like every other
      FormDesigner config field, or stay code-only so it cannot be switched on
      from a deployment environment? Consistency argues for the env var; the
      threat model argues against. — *Owner: Jesus Lara*
- [ ] **Q2** — Should the bot derive `tenant` from the Bot Framework identity
      instead of trusting the envelope, making the signature a second line of
      defence rather than the only one? Out of scope here; worth its own feature
      if the answer is yes. — *Owner: Jesus Lara*
- [ ] **Q3** — Does any live deployment currently rely on unsigned envelopes? If
      yes, M1 is a breaking upgrade for it and needs a release note; if no (the
      expectation — the secret is unset *and* the producing side cannot sign, so
      the pairing has never worked), no migration path is needed. — *Owner: Jesus Lara*

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
  - M4 → M1, M2, M3 (documents their final names).
  - M5 → M1, M2, M3 (tests their behaviour).
- **Shared files**: `models.py` is touched by M1 only, at two separate anchors
  (`:64` field block, `:91` env-fallback tail). If M1 is split across tasks they
  serialize on that file.
- **Exclusive resources**: none. No migration, no lockfile change, no extension
  rebuild.
- **Cross-feature dependencies**: none. Touches no file in flight on
  `feat-FEAT-728-formbuilder-llm-validation-enforcement` or FEAT-732.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-23 | Jesus Lara | Initial draft from ledger `issue:bcd04b2170a0`; adds the `setup_form_api` signing-secret gap (M3) found during §4 verification |
