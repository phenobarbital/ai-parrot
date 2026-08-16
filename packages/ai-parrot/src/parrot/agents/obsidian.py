"""Fireflies → Obsidian Sync Agent

Syncs meeting transcripts from Fireflies.ai into a local Obsidian vault
under the 'meetings' folder. Supports two operations:

1. sync_fireflies_transcripts() — Deterministic (no LLM): fetch + save
2. summarize_transcript() — LLM-powered: generate summary + follow-ups + insights

The sync operation is safe to schedule every 8 hours via /schedule.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from navconfig import config
from parrot.bots.agent import BasicAgent
from parrot.tools.obsidian import ObsidianToolkit
from parrot.models.responses import AIMessage
from parrot.interfaces.obsidian.okf import project_okf_block
from parrot.knowledge.okf.ontology import ConceptType, SourceProvenance


logger = logging.getLogger(__name__)


class FirefliesObsidianAgent(BasicAgent):
    """Agent that syncs Fireflies.ai transcripts into Obsidian vault.

    Features:
    - Deterministic sync (no LLM required)
    - Incremental updates (tracks synced transcripts)
    - Optional LLM-powered summarization
    - Scheduler-friendly (stateless, idempotent)

    Usage:
        agent = FirefliesObsidianAgent(
            vault_path="~/vaults/notes",
            fireflies_token="your-token"
        )

        # Run manually
        report = await agent.sync_fireflies_transcripts()

        # Or schedule via /schedule every 8 hours
        /schedule create fireflies-sync \
            --cron "0 */8 * * *" \
            --command "agent FirefliesObsidianAgent sync"
    """

    def __init__(
        self,
        name: str = "FirefliesObsidianSync",
        vault_path: Optional[str | Path] = None,
        fireflies_token: Optional[str] = None,
        meetings_folder: str = "meetings",
        **kwargs,
    ):
        """Initialize the Fireflies→Obsidian sync agent.

        Args:
            name: Agent name
            vault_path: Path to Obsidian vault (e.g. ~/vaults/notes)
            fireflies_token: Fireflies.ai API token (if None, will prompt)
            meetings_folder: Subfolder in vault to store meetings (default: 'meetings')
            **kwargs: Forwarded to Agent.__init__()
        """
        super().__init__(name=name, **kwargs)

        self.vault_path = Path(vault_path) if vault_path else Path.home() / "vaults" / "notes"
        self.fireflies_token = fireflies_token
        self.meetings_folder = meetings_folder

        # Initialize Obsidian toolkit
        self.obsidian_toolkit = ObsidianToolkit(
            vault_path=str(self.vault_path),
            backend="local",
            allowed_operations={
                "read",
                "list",
                "search",
                "create",
                "update",
            }
        )

        self._mcp_fireflies_initialized = False
        self.logger = logging.getLogger(f"{self.name}.Agent")

    async def _ensure_fireflies_mcp(self) -> None:
        """Lazy-init Fireflies MCP server on first use."""
        if self._mcp_fireflies_initialized:
            return

        token = self.fireflies_token
        if not token:
            # Try to get from navconfig (env/.env loaded via navconfig)
            token = config.get("FIREFLIES_API_KEY") or os.getenv("FIREFLIES_API_KEY")

        if not token:
            raise ValueError(
                "Fireflies token required. Set via fireflies_token= or "
                "FIREFLIES_API_KEY environment variable (loaded via navconfig)."
            )

        try:
            tools = await self.add_fireflies_mcp_server(api_key=token)
            self.logger.info(f"Fireflies MCP initialized with tools: {tools}")
            self._mcp_fireflies_initialized = True
        except Exception as e:
            self.logger.error(f"Failed to initialize Fireflies MCP: {e}")
            raise

    async def sync_fireflies_transcripts(
        self,
        limit: int = 10,
        skip_existing: bool = True,
    ) -> Dict[str, Any]:
        """Fetch latest Fireflies transcripts and save to Obsidian.

        **Deterministic**: No LLM involved, safe to schedule every 8 hours.

        Args:
            limit: Max transcripts to fetch (default: 10)
            skip_existing: Skip transcripts already in vault (default: True)

        Returns:
            Dict with:
            - status: 'ok' | 'error'
            - synced: number of new transcripts saved
            - errors: list of error messages
            - timestamp: ISO-8601 sync time
        """
        report = {
            "status": "ok",
            "synced": 0,
            "skipped": 0,
            "errors": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            await self._ensure_fireflies_mcp()

            # List transcripts via Fireflies MCP tool
            self.logger.info(f"Fetching latest {limit} Fireflies transcripts...")

            # Call Fireflies get_transcripts tool
            tool_result = await self._call_fireflies_tool(
                "fireflies_get_transcripts",
                {"limit": limit}
            )

            # Extract transcripts from ToolResult
            # The result.result field contains formatted text with transcript metadata
            if not tool_result or not tool_result.success:
                self.logger.info("No transcripts found or API error")
                return report

            # Parse the result text to extract individual transcripts
            self.logger.debug(f"Fireflies API response: {tool_result.result[:200]}...")
            transcripts = self._parse_fireflies_response(tool_result.result)
            if not transcripts:
                self.logger.info("No transcripts found")
                return report

            # Get existing meeting files
            existing_titles = set()
            if skip_existing:
                existing_titles = await self._get_existing_meeting_titles()

            # Sync each transcript
            for transcript in transcripts:
                try:
                    transcript_id = transcript.get("id")
                    title = transcript.get("title", "Untitled Meeting")
                    date = transcript.get("date", datetime.utcnow().isoformat())

                    # Skip if already synced
                    note_title = self._make_note_title(date, title)
                    if note_title in existing_titles:
                        self.logger.info(f"Skipping existing: {note_title}")
                        report["skipped"] += 1
                        continue

                    # Fetch full transcript
                    transcript_result = await self._call_fireflies_tool(
                        "fireflies_get_transcript",
                        {"transcriptId": transcript_id}
                    )

                    # Extract transcript text from ToolResult
                    transcript_text = (
                        transcript_result.result
                        if hasattr(transcript_result, "result")
                        else str(transcript_result)
                    )

                    # Save to Obsidian
                    metadata = {
                        "fireflies_id": transcript_id,
                        "date": date,
                        "title": title,
                        "participants": transcript.get("participants", []),
                        "duration_minutes": transcript.get("duration", 0),
                        "synced_at": datetime.utcnow().isoformat(),
                    }

                    # Generate OKF frontmatter for knowledge graph integration
                    okf_metadata = self._build_okf_frontmatter(
                        fireflies_id=transcript_id,
                        title=title,
                        date=date,
                        participants=transcript.get("participants", []),
                        duration=transcript.get("duration", 0),
                    )

                    # Merge OKF metadata with basic Fireflies metadata
                    merged_metadata = {**metadata, **okf_metadata}

                    await self.obsidian_toolkit.create_note(
                        path=f"{self.meetings_folder}/{note_title}.md",
                        content=transcript_text,
                        frontmatter=merged_metadata,
                    )

                    self.logger.info(f"✅ Synced: {note_title}")
                    report["synced"] += 1

                    # Phase 2: Generate LLM summary for each synced transcript
                    self.logger.info(f"Generating summary for {note_title}...")
                    summary_result = await self.summarize_transcript(
                        note_title=note_title,
                        granularity="standard"
                    )

                    if summary_result.get("updated"):
                        self.logger.info(f"✅ Analysis added: {note_title}")
                    else:
                        if summary_result.get("status") == "error":
                            self.logger.warning(f"Summary failed for {note_title}: {summary_result.get('error')}")

                except Exception as e:
                    error_msg = f"Failed to sync {transcript.get('id', 'unknown')}: {e}"
                    self.logger.error(error_msg)
                    report["errors"].append(error_msg)

        except Exception as e:
            report["status"] = "error"
            report["errors"].append(str(e))
            self.logger.error(f"Sync failed: {e}", exc_info=True)

        return report

    async def summarize_transcript(
        self,
        note_title: str,
        granularity: str = "standard",
    ) -> Dict[str, Any]:
        """LLM-powered: Generate summary + follow-ups + insights for a meeting.

        Reads the transcript from Obsidian and generates:
        1. Executive summary (2-3 paragraphs)
        2. Follow-up questions (max 5)
        3. Key insights and action items

        Appends results to the note's "Analysis" section.

        Args:
            note_title: Title of meeting note (e.g. '2026-08-16-quarterly-planning')
            granularity: 'minimal' | 'standard' | 'detailed' (controls depth)

        Returns:
            Dict with:
            - status: 'ok' | 'error'
            - summary: The generated summary text
            - follow_ups: List of follow-up questions
            - insights: List of key insights
            - updated: Whether the note was updated
        """
        result = {
            "status": "ok",
            "summary": "",
            "follow_ups": [],
            "insights": [],
            "updated": False,
        }

        try:
            # Read transcript from Obsidian
            self.logger.info(f"Reading transcript: {note_title}")
            note = await self.obsidian_toolkit.read_note(
                path=f"{self.meetings_folder}/{note_title}",
            )

            if not note:
                result["status"] = "error"
                result["error"] = f"Note not found: {note_title}"
                return result

            transcript_text = note.get("content", "")

            # Call LLM for analysis
            analysis_prompt = self._build_analysis_prompt(
                transcript_text,
                granularity=granularity
            )

            self.logger.info(f"Analyzing with LLM (granularity={granularity})...")
            llm_response = await self.client.complete(analysis_prompt)

            # Parse LLM response
            parsed = self._parse_analysis_response(llm_response)
            result.update(parsed)

            # Update note with analysis
            enhanced_content = self._append_analysis_section(
                transcript_text,
                parsed["summary"],
                parsed["follow_ups"],
                parsed["insights"],
            )

            await self.obsidian_toolkit.update_note(
                path=f"{self.meetings_folder}/{note_title}",
                content=enhanced_content,
            )

            result["updated"] = True
            self.logger.info(f"✅ Updated {note_title} with analysis")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self.logger.error(f"Summarization failed: {e}", exc_info=True)

        return result

    # ========== Private Helpers ==========

    @staticmethod
    def _build_okf_frontmatter(
        fireflies_id: str,
        title: str,
        date: str,
        participants: List[str],
        duration: float,
    ) -> Dict[str, Any]:
        """Build OKF (Open Knowledge Format) frontmatter for knowledge graph integration.

        Generates the `okf:` block that AI-Parrot's knowledge graph expects,
        enabling the meeting to be indexed and queryable via PageIndex/GraphIndex.

        Args:
            fireflies_id: Unique identifier from Fireflies
            title: Meeting title
            date: Meeting date (YYYY-MM-DD)
            participants: List of participant emails
            duration: Duration in minutes

        Returns:
            Dict with 'okf' key containing the OKF metadata structure.
        """
        # Create a node dict compatible with project_okf_block()
        node = {
            "concept_id": f"fireflies-{fireflies_id[:8]}",  # Short unique ID
            "title": title,
            "node_id": f"obsidian::fireflies::{fireflies_id}",  # FEAT-392 convention
            "type": "DOCUMENT",  # Meeting is a document type
            "resource": f"fireflies://transcript/{fireflies_id}",  # Source reference
            "categories": [
                "meeting",
                "fireflies",
                f"date:{date[:7]}",  # YYYY-MM for easy filtering
            ] + (["audio-recorded"] if duration > 0 else []),
            "timestamp": datetime.utcnow().isoformat(),
            "summary": f"Meeting: {title}. Participants: {', '.join(participants[:3])}{'...' if len(participants) > 3 else ''}. Duration: {duration:.1f} minutes.",
            "relates_to": [
                {
                    "target_id": f"fireflies-participant:{email.split('@')[0]}",
                    "type": "MENTIONS",
                }
                for email in participants[:5]  # Limit to 5 participants
            ],
            "source": {
                "uri": f"fireflies://api/transcript/{fireflies_id}",
                "name": "Fireflies.ai",
                "timestamp": date,
            },
        }

        # Generate OKF block using AI-Parrot's deterministic projector
        try:
            okf_yaml = project_okf_block(node, tree_name="fireflies-meetings")
            # Parse the YAML string back to dict
            import yaml

            okf_dict = yaml.safe_load(okf_yaml)
            return okf_dict  # Contains 'okf' key
        except Exception as e:
            logger.warning(f"Failed to generate OKF block: {e}. Skipping OKF metadata.")
            return {}

    @staticmethod
    def _parse_fireflies_response(response_text: str) -> List[Dict[str, Any]]:
        """Parse Fireflies MCP response text into list of transcripts.

        Fireflies returns formatted text like:
        [10]:
          - id: 01KZ...
            title: Meeting Title
            dateString: 2026-08-16T...
            ...
        """
        transcripts = []
        current_transcript = {}
        in_participants = False

        for line in response_text.split("\n"):
            stripped = line.strip()

            # Skip empty lines and headers like [10]:
            if not stripped or stripped.startswith("["):
                in_participants = False
                continue

            # Detect start of new transcript (line starts with "- id:")
            if stripped.startswith("- id:"):
                # Save previous transcript if it has an id
                if current_transcript and "id" in current_transcript:
                    transcripts.append(current_transcript)

                # Parse the id from "- id: 01KZ..."
                current_transcript = {"participants": []}
                try:
                    _, id_value = stripped.split(":", 1)
                    current_transcript["id"] = id_value.strip().strip('"')
                except:
                    pass
                in_participants = False
                continue

            # Check if this is the participants section
            if "participants" in stripped.lower() and stripped.endswith("{"):
                in_participants = True
                continue

            # Collect participants (look for email addresses or names)
            if in_participants and stripped and not stripped.startswith("{") and not stripped.startswith("}"):
                # Line is either "null" or "email@domain.com"
                if "@" in stripped:
                    email = stripped.rstrip(",")
                    if email and email not in current_transcript["participants"]:
                        current_transcript["participants"].append(email)
                continue

            # Parse key-value pairs (indented lines that aren't "- id:")
            if ":" in stripped and not stripped.startswith("-") and not in_participants:
                try:
                    key, value = stripped.split(":", 1)
                    key = key.strip()
                    value = value.strip().strip('"').rstrip(",")

                    # Map Fireflies fields to our transcript format
                    if key == "title":
                        current_transcript["title"] = value
                    elif key == "dateString":
                        # Extract YYYY-MM-DD from ISO format
                        current_transcript["date"] = value[:10]
                    elif key == "organizer_email":
                        current_transcript["organizer"] = value
                        # Also add organizer to participants if not already there
                        if value not in current_transcript.get("participants", []):
                            current_transcript.setdefault("participants", []).append(value)
                    elif key == "duration":
                        try:
                            current_transcript["duration"] = float(value)
                        except ValueError:
                            pass
                except Exception:
                    pass

        # Add last transcript if exists
        if current_transcript and "id" in current_transcript:
            transcripts.append(current_transcript)

        return transcripts

    async def _call_fireflies_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Any:
        """Call a Fireflies MCP tool via tool manager.

        Args:
            tool_name: Fireflies tool name (e.g. 'fireflies_get_transcripts')
            args: Tool arguments

        Returns:
            Tool result (raw from MCP)
        """
        # MCP tools are registered as mcp_fireflies_<tool_name>
        full_name = f"mcp_fireflies_{tool_name}"

        # Get the tool from tool_manager
        tool = self.tool_manager.get_tool(full_name)
        if not tool:
            raise ValueError(f"Tool not found: {full_name}")

        # Execute the tool and return ToolResult
        result = await tool.execute(**args)
        return result

    async def _get_existing_meeting_titles(self) -> set[str]:
        """List all existing meeting notes in vault."""
        try:
            result = await self.obsidian_toolkit.list_notes(
                folder=self.meetings_folder,
                recursive=False,
            )
            # result is a dict with 'notes' key containing list of note dicts
            notes = result.get("notes", []) if isinstance(result, dict) else result or []
            return {note.get("title", "") for note in notes}
        except Exception as e:
            self.logger.warning(f"Failed to list existing notes: {e}")
            return set()

    @staticmethod
    def _make_note_title(date: str, meeting_title: str) -> str:
        """Create note title from date and meeting title.

        Format: YYYY-MM-DD-kebab-case-title
        """
        # Parse date (handle various formats)
        try:
            if isinstance(date, str):
                if "T" in date:
                    date_part = date.split("T")[0]
                else:
                    date_part = date[:10]
            else:
                date_part = datetime.fromisoformat(date).strftime("%Y-%m-%d")
        except:
            date_part = datetime.utcnow().strftime("%Y-%m-%d")

        # Slugify title
        slug = (
            meeting_title.lower()
            .replace(" ", "-")
            .replace("_", "-")
            .replace("/", "-")
            .replace("&", "-")
            .strip("-")
        )

        return f"{date_part}-{slug}"

    @staticmethod
    def _build_analysis_prompt(
        transcript_text: str,
        granularity: str = "standard",
    ) -> str:
        """Build LLM prompt for meeting analysis."""

        depth_instructions = {
            "minimal": "Keep to essential points only. 1-2 sentence summary.",
            "standard": "Balanced coverage. 2-3 paragraph summary with key details.",
            "detailed": "Comprehensive analysis. 4-5 paragraphs with all context.",
        }

        depth = depth_instructions.get(granularity, depth_instructions["standard"])

        return f"""Analyze this meeting transcript and provide a structured analysis.

TRANSCRIPT:
---
{transcript_text}
---

ANALYSIS REQUIREMENTS:

1. **Executive Summary** ({depth})
   - Main topics discussed
   - Key decisions made
   - Overall tone and outcome

2. **Follow-up Questions** (Max 5)
   - What wasn't clarified?
   - What needs discussion?
   - Format as numbered list

3. **Key Insights & Action Items** (Max 5-7)
   - Important takeaways
   - Commitments made
   - Next steps identified
   - Format as bullet points

Please structure your response with clear sections labeled:
## Summary
## Follow-ups
## Insights

Be concise and actionable."""

    @staticmethod
    def _parse_analysis_response(llm_response: AIMessage) -> Dict[str, Any]:
        """Parse LLM response into structured fields."""
        text = llm_response.message if hasattr(llm_response, "message") else str(llm_response)

        # Simple parsing: split by section headers
        summary = ""
        follow_ups = []
        insights = []

        sections = text.split("##")
        for section in sections:
            if "Summary" in section:
                summary = section.replace("Summary", "").strip()
            elif "Follow" in section:
                # Extract numbered list
                lines = section.strip().split("\n")
                for line in lines:
                    stripped = line.strip()
                    # Check if line starts with digit (handles indentation)
                    if stripped and stripped[0].isdigit():
                        follow_ups.append(stripped)
            elif "Insight" in section:
                # Extract bullet points
                lines = section.strip().split("\n")
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("-"):
                        insights.append(stripped)

        return {
            "summary": summary,
            "follow_ups": follow_ups,
            "insights": insights,
        }

    @staticmethod
    def _append_analysis_section(
        transcript: str,
        summary: str,
        follow_ups: List[str],
        insights: List[str],
    ) -> str:
        """Append analysis section to transcript."""

        follow_ups_text = "\n".join(f"- {q}" for q in follow_ups) if follow_ups else "None identified"
        insights_text = "\n".join(f"- {i}" for i in insights) if insights else "None identified"

        analysis = f"""
---

## Analysis (Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')})

### Summary
{summary}

### Follow-ups
{follow_ups_text}

### Key Insights & Action Items
{insights_text}
"""

        return transcript + analysis
