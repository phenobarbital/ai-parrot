"""Fireflies → Obsidian Sync Agent

Syncs meeting transcripts from Fireflies.ai into a local Obsidian vault
under the 'meetings' folder. Supports two operations:

1. sync_fireflies_transcripts() — Deterministic (no LLM): fetch + save
2. summarize_transcript() — LLM-powered: generate summary + follow-ups + insights

The sync operation is safe to schedule every 8 hours via /schedule.
"""
import logging
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Literal, Optional

from navconfig import config
from pydantic import BaseModel, EmailStr, Field

from parrot.bots.agent import BasicAgent
from parrot.interfaces.obsidian.okf import project_okf_block
from parrot.knowledge.okf.ontology import ConceptType, RelationType
from parrot.models.responses import AIMessage
from parrot.tools.obsidian import ObsidianToolkit

#: Leading markdown/ordered list markers the LLM may already have written
#: ("- ", "* ", "1. ", "2) ") — stripped so
#: :meth:`FirefliesObsidianAgent._append_analysis_section` does not render a
#: doubled bullet like ``- 1. ...`` or ``- - ...``.
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*\u2022]\s*|\d+\s*[.)]\s*)+")


def _strip_list_marker(line: str) -> str:
    """Remove leading bullet or numbering from one list item.

    Args:
        line: A single raw list line from the LLM response.

    Returns:
        The item text without its leading marker(s).
    """
    return _LIST_MARKER_RE.sub("", line).strip()
# SourceProvenance


logger = logging.getLogger(__name__)


class FirefliesFilters(BaseModel):
    """Structured, validated filters over the ``fireflies_get_transcripts``
    MCP tool.

    Field names are snake_case; :func:`_filters_to_tool_args` maps them to
    the tool's camelCase parameter names before the call. See
    ``sdd/specs/fireflies-mcp-improvements.spec.md`` §2 (Data Models).
    """

    from_date: Optional[str] = None
    """ISO-8601 date string (e.g. ``"2023-01-01"``) → tool's ``fromDate``."""

    to_date: Optional[str] = None
    """ISO-8601 date string → tool's ``toDate``."""

    keyword: Optional[str] = Field(default=None, max_length=255)
    """Keyword to search for in meeting content."""

    scope: Literal["title", "sentences", "all"] = "all"
    """Keyword-search scope."""

    organizers: List[EmailStr] = Field(default_factory=list)
    """Organizer email addresses to filter by."""

    participants: List[EmailStr] = Field(default_factory=list)
    """Participant email addresses to filter by."""

    mine: Optional[bool] = None
    """Only include meetings owned by the authenticated user."""

    channel_id: Optional[str] = None
    """Raw Fireflies channel/folder ID → tool's ``channelId``. No
    name-to-ID resolution is performed (out of scope)."""


def _filters_to_tool_args(filters: "FirefliesFilters") -> Dict[str, Any]:
    """Map a :class:`FirefliesFilters` instance to ``fireflies_get_transcripts``
    tool arguments.

    Converts snake_case field names to the tool's camelCase parameter names
    and omits any field left at its unset/default value, so the resulting
    dict only carries filters the caller actually specified.

    Args:
        filters: The filters to convert.

    Returns:
        A dict suitable for merging into the ``fireflies_get_transcripts``
        tool-call arguments.
    """
    args: Dict[str, Any] = {}
    if filters.from_date is not None:
        args["fromDate"] = filters.from_date
    if filters.to_date is not None:
        args["toDate"] = filters.to_date
    if filters.keyword is not None:
        args["keyword"] = filters.keyword
    if filters.scope != "all":
        args["scope"] = filters.scope
    if filters.organizers:
        args["organizers"] = [str(email) for email in filters.organizers]
    if filters.participants:
        args["participants"] = [str(email) for email in filters.participants]
    if filters.mine is not None:
        args["mine"] = filters.mine
    if filters.channel_id is not None:
        args["channelId"] = filters.channel_id
    return args


def _merge_filters(
    default: Optional["FirefliesFilters"],
    call: Optional["FirefliesFilters"],
) -> Optional["FirefliesFilters"]:
    """Merge agent-level default filters with a per-call override.

    Per-call fields win wherever the caller explicitly set them; the
    agent's ``default_filters`` fills in any field the call left at its
    model-default (unset) value. Field-by-field, never whole-object — see
    ``sdd/specs/fireflies-mcp-improvements.spec.md`` §7 Known Risks.

    Args:
        default: The agent's standing ``default_filters`` (may be ``None``).
        call: The per-call ``filters`` argument (may be ``None``).

    Returns:
        The merged filters, or ``None`` if both inputs are ``None``.
    """
    if default is None and call is None:
        return None
    if default is None:
        return call
    if call is None:
        return default

    merged = default.model_dump()
    call_explicit = call.model_dump(exclude_defaults=True)
    merged.update(call_explicit)
    return FirefliesFilters(**merged)


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

    #: Heading written by :meth:`_append_analysis_section`; also the marker
    #: used to detect notes that were already summarized.
    ANALYSIS_HEADING: str = "## Analysis"

    def __init__(
        self,
        name: str = "FirefliesObsidianSync",
        vault_path: Optional[str | Path] = None,
        fireflies_token: Optional[str] = None,
        meetings_folder: str = "meetings",
        default_filters: Optional["FirefliesFilters"] = None,
        **kwargs,
    ):
        """Initialize the Fireflies→Obsidian sync agent.

        Args:
            name: Agent name
            vault_path: Path to Obsidian vault (e.g. ~/vaults/notes)
            fireflies_token: Fireflies.ai API token (if None, will prompt)
            meetings_folder: Subfolder in vault to store meetings (default: 'meetings')
            default_filters: Standing :class:`FirefliesFilters` scope applied
                to every :meth:`sync_fireflies_transcripts` call (e.g. for a
                scheduled daemon). Per-call ``filters`` override this
                field-by-field — see :func:`_merge_filters`.
            **kwargs: Forwarded to Agent.__init__()
        """
        super().__init__(name=name, **kwargs)

        if vault_path:
            self.vault_path = Path(vault_path)
        else:
            # Fall back to OBSIDIAN_VAULT_PATH from navconfig/env, then ~/vaults/notes
            env_vault = config.get("OBSIDIAN_VAULT_PATH") or os.getenv("OBSIDIAN_VAULT_PATH")
            self.vault_path = Path(env_vault) if env_vault else Path.home() / "vaults" / "notes"
        self.fireflies_token = fireflies_token
        self.meetings_folder = meetings_folder
        self.default_filters = default_filters

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

    async def configure(self, app=None) -> None:
        """Async setup: register Obsidian toolkit and Fireflies MCP tools.

        The ObsidianToolkit is instantiated in ``__init__`` but must be
        registered with the ``ToolManager`` so the LLM can discover and
        invoke its tools.  Fireflies MCP is also initialized eagerly here
        (instead of lazily in ``sync_fireflies_transcripts``) so the LLM
        can answer free-text questions about meetings.
        """
        await super().configure(app)

        # --- Register Obsidian toolkit tools with ToolManager ---
        self._initialize_tools([self.obsidian_toolkit])
        self.logger.info(
            "Registered ObsidianToolkit tools: %s",
            [t.name for t in self.obsidian_toolkit.get_tools()],
        )

        # --- Eagerly init Fireflies MCP so tools are available to the LLM ---
        try:
            await self._ensure_fireflies_mcp()
        except Exception as exc:
            # Warning-only: agent should still boot without Fireflies
            self.logger.warning(
                "Fireflies MCP not available (agent will work without "
                "Fireflies tools): %s", exc,
            )

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
        filters: Optional["FirefliesFilters"] = None,
    ) -> Dict[str, Any]:
        """Fetch latest Fireflies transcripts and save to Obsidian.

        **Deterministic**: No LLM involved, safe to schedule every 8 hours.

        ``limit`` is the **total** number of transcripts desired across all
        pages, not a page size — the underlying ``fireflies_get_transcripts``
        tool caps a single call at 50, so any ``limit > 50`` is satisfied by
        multiple internal calls (``skip=0,50,100,…``) until either ``limit``
        is reached or the API returns a short/exhausted page.

        **No pagination ceiling is enforced.** A broad or unfiltered
        ``limit``/``filters`` combination against a large Fireflies account
        can issue many sequential tool calls in one invocation — this is an
        accepted, explicit design choice (see
        ``sdd/specs/fireflies-mcp-improvements.spec.md`` §7 Known Risks), not
        a bug. Scope ``filters``/``limit`` accordingly for large accounts.

        Args:
            limit: Max transcripts to fetch, total across all pages (default: 10)
            skip_existing: Skip transcripts already in vault (default: True)
            filters: Optional :class:`FirefliesFilters` to scope which
                meetings are fetched (date range, keyword/scope,
                organizer/participant emails, mine-only, channel). Merged
                with ``self.default_filters`` — per-call fields here win over
                the agent's default on the same field (see
                :func:`_merge_filters`).

        Returns:
            Dict with:
            - status: 'ok' | 'error'
            - synced: number of new transcripts saved
            - skipped: number of transcripts already in the vault
            - notes: list of note titles created by this run (feed these to
              :meth:`summarize_transcript`)
            - errors: list of error messages
            - timestamp: ISO-8601 sync time
        """
        report = {
            "status": "ok",
            "synced": 0,
            "skipped": 0,
            "notes": [],
            "errors": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            await self._ensure_fireflies_mcp()

            effective_filters = _merge_filters(self.default_filters, filters)
            filter_args = (
                _filters_to_tool_args(effective_filters) if effective_filters else {}
            )

            # Fetch transcripts, paginating transparently past the tool's
            # 50-per-call cap until `limit` is reached or the API is
            # exhausted. `limit` means "total across all pages."
            self.logger.info(f"Fetching latest {limit} Fireflies transcripts...")
            transcripts: List[Dict[str, Any]] = []
            skip = 0
            while len(transcripts) < limit:
                page_limit = min(50, limit - len(transcripts))
                if page_limit <= 0:
                    break
                try:
                    tool_result = await self._call_fireflies_tool(
                        "fireflies_get_transcripts",
                        {**filter_args, "limit": page_limit, "skip": skip},
                    )
                except Exception as e:
                    report["errors"].append(
                        f"Page fetch failed (skip={skip}): {e}"
                    )
                    self.logger.error(
                        f"Fireflies page fetch failed (skip={skip}): {e}"
                    )
                    break

                if not tool_result or not tool_result.success:
                    self.logger.info("No transcripts found or API error")
                    break

                self.logger.debug(
                    f"Fireflies API response: {tool_result.result[:200]}..."
                )
                page = self._parse_fireflies_response(tool_result.result)
                transcripts.extend(page)
                if len(page) < page_limit:
                    break  # API exhausted — fewer results than requested
                skip += page_limit

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
                    report["notes"].append(note_title)
                    report["synced"] += 1

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

            # Drop any previous Analysis block so a re-analysis replaces it
            # instead of stacking a second one, and so the LLM sees the raw
            # transcript rather than its own earlier summary.
            transcript_text = self._strip_analysis_section(note.get("content", ""))

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

    async def summarize_pending_transcripts(
        self,
        note_titles: Optional[List[str]] = None,
        granularity: str = "standard",
        limit: Optional[int] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """LLM-powered: summarize every meeting note that has no analysis yet.

        Wraps :meth:`summarize_transcript` over a set of notes instead of a
        single one, so a sync that brought in N meetings produces N summaries.

        Args:
            note_titles: Explicit notes to consider (e.g. ``report['notes']``
                from :meth:`sync_fireflies_transcripts`). When None, the whole
                meetings folder is scanned.
            granularity: 'minimal' | 'standard' | 'detailed'.
            limit: Max notes to analyze in this run (None = no limit). Useful
                to bound LLM cost when catching up on a backlog.
            force: Re-analyze notes that already carry an Analysis section.

        Returns:
            Dict with:
            - status: 'ok' | 'error'
            - analyzed: list of note titles that got a fresh analysis
            - skipped: list of note titles already analyzed
            - errors: list of ``{'note': title, 'error': msg}`` entries
        """
        outcome: Dict[str, Any] = {
            "status": "ok",
            "analyzed": [],
            "skipped": [],
            "errors": [],
        }

        try:
            if note_titles is None:
                candidates = sorted(await self._get_existing_meeting_titles())
            else:
                candidates = list(note_titles)

            if not candidates:
                self.logger.info("No meeting notes to analyze.")
                return outcome

            for note_title in candidates:
                if limit is not None and len(outcome["analyzed"]) >= limit:
                    self.logger.info(
                        "Analysis limit reached (%s); %s note(s) left for the "
                        "next run.",
                        limit,
                        len(candidates) - len(outcome["analyzed"])
                        - len(outcome["skipped"]) - len(outcome["errors"]),
                    )
                    break

                if not force and await self._has_analysis(note_title):
                    self.logger.debug("Already analyzed, skipping: %s", note_title)
                    outcome["skipped"].append(note_title)
                    continue

                analysis = await self.summarize_transcript(
                    note_title=note_title,
                    granularity=granularity,
                )
                if analysis.get("status") == "ok":
                    outcome["analyzed"].append(note_title)
                else:
                    outcome["errors"].append({
                        "note": note_title,
                        "error": analysis.get("error", "unknown error"),
                    })

            if outcome["errors"]:
                outcome["status"] = "partial"

        except Exception as e:
            outcome["status"] = "error"
            outcome["errors"].append({"note": None, "error": str(e)})
            self.logger.error(f"Batch summarization failed: {e}", exc_info=True)

        return outcome

    @classmethod
    def _strip_analysis_section(cls, content: str) -> str:
        """Remove a previously generated Analysis block from a note body.

        :meth:`_append_analysis_section` appends ``\n---\n\n## Analysis ...``
        to the transcript, so re-analyzing a note must cut that block off
        first — otherwise the note accumulates one Analysis section per run.

        Args:
            content: Full note body, with or without an Analysis block.

        Returns:
            The transcript with any Analysis block (and its preceding ``---``
            separator) removed.
        """
        head, sep, _ = content.partition(cls.ANALYSIS_HEADING)
        if not sep:
            return content
        # Drop the '---' separator emitted just before the heading.
        return head.rstrip().removesuffix("---").rstrip()

    async def _has_analysis(self, note_title: str) -> bool:
        """Whether a meeting note already carries a generated Analysis section.

        Args:
            note_title: Note title (file stem) inside the meetings folder.

        Returns:
            True when the note body contains the ``## Analysis`` heading
            written by :meth:`_append_analysis_section`.
        """
        try:
            note = await self.obsidian_toolkit.read_note(
                path=f"{self.meetings_folder}/{note_title}",
            )
        except Exception as e:  # noqa: BLE001 — missing/unreadable note
            self.logger.warning(f"Could not read {note_title}: {e}")
            return False

        content = (note or {}).get("content", "") or ""
        return self.ANALYSIS_HEADING in content

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
            "type": ConceptType.DOCUMENT_NODE.value,  # Meeting is a document
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
                    "concept": f"fireflies-participant:{email.split('@')[0]}",
                    "rel": RelationType.MENTIONS.value,
                }
                for email in participants[:5]  # Limit to 5 participants
            ],
            "source": {
                "document": f"fireflies-{fireflies_id[:8]}.transcript",
                "url": f"fireflies://api/transcript/{fireflies_id}",
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
        """List all existing meeting notes in vault.

        ``list_notes()`` returns :class:`VaultFileInfo` descriptors
        (path/name/size/mtime) — there is **no** ``title`` key — so the note
        title is derived from the file stem, which is exactly what
        :meth:`_make_note_title` produced when the note was created.

        Returns:
            Set of note titles (file stems, without the ``.md`` suffix).
        """
        try:
            result = await self.obsidian_toolkit.list_notes(
                folder=self.meetings_folder,
                recursive=False,
            )
            # result is a dict with 'notes' key containing VaultFileInfo dicts
            notes = result.get("notes", []) if isinstance(result, dict) else result or []
            titles: set[str] = set()
            for note in notes:
                if not isinstance(note, dict):
                    continue
                # Prefer an explicit title when a backend supplies one,
                # otherwise fall back to the file stem.
                name = note.get("title") or note.get("name") or note.get("path") or ""
                if not name:
                    continue
                stem = PurePosixPath(str(name)).stem
                if stem:
                    titles.add(stem)
            return titles
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
                        follow_ups.append(_strip_list_marker(stripped))
            elif "Insight" in section:
                # Extract bullet points
                lines = section.strip().split("\n")
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("-"):
                        insights.append(_strip_list_marker(stripped))

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

{FirefliesObsidianAgent.ANALYSIS_HEADING} (Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')})

### Summary
{summary}

### Follow-ups
{follow_ups_text}

### Key Insights & Action Items
{insights_text}
"""

        return transcript + analysis
