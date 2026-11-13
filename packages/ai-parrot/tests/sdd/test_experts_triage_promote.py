"""Tests for expert triage and promote commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from click.testing import CliRunner

from parrot.experts.contributions import Contribution, Finding, save_contribution
from parrot.sdd.experts_cli import experts


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_contribution(tmp_path):
    """Create a temporary contribution file for testing."""
    contribution = Contribution(
        expert="test-expert",
        tier="primary",
        doc_path="test.md",
        doc_digest="abc123",
        feature_id="FEAT-123",
        created_at="2023-01-01T00:00:00Z",
        findings=[
            Finding(
                id="f-1",
                severity="major",
                section="test-section",
                statement="Test finding",
                evidence=["evidence1", "evidence2"],
                status="pending",
                reason="",
            ),
            Finding(
                id="f-2",
                severity="minor",
                section="another-section",
                statement="Another finding",
                evidence=[],
                status="confirm",
                reason="Already confirmed",
            ),
        ],
    )

    contrib_path = tmp_path / "contribution.json"
    save_contribution(contrib_path, contribution)
    return contrib_path


def test_triage_confirm_finding(runner, temp_contribution):
    """Test triaging a finding to confirm status."""
    result = runner.invoke(experts, ["triage", str(temp_contribution), "f-1", "confirm", "--reason", "Valid concern"])

    assert result.exit_code == 0
    assert "Updated finding f-1 status to confirm" in result.output

    # Verify the contribution was updated
    updated_contrib = json.loads(temp_contribution.read_text())
    finding = next(f for f in updated_contrib["findings"] if f["id"] == "f-1")
    assert finding["status"] == "confirm"
    assert finding["reason"] == "Valid concern"


def test_triage_reject_finding(runner, temp_contribution):
    """Test triaging a finding to reject status."""
    result = runner.invoke(experts, ["triage", str(temp_contribution), "f-1", "reject", "--reason", "Not applicable"])

    assert result.exit_code == 0
    assert "Updated finding f-1 status to reject" in result.output

    # Verify the contribution was updated
    updated_contrib = json.loads(temp_contribution.read_text())
    finding = next(f for f in updated_contrib["findings"] if f["id"] == "f-1")
    assert finding["status"] == "reject"
    assert finding["reason"] == "Not applicable"


def test_triage_escalate_finding(runner, temp_contribution):
    """Test triaging a finding to escalate status."""
    result = runner.invoke(
        experts, ["triage", str(temp_contribution), "f-1", "escalate", "--reason", "Needs human review"]
    )

    assert result.exit_code == 0
    assert "Updated finding f-1 status to escalate" in result.output

    # Verify the contribution was updated
    updated_contrib = json.loads(temp_contribution.read_text())
    finding = next(f for f in updated_contrib["findings"] if f["id"] == "f-1")
    assert finding["status"] == "escalate"
    assert finding["reason"] == "Needs human review"


def test_triage_nonexistent_finding(runner, temp_contribution):
    """Test triaging a finding that doesn't exist."""
    result = runner.invoke(experts, ["triage", str(temp_contribution), "nonexistent", "confirm"])

    assert result.exit_code != 0
    assert "Finding nonexistent not found" in result.output


def test_promote_confirmed_finding(runner, temp_contribution):
    """Test promoting a confirmed finding."""
    with patch("parrot.experts.promotion.DecisionService") as mock_service_class:
        mock_service = AsyncMock()
        mock_service.generate = AsyncMock(return_value=AsyncMock(decision_ids=["decision-123"], reused=[]))
        mock_service_class.return_value = mock_service

        with patch("parrot.knowledge.wiki.store.create_wiki_store") as mock_factory:
            mock_factory.return_value = Mock()

            result = runner.invoke(experts, ["promote", str(temp_contribution), "f-2", "--root", "."])

            assert result.exit_code == 0
            assert "Created inferred decision: decision-123" in result.output


def test_promote_unconfirmed_finding(runner, temp_contribution):
    """Test promoting a finding that is not confirmed."""
    result = runner.invoke(experts, ["promote", str(temp_contribution), "f-1", "--root", "."])

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "not confirmed" in result.output


def test_promote_nonexistent_finding(runner, temp_contribution):
    """Test promoting a finding that doesn't exist."""
    result = runner.invoke(experts, ["promote", str(temp_contribution), "nonexistent", "--root", "."])

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "not found" in result.output


# Import Mock for the patch
from unittest.mock import Mock
