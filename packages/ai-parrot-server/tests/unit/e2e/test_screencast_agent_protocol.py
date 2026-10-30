"""Prose-contract test for e2e-ui-tester's on-anomaly screencast protocol (FEAT-762 M3)."""

from __future__ import annotations

from pathlib import Path

AGENT = Path(__file__).resolve().parents[5] / ".claude" / "agents" / "e2e-ui-tester.md"


def test_exploration_screencast_protocol() -> None:
    """Agent prose uses record_on_anomaly, post-detection wording, explicit endpoint, no daemon CLI."""
    text = AGENT.read_text(encoding="utf-8")
    assert "record_on_anomaly" in text
    assert "post-detection" in text
    assert "screencast.webm" in text
    assert "`RunState.endpoint` is not populated" in text
    assert "parrot e2e screencast start" not in text
    assert "page-target-id" not in text
    assert "DevTools MCP" in text
    assert text.index("record_on_anomaly") < text.index("4. Stop every target you started")
