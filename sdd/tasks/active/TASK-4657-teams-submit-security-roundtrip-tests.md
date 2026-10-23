# TASK-4657: End-to-end security round-trips — cross-tenant refusal, signed path, private-form bearer

**Feature**: FEAT-733 — MS Teams submit envelope — fail-closed tenant isolation
**Spec**: `sdd/specs/msteams-submit-envelope-fail-closed.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4655, TASK-4656
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. The unit tests in TASK-4653/4654/4655/4656 each prove
one gate in isolation; this task proves the **vulnerability is actually closed**
end to end — render a card, submit it through the bot, observe what reaches the
FormDesigner endpoint.

It also closes ledger `issue:89f47e08b13a` (missing private-form `403`-then-bearer
test). That test was already specified for FEAT-551 and never written; its
fixture is the one this task needs anyway, so it is folded in here rather than
left to rot.

**Discovered-from**: `issue:89f47e08b13a`

---

## Scope

Add integration tests to
`packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py`:

- `test_cross_tenant_envelope_is_refused` — **the regression test for the
  vulnerability**. Must fail against the pre-fix code.
- `test_teams_card_roundtrip_signed` — the happy path end to end.
- `test_teams_card_roundtrip_private_form_403_then_bearer` — closes
  `issue:89f47e08b13a`.
- `test_unsigned_renderer_against_signed_bot_is_refused` — the misconfiguration
  TASK-4656 exists to prevent.
- `test_mapped_tenant_overrides_validly_signed_cross_tenant_claim` — M6's reason
  to exist: a *correctly signed* envelope claiming another tenant, from a mapped
  AAD tenant, lands on the mapped slug.
- `test_derivation_runs_after_verification` — a rewritten `submit_url` cannot
  launder an envelope past the SSRF/path guard.

**NOT in scope**:
- Any production-code change. This task is tests only; if a test cannot pass
  without a code change, that is a defect in TASK-4653/4654/4655/4656 — report
  it rather than patching production code here.
- Unit-level tests of the helpers — TASK-4654.
- Wrapper-level mocking tests — TASK-4655.
- Closing the ledger issues; `/sdd-done` does that with `--resolved-by`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py` | MODIFY | Six integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.renderers.teams import (   # verified: formdesigner_submit.py:22
    ENVELOPE_KEY, RESERVED_CONTROL_KEYS, TeamsSubmitEnvelope,
)
from parrot_formdesigner.renderers.teams import TeamsFormRenderer  # verified: teams.py:88
from parrot.integrations.msteams.formdesigner_submit import (      # verified: wrapper.py:36
    EnvelopeRejected, parse_envelope, verify_envelope, post_submission,
    extract_answers, build_reply_card,
)
```

Symbols landed by this task's dependencies:

```python
resolve_submit_tenant                                         # TASK-4654
MSTeamsAgentConfig.formdesigner_allow_unsigned_submissions    # TASK-4653
MSTeamsAgentConfig.formdesigner_tenant_map                    # TASK-4653
setup_form_api(teams_signing_secret=...)                      # TASK-4656
```

**Read the existing `test_formdesigner_roundtrip.py` first** (6.9K) — it already
establishes how a card is rendered, how the bot leg is driven and how the POST
is intercepted. Reuse that harness; do not build a second one.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
class TeamsSubmitEnvelope(BaseModel):                             # line 52
    form_uid: uuid.UUID                                           # line 57
    tenant: str = Field(min_length=1)                             # line 58
    submit_url: HttpUrl                                           # line 61
    sig: str | None = None                                        # line 63
    def canonical_payload(self) -> bytes: ...                     # line 65
    def sign(self, secret: str) -> "TeamsSubmitEnvelope": ...     # line 71  (returns a COPY)
    def verify(self, secret: str) -> bool: ...                    # line 76

class TeamsFormRenderer(AdaptiveCardRenderer):                    # line 88
    RENDERER_NAME = "teams"                                       # line 91
    accepts_tenant = True                                         # line 92
    def __init__(self, public_base_url=None, *, api_base_path="/api/v1",
                 ui_base_path="", signing_secret=None, version=None): ...   # line 94
    def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope: ...  # line 112

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
class SubmitOutcome(BaseModel):                                   # line 65
    status: int                                                   # line 68
    body: dict[str, Any] | None = None                            # line 69
    error: str | None = None                                      # line 70
def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict[str, Any]: ...  # line 122
#   status 200 -> "Thank you!" + submission_id          (line 126)
#   status 422 -> validation errors listed              (line 134)
#   status 401/403 -> "You do not have permission ..."  (line 160)
#   status 404 -> "target form could not be found"      (line 170)
class RecentActivityCache:                                        # line 201
    def seen(self, activity_id: str) -> bool: ...                 # line 209
```

### Does NOT Exist

- ~~A pytest fixture that signs an envelope~~ — none exists yet. Build one from
  `TeamsSubmitEnvelope.sign()`, which returns a **copy** (`teams.py:74`); the
  original is not mutated.
- ~~`TeamsSubmitEnvelope.sign()` mutating in place~~ — it returns a new model.
- ~~`SubmitOutcome.ok`~~ / ~~`.success`~~ — the field is `status: int`
  (`formdesigner_submit.py:68`). `forwarded`/`success` belong to
  `parrot_formdesigner`'s own `SubmitOutcome`, a different class with the same
  name — do not confuse them.
- ~~`build_reply_card` raising on an unknown status~~ — it falls through to a
  generic "Could not reach the submission server" card (`formdesigner_submit.py:180`).
- ~~A live Bot Framework connection being required~~ — the existing round-trip
  tests drive the bot leg directly. Do not introduce network calls.
- ~~`RecentActivityCache` being reset between tests automatically~~ — it is an
  in-process TTL set held on the wrapper (`wrapper.py`, `self._formdesigner_recent`).
  Reusing one activity id across tests silently makes the second submission a
  no-op (`formdesigner_submit.py:209-224`). Use distinct ids.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsSubmitEnvelope",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#build_reply_card",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#SubmitOutcome"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **`test_cross_tenant_envelope_is_refused` must fail against the pre-fix code.**
  That is its entire value and it is an acceptance criterion. Verify it by
  stashing the fix (or by temporarily passing `require_signature=False`) and
  confirming it goes red; then restore. A regression test that passes before the
  fix is not a regression test.
- The attack payload is **self-consistent**: the envelope names another tenant
  *and* a `submit_url` whose path agrees with it, on an **allowed** host. An
  inconsistent payload would be refused by the pre-existing path check at
  `formdesigner_submit.py:54` and would prove nothing about this fix.
- Use distinct Bot Framework activity ids per test — see "Does NOT Exist".
- No network. Intercept the POST the way the existing round-trip tests do.

### References in Codebase

- `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py` —
  the existing harness; read it before writing anything.
- `formdesigner_submit.py:122-198` — the status→card mapping the assertions read.

---

## Implementation Blueprint

### Steps (in order)

1. Read the existing round-trip harness and identify its render → submit → POST
   seam — *why*: six new tests on a second harness would drift from the first.
2. Add a signing fixture and a `cross_tenant_envelope` fixture — *why*: five of
   the six tests need one or both.
3. Write `test_cross_tenant_envelope_is_refused` first and prove it red against
   the pre-fix behaviour — *why*: see Key Constraints.
4. Write the remaining five — *why*: they pin the behaviours the first one does
   not reach (happy path, private form, misconfiguration, override, ordering).

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py` (MODIFY)

```python
# AFTER — append fixtures and tests at end of file
SIGNING_SECRET = "test-secret-not-a-real-key"


@pytest.fixture
def signed_envelope():
    """A valid envelope for tenant 'navigator', signed — the happy path."""
    # FILL IN: build a TeamsSubmitEnvelope for tenant="navigator" with a submit_url whose path
    # is /api/v1/navigator/forms/<uid>/data on an allowed host, then .sign(SIGNING_SECRET).
    # Remember sign() returns a COPY.


@pytest.fixture
def cross_tenant_envelope():
    """The attack payload: unsigned, names tenant 'victim', self-consistent submit_url."""
    # FILL IN: tenant="victim" AND submit_url path /api/v1/victim/forms/<uid>/data on an
    # ALLOWED host, sig=None. Self-consistency matters: an inconsistent payload is caught by
    # the pre-existing path check and would prove nothing.


class TestSubmitSecurityRoundtrip:
    """FEAT-733 — what actually reaches the FormDesigner endpoint."""

    async def test_cross_tenant_envelope_is_refused(self, cross_tenant_envelope):
        """THE regression test: signed-mode bot + cross-tenant card -> refused, no POST."""
        # FILL IN: drive the bot leg with a signature-requiring config; assert the POST was
        # never made and the user got a refusal. MUST fail against the pre-fix code.

    async def test_teams_card_roundtrip_signed(self, signed_envelope):
        """render teams (with secret) -> bot verifies -> POST -> 200 reply card."""
        # FILL IN: assert the reply card carries the "Thank you!" text and the submission_id
        # (build_reply_card, formdesigner_submit.py:126-133)

    async def test_teams_card_roundtrip_private_form_403_then_bearer(self, signed_envelope):
        """Closes issue:89f47e08b13a — private form: no token -> 403 card; accepted bearer -> 200."""
        # FILL IN: two legs. The 403 card text comes from formdesigner_submit.py:160-169.
        # Use DISTINCT activity ids for the two legs or RecentActivityCache swallows the second.

    async def test_unsigned_renderer_against_signed_bot_is_refused(self):
        """The misconfiguration TASK-4656 prevents: sig=None meets a bot with a secret."""
        # FILL IN: render with signing_secret=None, submit to a signature-requiring bot;
        # assert refusal, NOT silent acceptance.

    async def test_mapped_tenant_overrides_validly_signed_cross_tenant_claim(self):
        """M6's reason to exist: a CORRECTLY SIGNED cross-tenant claim from a mapped AAD tenant."""
        # FILL IN: sign an envelope for tenant="victim" with the real secret (so it passes
        # verification), deliver it on an activity whose channel_data.tenant.id maps to
        # "navigator"; assert the POST went to the NAVIGATOR url, not the victim one.
        # This is the blast-radius reduction: a leaked secret stops being a cross-tenant write.

    async def test_derivation_runs_after_verification(self, cross_tenant_envelope):
        """A rewritten submit_url cannot launder an envelope past the SSRF/path guard."""
        # FILL IN: an envelope that fails verify_envelope must never reach resolve_submit_tenant
        # and must never be POSTed, even when its AAD tenant IS mapped.
```

**Why these six**: the first proves the hole is closed; the second proves the fix
did not break the normal path (the failure mode of a fail-closed change);
the third pays off an old ledger debt with a fixture we need anyway; the fourth
covers the operational trap that signing only one side creates; the fifth is the
only test that demonstrates M6 buys anything beyond the signature; the sixth pins
an ordering constraint that a future refactor of `_handle_formdesigner_submit`
would otherwise silently break.

### FILL IN checklist

- [ ] Read `test_formdesigner_roundtrip.py` and reuse its render/submit/POST-intercept seam
- [ ] `signed_envelope` and `cross_tenant_envelope` fixtures
- [ ] Six test bodies
- [ ] Prove `test_cross_tenant_envelope_is_refused` red against pre-fix behaviour, then restore
- [ ] Distinct activity ids across tests and across the two legs of the 403-then-bearer test

---

## Acceptance Criteria

- [ ] `test_cross_tenant_envelope_is_refused` passes after the fix and **fails
      against the pre-fix code** (verified by hand, noted in the Completion Note).
- [ ] The attack payload is self-consistent (tenant, `form_uid` and `submit_url`
      path all agree) on an allowed host, so it is not refused by the
      pre-existing path check.
- [ ] A signed round-trip returns a `200` reply card carrying the submission id.
- [ ] The private-form leg returns the `403` permission card without a token and
      `200` with an accepted bearer — `issue:89f47e08b13a` satisfied.
- [ ] An unsigned renderer against a signature-requiring bot is refused.
- [ ] A validly signed cross-tenant claim from a **mapped** AAD tenant is
      redirected to the mapped slug.
- [ ] An envelope that fails verification never reaches `resolve_submit_tenant`
      and is never POSTed.
- [ ] No production code was modified by this task.
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py`

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py -q`
- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py -q`

---

## Completion Note

<!-- Filled in by the implementing agent when the task is closed.
     MUST record the result of running test_cross_tenant_envelope_is_refused
     against the pre-fix code. -->
