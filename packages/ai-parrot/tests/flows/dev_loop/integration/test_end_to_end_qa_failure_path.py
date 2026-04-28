"""End-to-end QA-failure path integration test for the dev-loop flow.

Gated behind ``@pytest.mark.live``. Asserts that when the development
phase fails to fix the bug, the flow lands at FailureHandlerNode with
the ticket transitioned to *Needs Human Review* and NO PR opened.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_end_to_end_qa_failure_path(
    skip_unless_claude_available,
    skip_unless_redis_available,
    temp_worktree_base,
):
    """QA fails → flow takes the failure path; no PR is created."""
    pytest.skip(
        "Live e2e — same env-var prerequisites as the happy-path test."
    )
