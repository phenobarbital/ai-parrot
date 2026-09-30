"""Live planogram compliance cases (FEAT-612). Opt-in, private local assets, not a CI gate.

Run: PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/manifest.json pytest examples/planogram/e2e -q
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from models import LiveCase  # annotation only; runtime loading goes through conftest

pytestmark = [pytest.mark.live, pytest.mark.real_llm]


async def test_live_compliance(case: "LiveCase") -> None:
    """Assert human labels/tolerances after explicit opt-in and required local prerequisites."""
    harness = sys.modules["planogram_e2e_runner"]  # loaded by conftest's `harness` fixture via `case`
    outcome = await harness.run_case(case)
    violations = outcome.get("violations", [])
    assert violations == [], (
        f"Ground-truth violations found ({len(violations)}):\n" +
        "\n".join(f"  - {v}" for v in violations) +
        f"\nSee report: {outcome.get('report_path')}"
    )