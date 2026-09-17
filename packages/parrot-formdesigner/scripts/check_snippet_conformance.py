"""Compatibility shim — the snippet conformance gate now ships in the package.

The implementation lives in :mod:`parrot_formdesigner.services.snippets.conformance`
so ``parrot_formdesigner.tools.snippet_authoring`` imports it from an installed
wheel (which never contains the repo-local ``scripts`` package). This module
re-exports the public API for existing ``scripts.check_snippet_conformance`` callers.
"""

from parrot_formdesigner.services.snippets.conformance import (  # noqa: F401
    ConformanceResult,
    EquivalenceFixture,
    JsRunnerFn,
    check_equivalence,
    check_tier_conformance,
    run_gate,
)
