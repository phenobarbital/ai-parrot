# TASK-3176: LLM authoring surface — `tools/snippet_authoring.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161, TASK-3175
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 16 — the last module, and the one that makes the whole
feature usable by a non-engineer end user. Given a natural-language rule
("if total > 5000, require approver_email"), this toolkit generates a
conformant bundle: the Python half, the TS half, the manifest, **and the
equivalence fixtures OQ-8 requires** — then runs TASK-3175's gate locally
before ever proposing the bundle, and surfaces a plain-language capability
summary for whoever approves it (a PR reviewer for git, a tenant admin for
DB). This is the "Author describes a rule in natural language" flow from
spec §2's Overview.

This module targets **both sources**: a PR for platform snippets, a draft
row for tenant snippets (via TASK-3166's `draft()`).

---

## Scope

- Implement an `AbstractToolkit` (per `.agent/CONTEXT.md`'s Tool-Centric
  Architecture convention — `parrot.tools.AbstractToolkit`) named
  `SnippetAuthoringToolkit` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/tools/snippet_authoring.py`,
  exposing tools to: draft a bundle from a natural-language rule
  description, run the local conformance gate against a draft, and
  produce the plain-language capability summary an approver reads.
- The actual LLM generation call is injected (a `Callable`/client
  parameter — this toolkit's job is orchestration and safety-gating, not
  prompt engineering; the exact prompt template is a `# FILL IN` since it
  is genuinely a large, iterative design surface outside a task blueprint's
  scope, per the skill's own instruction that judgment calls stay stubs).
- Every generated bundle MUST be run through TASK-3175's `run_gate()`
  BEFORE being proposed (returned to the caller) — a bundle failing the
  gate is never returned as a finished proposal; it is returned with the
  gate's `errors` so the toolkit's caller (an agent loop) can retry
  generation.
- Write `packages/parrot-formdesigner/tests/unit/test_snippet_authoring.py`.

**NOT in scope**: actually calling an LLM (injected, not implemented
here); the git PR creation workflow itself (out of this task — the
toolkit produces bundle files ready to commit, not a `gh pr create` call,
unless another task in the repo already owns that generic capability,
which this task does not assume); the DB draft insertion mechanics
themselves (delegates to TASK-3166's `draft()`, already implemented
there).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/snippet_authoring.py` | CREATE | `SnippetAuthoringToolkit` |
| `packages/parrot-formdesigner/tests/unit/test_snippet_authoring.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools import AbstractToolkit, tool  # verified: .agent/CONTEXT.md Tool-Centric Architecture section
from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource
from scripts.check_snippet_conformance import ConformanceResult, EquivalenceFixture, run_gate  # TASK-3175
from parrot_formdesigner.services.snippets.approval import SnippetApprovalService  # TASK-3166, for the DB-source path
```

### Existing Signatures to Use
```python
# From .agent/CONTEXT.md — Tool-Centric Architecture (verified against
# project instructions, not directly re-read from parrot/tools/ source in
# this task since that package is core/ai-parrot, outside this task's
# packages/parrot-formdesigner scope; if a signature mismatch is found at
# implementation time, trust the actual parrot.tools source over this note):
#   from parrot.tools import tool
#   @tool
#   def get_weather(location: str) -> str:
#       """Get the current weather for a location."""
#       ...
#   Toolkit Pattern: use AbstractToolkit for complex tool collections.
#   Every tool MUST have a clear docstring (becomes the LLM's tool description).

# TASK-3175 — packages/parrot-formdesigner/scripts/check_snippet_conformance.py
async def run_gate(
    bundle: SnippetBundle, fixtures: list[EquivalenceFixture], *, run_js: JsRunnerFn | None = None,
) -> ConformanceResult: ...

# TASK-3166 — packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/approval.py
class SnippetApprovalService:
    async def draft(self, bundle: SnippetBundle, *, tenant: str) -> SnippetBundle: ...
```

### Does NOT Exist
- ~~`tools/snippet_authoring.py`~~ — created by this task.
- ~~A concrete LLM-generation call already wired anywhere in
  `parrot-formdesigner`~~ — this package's `tools/` directory holds
  form-domain toolkits (`create_form.py`, `edit_toolkit.py`,
  `field_helpers.py`, `request_form.py`, `database_form.py`), none of
  which generate arbitrary executable code; do not assume a reusable
  "generate code from NL" helper exists there — read one of those files
  ONLY for the `AbstractToolkit` subclassing style, not for a code-gen
  pattern to copy.
- ~~Automatic approval or execution of a freshly generated bundle~~ —
  explicitly excluded by C4 (Non-Goal: "Autonomous execution of freshly
  generated code"). This toolkit's tools must never call
  `SnippetApprovalService.publish()` or otherwise cause a bundle to
  become executable — only `draft()` (DB) or "write files to be PR'd"
  (git) are in scope, both requiring a SEPARATE human action to approve.

### Verified Environment Facts (spec §6, applies to any test of this task)
- `runsc` is not installed on the reference dev machine — irrelevant to
  this task directly, but any fixture bundle this toolkit generates that
  happens to declare tier BROKERED/TOOLKIT would still be subject to
  OQ-4's hard prerequisite elsewhere in the pipeline; this toolkit itself
  performs no gVisor check (that is TASK-3164/3170's job).

---

## Implementation Notes

### Key Constraints
- **Never a bypass of C4.** No tool in this toolkit may cause code to
  execute or become approved. The strongest test in this task's suite
  should assert exactly that: no tool method calls `publish()`, `exec()`,
  or anything that runs the generated Python.
- **The gate runs before the bundle is ever returned as "ready".** A
  toolkit method returning a bundle without having run `run_gate()`
  against it first is a bug this task must not ship.
- **Capability summary must be plain language**, not a dump of the
  manifest JSON — an approver (possibly non-technical, e.g. a tenant
  admin) reads this to decide whether to approve; translate
  `CapabilityManifest` fields into sentences (e.g. "This code tier is
  'helpers' — it can read basic account info like your email, but cannot
  make network calls or access other systems.").
- Fixture generation (the OQ-8 equivalence fixtures) is itself an
  LLM-generation concern (the injected generator should be asked to
  produce fixtures alongside code) — this toolkit's job is to REQUIRE at
  least one fixture be present before calling `run_gate()`, not to
  invent fixtures itself when the generator fails to produce any.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`
  or `edit_toolkit.py` — read one for this package's `AbstractToolkit`
  subclassing conventions (constructor shape, `self.logger` usage,
  `@tool`-decorated method style) before writing this file.

---

## Implementation Blueprint

### Steps (in order)
1. Define the injected `BundleGeneratorFn` type (the LLM call site).
2. Implement `SnippetAuthoringToolkit.__init__`.
3. Implement `draft_from_description()` — generate, gate, return
   (never auto-approve).
4. Implement `summarize_capabilities()` — plain-language manifest translation.
5. Implement `propose_for_tenant()` — wraps `draft_from_description()` +
   `SnippetApprovalService.draft()` for the DB path.
6. Write and run tests, prioritizing the "never bypasses C4" test.

### `packages/parrot-formdesigner/src/parrot_formdesigner/tools/snippet_authoring.py` (CREATE)
```python
"""LLM authoring surface for snippet bundles (FEAT-459 / M16).

Generates conformant bundles (Python + TS + manifest + OQ-8 equivalence
fixtures) from a natural-language rule description, gates every draft
through TASK-3175's run_gate() BEFORE returning it, and produces a
plain-language capability summary for whoever approves it (PR reviewer
for git snippets, tenant admin for DB snippets via TASK-3166).

C4 (human approval, always) is enforced structurally here: no method in
this toolkit ever calls SnippetApprovalService.publish() or otherwise
causes generated code to become executable. Only draft()-ing (DB) or
returning files ready to be PR'd (git) are in scope.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from parrot.tools import AbstractToolkit, tool
from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle
from parrot_formdesigner.services.snippets.approval import SnippetApprovalService
from scripts.check_snippet_conformance import ConformanceResult, EquivalenceFixture, run_gate

logger = logging.getLogger(__name__)


@dataclass
class GeneratedBundle:
    """One LLM-generation attempt: a candidate bundle plus its fixtures."""

    bundle: SnippetBundle
    fixtures: list[EquivalenceFixture]


# Injected — the actual LLM call. Kept as a Callable so this toolkit has
# no hard dependency on a specific AbstractClient/model choice; the
# caller (an Agent using this toolkit) wires a real generator.
BundleGeneratorFn = Callable[[str], Awaitable[GeneratedBundle]]

_TIER_PLAIN_LANGUAGE: dict[CapabilityTier, str] = {
    CapabilityTier.PURE: "cannot read any account information and cannot access the network",
    CapabilityTier.HELPERS: "can read basic account info (like your email or role) but cannot make network calls or access other systems",
    CapabilityTier.BROKERED: "can make a small number of pre-approved network calls or database lookups, but only to hosts/tables explicitly listed below",
    CapabilityTier.TOOLKIT: "can use pre-approved automated tools/agents in addition to everything the tier above allows",
}


class SnippetAuthoringToolkit(AbstractToolkit):
    """Generates, gates, and summarizes snippet bundles. NEVER approves or executes one."""

    def __init__(self, generate_bundle: BundleGeneratorFn) -> None:
        """
        Args:
            generate_bundle: Calls an LLM to produce a GeneratedBundle
                from a natural-language rule description. Injected —
                see module docstring.
        """
        super().__init__()
        self._generate_bundle = generate_bundle
        self.logger = logger

    @tool
    async def draft_from_description(self, rule_description: str) -> dict:
        """Generate a conformant snippet bundle from a natural-language rule.

        Runs the bundle through the tier-conformance and equivalence gate
        BEFORE returning it. Never approves or publishes the result —
        approval is always a separate human action (C4).

        Args:
            rule_description: Plain-language description of the desired
                behavior, e.g. "if total > 5000, require approver_email".

        Returns:
            A dict with keys: `ready` (bool — True only if the gate
            passed), `bundle` (the generated SnippetBundle, always
            returned even on failure so a caller can retry generation
            with the error context), `gate_errors` (list[str], empty if
            `ready`), `capability_summary` (str, plain language).
        """
        generated = await self._generate_bundle(rule_description)
        gate_result = await run_gate(generated.bundle, generated.fixtures)
        summary = self.summarize_capabilities(generated.bundle.manifest)
        return {
            "ready": gate_result.passed,
            "bundle": generated.bundle,
            "gate_errors": gate_result.errors,
            "capability_summary": summary,
        }

    @tool
    def summarize_capabilities(self, manifest: CapabilityManifest) -> str:
        """Translate a CapabilityManifest into a plain-language summary for an approver.

        Args:
            manifest: The manifest to summarize.

        Returns:
            A short paragraph, never a JSON/field dump.
        """
        base = _TIER_PLAIN_LANGUAGE[manifest.tier]
        lines = [f"This code's declared tier is '{manifest.tier.value}' — it {base}."]
        if manifest.allowlist.http_hosts:
            lines.append(f"It may contact these external services: {', '.join(manifest.allowlist.http_hosts)}.")
        if manifest.allowlist.query_tables:
            lines.append(f"It may read from these data tables: {', '.join(manifest.allowlist.query_tables)}.")
        if manifest.auth_claims:
            lines.append(f"It may see these account details: {', '.join(manifest.auth_claims)}.")
        lines.append(f"It must finish within {manifest.timeout_ms} ms and use at most {manifest.max_memory_mb} MB of memory.")
        return " ".join(lines)

    @tool
    async def propose_for_tenant(
        self, rule_description: str, *, tenant: str, approval_service: SnippetApprovalService,
    ) -> dict:
        """Generate a bundle and insert it as a DB draft (NOT published — C4).

        Args:
            rule_description: See draft_from_description.
            tenant: The tenant this draft belongs to.
            approval_service: TASK-3166's service — draft() only, never publish().

        Returns:
            Same shape as draft_from_description()'s return, plus a
            `draft_version` key when `ready` is True (the version number
            SnippetApprovalService.draft() assigned).
        """
        result = await self.draft_from_description(rule_description)
        if not result["ready"]:
            return result
        # FILL IN: bundle.source must be SnippetSource.DB before calling
        #   approval_service.draft() — the generator (injected) may
        #   produce a bundle with source=GIT by default; this method's
        #   job is a DB-targeted draft, so either the generator must be
        #   told the target source, or this method must clone/re-tag the
        #   bundle's `source` field before drafting. Bounded by
        #   SnippetApprovalService.draft()'s own ValueError guard
        #   ("only DB-sourced bundles can be drafted").
        drafted = await approval_service.draft(result["bundle"], tenant=tenant)
        result["draft_version"] = drafted.version
        return result
```
**Why this shape**: `draft_from_description()` ALWAYS returns the bundle
(even a gate-failing one) rather than raising on failure — an
agent-driven authoring loop needs the `gate_errors` to retry generation
with feedback, and raising would force awkward exception-based retry
logic in every caller. `summarize_capabilities()` is a separate `@tool`
(not folded into `draft_from_description`'s return construction only) so
an approver-facing UI can re-request the summary for an EXISTING bundle
(e.g. one pulled from `list_versions()`) without regenerating it.

### `packages/parrot-formdesigner/tests/unit/test_snippet_authoring.py` (CREATE)
```python
"""Unit tests for SnippetAuthoringToolkit — FEAT-459 / TASK-3176."""

from __future__ import annotations

import inspect

import pytest

from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource
from parrot_formdesigner.tools.snippet_authoring import GeneratedBundle, SnippetAuthoringToolkit
from scripts.check_snippet_conformance import EquivalenceFixture


def _pure_bundle(handler_ref: str = "f.onBeforeSubmit") -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT, handler_ref=handler_ref, event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=CapabilityTier.PURE), python_source="def run(ctx): return {}",
        python_sha256="a" * 64,
    )


async def test_draft_from_description_runs_gate_before_returning() -> None:
    async def _generate(description: str) -> GeneratedBundle:
        return GeneratedBundle(
            bundle=_pure_bundle(),
            fixtures=[EquivalenceFixture(name="basic", input_payload={}, expected_output={})],
        )

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    result = await toolkit.draft_from_description("if total > 5000, require approver_email")
    assert result["ready"] is True
    assert result["gate_errors"] == []


async def test_draft_from_description_surfaces_gate_failures_without_raising() -> None:
    async def _generate(description: str) -> GeneratedBundle:
        bad_bundle = SnippetBundle(
            source=SnippetSource.GIT, handler_ref="f.onBeforeSubmit", event="onBeforeSubmit",
            manifest=CapabilityManifest(tier=CapabilityTier.PURE),
            python_source="import socket\ndef run(ctx): return {}", python_sha256="a" * 64,
        )
        return GeneratedBundle(bundle=bad_bundle, fixtures=[])

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    result = await toolkit.draft_from_description("some rule")
    assert result["ready"] is False
    assert len(result["gate_errors"]) > 0
    assert result["bundle"] is not None  # still returned for retry context


def test_summarize_capabilities_is_plain_language_not_json() -> None:
    toolkit = SnippetAuthoringToolkit(generate_bundle=None)  # type: ignore[arg-type]
    summary = toolkit.summarize_capabilities(CapabilityManifest(tier=CapabilityTier.HELPERS))
    assert "{" not in summary
    assert "helpers" in summary.lower()


def test_toolkit_never_calls_publish_or_exec() -> None:
    """Structural C4 enforcement: no method in this toolkit's source calls
    SnippetApprovalService.publish() or exec()."""
    source = inspect.getsource(SnippetAuthoringToolkit)
    assert ".publish(" not in source
    assert "exec(" not in source  # only run_gate()'s OWN module (TASK-3175) may exec, not this toolkit


async def test_propose_for_tenant_calls_draft_never_publish() -> None:
    # FILL IN: construct a fake SnippetApprovalService (spy object
    #   recording calls to .draft()), call propose_for_tenant(), assert
    #   .draft() was called exactly once and no .publish attribute was
    #   ever accessed — bounded by the FILL IN in propose_for_tenant
    #   itself (source re-tagging) being resolved first.
    pass
```
**Why**: `test_toolkit_never_calls_publish_or_exec` is the single most
important test in this task — a structural, source-inspection assertion
of the C4 non-negotiable, complete and not dependent on any FILL IN. The
two `draft_from_description` tests and the plain-language test are also
complete; `propose_for_tenant`'s test is stubbed because it depends on
resolving the bundle-source re-tagging FILL IN in the blueprint above.

### FILL IN checklist
- [ ] `snippet_authoring.py::propose_for_tenant` — resolve bundle `source` re-tagging before calling `approval_service.draft()`
- [ ] `test_propose_for_tenant_calls_draft_never_publish` — full test body once the above is resolved
- [ ] The actual LLM prompt template for `BundleGeneratorFn` — explicitly out of blueprint scope (a large, iterative design surface); implement a minimal working generator against any available `AbstractClient` and iterate, do not block this task's core toolkit logic on prompt perfection

---

## Acceptance Criteria

- [ ] `draft_from_description()` always runs `run_gate()` before returning, never returns a bundle claiming `ready=True` that the gate rejected
- [ ] A gate failure is returned as data (`ready=False`, populated `gate_errors`), never raised as an exception
- [ ] `summarize_capabilities()` output contains no `{`/`}` JSON-dump characters and mentions the tier name in plain language
- [ ] No method in `SnippetAuthoringToolkit`'s source calls `.publish(` or `exec(` (structural C4 check, `test_toolkit_never_calls_publish_or_exec`)
- [ ] `propose_for_tenant()` calls `SnippetApprovalService.draft()`, never `.publish()`
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_snippet_authoring.py -v`
- [ ] `ruff check` and `mypy` clean on `tools/snippet_authoring.py`

---

## Test Specification

See the blueprint's test file above — 5 test functions, 1 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview "User-facing flow", §3 Module 16, Non-Goals "Autonomous execution of freshly generated code")
2. **Check dependencies** — TASK-3161 and TASK-3175 must be `done`; TASK-3166 should be `done` too for `propose_for_tenant()`, though the method can be stubbed against TASK-3166's Protocol shape if not
3. **Verify the Codebase Contract** — read `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` (or `edit_toolkit.py`) for this package's actual `AbstractToolkit` subclassing conventions, since this task's contract note about `parrot.tools.AbstractToolkit`'s exact constructor signature was not independently re-verified against source
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3176-llm-authoring-surface.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (direct implementation — parrot-sdd-coder's
gemini attempt produced a `fidelity_violation`: it touched
`core/__init__.py`, which is not in this task's file list, so it was
discarded rather than merged)
**Date**: 2026-09-11
**Notes**: Implemented `SnippetAuthoringToolkit(AbstractToolkit)` with
`draft_from_description()`, `summarize_capabilities()`, and
`propose_for_tenant()`. `draft_from_description()` always runs
`run_gate()` before returning and never raises on a gate failure
(returned as `ready=False` + `gate_errors`). `summarize_capabilities()`
translates `CapabilityManifest` into a plain-language paragraph (verified
no `{`/`}` characters). `propose_for_tenant()` resolves the blueprint's
FILL IN by re-tagging the generated bundle to `source=SnippetSource.DB`
+ the target `tenant` via `model_copy(update=...)` (`SnippetBundle` is
not frozen) before calling `SnippetApprovalService.draft()` — verified
`draft()` raises `ValueError` on a non-DB source, confirming the re-tag
is required. Structural C4 test (`test_toolkit_never_calls_publish_or_exec`)
passes: no `.publish(`/`exec(` anywhere in the class source.

**Codebase-contract correction (documented per Cardinal Rule 4 — the
task's own contract flagged this as unverified)**: the blueprint's
`from parrot.tools import AbstractToolkit, tool` + `@tool`-decorated
methods does not match this framework's actual mechanism. Verified
against `parrot/tools/toolkit.py` (`AbstractToolkit` auto-converts every
**public async method** into a tool) and `tools/edit_toolkit.py` (the
real convention in this package: no per-method decorator, plain
`async def`). Dropped the `tool` import and all `@tool` decorators
accordingly; made `summarize_capabilities()` async (was sync in the
blueprint) so it is auto-exposed as a tool too, consistent with this
task's own Scope ("exposing tools to: ... produce the plain-language
capability summary"). Added 2 tests beyond the blueprint's 5 (both
`propose_for_tenant` paths — success re-tagging + gate-failure skip),
resolving the blueprint's stubbed `test_propose_for_tenant_calls_draft_never_publish`.
6/6 tests pass, `ruff check`/`mypy` clean.

**Deviations from spec**: the `@tool`-decorator → auto-async-method
correction above is a deliberate, documented fix of an unverified
blueprint pattern, not a deviation from any acceptance criterion —
all acceptance criteria are met as specified.

**Seat: sonnet (orchestrator, direct attempt 2 after gemini's fidelity violation) · Backend: n/a · Model: claude-sonnet-5 · Attempts: 1 · Duration: n/a (interactive) · Tokens: n/a**

**Prior failed dispatch attempt** (for the record): `gemini`
(google-compat backend, `gemini-3.5-flash`) ran for 119s, produced
`tools/snippet_authoring.py`/`tests/unit/test_snippet_authoring.py`
plus an out-of-scope edit to `core/__init__.py` — surfaced as
`fidelity_violation` and never merged.
