"""Tests for FirefliesObsidianAgent.

Covers:
- sync_fireflies_transcripts() — deterministic sync
- summarize_transcript() — LLM-powered analysis
- Note title generation and deduplication
"""

import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.agents.obsidian import (
    FirefliesFilters,
    FirefliesObsidianAgent,
    _filters_to_tool_args,
)
from parrot.clients.codex_agent import CodexAgentRunOptions, OpenAICodexClient
from pydantic import ValidationError


class _FakeCodexClient(OpenAICodexClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.commands: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.output = """## Summary
The team reviewed the launch plan, confirmed the release owner, and agreed to publish the checklist.

## Follow-ups
1. Confirm the launch checklist owner
2. Share the final release notes

## Insights
- Release ownership is clear
- The checklist is the main next step
"""
        self.stdout = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 24,
                    "total_tokens": 36,
                },
            }
        )

    async def _run_cli_command(
        self,
        command: list[str],
        input_text: str | None = None,
    ) -> tuple[str, str, int]:
        self.commands.append(command)
        self.inputs.append(input_text)
        output_index = command.index("-o") + 1
        Path(command[output_index]).write_text(self.output, encoding="utf-8")
        return self.stdout, "", 0


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
        injection_detection=False,
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

    def test_explicit_codex_llm_is_active_client(self, vault_path):
        """FirefliesObsidianAgent keeps an explicit Codex LLM on self.client."""
        agent = FirefliesObsidianAgent(
            name="CodexFirefliesAgent",
            vault_path=str(vault_path),
            llm="openai-codex:gpt-codex-test",
            llm_kwargs={"backend": "cli"},
            injection_detection=False,
            use_tools=False,
        )

        assert isinstance(agent.client, OpenAICodexClient)
        assert agent.client is agent.llm
        assert agent.client.model == "gpt-codex-test"

    @pytest.mark.asyncio
    async def test_summarize_reads_note(self, agent):
        """Summarize reads note from vault."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value={"content": "Meeting transcript"}
        )
        agent.client = AsyncMock()
        agent.client.complete = AsyncMock(
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
        agent.client.complete = AsyncMock(
            return_value=MagicMock(message="## Summary\nTest")
        )

        await agent.summarize_transcript("test-meeting")

        agent.client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_updates_note(self, agent):
        """Summarize updates note with analysis."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.read_note = AsyncMock(
            return_value={"content": "Transcript"}
        )
        agent.obsidian_toolkit.update_note = AsyncMock()
        agent.client = AsyncMock()
        agent.client.complete = AsyncMock(
            return_value=MagicMock(message="## Summary\nTest\n\n## Follow-ups\n1. Item\n\n## Insights\n- Point")
        )

        result = await agent.summarize_transcript("test-meeting")

        agent.obsidian_toolkit.update_note.assert_called_once()
        assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_summarize_with_codex_client(self, vault_path):
        """Summarize a real vault note through a CLI-backed Codex client."""
        codex = _FakeCodexClient(backend="cli")
        agent = FirefliesObsidianAgent(
            name="CodexFirefliesAgent",
            vault_path=str(vault_path),
            llm=codex,
            injection_detection=False,
            use_tools=False,
        )
        await agent.obsidian_toolkit.create_note(
            path="meetings/2026-08-20-launch-sync.md",
            content=(
                "Speaker A: We need a launch checklist owner.\n"
                "Speaker B: I will own it and share release notes tomorrow."
            ),
        )

        result = await agent.summarize_transcript(
            "2026-08-20-launch-sync",
            granularity="minimal",
        )

        assert result["status"] == "ok"
        assert result["updated"] is True
        assert "launch plan" in result["summary"]
        assert len(result["follow_ups"]) == 2
        assert len(result["insights"]) == 2
        assert codex.commands
        assert "launch checklist owner" in (codex.inputs[0] or "")

    @pytest.mark.real_llm
    @pytest.mark.asyncio
    async def test_real_codex_client_summarizes_temp_obsidian_note(self, vault_path):
        """Opt-in smoke: real OpenAICodexClient + FirefliesObsidianAgent."""
        if not shutil.which("codex"):
            pytest.skip("codex CLI is not installed")

        model = os.getenv("PARROT_CODEX_TEST_MODEL")
        backend = os.getenv("PARROT_CODEX_BACKEND", "cli")
        agent = FirefliesObsidianAgent(
            name="RealCodexFirefliesAgent",
            vault_path=str(vault_path),
            llm=f"openai-codex:{model}" if model else "openai-codex",
            llm_kwargs={
                "backend": backend,
                "run_options": CodexAgentRunOptions(
                    backend=backend,
                    model=model or "",
                    sandbox="read-only",
                    approval_policy="never",
                    expose_parrot_tools=False,
                    ephemeral=True,
                    ignore_rules=True,
                ),
            },
            injection_detection=False,
            use_tools=False,
        )
        await agent.obsidian_toolkit.create_note(
            path="meetings/2026-08-20-real-codex-smoke.md",
            content=(
                "Alex: We agreed to ship the Fireflies Obsidian sync next week.\n"
                "Mira: I will validate Codex as the summarization client and "
                "write down any integration risks."
            ),
        )

        result = await asyncio.wait_for(
            agent.summarize_transcript(
                "2026-08-20-real-codex-smoke",
                granularity="minimal",
            ),
            timeout=180,
        )

        assert result["status"] == "ok"
        assert result["updated"] is True
        assert result["summary"]

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


class TestExistingMeetingsRealToolkitShape:
    """Regression: list_notes() returns VaultFileInfo dicts, not titles.

    The real ``ObsidianToolkit.list_notes()`` returns
    ``{"notes": [VaultFileInfo.model_dump(), ...], "count": N}`` — those
    descriptors carry ``path``/``name``/``size``/``mtime`` and have **no**
    ``title`` key. Reading ``note["title"]`` therefore yielded an empty set,
    which silently disabled both ``skip_existing`` and the summarization
    phase.
    """

    @pytest.mark.asyncio
    async def test_titles_derived_from_file_stem(self, agent):
        """Titles come from the file stem when no 'title' key exists."""
        agent.obsidian_toolkit = AsyncMock()
        agent.obsidian_toolkit.list_notes = AsyncMock(
            return_value={
                "notes": [
                    {
                        "path": "meetings/2026-08-19-troc360-mobile-sync.md",
                        "name": "2026-08-19-troc360-mobile-sync.md",
                        "size": 1024,
                        "mtime": 1.0,
                        "is_note": True,
                        "is_canvas": False,
                    },
                    {
                        "path": "meetings/2026-08-17-inventory-review.md",
                        "name": "2026-08-17-inventory-review.md",
                        "size": 512,
                        "mtime": 2.0,
                        "is_note": True,
                        "is_canvas": False,
                    },
                ],
                "count": 2,
            }
        )

        titles = await agent._get_existing_meeting_titles()

        assert titles == {
            "2026-08-19-troc360-mobile-sync",
            "2026-08-17-inventory-review",
        }

    @pytest.mark.asyncio
    async def test_titles_round_trip_through_real_vault(self, agent, vault_path):
        """A note created via the real toolkit is found again by its title."""
        note_title = agent._make_note_title("2026-08-19T10:00:00", "Weekly Sync")
        await agent.obsidian_toolkit.create_note(
            path=f"{agent.meetings_folder}/{note_title}.md",
            content="Transcript body",
        )

        titles = await agent._get_existing_meeting_titles()

        assert note_title in titles


class TestHasAnalysis:
    """Test the _has_analysis marker check."""

    @pytest.mark.asyncio
    async def test_detects_missing_analysis(self, agent):
        """A freshly synced note reports no analysis."""
        await agent.obsidian_toolkit.create_note(
            path=f"{agent.meetings_folder}/2026-08-19-plain.md",
            content="Just a transcript.",
        )

        assert await agent._has_analysis("2026-08-19-plain") is False

    @pytest.mark.asyncio
    async def test_detects_existing_analysis(self, agent):
        """A note carrying the Analysis heading reports True."""
        enhanced = agent._append_analysis_section(
            "Transcript body", "A summary", ["Q1"], ["Insight"]
        )
        await agent.obsidian_toolkit.create_note(
            path=f"{agent.meetings_folder}/2026-08-19-analyzed.md",
            content=enhanced,
        )

        assert await agent._has_analysis("2026-08-19-analyzed") is True

    @pytest.mark.asyncio
    async def test_missing_note_is_not_analyzed(self, agent):
        """A note that does not exist reports False instead of raising."""
        assert await agent._has_analysis("does-not-exist") is False


class TestSummarizePendingTranscripts:
    """Test the batch summarization entry point."""

    @pytest.mark.asyncio
    async def test_summarizes_every_pending_note(self, agent):
        """All notes without analysis are summarized, not just the newest."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"2026-08-19-a", "2026-08-19-b", "2026-08-18-c"}
        )
        agent._has_analysis = AsyncMock(return_value=False)
        agent.summarize_transcript = AsyncMock(
            return_value={"status": "ok", "summary": "s", "follow_ups": [], "insights": []}
        )

        outcome = await agent.summarize_pending_transcripts()

        assert outcome["status"] == "ok"
        assert sorted(outcome["analyzed"]) == ["2026-08-18-c", "2026-08-19-a", "2026-08-19-b"]
        assert agent.summarize_transcript.await_count == 3

    @pytest.mark.asyncio
    async def test_skips_already_analyzed_notes(self, agent):
        """Notes that already carry an Analysis section are skipped."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"2026-08-19-a", "2026-08-19-b"}
        )
        agent._has_analysis = AsyncMock(side_effect=[True, False])
        agent.summarize_transcript = AsyncMock(
            return_value={"status": "ok", "summary": "s", "follow_ups": [], "insights": []}
        )

        outcome = await agent.summarize_pending_transcripts()

        assert len(outcome["analyzed"]) == 1
        assert len(outcome["skipped"]) == 1
        assert agent.summarize_transcript.await_count == 1

    @pytest.mark.asyncio
    async def test_force_reanalyzes(self, agent):
        """force=True ignores the already-analyzed marker."""
        agent._get_existing_meeting_titles = AsyncMock(return_value={"2026-08-19-a"})
        agent._has_analysis = AsyncMock(return_value=True)
        agent.summarize_transcript = AsyncMock(
            return_value={"status": "ok", "summary": "s", "follow_ups": [], "insights": []}
        )

        outcome = await agent.summarize_pending_transcripts(force=True)

        assert outcome["analyzed"] == ["2026-08-19-a"]
        agent._has_analysis.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_limit_bounds_llm_calls(self, agent):
        """limit caps how many notes are analyzed per run."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={f"2026-08-19-{i}" for i in range(5)}
        )
        agent._has_analysis = AsyncMock(return_value=False)
        agent.summarize_transcript = AsyncMock(
            return_value={"status": "ok", "summary": "s", "follow_ups": [], "insights": []}
        )

        outcome = await agent.summarize_pending_transcripts(limit=2)

        assert len(outcome["analyzed"]) == 2
        assert agent.summarize_transcript.await_count == 2

    @pytest.mark.asyncio
    async def test_explicit_titles_take_precedence(self, agent):
        """Passing note_titles skips the vault scan."""
        agent._get_existing_meeting_titles = AsyncMock(return_value={"unused"})
        agent._has_analysis = AsyncMock(return_value=False)
        agent.summarize_transcript = AsyncMock(
            return_value={"status": "ok", "summary": "s", "follow_ups": [], "insights": []}
        )

        outcome = await agent.summarize_pending_transcripts(
            note_titles=["2026-08-19-explicit"]
        )

        assert outcome["analyzed"] == ["2026-08-19-explicit"]
        agent._get_existing_meeting_titles.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failures_are_collected_not_raised(self, agent):
        """One failing note does not abort the batch."""
        agent._get_existing_meeting_titles = AsyncMock(
            return_value={"2026-08-19-a", "2026-08-19-b"}
        )
        agent._has_analysis = AsyncMock(return_value=False)
        agent.summarize_transcript = AsyncMock(
            side_effect=[
                {"status": "error", "error": "LLM timeout"},
                {"status": "ok", "summary": "s", "follow_ups": [], "insights": []},
            ]
        )

        outcome = await agent.summarize_pending_transcripts()

        assert outcome["status"] == "partial"
        assert len(outcome["analyzed"]) == 1
        assert outcome["errors"][0]["error"] == "LLM timeout"


class TestSyncReportsSyncedNotes:
    """Sync report exposes the titles it created."""

    @pytest.mark.asyncio
    async def test_report_has_notes_key(self, agent):
        """The report carries a 'notes' list of created note titles."""
        agent.add_fireflies_mcp_server = AsyncMock(return_value=[])
        agent._call_fireflies_tool = AsyncMock(return_value=[])
        agent.obsidian_toolkit = AsyncMock()

        report = await agent.sync_fireflies_transcripts()

        assert report["notes"] == []


class TestStripListMarker:
    """The parser must not leave a marker for _append_analysis_section to double."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1. Has the pallet shipped?", "Has the pallet shipped?"),
            ("2) Where are they?", "Where are they?"),
            ("- Shoe organizers first", "Shoe organizers first"),
            ("- - double bullet", "double bullet"),
            ("* asterisk bullet", "asterisk bullet"),
            ("no marker at all", "no marker at all"),
        ],
    )
    def test_marker_stripped(self, raw, expected):
        from parrot.agents.obsidian import _strip_list_marker

        assert _strip_list_marker(raw) == expected

    def test_rendered_section_has_single_bullet(self):
        """End-to-end: parsed items render as one '- ' each."""
        class MockAIMessage:
            def __init__(self, msg):
                self.message = msg

        response = MockAIMessage(
            "## Summary\nA summary.\n\n"
            "## Follow-ups\n1. First question?\n2. Second question?\n\n"
            "## Insights\n- First insight\n- Second insight\n"
        )
        parsed = FirefliesObsidianAgent._parse_analysis_response(response)
        rendered = FirefliesObsidianAgent._append_analysis_section(
            "Transcript", parsed["summary"], parsed["follow_ups"], parsed["insights"]
        )

        assert "- First question?" in rendered
        assert "- 1. " not in rendered
        assert "- - " not in rendered


class TestStripAnalysisSection:
    """Re-analysis must replace the Analysis block, never stack a second one."""

    def test_strips_appended_block(self):
        """The block written by _append_analysis_section round-trips away."""
        transcript = "Speaker A: hello\nSpeaker B: hi"
        enhanced = FirefliesObsidianAgent._append_analysis_section(
            transcript, "A summary", ["Q1"], ["Insight"]
        )

        assert (
            FirefliesObsidianAgent._strip_analysis_section(enhanced) == transcript
        )

    def test_plain_transcript_untouched(self):
        """A note with no Analysis block is returned unchanged."""
        transcript = "Speaker A: hello"

        assert (
            FirefliesObsidianAgent._strip_analysis_section(transcript) == transcript
        )

    @pytest.mark.asyncio
    async def test_reanalysis_keeps_one_section(self, agent):
        """Summarizing twice leaves exactly one Analysis heading."""
        note_title = "2026-08-19-twice"
        await agent.obsidian_toolkit.create_note(
            path=f"{agent.meetings_folder}/{note_title}.md",
            content="Speaker A: hello",
        )

        class MockAIMessage:
            def __init__(self, msg):
                self.message = msg

        agent.client = MagicMock()
        agent.client.complete = AsyncMock(
            return_value=MockAIMessage(
                "## Summary\nA summary.\n\n## Follow-ups\n1. Q?\n\n## Insights\n- I\n"
            )
        )

        await agent.summarize_transcript(note_title)
        await agent.summarize_transcript(note_title)

        note = await agent.obsidian_toolkit.read_note(
            path=f"{agent.meetings_folder}/{note_title}"
        )
        assert note["content"].count(FirefliesObsidianAgent.ANALYSIS_HEADING) == 1


class TestFirefliesFilters:
    """Test the FirefliesFilters Pydantic model (TASK-2346)."""

    def test_valid_construction(self):
        f = FirefliesFilters(from_date="2026-08-01", mine=True)
        assert f.from_date == "2026-08-01"
        assert f.mine is True

    def test_rejects_bad_scope(self):
        with pytest.raises(ValidationError):
            FirefliesFilters(scope="invalid")

    def test_rejects_malformed_email_in_organizers(self):
        with pytest.raises(ValidationError):
            FirefliesFilters(organizers=["not-an-email"])

    def test_rejects_malformed_email_in_participants(self):
        with pytest.raises(ValidationError):
            FirefliesFilters(participants=["also-not-an-email"])

    def test_defaults(self):
        f = FirefliesFilters()
        assert f.scope == "all"
        assert f.organizers == []
        assert f.participants == []
        assert f.from_date is None
        assert f.to_date is None
        assert f.keyword is None
        assert f.mine is None
        assert f.channel_id is None

    def test_keyword_max_length_enforced(self):
        with pytest.raises(ValidationError):
            FirefliesFilters(keyword="x" * 256)


class TestFiltersToToolArgs:
    """Test the _filters_to_tool_args() field-name mapping (TASK-2346)."""

    def test_maps_camel_case_fields(self):
        f = FirefliesFilters(
            from_date="2026-08-01", to_date="2026-08-31", channel_id="abc123"
        )
        args = _filters_to_tool_args(f)
        assert args["fromDate"] == "2026-08-01"
        assert args["toDate"] == "2026-08-31"
        assert args["channelId"] == "abc123"

    def test_passthrough_fields_unchanged(self):
        f = FirefliesFilters(keyword="standup", scope="title", mine=True)
        args = _filters_to_tool_args(f)
        assert args["keyword"] == "standup"
        assert args["scope"] == "title"
        assert args["mine"] is True

    def test_email_lists_serialized_as_strings(self):
        f = FirefliesFilters(
            organizers=["boss@company.com"],
            participants=["a@x.com", "b@x.com"],
        )
        args = _filters_to_tool_args(f)
        assert args["organizers"] == ["boss@company.com"]
        assert args["participants"] == ["a@x.com", "b@x.com"]

    def test_unset_fields_omitted(self):
        args = _filters_to_tool_args(FirefliesFilters())
        assert "fromDate" not in args
        assert "toDate" not in args
        assert "keyword" not in args
        assert "scope" not in args  # default "all" is omitted too
        assert "organizers" not in args
        assert "participants" not in args
        assert "mine" not in args
        assert "channelId" not in args
