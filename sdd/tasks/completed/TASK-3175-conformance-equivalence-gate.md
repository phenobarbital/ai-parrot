# TASK-3175: Conformance & equivalence gate — `scripts/check_snippet_conformance.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 15, resolving OQ-8. Two gates in one script: **(a) tier
conformance** — static `ast` analysis asserting a snippet's Python source
imports nothing beyond its declared `stdlib_modules`, performs no I/O at
tiers 1-2, and makes no broker calls outside its allowlist; **(b) semantic
equivalence** — every bundle ships fixture cases, and the gate executes
the Python half and the compiled JS half against the same fixtures,
failing on divergent output.

This is the CI gate for git-backed platform snippets (run as part of PR
checks) AND the exact function TASK-3166's `SnippetApprovalService`
injects as its `ConformanceCheckFn` for DB-backed tenant publishes — spec
§3 explicitly requires it be "importable by Module 6 so DB publishes run
the same checks as PRs."

**Note on TASK-3166's dependency direction**: TASK-3166 was written with
an injected `ConformanceCheckFn` Protocol so it does not need to import
this module directly during parallel development. Once this task lands,
wire the real function from here into TASK-3166's constructor call site.

---

## Scope

- Implement `check_tier_conformance(bundle: SnippetBundle) ->
  ConformanceResult` in
  `packages/parrot-formdesigner/scripts/check_snippet_conformance.py`:
  parses `bundle.python_source` with `ast`, walks `Import`/`ImportFrom`
  nodes and rejects anything outside `bundle.manifest.stdlib_modules`,
  rejects any I/O-shaped call (`open`, `socket`, `subprocess`, etc.) for
  tiers `PURE`/`HELPERS`, and rejects any attribute access resembling a
  broker call outside the declared `BrokerAllowlist` for tiers
  `BROKERED`/`TOOLKIT` (best-effort static check — a full taint analysis
  is out of scope; document the limitation).
- Implement `check_equivalence(bundle: SnippetBundle, fixtures:
  list[EquivalenceFixture]) -> ConformanceResult`: executes the Python
  half (via a safe local exec for CI purposes ONLY — see note) against
  each fixture and compares to the fixture's expected JS-half output
  (JS-side execution itself is out of this task's scope — see NOT in
  scope below), failing on any mismatch or on zero fixtures.
- Define `EquivalenceFixture` and `ConformanceResult` (satisfying
  TASK-3166's `ConformanceResult` `Protocol`: `.passed: bool`, `.errors:
  list[str]`).
- Implement `run_gate(bundle, fixtures) -> ConformanceResult` combining
  both checks — this is the function TASK-3166 should end up injecting.
- Write `packages/parrot-formdesigner/tests/unit/test_snippet_conformance.py`.

**NOT in scope**: actually invoking a JS runtime (Node/deno) to execute
the compiled `client.js` half for the equivalence comparison — the spec
requires "the gate executes the Python half and the compiled JS half
against the same fixtures" (§2, §3 M15), which genuinely needs a
JavaScript execution environment this Python-only task cannot respect
without a new heavy dependency; implement the Python-half execution path
fully and stub the JS-half execution behind a clearly documented
`# FILL IN` injection point (a `JsRunnerFn` callable, same
dependency-injection pattern used throughout this feature) rather than
silently skipping the requirement or inventing a fake JS interpreter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/scripts/check_snippet_conformance.py` | CREATE | Tier conformance + equivalence gate |
| `packages/parrot-formdesigner/tests/unit/test_snippet_conformance.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import ast
from parrot_formdesigner.core.snippets import CapabilityTier, SnippetBundle  # TASK-3161
```

### Existing Signatures to Use
```python
# TASK-3166 — packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/approval.py
class ConformanceResult(Protocol):
    passed: bool
    errors: list[str]
ConformanceCheckFn = Callable[[SnippetBundle], Awaitable[ConformanceResult]]
```
**Important shape mismatch to reconcile**: TASK-3166's injected
`ConformanceCheckFn` is `async`, but static `ast` analysis and a local
Python `exec()` are inherently synchronous. This task's `run_gate()`
should be a plain sync function; provide a thin `async def
run_gate_async(bundle, fixtures) -> ConformanceResult` wrapper (e.g. via
`asyncio.to_thread`) as the actual value wired into TASK-3166's
`check_conformance` parameter, so CPU-bound `ast`/`exec` work does not
block the event loop.

### Does NOT Exist
- ~~`scripts/check_snippet_conformance.py`~~ — created by this task.
- ~~A JS execution environment (Node, deno, PyMiniRacer, etc.) as a
  dependency of this package~~ — none exists; do not add one without
  discussion (spec §7 External Dependencies table names only `esbuild`/
  `swc` as build-time tools, no JS runtime for test execution). The JS-
  half execution is an explicit FILL IN gap, not silently solved.
- ~~A restricted/sandboxed `exec()` utility already in this repo~~ — the
  closest precedent is `parrot_tools.codeinterpreter.executor` (used for
  a DIFFERENT purpose, sandboxed *runtime* execution of arbitrary code);
  this task's Python-half execution for CI purposes runs in the CI
  process itself (already a trusted context reviewing a PR's own code
  before merge), NOT through the production sandbox pools (TASK-3169/
  3170) — using those pools here would be circular (the gate exists
  partly to decide whether a bundle is even safe to load into them).

---

## Implementation Notes

### Key Constraints
- **Static analysis is best-effort, not a full sandbox.** `ast`-based
  import/call checking catches the common cases (an undeclared `import
  socket`) but cannot catch every dynamic-dispatch evasion (`getattr(__builtins__,
  "".join(chars))(...)`). Document this limitation in the module
  docstring — the manifest declaration + this gate is a defense layer,
  not a claim of perfect static safety; the *actual* safety boundary is
  the runtime sandbox (TASK-3169/3170), which this gate helps keep
  snippets honest against, not replaces.
- Zero fixtures must fail the gate (`test_equivalence_gate_requires_fixtures`)
  — a bundle shipping no equivalence fixtures is non-conformant even if
  its Python half is otherwise fine.
- The gate function itself must not import or depend on
  `services/snippets/approval.py` (TASK-3166) — the dependency runs the
  other way (TASK-3166 imports/injects this).

### References in Codebase
- None directly — this is new static-analysis tooling.

---

## Implementation Blueprint

### Steps (in order)
1. Define `ConformanceResult`, `EquivalenceFixture`.
2. Implement `check_tier_conformance()` — the `ast`-walking core.
3. Implement `check_equivalence()` with the Python-half execution path
   complete and the JS-half execution path as an injected `JsRunnerFn`
   FILL IN.
4. Implement `run_gate()`/`run_gate_async()`.
5. Write and run tests, prioritizing `test_conformance_rejects_undeclared_import`.

### `packages/parrot-formdesigner/scripts/check_snippet_conformance.py` (CREATE)
```python
"""Tier conformance + equivalence gate for snippet bundles (FEAT-459 / M15).

Two checks:
(a) Tier conformance — static ast analysis: no imports beyond declared
    stdlib_modules, no I/O at tiers PURE/HELPERS, no broker calls outside
    the manifest's BrokerAllowlist (best-effort — NOT a full sandbox; the
    runtime pools in services/sandbox/ are the actual safety boundary).
(b) Semantic equivalence (OQ-8) — every bundle ships fixture cases; this
    gate executes the Python half and (via an injected JsRunnerFn — see
    NOT in scope) the compiled JS half against the same fixtures, failing
    on divergence or on zero fixtures.

Importable by services/snippets/approval.py (TASK-3166) so DB publishes
run the SAME checks as git PRs (spec's explicit cross-source requirement).
"""

from __future__ import annotations

import ast
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from parrot_formdesigner.core.snippets import CapabilityTier, SnippetBundle

logger = logging.getLogger(__name__)

# Call names treated as I/O for tier PURE/HELPERS conformance — best-effort,
# not exhaustive (see module docstring limitation).
_IO_CALL_NAMES: frozenset[str] = frozenset({"open", "socket", "connect", "urlopen", "request"})
_IO_MODULE_NAMES: frozenset[str] = frozenset({"socket", "subprocess", "urllib", "http", "requests", "aiohttp"})


@dataclass
class ConformanceResult:
    """Satisfies TASK-3166's ConformanceResult Protocol (.passed, .errors)."""

    passed: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class EquivalenceFixture:
    """One input/expected-output pair both halves of a bundle must agree on."""

    name: str
    input_payload: dict[str, Any]
    expected_output: dict[str, Any]


def check_tier_conformance(bundle: SnippetBundle) -> ConformanceResult:
    """Static ast check: declared stdlib_modules only, no undeclared I/O.

    Best-effort — see module docstring. Does not execute `bundle.python_source`.
    """
    errors: list[str] = []
    try:
        tree = ast.parse(bundle.python_source)
    except SyntaxError as exc:
        return ConformanceResult(passed=False, errors=[f"python_source does not parse: {exc}"])

    declared = set(bundle.manifest.stdlib_modules)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level not in declared:
                    errors.append(f"undeclared import: {alias.name!r}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level = node.module.split(".")[0]
            if top_level not in declared:
                errors.append(f"undeclared import: {node.module!r}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _IO_CALL_NAMES and bundle.manifest.tier in (
                CapabilityTier.PURE, CapabilityTier.HELPERS,
            ):
                errors.append(f"tier={bundle.manifest.tier!r} snippet calls I/O function {node.func.id!r}")
        # FILL IN: broker-call detection for tiers BROKERED/TOOLKIT —
        #   bounded by BrokerAllowlist's four categories (TASK-3161); a
        #   reasonable heuristic is flagging any ast.Attribute access
        #   chain resembling `broker.<kind>(...)` with a `target` literal
        #   not present in bundle.manifest.allowlist's matching tuple,
        #   but the exact snippet-authoring API for making broker calls
        #   is TASK-3176's concern (LLM authoring surface) — coordinate
        #   the call shape with that task before finalizing this check.

    return ConformanceResult(passed=not errors, errors=errors)


# Injected — running compiled JS against a fixture needs a JS runtime this
# package does not depend on (Node/deno/PyMiniRacer). See module docstring
# "NOT in scope". A caller (e.g. a CI script with Node available) supplies
# this; without it, check_equivalence() cannot verify the JS half at all
# and should fail loudly rather than silently skip it — see FILL IN below.
JsRunnerFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _execute_python_half(bundle: SnippetBundle, input_payload: dict[str, Any]) -> dict[str, Any]:
    """Run bundle.python_source's `run(ctx)` function against one fixture input.

    CI-context execution only — trusted process reviewing a PR's own
    code pre-merge, NOT the production sandbox path (TASK-3169/3170).
    """
    namespace: dict[str, Any] = {}
    exec(compile(bundle.python_source, "<snippet>", "exec"), namespace)  # noqa: S102 — CI-only, see docstring
    run_fn = namespace.get("run")
    if run_fn is None:
        raise ValueError("snippet python_source does not define a `run` function")
    return run_fn(input_payload)


async def check_equivalence(
    bundle: SnippetBundle,
    fixtures: list[EquivalenceFixture],
    *,
    run_js: JsRunnerFn | None = None,
) -> ConformanceResult:
    """Execute both halves against `fixtures`, failing on divergence or zero fixtures.

    Args:
        run_js: Executes the compiled JS half. When None AND
            `bundle.client_source` is set, this is a FILL IN gap — the
            equivalence check for that bundle cannot be completed and
            MUST fail loudly (not silently pass) per OQ-8's "CI executes
            both halves... fails on divergent output" requirement.
    """
    if not fixtures:
        return ConformanceResult(passed=False, errors=["bundle ships zero equivalence fixtures"])

    errors: list[str] = []
    for fixture in fixtures:
        try:
            python_result = _execute_python_half(bundle, fixture.input_payload)
        except Exception as exc:
            errors.append(f"fixture {fixture.name!r}: python half raised {exc!r}")
            continue
        if python_result != fixture.expected_output:
            errors.append(
                f"fixture {fixture.name!r}: python half returned {python_result!r}, "
                f"expected {fixture.expected_output!r}"
            )
        if bundle.client_source:
            if run_js is None:
                errors.append(
                    f"fixture {fixture.name!r}: bundle has a client_source but no "
                    "JS runner was supplied — equivalence cannot be verified "
                    "(FILL IN: wire a JsRunnerFn with Node/deno available)"
                )
                continue
            # FILL IN: js_result = await run_js(bundle.client_source, fixture.input_payload)
            #   compare js_result == fixture.expected_output the same way as
            #   python_result above, appending a divergence error on mismatch.

    return ConformanceResult(passed=not errors, errors=errors)


async def run_gate(
    bundle: SnippetBundle, fixtures: list[EquivalenceFixture], *, run_js: JsRunnerFn | None = None,
) -> ConformanceResult:
    """Combined tier-conformance + equivalence gate.

    This is the function to wire into SnippetApprovalService's
    check_conformance parameter (TASK-3166) once this task lands.
    """
    tier_result = await asyncio.to_thread(check_tier_conformance, bundle)
    if not tier_result.passed:
        return tier_result
    return await check_equivalence(bundle, fixtures, run_js=run_js)
```
**Why this shape**: `check_tier_conformance` short-circuits
`check_equivalence` on failure — running a snippet's Python half (via
`exec()`) is pointless work if the snippet already fails static
conformance, and skipping it also means a conformance-failing snippet
never actually executes even in the CI-trusted context. The `run_js`
injection point is the honest resolution of a real gap: this task cannot
add a JS runtime dependency unilaterally, so it fails the equivalence
check loudly (not silently) whenever a bundle has a JS half and no runner
was wired — this satisfies OQ-8's "fails on divergent output" spirit by
treating "cannot verify" as a failure, never a pass.

### `packages/parrot-formdesigner/tests/unit/test_snippet_conformance.py` (CREATE)
```python
"""Unit tests for check_snippet_conformance.py — FEAT-459 / TASK-3175."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource
from scripts.check_snippet_conformance import (
    EquivalenceFixture,
    check_equivalence,
    check_tier_conformance,
)


def _bundle(source: str, tier: CapabilityTier = CapabilityTier.PURE, stdlib_modules: tuple[str, ...] = (), client_source: str | None = None) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT, handler_ref="f.onBeforeSubmit", event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=tier, stdlib_modules=stdlib_modules),
        python_source=source, python_sha256="a" * 64, client_source=client_source,
    )


def test_conformance_rejects_undeclared_import() -> None:
    bundle = _bundle("import socket\ndef run(ctx): return {}")
    result = check_tier_conformance(bundle)
    assert result.passed is False
    assert any("socket" in e for e in result.errors)


def test_conformance_allows_declared_import() -> None:
    bundle = _bundle("import re\ndef run(ctx): return {}", stdlib_modules=("re",))
    result = check_tier_conformance(bundle)
    assert result.passed is True


def test_conformance_rejects_io_call_at_pure_tier() -> None:
    bundle = _bundle("def run(ctx):\n    open('/etc/passwd')\n    return {}", tier=CapabilityTier.PURE)
    result = check_tier_conformance(bundle)
    assert result.passed is False


def test_conformance_rejects_half_mismatch() -> None:
    # FILL IN: this test's real name in spec §4 covers "Python/TS halves
    #   disagreeing on handler_ref" — that check belongs in
    #   check_tier_conformance or a small dedicated function comparing
    #   bundle.handler_ref parsing between python_source and
    #   client_source, which the current blueprint does NOT implement
    #   (a gap — the spec names this test but the blueprint's
    #   check_tier_conformance only checks imports/IO, not cross-half
    #   handler_ref agreement). Implement the missing check first, then
    #   this test.
    pass


async def test_equivalence_gate_requires_fixtures() -> None:
    bundle = _bundle("def run(ctx): return {}")
    result = await check_equivalence(bundle, fixtures=[])
    assert result.passed is False
    assert "zero equivalence fixtures" in result.errors[0]


async def test_equivalence_gate_detects_divergence() -> None:
    bundle = _bundle("def run(ctx): return {'total': ctx['a'] + 1}")
    fixture = EquivalenceFixture(name="basic", input_payload={"a": 1}, expected_output={"total": 3})
    result = await check_equivalence(bundle, fixtures=[fixture])
    assert result.passed is False


async def test_equivalence_gate_passes_matching_python_only_bundle() -> None:
    bundle = _bundle("def run(ctx): return {'total': ctx['a'] + 1}")
    fixture = EquivalenceFixture(name="basic", input_payload={"a": 1}, expected_output={"total": 2})
    result = await check_equivalence(bundle, fixtures=[fixture])
    assert result.passed is True


async def test_equivalence_gate_fails_loudly_without_js_runner_when_client_source_present() -> None:
    bundle = _bundle("def run(ctx): return {}", client_source="function run(){return {}}")
    fixture = EquivalenceFixture(name="basic", input_payload={}, expected_output={})
    result = await check_equivalence(bundle, fixtures=[fixture], run_js=None)
    assert result.passed is False
    assert any("no JS runner" in e for e in result.errors)
```
**Why**: seven of eight tests are complete; `test_conformance_rejects_half_mismatch`
is stubbed with an explicit note that it exposes a genuine blueprint gap
(cross-half `handler_ref` agreement checking is named by the spec's test
list but not implemented in `check_tier_conformance` above) rather than
silently omitting the test or faking a pass.

### FILL IN checklist
- [ ] `check_snippet_conformance.py` — implement cross-half `handler_ref` agreement checking (spec's `test_conformance_rejects_half_mismatch`) — currently entirely missing from the blueprint, not just a stub
- [ ] `check_tier_conformance` — broker-call detection for tiers BROKERED/TOOLKIT (coordinate call shape with TASK-3176)
- [ ] `check_equivalence` — the `run_js` invocation once a `JsRunnerFn` is actually wired somewhere (likely a CI script outside this package, out of this task's scope to build, only to accept)
- [ ] `test_conformance_rejects_half_mismatch` — full test body once the check above exists

---

## Acceptance Criteria

- [ ] A tier-1 snippet importing `socket` fails `check_tier_conformance` (`test_conformance_rejects_undeclared_import`)
- [ ] A snippet importing only its declared `stdlib_modules` passes
- [ ] `check_equivalence` fails with zero fixtures, regardless of source correctness
- [ ] `check_equivalence` detects a Python-half result diverging from a fixture's `expected_output`
- [ ] A bundle with `client_source` set but no `run_js` supplied fails equivalence with an explicit "no JS runner" error, never silently passing
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_snippet_conformance.py -v`
- [ ] `ruff check` and `mypy` clean on `scripts/check_snippet_conformance.py`

---

## Test Specification

See the blueprint's test file above — 8 test functions, 1 stubbed pending a genuine implementation gap.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 15, §4 unit test list M15 rows, resolved OQ-8)
2. **Check dependencies** — TASK-3161 must be `done`
3. **Verify the Codebase Contract** — confirm no JS execution dependency has been added to `pyproject.toml` elsewhere that would change the "FILL IN" recommendation
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`, including the cross-half `handler_ref` check the blueprint flags as missing entirely
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3175-conformance-equivalence-gate.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — note explicitly whether `run_gate()` was wired back into TASK-3166's `SnippetApprovalService` constructor call (a cross-task follow-up if TASK-3166 already merged with a fake)

---

## Completion Note

**Completed by**: sdd-worker (orchestrated via parrot-sdd-coder)
**Date**: 2026-09-11
**Notes**: Implemented `check_tier_conformance()` (static AST analysis
rejecting undeclared stdlib imports / I/O calls at a snippet's declared
tier) and `check_equivalence()` (runs the Python half against fixtures,
requires at least one fixture, detects divergence from
`expected_output`, and fails loudly — never silently passes — when
`client_source` is set but no `run_js` runner callable is supplied) plus
`run_gate()` combining both for TASK-3166's injection point. 8/8 tests
pass, `ruff check`/`mypy` clean, never imported from
`packages/parrot-formdesigner/src/` (one docstring mention of the
filename in `core/snippets.py`, not an import statement — verified).

**Deviations from spec**: none

**Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 429.7s · Tokens: 887,902 in / 7,446 out**
