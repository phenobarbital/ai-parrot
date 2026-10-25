# TASK-4658: Document the signing-secret pairing, the escape hatch and tenant resolution

**Feature**: FEAT-733 — MS Teams submit envelope — fail-closed tenant isolation
**Spec**: `sdd/specs/msteams-submit-envelope-fail-closed.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4653, TASK-4654, TASK-4655, TASK-4656
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The documentation is part of the fix, not an afterthought.

`docs/formdesigner-msteams-renderer.md:68` today says only:

> `sig` is omitted (`null`) when no secret is configured.

It states the mechanism and omits the consequence — that an unsigned envelope
is unauthenticated routing, that the two secrets are one setting in two places,
and that configuring only one of them breaks every submission. That omission is
a named cause in ledger `issue:bcd04b2170a0` ("Undocumented"), so this task is
required to close it.

Depends on all four implementation tasks because it documents their final names.

---

## Scope

Edit `docs/formdesigner-msteams-renderer.md`:

- Replace the bare `sig`-is-optional sentence with the pairing rule.
- Add a **"Configuring Teams submissions securely"** section listing all three
  environment variables with which side each belongs to.
- Add a **"Tenant resolution"** subsection: the AAD-GUID → slug mapping, the
  fallback, and explicitly that the mapping does **not** remove the need for the
  signature.
- Document the escape hatch and why it is development-only.

**NOT in scope**:
- Any code change.
- `docs/` files other than `formdesigner-msteams-renderer.md`.
- A migration note for existing deployments — spec §8 Q3 resolved that no live
  deployment relies on unsigned envelopes, so there is nothing to migrate.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/formdesigner-msteams-renderer.md` | MODIFY | Pairing rule, secure-configuration section, tenant resolution |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

None — documentation only.

### Existing Signatures to Use

The names this document must get exactly right, all verified:

```python
# FormDesigner side (packages/parrot-formdesigner)
setup_form_api(..., teams_signing_secret: str | None = None)   # TASK-4656, routes.py
FORMDESIGNER_TEAMS_SIGNING_SECRET                              # TASK-4656, env var
TeamsFormRenderer(..., signing_secret: str | None = None)      # verified: teams.py:94,108

# Bot side (packages/ai-parrot-integrations)
MSTeamsAgentConfig.formdesigner_submit_secret                  # verified: models.py:64
MSTeamsAgentConfig.formdesigner_submit_token                   # verified: models.py:63
MSTeamsAgentConfig.formdesigner_allowed_hosts                  # verified: models.py:62
MSTeamsAgentConfig.formdesigner_allow_unsigned_submissions     # TASK-4653
MSTeamsAgentConfig.formdesigner_tenant_map                     # TASK-4653
UnsignedSubmitConfigError                                      # TASK-4653
<NAME>_FORMDESIGNER_SUBMIT_SECRET                              # verified: models.py:91
<NAME>_FORMDESIGNER_ALLOW_UNSIGNED                             # TASK-4653
<NAME>_FORMDESIGNER_TENANT_MAP                                 # TASK-4653
```

Existing document structure (`docs/formdesigner-msteams-renderer.md`):

```
# FormDesigner → MS Teams: Adaptive Card renderer and bot submit path (FEAT-551)
## What it does                     (line 3)
## Rendering a form                 (line 25)
## The `_formdesigner` envelope      (line 49)
   line 67: "`sig` is the HMAC-SHA256 hex digest of the envelope's canonical JSON (every field except `sig`,"
```

### Does NOT Exist

- ~~A security or configuration section in this document today~~ — there is
  none; this task creates it.
- ~~`FORMDESIGNER_SIGNING_SECRET`~~ (without `TEAMS_`) — the variable is
  `FORMDESIGNER_TEAMS_SIGNING_SECRET`. Do not shorten it in the docs.
- ~~A single shared variable for both sides~~ — they are two independent
  settings in two distributions that the operator gives the same value. No code
  compares them (spec §7). Do not write that the system checks they match.
- ~~`formdesigner_require_signature`~~ — the field is
  `formdesigner_allow_unsigned_submissions`, inverted.
- ~~The tenant map being derived from `app_tenantid`~~ — that is the *bot's* AAD
  tenant, not the caller's, and a different namespace from the FormDesigner slug.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/formdesigner-msteams-renderer.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Do not overstate M6.** The tenant mapping narrows blast radius for *mapped*
  tenants; an unmapped caller falls back to the envelope. Writing that the bot
  "always determines the tenant itself" would be false and would invite a future
  reader to relax the signature requirement — reopening the vulnerability. The
  spec's §2 "Why derivation does not replace the signature" is the wording to
  follow.
- Match the document's existing voice: short declarative sentences, fenced
  blocks for wire shapes and config, no marketing register.
- Name which side each setting belongs to on every mention. Operators configure
  the two distributions separately and the whole bug class here is setting one
  and not the other.

### References in Codebase

- `docs/formdesigner-msteams-renderer.md:49-70` — the envelope section being extended.
- Spec §2 of FEAT-733 — the derivation/signature relationship, to paraphrase.

---

## Implementation Blueprint

### Steps (in order)

1. Replace the `sig` sentence with the pairing rule — *why*: it is the sentence
   that currently misleads, and the one a reader lands on first.
2. Add "Configuring Teams submissions securely" after the envelope section —
   *why*: an operator needs all three variables in one place, not scattered.
3. Add "Tenant resolution" under it — *why*: it is a consequence of the same
   configuration and belongs beside it.
4. Re-read for the overstatement trap in Key Constraints — *why*: it is the one
   way this document can actively cause harm later.

### `docs/formdesigner-msteams-renderer.md` (MODIFY) — the `sig` sentence

```markdown
<!-- occurrences: 1 (verified: grep -c '`sig` is the HMAC-SHA256 hex digest of the envelope.s canonical JSON (every field except `sig`,' docs/formdesigner-msteams-renderer.md) -->
<!-- REPLACE the paragraph beginning at line 67 (verified: docs/formdesigner-msteams-renderer.md:67) -->
`sig` is the HMAC-SHA256 hex digest of the envelope's canonical JSON (every field except
`sig`, keys sorted, compact separators), computed with `TeamsSubmitEnvelope.sign()`.

**The signature is required.** `tenant` and `form_uid` inside the envelope are
client-supplied Adaptive Card data: without a valid signature the bot has no way to tell
a legitimate card from one a user crafted to target another tenant, and it forwards the
submission under its own bearer token. A bot configured with a bearer token but no
signing secret therefore refuses to start, raising `UnsignedSubmitConfigError`.
```

**Why**: states the consequence, not just the mechanism, and names the exception
so an operator who hits it can search for it.

### `docs/formdesigner-msteams-renderer.md` (MODIFY) — new sections

```markdown
<!-- AFTER — insert a new section below the `_formdesigner` envelope section -->
## Configuring Teams submissions securely

The signing secret is **one setting in two places**. Both sides must be given the
same value; nothing in the code compares them.

| Side | Setting | Environment variable |
|---|---|---|
| FormDesigner (emits + signs) | `setup_form_api(teams_signing_secret=...)` | `FORMDESIGNER_TEAMS_SIGNING_SECRET` |
| Teams bot (verifies) | `MSTeamsAgentConfig.formdesigner_submit_secret` | `<NAME>_FORMDESIGNER_SUBMIT_SECRET` |

Configure **both or neither**:

- Neither → envelopes carry `sig: null`. Acceptable only when the bot has no
  `formdesigner_submit_token`: with no bearer there is nothing to escalate with.
- FormDesigner only → the bot ignores the signature. No protection.
- Bot only → every submission is refused, because nothing signs the envelopes.

Passing an explicit `teams_renderer=` to `setup_form_api()` takes precedence;
configure `signing_secret` on that renderer instead.

### The escape hatch

`formdesigner_allow_unsigned_submissions=True` (or `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED`)
permits the unsigned combination and logs a `WARNING` on every startup.

**Development only.** With it set, any user who can reach the bot can submit into
any tenant whose form is served from an allowed host. Never set it in an
environment holding real data.

### Tenant resolution

When `formdesigner_tenant_map` is configured, the bot prefers the tenant Microsoft
Teams asserts over the one the card claims:

```
{"<azure-ad-tenant-guid>": "<formdesigner-tenant-slug>"}
```

The GUID comes from the activity (`channelData.tenant.id`) and is asserted by Bot
Framework, not by the card. On a mapped GUID the bot rewrites the envelope's
`tenant` and the `{tenant}` segment of `submit_url`; on an unmapped or absent GUID
it uses the envelope's `tenant` unchanged.

**This does not replace the signature.** Because an unmapped caller falls back to
the envelope, the mapping constrains mapped tenants only. What it buys is blast
radius: for a mapped tenant, a leaked or replayed signing secret is no longer
enough to write into a different tenant.
```

**Why this shape**: the "both or neither" table is the operational core — the
three-row failure enumeration is what prevents the half-configured state that
caused this feature to exist. The closing paragraph of "Tenant resolution" is
load-bearing: it is the sentence that stops a future reader concluding the
signature is now optional.

### FILL IN checklist

- [ ] Confirm the exact heading level and position so the new sections sit correctly in the document's existing structure
- [ ] Check whether the document has a table of contents that needs the new headings

---

## Acceptance Criteria

- [ ] The `sig` paragraph states that the signature is required and why, naming
      `UnsignedSubmitConfigError`.
- [ ] A "Configuring Teams submissions securely" section lists all three
      environment variables with the side each belongs to.
- [ ] The both-or-neither rule is stated, with all three misconfiguration
      outcomes enumerated.
- [ ] The `teams_renderer=` precedence is documented.
- [ ] The escape hatch is documented as development-only, with its concrete risk.
- [ ] A "Tenant resolution" subsection documents the map, the fallback, and
      explicitly that it does **not** replace the signature.
- [ ] No setting is named inconsistently with the Codebase Contract above.
- [ ] No code files were modified by this task.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py -q`
- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py -q`

> Documentation-only task: these commands are the feature's regression guard,
> re-run to confirm the tree is still green at close time.

---

## Completion Note

Seat qwen failed fidelity twice (edited test_formdesigner_roundtrip.py and sdd/ledger/events.jsonl, out of scope); attempt 3 implemented by the orchestrator (docs only). Merge-tier validation green.
