"""Tests for FirefliesObsidianAgent.

Covers:
- sync_fireflies_transcripts() — deterministic sync
- summarize_transcript() — LLM-powered analysis
- Note title generation and deduplication
"""

import pytest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.agents.obsidian import FirefliesObsidianAgent


@pytest.fixture
def vault_path(tmp_path):
    """Create a temporary vault directory."""
    vault = tmp_path / "test_vault"
    vault.mkdir()
    (vault / "meetings").mkdir()
    return vault


@pytest.fixture
def agent(vault_path):
    """Create a FirefliesObsidianAgent instance."""
    agent = FirefliesObsidianAgent(
        name="TestFirefliesAgent",
        vault_path=str(vault_path),
        fireflies_token="test-token-12345",
    )
    return agent


class TestNoteTitleGeneration:
    """Test _make_note_title static method."""

    def test_basic_title_generation(self):
        """Generate title from date and meeting title."""
        title = FirefliesObsidianAgent._make_note_title(
            "2026-08-16",
            "Quarterly Planning"
        )
        assert title == "2026-08-16-quarterly-planning"

    def test_title_with_special_chars(self):
        """Handle special characters in title."""
        title = FirefliesObsidianAgent._make_note_title(
            "2026-08-16",
            "Q3 Planning / Review & Analysis"
        )
        assert "-" in title
        assert "/" not in title
        assert "&" not in title

    def test_title_with_iso_datetime(self):
        """Parse ISO datetime format."""
        title = FirefliesObsidianAgent._make_note_title(
            "2026-08-16T14:30:00",
            "Team Standup"
        )
        assert title.startswith("2026-08-16")
        assert "team-standup" in title

    def test_title_fallback_to_utc(self):
        """Fallback to UTC when date parsing fails."""
        title = FirefliesObsidianAgent._make_note_title(
            "invalid-date",
            "Test Meeting"
        )
        # Should contain date part (even if today's date)
        assert title.count("-") >= 2


class TestAnalysisPromptBuilding:
    """Test _build_analysis_prompt static method."""

    def test_minimal_granularity(self):
        """Minimal granularity keeps prompt concise."""
        prompt = FirefliesObsidianAgent._build_analysis_prompt(
            "Test transcript content",
            granularity="minimal"
        )
        assert "minimal" in prompt.lower() or "essential" in prompt.lower()

    def test_standard_granularity(self):
        """Standard granularity is balanced."""
        prompt = FirefliesObsidianAgent._build_analysis_prompt(
            "Test transcript content",
            granularity="standard"
        )
        assert "standard" in prompt.lower() or "balanced" in prompt.lower()

    def test_detailed_granularity(self):
        """Detailed granularity covers comprehensive analysis."""
        prompt = FirefliesObsidianAgent._build_analysis_prompt(
            "Test transcript content",
            granularity="detailed"
        )
        assert "comprehensive" in prompt.lower() or "detailed" in prompt.lower()

    def test_prompt_includes_transcript(self):
        """Prompt includes the transcript text."""
        transcript = "This is a test transcript about quarterly planning."
        prompt = FirefliesObsidianAgent._build_analysis_prompt(transcript)
        assert "quarterly planning" in prompt.lower()

    def test_prompt_includes_sections(self):
        """Prompt requests structured sections."""
        prompt = FirefliesObsidianAgent._build_analysis_prompt("test")
        assert "Summary" in prompt
        assert "Follow" in prompt
        assert "Insights" in prompt


class TestAnalysisResponseParsing:
    """Test _parse_analysis_response static method."""

    def test_parse_structured_response(self):
        """Parse response with clear section headers."""
        response_text = """## Summary
        This meeting covered Q3 planning and discussed budget allocation.

        ## Follow-ups
        1. Get approval from finance on budget split
        2. Schedule follow-up meeting with team leads
        3. Document decisions in wiki

        ## Insights
        - Team is aligned on priorities
        - Budget constraints require careful planning
        - Need better communication channels
        """

        class MockAIMessage:
            def __init__(self, msg):
                self.message = msg

        result = FirefliesObsidianAgent._parse_analysis_response(
            MockAIMessage(response_text)
        )

        assert "Q3 planning" in result["summary"]
        assert len(result["follow_ups"]) == 3
        assert len(result["insights"]) == 3
        assert "Team is aligned" in str(result["insights"])

    def test_parse_minimal_response(self):
        """Handle response with minimal structure."""
        response_text = "Brief summary of meeting"

        class MockAIMessage:
            def __init__(self, msg):
                self.message = msg

        result = FirefliesObsidianAgent._parse_analysis_response(
            MockAIMessage(response_text)
        )

        assert isinstance(result["summary"], str)
        assert isinstance(result["follow_ups"], list)
        assert isinstance(result["insights"], list)


class TestAppendAnalysisSection:
    """Test _append_analysis_section static method."""

    def test_append_analysis_to_transcript(self):
        """Append analysis to existing transcript."""
        transcript = "Original transcript content here."
        result = FirefliesObsidianAgent._append_analysis_section(
            transcript,
            summary="Key decisions made",
            follow_ups=["Action item 1", "Action item 2"],
            insights=["Insight 1", "Insight 2"],
        )

        # Original content should be preserved
        assert "Original transcript content" in result
        # Analysis section should be added
        assert "## Analysis" in result
        assert "Summary" in result
        assert "Follow-ups" in result
        assert "Key Insights" in result

    def test_append_with_empty_lists(self):
        """Handle empty follow-ups and insights gracefully."""
        transcript = "Transcript"
        result = FirefliesObsidianAgent._append_analysis_section(
            transcript,
            summary="Summary",
            follow_ups=[],
            insights=[],
        )

        assert "None identified" in result


class TestSyncMethod:
    """Test sync_fireflies_transcripts method."""

    @pytest.mark.asyncio
    async def test_sync_initializes_mcp(self, agent):
        """Sync method initializes Fireflies MCP."""
        # Mock the MCP initialization
        agent.add_fireflies_mcp_server = AsyncMock(return_value=["tool1", "tool2"])
        agent._call_fireflies_tool = AsyncMock(return_value=[])

        await agent.sync_fireflies_transcripts()

        # Should have called the MCP init
        agent.add_fireflies_mcp_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_returns_report(self, agent):
        """Sync returns structured report."""
        agent.add_fireflies_mcp_server = AsyncMock(return_value=[])
        agent._call_fireflies_tool = AsyncMock(return_value=[])
        agent.obsidian_toolkit = AsyncMock()

        report = await agent.sync_fireflies_transcripts()

        assert "status" in report
        assert "synced" in report
        assert "errors" in report
        assert "timestamp" in report

    @pytest.mark.asyncio
    async def test_sync_handles_error(self, agent):
        """Sync handles errors gracefully."""
        agent.add_fireflies_mcp_server = AsyncMock(
            side_effect=Exception("MCP connection failed")
        )

        report = await agent.sync_fireflies_transcripts()

        assert report["status"] == "error"
        assert len(report["errors"]) > 0


class TestSummarizeMethod:
    """Test summarize_transcript method."""

    @pytest.mark.asyncio
    async def test_summarize_reads_note(self, agent):
        """Summarize reads note from vault."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value={"content": "Meeting transcript"}
        )
        agent.client = AsyncMock()
        agent.client.completion = AsyncMock(
            return_value=MagicMock(message="## Summary\nTest\n\n## Follow-ups\n1. Item")
        )

        result = await agent.summarize_transcript("test-meeting")

        agent.obsidian_toolkit.read_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_calls_llm(self, agent):
        """Summarize calls LLM for analysis."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value={"content": "Meeting transcript"}
        )
        agent.client = AsyncMock()
        agent.client.completion = AsyncMock(
            return_value=MagicMock(message="## Summary\nTest")
        )

        await agent.summarize_transcript("test-meeting")

        agent.client.completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_updates_note(self, agent):
        """Summarize updates note with analysis."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value={"content": "Transcript"}
        )
        agent.obsidian_toolkit.update_note = AsyncMock()
        agent.client = AsyncMock()
        agent.client.completion = AsyncMock(
            return_value=MagicMock(message="## Summary\nTest\n\n## Follow-ups\n1. Item\n\n## Insights\n- Point")
        )

        result = await agent.summarize_transcript("test-meeting")

        agent.obsidian_toolkit.update_note.assert_called_once()
        assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_summarize_handles_missing_note(self, agent):
        """Summarize handles missing notes gracefully."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.read_note = AsyncMock(return_value=None)

        result = await agent.summarize_transcript("nonexistent-note")

        assert result["status"] == "error"
        assert "not found" in result.get("error", "").lower()


class TestGetExistingMeetings:
    """Test _get_existing_meeting_titles helper."""

    @pytest.mark.asyncio
    async def test_list_existing_notes(self, agent):
        """List existing meeting notes."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.list_notes = AsyncMock(
            return_value=[
                {"title": "2026-08-16-planning"},
                {"title": "2026-08-15-standup"},
            ]
        )

        titles = await agent._get_existing_meeting_titles()

        assert "2026-08-16-planning" in titles
        assert "2026-08-15-standup" in titles

    @pytest.mark.asyncio
    async def test_handle_list_error(self, agent):
        """Handle errors when listing notes."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.list_notes = AsyncMock(
            side_effect=Exception("List failed")
        )

        titles = await agent._get_existing_meeting_titles()

        # Should return empty set on error
        assert titles == set()
