"""FirefliesInsightsAgent — Fireflies meetings to wiki inbox, insights, Telegram and Jira (FEAT-715).

This module starts with the data contracts shared by the ingestion path and the
insight path. The agent class is added by later tasks of the same feature.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from navconfig import config
from pydantic import BaseModel, Field

from parrot.agents.conf import FIREFLIES_REGISTRY_DIR, FIREFLIES_SYNC_OVERLAP_DAYS
from parrot.agents.meeting_registry import MeetingRegistry, fingerprint
from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.bots.agent import Agent
from parrot.conf import AGENTS_DIR
from parrot.knowledge.wiki.project import find_project_root, load_effective_config
from parrot.registry import register_agent
from parrot.skills.mixin import SkillRegistryMixin
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot_tools.jiratoolkit import JiraToolkit

#: Telegram chat identifier. GitHubReviewer defines the same alias locally
#: (bots/github_reviewer.py:88); it is not importable from a shared module.
ChatId = int | str


class FirefliesMeeting(BaseModel):
    """One meeting's raw inputs, carried by both the ingestion and the insight paths.

    ``sync_fireflies_transcripts`` returns a report dict rather than these fields,
    so the agent owns its own fetch and builds this model from it.
    """

    fireflies_id: str
    title: str
    meeting_date: str
    transcript: str
    summary: str = ""
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    fingerprint: str
    summary_fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionItem(BaseModel):
    """One actionable commitment extracted from a meeting."""

    title: str
    owner: str | None = None
    due_date: str | None = None
    evidence: str


class MeetingInsights(BaseModel):
    """Structured insight set for one meeting; the LLM ``output_type``."""

    meeting_id: str
    meeting_title: str
    meeting_date: str
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)


class PendingApproval(BaseModel):
    """One outstanding Telegram confirmation for turning an action item into a ticket.

    ``telegram_command`` only attaches slash-command metadata and carries no
    approval state, so this feature owns the protocol explicitly.
    """

    insight_id: str
    fireflies_id: str
    action_index: int
    chat_id: str
    user_id: str | None = None
    expires_at: str
    created_ticket: str | None = None


class InsightRunReport(BaseModel):
    """Outcome of one agent run; never raised into a scheduler."""

    fetched: int = 0
    skipped: int = 0
    dropped_to_inbox: int = 0
    insights_sent: int = 0
    errors: list[str] = Field(default_factory=list)


@register_agent(name="fireflies_insights")
class FirefliesInsightsAgent(SkillRegistryMixin, Agent):
    """Fireflies meetings → wiki inbox + insights → Telegram → Jira (FEAT-715)."""

    #: S6 — never build the DB-backed registry at AGENTS_DIR/{agent_id}/skills.
    enable_skill_registry: bool = False
    #: Absolute, so discovery does not depend on the launch directory.
    skill_paths: list[Path] = [AGENTS_DIR / "fireflies_insights" / "skills"]

    def __init__(
        self,
        name: str = "FirefliesInsights",
        *,
        fireflies_token: str | None = None,
        wiki_root: str | Path | None = None,
        public_channel_id: ChatId | None = None,
        jira_templates_dir: str | Path | None = None,
        jira_project: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind configuration; nothing touches the network until configure()."""
        super().__init__(name=name, **kwargs)
        self.fireflies_token = fireflies_token
        self.wiki_root = Path(wiki_root).expanduser() if wiki_root else None
        self.public_channel_id = public_channel_id
        self.jira_templates_dir = (
            Path(jira_templates_dir).expanduser()
            if jira_templates_dir
            else AGENTS_DIR / "fireflies_insights" / "templates"
        )
        self.jira_project = jira_project
        self.inbox_dir: Path | None = None
        self.registry = MeetingRegistry(Path(FIREFLIES_REGISTRY_DIR).expanduser())
        self.working_memory: WorkingMemoryToolkit | None = None
        self.jira_toolkit: JiraToolkit | None = None
        self._wrapper: Any = None
        self._mcp_fireflies_initialized = False

    async def configure(self, app=None) -> None:
        """Resolve the inbox dir and load file-only skills (S6)."""
        await super().configure(app)
        await self._configure_skill_file_registry()
        root = self.wiki_root or find_project_root()
        if root is None:
            raise ValueError("FirefliesInsightsAgent needs wiki_root= or a configured wiki project")
        config = load_effective_config(root).config
        self.inbox_dir = config.inbox_path(root)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_root = root

    async def post_configure(self) -> None:
        """Wire WorkingMemoryToolkit and JiraToolkit once self.app exists."""
        await super().post_configure()
        self.working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-meetings")
        self.jira_toolkit = self._build_jira_toolkit()
        for toolkit in (self.working_memory, self.jira_toolkit):
            if toolkit is not None:
                self.tool_manager.register_toolkit(toolkit)

    def _build_jira_toolkit(self) -> JiraToolkit | None:
        """Build JiraToolkit like GitHubReviewer does; None (logged) on failure."""
        try:
            auth_type = (config.get("JIRA_AUTH_TYPE") or "").lower()
            if auth_type == "oauth2_3lo":
                self.logger.error(
                    "FirefliesInsightsAgent: per-user OAuth2 3LO is not supported; "
                    "falling back to service-account basic_auth."
                )
                auth_type = ""

            effective = auth_type or "basic_auth"
            toolkit_kwargs: dict[str, Any] = {
                "server_url": config.get("JIRA_INSTANCE"),
                "auth_type": effective,
                "templates_dir": self.jira_templates_dir,
                "default_project": self.jira_project,
            }
            if effective == "basic_auth":
                username = config.get("JIRA_USERNAME")
                password = config.get("JIRA_API_TOKEN")
                if not (username and password):
                    self.logger.error(
                        "FirefliesInsightsAgent: basic_auth requires JIRA_USERNAME and "
                        "JIRA_API_TOKEN; Jira integration disabled."
                    )
                    return None
                toolkit_kwargs["username"] = username
                toolkit_kwargs["password"] = password
            elif effective == "token_auth":
                token = config.get("JIRA_SECRET_TOKEN") or config.get("JIRA_API_TOKEN")
                if not token:
                    self.logger.error(
                        "FirefliesInsightsAgent: token_auth requires JIRA_SECRET_TOKEN or "
                        "JIRA_API_TOKEN; Jira integration disabled."
                    )
                    return None
                toolkit_kwargs["token"] = token
            return JiraToolkit(**toolkit_kwargs)
        except Exception as exc:
            self.logger.error("FirefliesInsightsAgent: failed to initialize Jira integration: %s", exc)
            return None

    async def _ensure_fireflies_mcp(self) -> None:
        """Lazy MCP init; api_key → FIREFLIES_API_KEY → ValueError."""
        if self._mcp_fireflies_initialized:
            return
        token = self.fireflies_token
        if not token:
            token = config.get("FIREFLIES_API_KEY") or os.getenv("FIREFLIES_API_KEY")
        if not token:
            raise ValueError(
                "Fireflies token required. Set via fireflies_token= or "
                "FIREFLIES_API_KEY environment variable (loaded via navconfig)."
            )
        try:
            tools = await self.add_fireflies_mcp_server(api_key=token)
            self.logger.info("Fireflies MCP initialized with tools: %s", tools)
            self._mcp_fireflies_initialized = True
        except Exception as exc:
            self.logger.error("Failed to initialize Fireflies MCP: %s", exc)
            raise

    async def _call_fireflies_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Call an MCP Fireflies tool through the tool manager."""
        tool = self.tool_manager.get_tool(f"mcp_fireflies_{tool_name}")
        if not tool:
            raise ValueError(f"Tool not found: mcp_fireflies_{tool_name}")
        return await tool.execute(**args)

    async def _fetch_listing(self, limit: int, from_date: str | None = None) -> list[dict[str, Any]]:
        """Page through Fireflies transcripts; ``limit`` is total, with ≤50 per call."""
        transcripts: list[dict[str, Any]] = []
        skip = 0
        while len(transcripts) < limit:
            page_limit = min(50, limit - len(transcripts))
            if page_limit <= 0:
                break
            args: dict[str, Any] = {"limit": page_limit, "skip": skip}
            if from_date:
                args["fromDate"] = from_date
            try:
                result = await self._call_fireflies_tool("fireflies_get_transcripts", args)
            except Exception as exc:
                self.logger.warning("Fireflies listing fetch failed (skip=%d): %s", skip, exc)
                break
            if not result or not getattr(result, "success", False):
                break
            page = FirefliesObsidianAgent._parse_fireflies_response(result.result)
            transcripts.extend(page)
            if len(page) < page_limit:
                break
            skip += page_limit
        return transcripts

    async def _fetch_transcript(self, fireflies_id: str) -> str:
        """Return full transcript text for one meeting."""
        result = await self._call_fireflies_tool("fireflies_get_transcript", {"transcriptId": fireflies_id})
        return result.result if hasattr(result, "result") else str(result)

    async def _fetch_summary(self, fireflies_id: str) -> str | None:
        """Return Fireflies' native summary, or ``None`` without raising."""
        try:
            result = await self._call_fireflies_tool("fireflies_get_summary", {"transcriptId": fireflies_id})
            if result and getattr(result, "success", False):
                return result.result if hasattr(result, "result") else str(result)
            self.logger.warning("Fireflies summary unavailable for %s", fireflies_id)
        except Exception as exc:
            self.logger.warning("Fireflies summary fetch failed for %s: %s", fireflies_id, exc)
        return None

    _SLUG_RE = re.compile(r"[^a-z0-9]+")

    def _inbox_filename(self, meeting: FirefliesMeeting) -> str:
        """Return the stable inbox filename for a meeting."""
        slug = self._SLUG_RE.sub("-", meeting.title.lower()).strip("-")[:60] or "meeting"
        return f"{meeting.meeting_date[:10]}-{slug}-{meeting.fireflies_id}.md"

    @staticmethod
    def _yaml_scalar(value: object) -> str:
        """Return a safely quoted YAML scalar without requiring a YAML emitter."""
        text = str(value).replace("\r", " ").replace("\n", " ")
        return f"'{text.replace(chr(39), chr(39) * 2)}'"

    def _render_inbox_document(self, meeting: FirefliesMeeting) -> str:
        """Render markdown with the Fireflies external identity in frontmatter."""
        participants = (
            "\n".join(f"  - {self._yaml_scalar(participant)}" for participant in meeting.participants)
            if meeting.participants
            else "[]"
        )
        sections = [
            "---",
            f"fireflies_id: {self._yaml_scalar(meeting.fireflies_id)}",
            f"title: {self._yaml_scalar(meeting.title)}",
            f"date: {self._yaml_scalar(meeting.meeting_date)}",
            f"participants: {participants}",
            "---",
            "",
        ]
        if meeting.summary:
            sections.extend(["## Fireflies Summary", "", meeting.summary.strip(), ""])
        sections.extend(["## Transcript", "", meeting.transcript.strip(), ""])
        return "\n".join(sections)

    def _drop_to_inbox(self, meeting: FirefliesMeeting) -> Path:
        """Write a dot-prefixed temporary file and atomically replace the final path."""
        if self.inbox_dir is None:
            raise RuntimeError("configure() must run before _drop_to_inbox()")
        final = self.inbox_dir / self._inbox_filename(meeting)
        tmp = self.inbox_dir / f".{final.name}.tmp"
        tmp.write_text(self._render_inbox_document(meeting), encoding="utf-8")
        os.replace(tmp, final)
        return final

    async def sync_meetings(self, limit: int = 10) -> InsightRunReport:
        """Fetch, gate on MeetingRegistry, and atomically drop meetings without raising."""
        report = InsightRunReport()
        processed: list[FirefliesMeeting] = []
        try:
            await self._ensure_fireflies_mcp()
            from_date = None
            if self.registry.available:
                from_date = await self.registry.suggest_from_date(overlap_days=FIREFLIES_SYNC_OVERLAP_DAYS)
            listing = await self._fetch_listing(limit, from_date)
        except Exception as exc:
            report.errors.append(f"fireflies sync: {exc}")
            return report
        report.fetched = len(listing)
        for item in listing:
            try:
                meeting = await self._gate_meeting(item, report)
                if meeting is None:
                    continue
                path = await asyncio.to_thread(self._drop_to_inbox, meeting)
                report.dropped_to_inbox += 1
                if self.registry.available:
                    await self.registry.record_synced(
                        fireflies_id=meeting.fireflies_id,
                        note_path=path,
                        title=meeting.title,
                        meeting_date=meeting.meeting_date,
                        participants=meeting.participants,
                        duration_minutes=meeting.duration_minutes,
                        fingerprint=meeting.fingerprint,
                        summary_fingerprint=meeting.summary_fingerprint,
                        reset_analysis=meeting.metadata.get("classification") == "revise",
                    )
            except Exception as exc:
                self.logger.error("FirefliesInsights: meeting %s failed: %s", item.get("id"), exc)
                report.errors.append(f"{item.get('id')}: {exc}")
                continue
            processed.append(meeting)
        return report

    async def _gate_meeting(self, item: dict[str, Any], report: InsightRunReport) -> FirefliesMeeting | None:
        """Classify an item and return its populated meeting unless it should be skipped."""
        fireflies_id = str(item["id"])
        title = str(item.get("title") or "Untitled Meeting")
        meeting_date = str(item.get("date") or "")
        participants = [str(participant) for participant in item.get("participants") or []]
        duration_minutes = float(item.get("duration") or 0.0)
        transcript_cache: dict[str, str] = {}
        summary_cache: dict[str, str] = {}

        async def fetch_transcript(transcript_id: str) -> str:
            if transcript_id not in transcript_cache:
                transcript_cache[transcript_id] = await self._fetch_transcript(transcript_id)
            return transcript_cache[transcript_id]

        async def fetch_summary(transcript_id: str) -> str | None:
            if transcript_id not in summary_cache:
                summary = await self._fetch_summary(transcript_id)
                summary_cache[transcript_id] = summary or ""
            return summary_cache[transcript_id] or None

        if self.registry.available:
            classified = await self.registry.classify(
                item,
                fetch=fetch_transcript,
                fetch_summary=fetch_summary,
            )
            if classified.action == "skip":
                report.skipped += 1
                return None
            transcript = classified.fetched_text or await fetch_transcript(fireflies_id)
            summary = summary_cache.get(fireflies_id, "")
            transcript_fingerprint = classified.fingerprint or fingerprint(transcript)
            summary_fingerprint = classified.summary_fingerprint
            classification = classified.action
        else:
            candidate = FirefliesMeeting(
                fireflies_id=fireflies_id,
                title=title,
                meeting_date=meeting_date,
                transcript="",
                participants=participants,
                duration_minutes=duration_minutes,
                fingerprint="",
            )
            if self.inbox_dir is not None and (self.inbox_dir / self._inbox_filename(candidate)).exists():
                report.skipped += 1
                return None
            transcript = await fetch_transcript(fireflies_id)
            summary = (await fetch_summary(fireflies_id)) or ""
            transcript_fingerprint = fingerprint(transcript)
            summary_fingerprint = fingerprint(summary) if summary else None
            classification = "create"

        return FirefliesMeeting(
            fireflies_id=fireflies_id,
            title=title,
            meeting_date=meeting_date,
            transcript=transcript,
            summary=summary,
            participants=participants,
            duration_minutes=duration_minutes,
            fingerprint=transcript_fingerprint,
            summary_fingerprint=summary_fingerprint,
            metadata={"classification": classification},
        )
