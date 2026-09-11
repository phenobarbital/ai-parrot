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
                CapabilityTier.PURE,
                CapabilityTier.HELPERS,
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
    bundle: SnippetBundle,
    fixtures: list[EquivalenceFixture],
    *,
    run_js: JsRunnerFn | None = None,
) -> ConformanceResult:
    """Combined tier-conformance + equivalence gate.

    This is the function to wire into SnippetApprovalService's
    check_conformance parameter (TASK-3166) once this task lands.
    """
    tier_result = await asyncio.to_thread(check_tier_conformance, bundle)
    if not tier_result.passed:
        return tier_result
    return await check_equivalence(bundle, fixtures, run_js=run_js)
