# TASK-4654: `require_signature` on `verify_envelope` + `resolve_submit_tenant` helper

**Feature**: FEAT-733 — MS Teams submit envelope — fail-closed tenant isolation
**Spec**: `sdd/specs/msteams-submit-envelope-fail-closed.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Modules 2 and 6 (pure-helper halves). This is **gate 2 of 3**: make an
unsigned envelope a refusal by default at request time, and add the pure helper
that lets the bot prefer a Bot Framework-asserted tenant over the card's claim.

The defect is `formdesigner_submit.py:56`:

```python
if secret is not None and not env.verify(secret):
```

With `secret=None` the HMAC check does not run. The preceding path check does
not compensate, because `env.tenant` and `env.form_uid` are **client-supplied
Adaptive Card data** — the attacker controls both sides of the comparison.

Both changes live in the same file, so they are one task.

---

## Scope

- Add a keyword-only `require_signature: bool = True` to `verify_envelope()`.
- Rewrite the final branch so that skipping the signature is an explicit choice.
- Add `resolve_submit_tenant()` — a pure function, no `botbuilder` import.
- Write unit tests in `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py`,
  and update the existing call at `test_formdesigner_submit.py:56` that passes
  `secret=None` and now hits the new default.

**NOT in scope**:
- The config fields `formdesigner_allow_unsigned_submissions` /
  `formdesigner_tenant_map` — TASK-4653.
- The wrapper call site that passes the new arguments and extracts
  `channel_data` — TASK-4655.
- `setup_form_api(teams_signing_secret=...)` — TASK-4656.
- Roundtrip / integration tests — TASK-4657.
- Deriving `form_uid` from anything but the envelope (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` | MODIFY | `require_signature` param + `resolve_submit_tenant()` |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py` | MODIFY | Unit tests; update the existing `secret=None` call |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already at the top of formdesigner_submit.py — do NOT re-import:
from urllib.parse import urlparse                  # verified: formdesigner_submit.py:16
from parrot_formdesigner.renderers.teams import (  # verified: formdesigner_submit.py:22
    ENVELOPE_KEY, RESERVED_CONTROL_KEYS, TeamsSubmitEnvelope,
)
```

**`formdesigner_submit.py` imports no `botbuilder` symbol on purpose**
(docstring, `formdesigner_submit.py:3`) so the module stays unit-testable
without the `msteams` extra. **Do not add one.** `resolve_submit_tenant()` takes
the already-extracted GUID as a `str | None`, never a `TurnContext` or
`Activity`.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
class EnvelopeRejected(Exception):                                   # line 28
    """User-facing reason why a card submission was refused."""

def verify_envelope(                                                 # line 44
    env: TeamsSubmitEnvelope, *, allowed_hosts: list[str],
    secret: str | None, api_base_path: str = "/api/v1",
) -> None:
    # line 48  url = urlparse(str(env.submit_url))
    # line 49  if url.scheme != "https":
    # line 51  if (url.hostname or "").lower() not in {h.lower() for h in allowed_hosts}:
    # line 53  expected_path = f"{api_base_path.rstrip('/')}/{env.tenant}/forms/{env.form_uid}/data"
    # line 54  if url.path != expected_path:
    # line 56  if secret is not None and not env.verify(secret):     ← THE DEFECT

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
class TeamsSubmitEnvelope(BaseModel):                                # line 52
    v: Literal[1] = 1                                                # line 55
    wire: Literal["legacy"] = "legacy"                               # line 56
    form_uid: uuid.UUID                                              # line 57
    tenant: str = Field(min_length=1)                                # line 58
    form_version: str                                                # line 59
    is_public: bool                                                  # line 60
    submit_url: HttpUrl                                              # line 61
    form_url: HttpUrl                                                # line 62
    sig: str | None = None                                           # line 63
    def canonical_payload(self) -> bytes: ...                        # line 65
    def sign(self, secret: str) -> "TeamsSubmitEnvelope": ...        # line 71
    def verify(self, secret: str) -> bool: ...                       # line 76
```

`TeamsSubmitEnvelope` is a **Pydantic v2 `BaseModel`**: produce a modified copy
with `model_copy(update={...})` — the same idiom `sign()` already uses
(`teams.py:74`). It is not frozen, but copying keeps the function pure.

### Does NOT Exist

- ~~`verify_envelope(..., strict=...)`~~ — the parameter name is
  `require_signature`.
- ~~`TeamsSubmitEnvelope.is_signed`~~ / ~~`.require_signature`~~ — not model
  fields. Signedness is `env.sig is not None`.
- ~~`TeamsSubmitEnvelope.tenant_id`~~ — the field is `tenant` (a slug string),
  `teams.py:58`.
- ~~`env.submit_url` being a `str`~~ — it is a Pydantic `HttpUrl`
  (`teams.py:61`). `verify_envelope` already wraps it (`str(env.submit_url)`,
  `formdesigner_submit.py:48`); do the same, and note that assigning a plain
  `str` back through `model_copy` is re-validated by Pydantic.
- ~~A `botbuilder` import in this module~~ — there is none and must remain none.
- ~~`TenantInfo` carrying a name or slug~~ — its only field is `id`. The GUID is
  all the activity gives you; the slug can only come from the map.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#verify_envelope",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#EnvelopeRejected",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsSubmitEnvelope"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **The refusal text must not be an oracle.** "No secret configured" and "bad
  signature" must produce the *same* user-facing message, or an attacker can
  distinguish a misconfigured deployment from a signed one by probing. Log the
  distinction at `WARNING`; never return it.
- **Rebuild the URL, never string-replace the slug.** A tenant slug can also
  appear in the host (`navigator.forms.example.com`) or elsewhere in the path.
  `resolve_submit_tenant` must construct the new path from `api_base_path`, the
  resolved tenant and `env.form_uid`, exactly as `verify_envelope` builds
  `expected_path` at line 53. There is a test for this.
- **Keep the module `botbuilder`-free** (see Verified Imports).
- `resolve_submit_tenant` returns `(envelope, overridden)` — the caller logs on
  `overridden`, so the helper itself stays pure and side-effect free.

### References in Codebase

- `formdesigner_submit.py:53` — how `expected_path` is built; reuse the shape.
- `teams.py:71-74` — the `model_copy(update=...)` idiom.

---

## Implementation Blueprint

### Steps (in order)

1. Add the keyword-only `require_signature: bool = True` parameter — *why*: a
   default of `True` is what turns the silent skip into a refusal.
2. Replace the line-56 branch with the three-way logic below — *why*: the
   "no secret at request time" case must refuse, not pass.
3. Add `resolve_submit_tenant()` below `verify_envelope` — *why*: it belongs
   next to the other pure envelope helpers and before `extract_answers`.
4. Update `test_formdesigner_submit.py:56` to pass `require_signature=False` —
   *why*: that helper exercises the host/path guards, not the signature; without
   the flag every one of those cases now raises for the wrong reason.
5. Write the new tests — *why*: the URL-rebuild test is the only thing that
   catches a `str.replace` shortcut.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` (MODIFY) — signature

```python
# occurrences: 1 (verified: grep -c 'def verify_envelope(' formdesigner_submit.py)
# REPLACE the signature and docstring at `def verify_envelope(` (verified: formdesigner_submit.py:44)
def verify_envelope(
    env: TeamsSubmitEnvelope,
    *,
    allowed_hosts: list[str],
    secret: str | None,
    api_base_path: str = "/api/v1",
    require_signature: bool = True,
) -> None:
    """SSRF guard (spec S3). Order: https -> host allowlist -> path/tenant/uid -> signature.

    ``tenant`` and ``form_uid`` inside the envelope are client-supplied card data, so an
    unsigned envelope is unauthenticated routing. Raises ``EnvelopeRejected`` when
    ``require_signature`` is True and ``secret`` is None; pass ``require_signature=False``
    only where unsigned submissions were explicitly allowed.
    """
```

**Why this shape**: keyword-only keeps every existing positional call valid, and
the default is the safe value so a caller that does not know about the parameter
gets the fix. The docstring states *why* an unsigned envelope is refused, because
the next reader's instinct is that the path check already covers it.

### `formdesigner_submit.py` (MODIFY) — the branch

```python
# occurrences: 1 (verified: grep -c '    if secret is not None and not env.verify(secret):' formdesigner_submit.py)
# REPLACE `    if secret is not None and not env.verify(secret):` and its raise (verified: formdesigner_submit.py:56-57)
    if secret is None:
        if require_signature:
            logger.warning(
                "formdesigner envelope refused: no signing secret configured (tenant=%s)", env.tenant
            )
            raise EnvelopeRejected("Submission envelope signature is invalid.")
    elif not env.verify(secret):
        raise EnvelopeRejected("Submission envelope signature is invalid.")
```

**Why**: both failure paths raise the **identical** message — that is
deliberate, see Key Constraints, and there is a test asserting it. The
distinguishing detail goes to the log. `elif` (not a second `if`) keeps
`env.verify` from being called with `None`.

### `formdesigner_submit.py` (MODIFY) — the helper

```python
# occurrences: 1 (verified: grep -c 'def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]:' formdesigner_submit.py)
# BEFORE — insert above `def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]:` (verified: formdesigner_submit.py:60)
def resolve_submit_tenant(
    env: TeamsSubmitEnvelope,
    *,
    asserted_tenant_id: str | None,
    tenant_map: dict[str, str] | None,
    api_base_path: str = "/api/v1",
) -> tuple[TeamsSubmitEnvelope, bool]:
    """Return ``(envelope, overridden)``. A mapped ``asserted_tenant_id`` wins over ``env.tenant``.

    ``asserted_tenant_id`` is the Bot Framework-asserted Azure AD tenant GUID; ``tenant_map``
    maps it to a FormDesigner tenant slug. On override the ``submit_url`` path is REBUILT from
    ``api_base_path``/tenant/``form_uid`` — never string-replaced. Returns the envelope
    unchanged with ``False`` when the id is None, unmapped, or already agrees.
    """
    if not asserted_tenant_id or not tenant_map:
        return env, False
    resolved = tenant_map.get(asserted_tenant_id)
    if not resolved or resolved == env.tenant:
        return env, False
    # FILL IN: rebuild submit_url — take urlparse(str(env.submit_url)), replace ONLY the path
    # with f"{api_base_path.rstrip('/')}/{resolved}/forms/{env.form_uid}/data" (same shape as
    # verify_envelope's expected_path, formdesigner_submit.py:53), keep scheme/netloc/query,
    # and return env.model_copy(update={"tenant": resolved, "submit_url": <rebuilt>}), True.
    # Bounded by AC "rebuilding the path — never by string replacement".
    raise NotImplementedError
```

**Why**: the two early returns make "no assertion" and "unmapped" behave
identically to today, which is what keeps non-Teams channels and unmapped
tenants working. The third early return (`resolved == env.tenant`) means the
common, correctly-configured case reports `overridden=False` so the caller does
not log a spurious override on every submission.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        verify_envelope(_env(**over), allowed_hosts=["forms.test"], secret=None)' test_formdesigner_submit.py)
# REPLACE `        verify_envelope(_env(**over), allowed_hosts=["forms.test"], secret=None)` (verified: test_formdesigner_submit.py:56)
        verify_envelope(
            _env(**over), allowed_hosts=["forms.test"], secret=None, require_signature=False
        )
```

**Why**: that call exercises the https/host/path guards. Without the flag it now
raises on the signature before reaching the assertion under test, and the test
would pass for the wrong reason.

```python
# AFTER — append new test classes at end of file
class TestRequireSignature:
    """FEAT-733 — an unsigned envelope is refused unless explicitly permitted."""

    def test_verify_envelope_rejects_unsigned_by_default(self):
        """secret=None with default args -> EnvelopeRejected."""
        # FILL IN

    def test_verify_envelope_skips_when_not_required(self):
        """secret=None, require_signature=False -> passes."""
        # FILL IN

    def test_verify_envelope_rejects_bad_sig(self):
        """A secret set and a wrong sig -> EnvelopeRejected (unchanged behaviour)."""
        # FILL IN

    def test_verify_envelope_accepts_valid_sig(self):
        """Round-trip through TeamsSubmitEnvelope.sign() -> passes."""
        # FILL IN

    def test_verify_envelope_message_does_not_leak_cause(self):
        """Unsigned and bad-signature produce the SAME user-facing text."""
        # FILL IN: capture str(exc) from both paths and assert equality; bounded by AC
        # "the refusal text is identical ... no oracle"


class TestResolveSubmitTenant:
    """FEAT-733 — a mapped AAD GUID overrides the envelope's tenant claim."""

    def test_resolve_tenant_mapped_guid_overrides_envelope(self):
        """Mapped GUID != env.tenant -> tenant and submit_url rewritten, overridden True."""
        # FILL IN

    def test_resolve_tenant_mapped_guid_matching_is_noop(self):
        """Mapped GUID == env.tenant -> unchanged, overridden False."""
        # FILL IN

    def test_resolve_tenant_unmapped_guid_falls_back(self):
        """GUID absent from the map -> envelope untouched."""
        # FILL IN

    def test_resolve_tenant_no_asserted_id_falls_back(self):
        """asserted_tenant_id=None (non-Teams channel) -> untouched, no raise."""
        # FILL IN

    def test_resolve_tenant_rebuilds_url_not_string_replace(self):
        """A tenant slug that ALSO appears in the host survives the rewrite intact."""
        # FILL IN: e.g. env.tenant="forms", submit_url="https://forms.test/api/v1/forms/forms/<uid>/data",
        # map the GUID to "other"; assert the host is still "forms.test" and only the tenant
        # segment changed. This test fails for any str.replace implementation.
```

**Why**: `test_resolve_tenant_rebuilds_url_not_string_replace` is the only test
that distinguishes a correct rebuild from a `.replace()` shortcut, and the
shortcut is the obvious thing to write. Keep its fixture deliberately adversarial.

### FILL IN checklist

- [ ] `formdesigner_submit.py::resolve_submit_tenant` — the URL rebuild; bounded by "rebuild, never string-replace"
- [ ] `test_formdesigner_submit.py::TestRequireSignature` — five test bodies, including the no-oracle assertion
- [ ] `test_formdesigner_submit.py::TestResolveSubmitTenant` — five test bodies, including the adversarial host fixture
- [ ] Confirm `logger` is in scope in `formdesigner_submit.py` (it is — `logger = logging.getLogger(__name__)`, line 24)

---

## Acceptance Criteria

- [ ] `verify_envelope()` refuses an unsigned envelope by default; the skip
      requires an explicit `require_signature=False`.
- [ ] The refusal text is identical for "no secret configured" and "bad
      signature"; the distinction appears only in the log.
- [ ] `env.verify()` is never called with `secret=None`.
- [ ] `resolve_submit_tenant()` overrides a conflicting `env.tenant` for a mapped
      GUID, rewriting the `{tenant}` segment by **rebuilding** the path.
- [ ] An absent, unmapped, or already-matching GUID returns the envelope
      unchanged with `overridden=False`, and raises nothing.
- [ ] `formdesigner_submit.py` still imports no `botbuilder` symbol and the
      module imports cleanly without the `msteams` extra.
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py`

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py -q`

---

## Completion Note

<!-- Filled in by the implementing agent when the task is closed. -->
