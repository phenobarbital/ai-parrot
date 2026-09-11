# TASK-3167: Context projector — `services/sandbox/projector.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, resolving OQ-5. `FormEventContext.auth_context` is typed
`Any` and is a **live** `AuthContext` object (`core/events.py:128`) — it
can never be serialized across a sandbox boundary. This module is the ONE
place that converts a live `FormEventContext` into the serializable
`SandboxContext` (TASK-3161), applying the per-tier claim projection
policy: `token`/`headers` never cross at any tier; tier 1 gets no identity
at all; tiers 2-4 get `scheme` plus manifest-declared subkeys of `claims`
from a fixed safe set.

**The governing invariant, restated because it is the single most
important line in this task**: the projected identity set never grows
with tier. Higher tiers buy more brokered *actions* (via the host broker,
TASK-3171), never more *secrets*.

---

## Scope

- Implement `ContextProjector.project(ctx: FormEventContext, bundle:
  SnippetBundle) -> SandboxContext` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/projector.py`.
- Implement the per-tier claim policy exactly as specified (see blueprint
  table).
- Reject non-JSON-serialisable payload/schema_dump values loudly (raise,
  do not silently drop).
- Write `packages/parrot-formdesigner/tests/unit/test_context_projector.py`.

**NOT in scope**: anything about `VisitEventContext`/`dispatch_visit()` —
the spec's snippet feature only binds to the five `FormEventName` members
(G2/C2); visit events are out of scope entirely, not just for this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/__init__.py` | CREATE | Empty package marker |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/projector.py` | CREATE | `ContextProjector` |
| `packages/parrot-formdesigner/tests/unit/test_context_projector.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.events import FormEventContext  # verified: core/events.py:106
from parrot_formdesigner.core.snippets import (
    CapabilityTier, SandboxContext, SnippetBundle,
)  # TASK-3161
from parrot_formdesigner.services.auth_context import AuthContext  # verified: services/auth_context.py:20
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
class FormEventContext(BaseModel):                          # line 106
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    event: FormEventName
    form_id: str
    tenant: str | None
    auth_context: Any                              # line 128 — LIVE AuthContext object
    payload: Mapping[str, Any] | None = None
    schema_dump: Mapping[str, Any] | None = None
    error: BaseException | None = None
    user_message: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py
class AuthContext(BaseModel):                                # line 20
    scheme: Literal["none", "bearer", "api_key", "custom"]   # line 39 — safe metadata
    token: str | None = None                                 # line 40 — SECRET, NEVER project
    headers: dict[str, str] = {}                              # line 41 — SECRET, NEVER project
    claims: dict[str, Any] = {}                               # line 42 — selectively projectable
```

### Per-tier claim projection policy (resolved OQ-5, spec §2)
| Tier | Projected identity |
|---|---|
| 1 `pure` | Nothing. `claims={}`, no `scheme` field populated in `SandboxContext` (note: `SandboxContext` has no separate `scheme` field — TASK-3161's model only has `claims: Mapping[str, Any]`; represent "scheme" as `claims.get("_scheme")` **only for tiers ≥2** — see blueprint FILL IN for the exact key choice) |
| 2 `helpers` | `scheme` + manifest-declared subkeys of `claims`, drawn from the fixed safe set: `sub`, `tenant`, `roles`, `scope`, `email`, `preferred_username` |
| 3 `brokered` | Identical to tier 2 |
| 4 `toolkit` | Identical to tier 2 |

### Does NOT Exist
- ~~`SandboxContext.scheme`~~ — the model (TASK-3161) has no dedicated
  `scheme` field; it must be folded into `claims` or the model must gain
  one — this is a genuine design gap between §2's prose table (which
  talks about "scheme" as if projected separately) and §2's actual
  `SandboxContext` Pydantic definition (which has only `claims`). Resolve
  as a `# FILL IN` in the blueprint — do not silently invent a field on
  `SandboxContext` without also updating TASK-3161's file, and do not
  silently drop `scheme` either.
- ~~`services/sandbox/`~~ — does not exist yet; this task creates the
  subpackage (shared with TASK-3168-3172, first module to land in it).
- ~~Any network or broker call in this module~~ — `ContextProjector` is
  pure data transformation; it must not call the broker or execute
  anything.

---

## Implementation Notes

### Key Constraints
- **Structural enforcement, not policy**: because `SandboxContext` has no
  `token`/`headers` field (TASK-3161), there is no code path in this
  module that could serialize one even by accident — do not add a
  "redact" step that reads `auth_context.token`; simply never reference it.
- The safe claim-subkey set (`sub`, `tenant`, `roles`, `scope`, `email`,
  `preferred_username`) is a **maximum**, not a mandate — a manifest may
  declare a subset via `auth_claims`; project only the intersection of
  `auth_claims` and the safe set (a manifest declaring an *unsafe* key,
  e.g. `"password"`, must not get it projected just because it asked).
- Non-serialisable `payload`/`schema_dump` values must fail loudly
  (`raise TypeError` or similar) at projection time — a snippet receiving
  a truncated/`None`-substituted payload silently is worse than a 500.

### References in Codebase
- `core/events.py:106-133` — `FormEventContext`, full definition shown above.
- `services/auth_context.py:20-45` — `AuthContext`, full definition shown above.

---

## Implementation Blueprint

### Steps (in order)
1. Resolve the `SandboxContext.scheme` gap noted above — *why*: every
   other step depends on where "scheme" goes.
2. Implement the safe-claims constant and the per-tier branch.
3. Implement JSON-serialisability validation for `payload`/`schema_dump`.
4. Implement `ContextProjector.project()`.
5. Write and run tests, covering all four tiers plus the two negative
   tests (`test_projector_never_emits_token`, `test_projector_rejects_unserialisable`).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/sandbox/projector.py` (CREATE)
```python
"""Live FormEventContext -> serialisable SandboxContext (FEAT-459 / M7).

Resolves OQ-5: token/headers NEVER cross the sandbox boundary at any tier
(structurally — SandboxContext has no such field to populate). Tier 1
receives no identity at all. Tiers 2-4 receive an identical projected
identity set — the governing invariant is that MORE TIER NEVER MEANS MORE
SECRETS, only more brokered actions (enforced elsewhere, by the host
broker, TASK-3171).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from parrot_formdesigner.core.events import FormEventContext
from parrot_formdesigner.core.snippets import CapabilityTier, SandboxContext, SnippetBundle
from parrot_formdesigner.services.auth_context import AuthContext

logger = logging.getLogger(__name__)

# Fixed maximum safe-claim set (spec §2 OQ-5). A manifest's `auth_claims`
# may only narrow this set, never extend it.
SAFE_CLAIM_KEYS: frozenset[str] = frozenset(
    {"sub", "tenant", "roles", "scope", "email", "preferred_username"}
)

# FILL IN (resolves the SandboxContext.scheme gap noted in the Codebase
# Contract): this key folds AuthContext.scheme into SandboxContext.claims
# for tiers >= 2, since SandboxContext has no dedicated scheme field.
# Leading underscore signals "projector-injected metadata, not a real
# claim" to a snippet author reading their own ctx.claims. If a reviewer
# prefers adding `scheme: str | None = None` to SandboxContext instead
# (TASK-3161), do that there and drop this constant — record the choice
# in the Completion Note either way, since it is a genuine spec gap, not
# an oversight in this task.
_SCHEME_CLAIM_KEY = "_scheme"


def _assert_json_serialisable(value: Mapping[str, Any] | None, *, field_name: str) -> None:
    """Raise loudly if `value` cannot round-trip through json.dumps/loads."""
    if value is None:
        return
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} is not JSON-serialisable and cannot cross the "
            f"sandbox boundary: {exc}"
        ) from exc


class ContextProjector:
    """Converts a live FormEventContext into a serialisable SandboxContext."""

    def __init__(self) -> None:
        self.logger = logger

    async def project(self, ctx: FormEventContext, bundle: SnippetBundle) -> SandboxContext:
        """Project `ctx` down to exactly what `bundle`'s tier is allowed to see.

        Args:
            ctx: The live dispatch-time context. `ctx.auth_context` is
                read ONLY for `.scheme` and `.claims` (never `.token`,
                never `.headers`) and only at tier >= 2.
            bundle: Supplies the tier (via `bundle.manifest.tier`) and the
                declared `auth_claims` allowlist.

        Returns:
            A SandboxContext safe to serialise across the worker boundary.

        Raises:
            TypeError: `ctx.payload` or `ctx.schema_dump` is not JSON-serialisable.
        """
        _assert_json_serialisable(ctx.payload, field_name="payload")
        _assert_json_serialisable(ctx.schema_dump, field_name="schema_dump")

        claims: dict[str, Any] = {}
        if bundle.manifest.tier != CapabilityTier.PURE:
            auth = ctx.auth_context
            if isinstance(auth, AuthContext):
                claims[_SCHEME_CLAIM_KEY] = auth.scheme
                allowed_keys = set(bundle.manifest.auth_claims) & SAFE_CLAIM_KEYS
                for key in allowed_keys:
                    if key in auth.claims:
                        claims[key] = auth.claims[key]
            else:
                # FILL IN: decide behavior when ctx.auth_context is not an
                #   AuthContext instance (e.g. None in a test harness) —
                #   bounded by "tier 1 has no identity" NOT applying here
                #   (tier is already known to be >= 2 in this branch); the
                #   safest default is an empty claims dict with a debug
                #   log, never raising, since a missing auth_context is a
                #   caller/test setup issue, not a security violation.
                self.logger.debug(
                    "ContextProjector: auth_context is not an AuthContext "
                    "instance (%r) — projecting empty claims", type(auth)
                )

        return SandboxContext(
            event=ctx.event,
            form_id=ctx.form_id,
            tenant=ctx.tenant,
            claims=claims,
            payload=ctx.payload,
            schema_dump=ctx.schema_dump,
            user_message=ctx.user_message,
            extra=ctx.extra,
        )
```
**Why this shape**: the `isinstance(auth, AuthContext)` guard exists
because `FormEventContext.auth_context` is typed `Any` specifically to
avoid a circular import (its own docstring says so) — this projector is
the first place in the codebase that needs to actually *use* it as an
`AuthContext`, so a defensive type check is the correct boundary
behavior, not paranoia. The `tier != PURE` branch (rather than `tier in
(HELPERS, BROKERED, TOOLKIT)`) is deliberately written as a negative check
against the one tier that gets nothing, so a fifth tier added later
defaults to "gets claims" rather than silently getting none — FILL IN
note if a reviewer prefers the explicit positive enumeration instead.

### `packages/parrot-formdesigner/tests/unit/test_context_projector.py` (CREATE)
```python
"""Unit tests for ContextProjector — FEAT-459 / TASK-3167."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import FormEventContext
from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource
from parrot_formdesigner.services.auth_context import AuthContext
from parrot_formdesigner.services.sandbox.projector import ContextProjector


def _bundle(tier: CapabilityTier, auth_claims: tuple[str, ...] = ()) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref="f.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=tier, auth_claims=auth_claims),
        python_source="def run(): ...",
        python_sha256="a" * 64,
    )


def _ctx(auth: AuthContext | None) -> FormEventContext:
    return FormEventContext(
        event="onBeforeSubmit", form_id="f1", tenant="acme",
        auth_context=auth, payload={"a": 1},
    )


async def test_projector_tier1_has_no_claims() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", token="secret", claims={"sub": "u1"})
    result = await projector.project(_ctx(auth), _bundle(CapabilityTier.PURE))
    assert result.claims == {}


async def test_projector_never_emits_token() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", token="super-secret", headers={"Authorization": "Bearer x"})
    result = await projector.project(_ctx(auth), _bundle(CapabilityTier.HELPERS, auth_claims=("sub",)))
    assert "token" not in result.model_fields
    assert "super-secret" not in str(result.model_dump())


async def test_projector_claims_are_allowlisted() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", claims={"sub": "u1", "password_hint": "nope"})
    bundle = _bundle(CapabilityTier.HELPERS, auth_claims=("sub", "password_hint"))
    result = await projector.project(_ctx(auth), bundle)
    assert result.claims.get("sub") == "u1"
    assert "password_hint" not in result.claims  # not in SAFE_CLAIM_KEYS


async def test_projector_tier4_claims_equal_tier2() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", claims={"sub": "u1"})
    tier2 = await projector.project(_ctx(auth), _bundle(CapabilityTier.HELPERS, auth_claims=("sub",)))
    tier4 = await projector.project(_ctx(auth), _bundle(CapabilityTier.TOOLKIT, auth_claims=("sub",)))
    assert tier2.claims == tier4.claims


async def test_projector_rejects_unserialisable() -> None:
    projector = ContextProjector()
    ctx = FormEventContext(
        event="onBeforeSubmit", form_id="f1", tenant="acme",
        auth_context=None, payload={"bad": object()},
    )
    with pytest.raises(TypeError):
        await projector.project(ctx, _bundle(CapabilityTier.PURE))


async def test_projector_handles_missing_auth_context_gracefully() -> None:
    # FILL IN: project with auth_context=None at tier HELPERS, assert no
    #   exception and claims == {} (or {_scheme_key: None} depending on
    #   the FILL IN decision in projector.py — align this assertion with
    #   whatever the implementer chose there).
    pass
```
**Why**: the four OQ-5-derived tests (tier1-empty, never-emits-token,
allowlist, tier-parity) are the security-critical assertions and are
written in full; the unserialisable-payload test is also complete since
it is a one-line negative test. The missing-auth-context test is a stub
because its expected value depends on the projector's own FILL IN
resolution.

### FILL IN checklist
- [ ] `projector.py` — resolve `SandboxContext.scheme` gap (fold into `claims` via `_SCHEME_CLAIM_KEY`, or add a field to `SandboxContext` in TASK-3161 and update here) — bounded by OQ-5
- [ ] `projector.py::project` — behavior when `auth_context` is not an `AuthContext` instance at tier >= 2
- [ ] `test_projector_handles_missing_auth_context_gracefully` — align assertion with the above

---

## Acceptance Criteria

- [ ] Tier `PURE` always projects `claims == {}` regardless of the live `AuthContext`
- [ ] `SandboxContext.model_dump()` never contains the string value of `AuthContext.token` or any `headers` entry, at any tier
- [ ] A manifest's `auth_claims` outside `SAFE_CLAIM_KEYS` is never projected, even if present in `AuthContext.claims`
- [ ] Tier `HELPERS`, `BROKERED`, and `TOOLKIT` produce an identical `claims` dict for the same input `AuthContext`/manifest `auth_claims`
- [ ] A non-JSON-serialisable `payload` or `schema_dump` raises `TypeError` from `project()`
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_context_projector.py -v`
- [ ] `ruff check` and `mypy` clean on `services/sandbox/projector.py`

---

## Test Specification

See the blueprint's test file above — 6 test functions, 1 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "Auth claim projection policy", §3 Module 7)
2. **Check dependencies** — TASK-3161 must be `done`
3. **Verify the Codebase Contract** — confirm `AuthContext` still has exactly `scheme`/`token`/`headers`/`claims` at `services/auth_context.py:39-42`
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:` — pay special attention to the `SandboxContext.scheme` design gap, which may require a small coordinated edit back to TASK-3161's file if TASK-3161 has already been merged
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3167-context-projector.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
