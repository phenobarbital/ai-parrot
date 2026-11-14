"""Tests for expert triage and promote commands."""

from __future__ import annotations

import json
from pathlib import Path

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


@pytest.fixture
async def repository(tmp_path):
    """A real SQLite wiki store behind a real DecisionRepository."""
    from parrot.knowledge.wiki.decisions.repository import DecisionRepository
    from parrot.knowledge.wiki.store import create_wiki_store

    store = create_wiki_store(tmp_path / "wiki", wiki_name="test", backend="sqlite")
    return DecisionRepository(store)


@pytest.mark.asyncio
async def test_promote_persists_the_findings_own_statement(temp_contribution, repository):
    """The decision carries the confirmed finding's statement, unreviewed and inferred - no model involved."""
    from parrot.experts.promotion import promote_finding

    decision_id = await promote_finding(temp_contribution, "f-2", repo_root=Path("."), repository=repository)

    loaded = await repository.get(decision_id)
    assert loaded is not None
    record, _hash = loaded
    assert record.decision == "Another finding"
    assert record.origin == "inferred"
    assert record.review_status == "unreviewed"
    assert record.source_status == "unknown"
    assert record.generation is None  # not model generated
    assert "test-expert" in record.context and "Already confirmed" in record.context


@pytest.mark.asyncio
async def test_promote_twice_returns_the_same_decision_and_keeps_it(temp_contribution, repository):
    """Idempotent: a second promotion neither duplicates nor overwrites the stored decision."""
    from parrot.experts.promotion import promote_finding

    first = await promote_finding(temp_contribution, "f-2", repo_root=Path("."), repository=repository)
    _record, content_hash = await repository.get(first)
    second = await promote_finding(temp_contribution, "f-2", repo_root=Path("."), repository=repository)

    assert second == first
    assert (await repository.get(first))[1] == content_hash
    assert len(await repository.inventory()) == 1


@pytest.mark.asyncio
async def test_promote_refuses_unconfirmed_and_missing_without_writing(temp_contribution, repository):
    from parrot.experts.promotion import promote_finding

    with pytest.raises(ValueError, match="not confirmed"):
        await promote_finding(temp_contribution, "f-1", repo_root=Path("."), repository=repository)
    with pytest.raises(ValueError, match="not found"):
        await promote_finding(temp_contribution, "nope", repo_root=Path("."), repository=repository)
    assert await repository.inventory() == []


def test_promote_command_prints_the_created_decision(runner, temp_contribution, repository, monkeypatch):
    """The CLI promotes through the same path; only the project-store opening is replaced."""
    import asyncio

    monkeypatch.setattr("parrot.experts.promotion._open_repository", lambda root: repository)
    result = runner.invoke(experts, ["promote", str(temp_contribution), "f-2", "--root", "."])

    assert result.exit_code == 0, result.output
    assert "Created inferred decision: adr:candidate:" in result.output
    assert len(asyncio.run(repository.inventory())) == 1


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
