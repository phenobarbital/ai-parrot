# TASK-3161: Snippet & manifest Pydantic models — `core/snippets.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. This is the Track 1 foundation: every other module in the
feature (M2–M16) imports from this file. It defines the data the rest of the
feature moves around — `CapabilityTier`, the manifest, the bundle, the
sandbox boundary types, and the typed exceptions the loader/router/broker
raise. None of this exists today (spec §6 "Does NOT Exist": `CodeSnippet`,
`CapabilityManifest`, `SandboxedHandler` all 0 hits).

Getting the model shapes right here is what lets M3 (resolver), M4/M5
(loaders), M7 (projector), M9-M12 (sandbox pools/router) all be written
against a stable contract without touching this file again.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py`
  with: `CapabilityTier`, `SnippetSource`, `SnippetStatus`, `BrokerAllowlist`,
  `CapabilityManifest`, `SnippetBundle`, `SandboxContext`, `AbortSignal`,
  `SandboxOutcome`, and the typed exceptions `SnippetIntegrityError`,
  `SnippetTierUnavailableError`, `CapabilityDenied`, `SnippetNotApprovedError`.
- Write `packages/parrot-formdesigner/tests/unit/test_snippets_models.py`
  covering the acceptance criteria below.

**NOT in scope**: the `on_failure` field on `FormEventBinding` (TASK-3162);
any loader, resolver, sandbox, or broker logic (TASK-3163 onward) — this
task is pure data modeling, no I/O, no registry interaction.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py` | CREATE | All new Pydantic models + typed exceptions |
| `packages/parrot-formdesigner/tests/unit/test_snippets_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
from parrot_formdesigner.core.events import (
    FormEventName,      # line 32 — Literal["onBeforeOpen", "onSchemaLoaded",
                         #   "onBeforeSubmit", "onAfterSubmit", "onError"]
    EventResolution,     # line 170
)
from pydantic import BaseModel, ConfigDict, Field
from enum import StrEnum
from collections.abc import Mapping
from typing import Any
from datetime import datetime
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/events.py
FormEventName = Literal[                                    # line 32
    "onBeforeOpen", "onSchemaLoaded", "onBeforeSubmit",
    "onAfterSubmit", "onError",
]

class EventResolution(BaseModel):                            # line 170
    model_config = ConfigDict(extra="forbid")
    payload: Mapping[str, Any] | None = None
    schema_overrides: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    user_message: str | None = None
```
Every existing model in `core/events.py` uses `model_config = ConfigDict(extra="forbid")`
with no exceptions — match that convention on every new model here (spec §7
"Patterns to Follow").

### Does NOT Exist
- ~~`CodeSnippet`~~ — no snippet model exists anywhere in `packages/` (spec §6, re-verified 2026-08-24).
- ~~`CapabilityManifest` / `capability_manifest`~~ — entirely new; this task creates the first.
- ~~`SandboxedHandler`~~ — does not exist.
- ~~`parrot_formdesigner/core/sandbox.py`~~ — the module path is `core/snippets.py`, not `core/sandbox.py`.
  Sandbox *execution* code (M7-M12) lives under `services/sandbox/`, a different
  subpackage — this task's file holds only the shared data models.
- ~~`FormEventBinding.on_failure`~~ — does not exist yet; TASK-3162 adds it to
  `core/events.py`, a different file from this task's.

---

## Implementation Notes

### Key Constraints
- `model_config = ConfigDict(extra="forbid")` on every model — no exceptions.
- Google-style docstrings + strict type hints on every class/field.
- No I/O, no imports from `services/` — this module sits below the service
  layer (`core/` never imports `services/`, matching the existing
  `core/events.py` boundary).
- `SandboxContext` must **structurally** have no `token`/`headers` field —
  this is the OQ-5 security invariant ("the field does not exist" is the
  enforcement mechanism, not a runtime check). Do not add either field even
  as `Optional`.
- `CapabilityManifest.timeout_ms` and `.max_memory_mb` use `Field(..., ge=X, le=Y)`
  bounds exactly as specified — these become the pool sizing bounds M9 enforces.

### References in Codebase
- `core/events.py` — the sibling module this one is modeled after: same
  `ConfigDict(extra="forbid")` convention, same "one file, all related
  models + one typed exception" shape.

---

## Implementation Blueprint

### Steps (in order)
1. Create `core/snippets.py` with the four enums first (`CapabilityTier`,
   `SnippetSource`, `SnippetStatus`) — *why*: every other model in the file
   references at least one of them.
2. Add `BrokerAllowlist` then `CapabilityManifest` — *why*: `SnippetBundle`
   embeds `CapabilityManifest`, so it must exist first.
3. Add `SnippetBundle`, `SandboxContext`, `AbortSignal`, `SandboxOutcome` —
   *why*: these are the cross-boundary wire types M7/M8/M12 depend on.
4. Add the four typed exceptions at the bottom — *why*: keeping exceptions
   after the models they reference in docstrings/type hints reads top-down.
5. Write the tests, run `pytest packages/parrot-formdesigner/tests/unit/test_snippets_models.py -v`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py` (CREATE)
```python
"""Snippet, manifest, and sandbox-boundary models for FEAT-459.

Defines the data every other formbuilder-custom-code module (loaders,
resolver, sandbox pools, router, broker) shares. Mirrors the
``model_config = ConfigDict(extra="forbid")`` convention of
``core/events.py`` — no new model in this feature accepts unknown fields.

Public surface:
    - CapabilityTier, SnippetSource, SnippetStatus
    - BrokerAllowlist, CapabilityManifest
    - SnippetBundle
    - SandboxContext, AbortSignal, SandboxOutcome
    - SnippetIntegrityError, SnippetTierUnavailableError,
      CapabilityDenied, SnippetNotApprovedError
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot_formdesigner.core.events import EventResolution, FormEventName


class CapabilityTier(StrEnum):
    """Declared power level of a snippet; selects its executor (spec §2)."""

    PURE = "pure"          # payload + schema only, no I/O
    HELPERS = "helpers"    # + curated stdlib subset, metadata, declared claims
    BROKERED = "brokered"  # + host-mediated allowlisted outbound calls
    TOOLKIT = "toolkit"    # + registered parrot tools/agents


class SnippetSource(StrEnum):
    """Where a bundle came from. Determines its approval gate and tier cap."""

    GIT = "git"  # platform-wide, tenant=None, approved by merged PR
    DB = "db"    # tenant-scoped, approved in-app by a tenant admin


class SnippetStatus(StrEnum):
    """Lifecycle of a DB-sourced tenant snippet.

    GIT bundles are always PUBLISHED by construction — an unmerged snippet
    does not exist on disk, so there is no DRAFT/REVOKED state for it.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    REVOKED = "revoked"


class BrokerAllowlist(BaseModel):
    """Explicit outbound permissions for tier BROKERED / TOOLKIT."""

    model_config = ConfigDict(extra="forbid")

    http_hosts: tuple[str, ...] = ()      # exact hostnames; no wildcards in v1
    query_tables: tuple[str, ...] = ()    # fully-qualified table names
    notifications: tuple[str, ...] = ()   # channel identifiers
    toolkits: tuple[str, ...] = ()        # registered parrot toolkit names


class CapabilityManifest(BaseModel):
    """What a snippet declares it needs.

    The security contract, and the unit `check_snippet_conformance.py` (M15)
    checks the source against. `timeout_ms`/`max_memory_mb` bounds mirror the
    OQ-6 pool sizing defaults documented in spec §7.
    """

    model_config = ConfigDict(extra="forbid")

    tier: CapabilityTier
    auth_claims: tuple[str, ...] = ()     # AuthContext.claims keys projected in (OQ-5)
    stdlib_modules: tuple[str, ...] = ()  # subset of a fixed curated allowlist
    allowlist: BrokerAllowlist = Field(default_factory=BrokerAllowlist)
    timeout_ms: int = Field(default=5_000, ge=1, le=30_000)
    max_memory_mb: int = Field(default=128, ge=16, le=2_048)


class SnippetBundle(BaseModel):
    """One snippet from either source: manifest + Python half + optional TS half."""

    model_config = ConfigDict(extra="forbid")

    source: SnippetSource
    status: SnippetStatus = SnippetStatus.PUBLISHED
    version: int = 1                # DB snippets increment; git is always 1
    approved_by: str | None = None  # tenant admin id (DB) or commit sha (git)
    approved_at: datetime | None = None
    handler_ref: str = Field(
        ...,
        # Same pattern as FormEventBinding.handler_ref — verified:
        # core/events.py:69
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    event: FormEventName
    tenant: str | None = None  # None = global, matching registry semantics
    manifest: CapabilityManifest
    python_source: str
    python_sha256: str
    client_source: str | None = None  # compiled JS for the Web Worker
    client_sha256: str | None = None


class SandboxContext(BaseModel):
    """Serialisable projection of ``FormEventContext`` that crosses the boundary.

    Deliberately NOT ``FormEventContext``: ``auth_context`` on that model is
    a live object typed ``Any`` (core/events.py:128) and must never be
    handed to a worker. This model has no ``token``/``headers`` field by
    construction (OQ-5) — there is no field to accidentally populate.
    """

    model_config = ConfigDict(extra="forbid")

    event: FormEventName
    form_id: str
    tenant: str | None
    claims: Mapping[str, Any]  # only manifest-declared auth_claims
    payload: Mapping[str, Any] | None = None
    schema_dump: Mapping[str, Any] | None = None
    user_message: str | None = None
    extra: Mapping[str, Any] = Field(default_factory=dict)


class AbortSignal(BaseModel):
    """Serialisable form of ``FormEventAbort`` — verified: core/events.py:201."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    user_message: str
    status_code: int = 403


class SandboxOutcome(BaseModel):
    """What a worker returns. Exactly one of ``resolution``/``abort`` is set."""

    model_config = ConfigDict(extra="forbid")

    resolution: EventResolution | None = None
    abort: AbortSignal | None = None
    duration_ms: float
    broker_calls: int = 0


class SnippetIntegrityError(Exception):
    """Raised when a snippet's source hash does not match its manifest."""


class SnippetTierUnavailableError(Exception):
    """Raised when a bundle declares tier 3/4 but gVisor is unavailable (OQ-4)."""


class CapabilityDenied(Exception):
    """Raised by the host broker when a request is outside the manifest allowlist."""


class SnippetNotApprovedError(Exception):
    """Raised when execution is attempted against a DRAFT or REVOKED bundle."""
```
**Why this shape**: one file, flat, no sub-imports beyond `core/events.py` —
matching the existing `core/events.py` "one module owns the whole public
surface" convention so `from parrot_formdesigner.core.snippets import X`
never needs a deeper path. `SandboxOutcome`'s "exactly one of
resolution/abort" invariant is documented, not enforced by a validator here
— TASK-3172 (M12, Tier Router) is the place that consumes and checks it, so
adding a `model_validator` here would duplicate logic across the boundary
for no benefit; leave it as a documented contract for now (note this
decision in the Completion Note if a reviewer disagrees).

### `packages/parrot-formdesigner/tests/unit/test_snippets_models.py` (CREATE)
```python
"""Unit tests for core/snippets.py models — FEAT-459 / TASK-3161."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.snippets import (
    BrokerAllowlist,
    CapabilityManifest,
    CapabilityTier,
    SandboxContext,
    SnippetBundle,
    SnippetSource,
    SnippetStatus,
)


def test_manifest_rejects_unknown_tier() -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest(tier="omniscient")  # type: ignore[arg-type]


def test_manifest_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest(tier=CapabilityTier.PURE, extra_field="nope")  # type: ignore[call-arg]


def test_manifest_defaults() -> None:
    m = CapabilityManifest(tier=CapabilityTier.PURE)
    assert m.timeout_ms == 5_000
    assert m.max_memory_mb == 128
    assert m.allowlist == BrokerAllowlist()


@pytest.mark.parametrize("timeout_ms", [0, 30_001])
def test_manifest_timeout_bounds(timeout_ms: int) -> None:
    # FILL IN: pytest.raises(ValidationError) — bounded by Field(ge=1, le=30_000)
    pass


def test_bundle_handler_ref_pattern() -> None:
    manifest = CapabilityManifest(tier=CapabilityTier.PURE)
    with pytest.raises(ValidationError):
        SnippetBundle(
            source=SnippetSource.GIT,
            handler_ref="no_dot_here",
            event="onBeforeSubmit",
            manifest=manifest,
            python_source="def run(): ...",
            python_sha256="a" * 64,
        )


def test_bundle_defaults_to_published_status() -> None:
    # FILL IN: construct a valid SnippetBundle with source=GIT, assert
    #   status == SnippetStatus.PUBLISHED and version == 1 by default
    pass


def test_sandbox_context_has_no_token_or_headers_field() -> None:
    """Structural OQ-5 enforcement: the fields must not exist on the model."""
    field_names = set(SandboxContext.model_fields)
    assert "token" not in field_names
    assert "headers" not in field_names


def test_sandbox_context_forbids_extra_fields() -> None:
    # FILL IN: SandboxContext(**valid_kwargs, token="leaked") raises ValidationError
    #   because `token` is not a declared field and extra="forbid"
    pass
```
**Why**: the pattern-rejection and structural-absence tests are written in
full because they are the security-critical assertions (handler_ref
namespacing, OQ-5's "no token field exists"); the remaining stubs are
bounded by their docstrings and the model definitions above.

### FILL IN checklist
- [ ] `test_manifest_timeout_bounds` — parametrized boundary test body
- [ ] `test_bundle_defaults_to_published_status` — construct + assert defaults
- [ ] `test_sandbox_context_forbids_extra_fields` — assert `ValidationError` on an injected `token` kwarg

---

## Acceptance Criteria

- [ ] `CapabilityManifest(tier=CapabilityTier.PURE)` constructs with documented defaults (`timeout_ms=5000`, `max_memory_mb=128`)
- [ ] Every model in `core/snippets.py` rejects unknown fields (`extra="forbid"`)
- [ ] `SnippetBundle.handler_ref` rejects a value with no dot, matching `FormEventBinding.handler_ref`'s pattern
- [ ] `SandboxContext` has no `token` or `headers` field in `model_fields` (OQ-5 structural check)
- [ ] All four typed exceptions (`SnippetIntegrityError`, `SnippetTierUnavailableError`, `CapabilityDenied`, `SnippetNotApprovedError`) are importable from `parrot_formdesigner.core.snippets`
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_snippets_models.py -v`
- [ ] `ruff check` and `mypy` clean on `core/snippets.py`

---

## Test Specification

See the blueprint's test file above — 8 test functions, 3 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Data Models, §3 Module 1, §6 Codebase Contract)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `core/events.py` still exports `FormEventName` (line 32) and `EventResolution` (line 170) unchanged
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3161-snippet-manifest-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrated via parrot-sdd-coder)
**Date**: 2026-09-11
**Notes**: Created `core/snippets.py` with `CapabilityTier`, `SnippetSource`,
`SnippetStatus`, `BrokerAllowlist`, `CapabilityManifest`, `SnippetBundle`,
`SandboxContext`, `AbortSignal`, `SandboxOutcome`, and the four typed
exceptions (`SnippetIntegrityError`, `SnippetTierUnavailableError`,
`CapabilityDenied`, `SnippetNotApprovedError`). All models use
`ConfigDict(extra="forbid")`. `SandboxContext` structurally has no
`token`/`headers` field (OQ-5). 9/9 tests pass
(`test_snippets_models.py`), `ruff check` and `mypy` clean.

**Deviations from spec**: none

**Seat: minimax (attempt 2, after qwen attempt-1 timeout) · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 2 · Duration: 782.7s (553.7s timeout + 229.0s success) · Tokens: 1,150,288 in / 10,139 out**
