"""FirefliesInsightsAgent — Fireflies meetings to wiki inbox, insights, Telegram and Jira (FEAT-715)."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from navconfig import config
from pydantic import BaseModel, Field

from parrot.agents.conf import FIREFLIES_REGISTRY_DIR, FIREFLIES_SYNC_OVERLAP_DAYS
from parrot.agents.meeting_registry import MeetingRegistry, fingerprint
from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.bots.agent import Agent
from parrot.conf import AGENTS_DIR
from parrot.integrations.telegram import telegram_command
from parrot.integrations.telegram.context import get_current_telegram_chat_id
from parrot.knowledge.wiki.project import find_project_root, load_effective_config
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.models.responses import InvokeResult
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

    _TELEGRAM_MAX_MESSAGE = 4096
    _TELEGRAM_PART_RESERVE = 32
    _INSIGHTS_SYSTEM_PROMPT = (
        "You extract decisions, risks/blockers and action items from a meeting. "
        "Quote evidence verbatim from the transcript. Never invent owners or dates."
    )
    APPROVAL_TTL = timedelta(hours=72)
    JIRA_TEMPLATE = "fireflies/action_item"

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
        self._state_lock = asyncio.Lock()

    async def configure(self, app=None) -> None:
        """Resolve the inbox dir and load file-only skills (S6)."""
        await super().configure(app)
        await self._configure_skill_file_registry()
        root = self.wiki_root or find_project_root()
        if root is None:
            raise ValueError("FirefliesInsightsAgent needs wiki_root= or a configured wiki project")
        wiki_config = load_effective_config(root).config
        self.inbox_dir = wiki_config.inbox_path(root)
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
            # Gate — must succeed for either path to proceed
            try:
                meeting = await self._gate_meeting(item, report)
                if meeting is None:
                    continue
            except Exception as exc:
                self.logger.error("FirefliesInsights: gate %s failed: %s", item.get("id"), exc)
                report.errors.append(f"{item.get('id')}: {exc}")
                continue
            processed.append(meeting)
            # Path 1: Drop to inbox (independent of insights — AC9/G6)
            try:
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
            except Exception as exc:  # noqa: BLE001 — AC9: drop failure must not block insights
                self.logger.error("FirefliesInsights: drop %s failed: %s", meeting.fireflies_id, exc)
                report.errors.append(f"drop {meeting.fireflies_id}: {exc}")
            # Path 2: Generate insights and notify (independent of drop — AC9/G6)
            try:
                insights = await self.generate_insights(
                    meeting.transcript,
                    meeting.summary,
                    {
                        "fireflies_id": meeting.fireflies_id,
                        "title": meeting.title,
                        "date": meeting.meeting_date,
                    },
                )
                delivery = await self.notify_insights(insights)
                sent = delivery.get("sent", 0)
                report.insights_sent += int(sent > 0)
                if self.registry.available:
                    if sent > 0 and not delivery.get("errors"):
                        await self.registry.mark_analyzed(meeting.fireflies_id, meeting.fingerprint)
                    else:
                        await self.registry.mark_analysis_failed(
                            meeting.fireflies_id,
                            f"delivery incomplete: sent={sent} errors={delivery.get('errors', [])}",
                        )
            except Exception as exc:  # noqa: BLE001 — G6: insights never block ingestion
                self.logger.error("FirefliesInsights: insights for %s failed: %s", meeting.fireflies_id, exc)
                report.errors.append(f"insights {meeting.fireflies_id}: {exc}")
                if self.registry.available:
                    await self.registry.mark_analysis_failed(meeting.fireflies_id, str(exc))
        return report

    async def generate_insights(self, transcript: str, summary: str, meta: dict[str, Any]) -> MeetingInsights:
        """Generate validated insights while isolating per-meeting working memory."""
        if self._llm is None:
            raise RuntimeError("FirefliesInsightsAgent has no LLM client configured")
        meeting_id = str(meta["fireflies_id"])
        keys = (f"meeting:{meeting_id}:transcript", f"meeting:{meeting_id}:summary")
        try:
            if self.working_memory is not None:
                await self.working_memory.store_result(keys[0], transcript)
                await self.working_memory.store_result(keys[1], summary)
            prompt = (
                f"Meeting title: {meta.get('title', '')}\n"
                f"Meeting date: {meta.get('date', '')}\n\n"
                f"Fireflies summary:\n{summary}\n\n"
                f"Transcript:\n{transcript}"
            )
            result: InvokeResult = await self._llm.invoke(
                prompt,
                output_type=MeetingInsights,
                system_prompt=self._INSIGHTS_SYSTEM_PROMPT,
            )
            if not isinstance(result.output, MeetingInsights):
                raise ValueError("LLM did not return a valid MeetingInsights result")
            return result.output
        finally:
            if self.working_memory is not None:
                for key in keys:
                    await self.working_memory.drop_stored(key)

    def _format_insights_message(self, insights: MeetingInsights) -> str:
        """Render Telegram HTML with every insight interpolation escaped."""
        title = html.escape(insights.meeting_title)
        meeting_date = html.escape(insights.meeting_date)
        lines = [f"<b>{title}</b> · {meeting_date}"]
        if insights.decisions:
            lines.extend(["", "<b>Decisions</b>"])
            lines.extend(f"{index}. {html.escape(decision)}" for index, decision in enumerate(insights.decisions, 1))
        if insights.risks:
            lines.extend(["", "<b>Risks</b>"])
            lines.extend(f"{index}. {html.escape(risk)}" for index, risk in enumerate(insights.risks, 1))
        if insights.action_items:
            lines.extend(["", "<b>Action items</b>"])
            for index, item in enumerate(insights.action_items, 1):
                details = []
                if item.owner:
                    details.append(f"owner: {html.escape(item.owner)}")
                if item.due_date:
                    details.append(f"due: {html.escape(item.due_date)}")
                suffix = f" — {'; '.join(details)}" if details else ""
                lines.append(f"{index}. {html.escape(item.title)}{suffix}")
                lines.append(f"   Evidence: {html.escape(item.evidence)}")
        return "\n".join(lines)

    def _chunk_message(self, text: str) -> list[str]:
        """Split text on line boundaries; word-split lines that exceed the budget.

        Word-boundary splitting avoids cutting inside HTML entities (``&amp;``)
        or tags, which would cause Telegram ``parse_mode="HTML"`` errors.
        """
        budget = self._TELEGRAM_MAX_MESSAGE - self._TELEGRAM_PART_RESERVE
        pieces: list[str] = []
        for line in text.splitlines(keepends=True):
            while len(line) > budget:
                # Find the last space within budget to split at a word boundary
                split_at = line.rfind(" ", 0, budget)
                if split_at <= 0:
                    # No space found — fall back to hard split as a last resort
                    split_at = budget
                pieces.append(line[:split_at])
                line = line[split_at:].lstrip(" ")
            if line:
                pieces.append(line)
        if not pieces:
            pieces = [""]

        chunks = [pieces[0]]
        for piece in pieces[1:]:
            if len(chunks[-1]) + len(piece) <= budget:
                chunks[-1] += piece
            else:
                chunks.append(piece)
        if len(chunks) == 1:
            return chunks
        total = len(chunks)
        return [f"(part {part}/{total})\n{chunk}" for part, chunk in enumerate(chunks, 1)]

    def set_wrapper(self, wrapper: Any) -> None:
        """Attach the Telegram wrapper for proactive delivery."""
        self._wrapper = wrapper

    def _get_telegram_bot(self) -> Any:
        """Return the wrapper's aiogram bot, or ``None``."""
        return getattr(self._wrapper, "bot", None) if self._wrapper is not None else None

    @property
    def _state_path(self) -> Path:
        """Return the durable Fireflies insight approval state location."""
        return Path(FIREFLIES_REGISTRY_DIR).expanduser() / "fireflies_insights_state.json"

    def _load_state(self) -> dict[str, Any]:
        """Load approvals and insights, treating absent or corrupt state as empty."""
        try:
            with self._state_path.open(encoding="utf-8") as state_file:
                state = json.load(state_file)
            if not isinstance(state, dict):
                raise ValueError("state root is not an object")
            state.setdefault("approvals", {})
            state.setdefault("insights", {})
            return state
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            if not isinstance(exc, FileNotFoundError):
                self.logger.warning("FirefliesInsights: corrupt approval state ignored: %s", exc)
            return {"approvals": {}, "insights": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        """Atomically persist approvals and insights to the registry directory."""
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.tmp"
        temporary.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        os.replace(temporary, path)

    def _prune_expired_approvals(self, state: dict[str, Any]) -> None:
        """Remove expired approvals that never created a ticket, plus orphaned insights."""
        approvals = state.get("approvals", {})
        now = datetime.now(timezone.utc)
        expired_ids = []
        for aid, raw in approvals.items():
            if raw.get("created_ticket") is not None:
                continue
            try:
                if datetime.fromisoformat(raw["expires_at"]) <= now:
                    expired_ids.append(aid)
            except (KeyError, ValueError, TypeError):
                expired_ids.append(aid)
        for aid in expired_ids:
            del approvals[aid]
        insights_store = state.get("insights", {})
        referenced = {raw.get("fireflies_id") for raw in approvals.values()}
        orphaned = [mid for mid in insights_store if mid not in referenced]
        for mid in orphaned:
            del insights_store[mid]

    async def _register_approvals(self, insights: MeetingInsights, chat_id: str) -> list[PendingApproval]:
        """Persist stable, chat-bound approvals for every reported action item.

        Pending approvals of the same meeting that the fresh report no longer
        lists are invalidated, so re-analysing a revised meeting cannot leave two
        confirmable ids for one action item; approvals that already created a
        ticket are kept as the idempotence record.
        """
        state = await asyncio.to_thread(self._load_state)
        self._prune_expired_approvals(state)
        approvals = state.setdefault("approvals", {})
        superseded = {
            insight_id
            for insight_id, raw in approvals.items()
            if raw.get("fireflies_id") == insights.meeting_id and not raw.get("created_ticket")
        }
        state.setdefault("insights", {})[insights.meeting_id] = insights.model_dump(mode="json")
        registered: list[PendingApproval] = []
        expires_at = (datetime.now(timezone.utc) + self.APPROVAL_TTL).isoformat()
        for index, item in enumerate(insights.action_items):
            insight_id = hashlib.sha256(f"{insights.meeting_id}:{index}:{item.title}".encode()).hexdigest()[:12]
            superseded.discard(insight_id)
            existing = approvals.get(insight_id)
            if existing is not None:
                approval = PendingApproval.model_validate(existing)
                if approval.created_ticket:
                    registered.append(approval)
                    continue
            approval = PendingApproval(
                insight_id=insight_id,
                fireflies_id=insights.meeting_id,
                action_index=index,
                chat_id=str(chat_id),
                expires_at=expires_at,
                created_ticket=approval.created_ticket if existing is not None else None,
            )
            approvals[insight_id] = approval.model_dump(mode="json")
            registered.append(approval)
        for insight_id in superseded:
            del approvals[insight_id]
        await asyncio.to_thread(self._save_state, state)
        return registered

    async def notify_insights(self, insights: MeetingInsights) -> dict[str, Any]:
        """Send insights to the public channel without propagating send failures."""
        bot = self._get_telegram_bot()
        if bot is None:
            return {"sent": 0, "reason": "no telegram wrapper"}
        if not self.public_channel_id:
            return {"sent": 0, "reason": "no public_channel_id configured"}
        text = self._format_insights_message(insights)
        approvals = await self._register_approvals(insights, str(self.public_channel_id))
        if approvals:
            lines = [
                f"/fireflies_ticket {approval.insight_id} — "
                f"{html.escape(insights.action_items[approval.action_index].title)}"
                for approval in approvals
            ]
            text = text + "\n\n<b>Open a Jira ticket</b>\n" + "\n".join(lines)
        sent = 0
        errors = []
        for chunk in self._chunk_message(text):
            try:
                await bot.send_message(
                    chat_id=self.public_channel_id,
                    text=chunk,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("FirefliesInsights: send to chat %s failed: %s", self.public_channel_id, exc)
                errors.append(f"{self.public_channel_id}: {exc}")
        return {"sent": sent, "errors": errors, "chat_id": self.public_channel_id}

    @telegram_command(
        "fireflies_ticket", description="Create a Jira ticket from a reported action item", parse_mode="raw"
    )
    async def cmd_create_ticket(self, text: str = "") -> str:
        """Create one Jira ticket only after an authorized human confirmation."""
        insight_id = text.strip()
        async with self._state_lock:
            state = await asyncio.to_thread(self._load_state)
            raw = state.get("approvals", {}).get(insight_id)
            if raw is None:
                return f"Unknown insight id: {insight_id or '(none)'}"
            approval = PendingApproval.model_validate(raw)
            # Authorize before revealing existing ticket info (S2)
            chat_id = get_current_telegram_chat_id()
            now = datetime.now(timezone.utc)
            try:
                expired = datetime.fromisoformat(approval.expires_at) <= now
            except ValueError:
                expired = True
            if not await self._authorize(approval, chat_id):
                if expired:
                    return "Confirmation expired"
                return "Confirmation refused: not the reporting chat"
            if approval.created_ticket:
                return f"Already created: {approval.created_ticket}"
            try:
                insights = MeetingInsights.model_validate(state["insights"][approval.fireflies_id])
                item = insights.action_items[approval.action_index]
            except (IndexError, KeyError, TypeError, ValueError):
                return "Insight details are no longer available"
            result = await self._create_ticket(insights, item)
            if not result.get("ok"):
                return f"Jira ticket creation failed: {result.get('error', 'unknown error')}"
            ticket_key = result.get("key")
            if not ticket_key:
                return "Jira ticket creation failed: Jira returned no ticket key"
            approval.created_ticket = str(ticket_key)
            state["approvals"][insight_id] = approval.model_dump(mode="json")
            await asyncio.to_thread(self._save_state, state)
            return f"Created {ticket_key}"

    async def _authorize(self, approval: PendingApproval, chat_id: str | None) -> bool:
        """Require the reporting chat and an unexpired approval.

        Authorization is chat-level only: the Telegram context exposes the chat
        id but not the confirming user, so any member of the reporting chat may
        confirm an action item reported there.
        """
        try:
            expires_at = datetime.fromisoformat(approval.expires_at)
        except ValueError:
            return False
        return str(chat_id) == approval.chat_id and expires_at > datetime.now(timezone.utc)

    #: Jira wiki-markup delimiters that open macros (``{quote}``) and links (``[...]``).
    _JIRA_MARKUP_RE = re.compile(r"([{}\[\]])")

    @classmethod
    def _jira_text(cls, value: str | None) -> str | None:
        """Backslash-escape macro and link delimiters so transcript text cannot break the template."""
        if value is None:
            return None
        return cls._JIRA_MARKUP_RE.sub(r"\\\1", value)

    async def _create_ticket(self, insights: MeetingInsights, item: ActionItem) -> dict[str, Any]:
        """Create an action-item issue through the configured Jira template.

        Every LLM-derived field is escaped with :meth:`_jira_text` before it
        reaches the wiki-markup template; identifiers and the backlink are not.
        """
        if self.jira_toolkit is None:
            return {"ok": False, "error": "Jira is not configured"}
        params = {
            "meeting_title": self._jira_text(insights.meeting_title),
            "meeting_date": self._jira_text(insights.meeting_date),
            "meeting_id": insights.meeting_id,
            "action_title": self._jira_text(item.title),
            "owner": self._jira_text(item.owner),
            "due_date": self._jira_text(item.due_date),
            "evidence": self._jira_text(item.evidence),
            "decisions": [self._jira_text(decision) for decision in insights.decisions],
            "risks": [self._jira_text(risk) for risk in insights.risks],
            "wiki_url": await self._wiki_backlink(insights.meeting_id),
        }
        return await self.jira_toolkit.jira_create_issue(
            summary=f"[{insights.meeting_title}] {item.title}"[:250],
            template=self.JIRA_TEMPLATE,
            template_params=params,
            labels=["fireflies", f"meeting-{insights.meeting_id}"],
        )

    async def _wiki_backlink(self, fireflies_id: str) -> str | None:
        """Return a best-effort wiki source link for a Fireflies meeting."""
        try:
            wiki_root = self.wiki_root
            if wiki_root is None:
                return None
            wiki_config = load_effective_config(wiki_root).config
            if wiki_config.backend not in {"sqlite", "json"}:
                return None
            storage = wiki_config.storage_path(wiki_root)
            sources = SourceCollectionManager(
                storage / "sources",
                db_path=storage / "wiki.db",
                backend=wiki_config.backend,
                busy_timeout=wiki_config.sqlite_busy_timeout,
            )
            entry = await asyncio.to_thread(sources.find_by_external_id, f"fireflies:{fireflies_id}")
            return entry.source_uri if entry is not None else None
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("FirefliesInsights: backlink for %s unavailable: %s", fireflies_id, exc)
            return None

    @telegram_command("fireflies_sync", description="Fetch and report the latest meetings", parse_mode="raw")
    async def cmd_sync(self, text: str = "") -> str:
        """Run an on-demand sync; a numeric argument overrides the default limit."""
        chat_id = get_current_telegram_chat_id()
        if self.public_channel_id and str(chat_id) != str(self.public_channel_id):
            return "Sync refused: not the configured channel"
        limit = min(int(text), 200) if text.strip().isdigit() else 10
        report = await self.sync_meetings(limit=limit)
        return (
            f"Fireflies: fetched={report.fetched} skipped={report.skipped} "
            f"dropped={report.dropped_to_inbox} sent={report.insights_sent} errors={len(report.errors)}"
        )

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
