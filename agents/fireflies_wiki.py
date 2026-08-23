"""FirefliesWikiAgent — autonomous meeting sync, wiki publication, and digests.

Extends :class:`~parrot.agents.obsidian.FirefliesObsidianAgent` with three
scheduled operations:

- ``sync_meetings_to_wiki``      — daily 07:00: Fireflies → Obsidian →
  summarize → GraphIndex LLM Wiki.
- ``email_daily_meeting_digest`` — daily 08:00: bullet summary of the last
  24h of meetings, emailed to the daily recipients.
- ``email_weekly_insights``      — Monday 09:00: cross-meeting insights over
  the previous week, emailed to the weekly recipients — intended as the
  agenda input for the weekly meeting.

The parent class already owns transcript fetching (Fireflies MCP), note
authoring (``ObsidianToolkit``), per-meeting LLM analysis, and the
``YYYY-MM-DD-slug`` note-title convention. This subclass adds only the wiki
plane, the Anthropic/Haiku client pin, and the three scheduled methods.

LLM: pinned to Claude Haiku 4.5 through the project's ``AbstractClient``
abstraction (never the Anthropic SDK directly). All three jobs are
semi-mechanical — condensing already-written ``## Analysis`` blocks into
bullets — so the cheapest capable model is the right one.

NOTE: This file lives in ``agents/``, which is gitignored. Commit with
``git add -f`` (same situation as agents/security_advisor.py).

See ``docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from navconfig import config

from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
#
# Read at import time on purpose: ``@schedule`` evaluates its arguments at
# decoration time, so the trigger values must be module-level constants.
# Same constraint that makes agents/security_advisor.py use _ADVISORY_HOUR.
# ---------------------------------------------------------------------------

def _int_env(key: str, default: int) -> int:
    """Read an integer setting, falling back when unset or unparseable.

    Args:
        key: navconfig / environment variable name.
        default: Value used when the variable is missing or not an int.

    Returns:
        The parsed integer, or ``default``.
    """
    raw = config.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(
            "%s=%r is not an integer — falling back to %s", key, raw, default
        )
        return default


def _bool_env(key: str, default: bool = False) -> bool:
    """Read a boolean setting from a truthy string.

    Args:
        key: navconfig / environment variable name.
        default: Value used when the variable is missing.

    Returns:
        ``True`` when the value is one of ``1/true/yes/on`` (case-insensitive).
    """
    raw = config.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _list_env(key: str) -> List[str]:
    """Read a comma-separated list setting.

    Args:
        key: navconfig / environment variable name.

    Returns:
        List of stripped, non-empty entries (empty list when unset).
    """
    raw = config.get(key)
    if not raw:
        return []
    return [item.strip() for item in str(raw).split(",") if item.strip()]


#: Timezone applied to all three cron triggers.
_TZ: str = config.get("FIREFLIES_WIKI_TZ", fallback="UTC")


def _schedule_tzinfo() -> timezone | ZoneInfo:
    """Resolve :data:`_TZ` to a tzinfo, falling back to UTC.

    The digest windows must be computed in the SAME timezone the cron
    triggers fire in. Computing "today" in UTC while the job fires at
    08:00 Asia/Tokyo would select the previous day's meetings — the
    window would be silently shifted by one day.

    Returns:
        A ``ZoneInfo`` for :data:`_TZ`, or ``timezone.utc`` when the name
        is unknown (missing tzdata, typo).
    """
    try:
        return ZoneInfo(_TZ)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning(
            "FIREFLIES_WIKI_TZ=%r is not a known timezone — using UTC.", _TZ
        )
        return timezone.utc

#: Daily sync (Fireflies → Obsidian → wiki).
_SYNC_HOUR: int = _int_env("FIREFLIES_WIKI_SYNC_HOUR", 7)
_SYNC_MINUTE: int = _int_env("FIREFLIES_WIKI_SYNC_MINUTE", 0)

#: Daily digest email.
_DIGEST_HOUR: int = _int_env("FIREFLIES_WIKI_DIGEST_HOUR", 8)
_DIGEST_MINUTE: int = _int_env("FIREFLIES_WIKI_DIGEST_MINUTE", 0)

#: Weekly insights email.
_WEEKLY_DAY: str = config.get("FIREFLIES_WIKI_WEEKLY_DAY", fallback="mon")
_WEEKLY_HOUR: int = _int_env("FIREFLIES_WIKI_WEEKLY_HOUR", 9)
_WEEKLY_MINUTE: int = _int_env("FIREFLIES_WIKI_WEEKLY_MINUTE", 0)

#: Claude Haiku 4.5 — cheap and fast, ample 200K context for a week of
#: meeting analyses. Resolved through LLMFactory ("anthropic" → AnthropicClient).
_DEFAULT_LLM: str = "anthropic:claude-haiku-4-5"
_LLM: str = config.get("FIREFLIES_WIKI_LLM", fallback=_DEFAULT_LLM)

#: Wiki plane.
_WIKI_NAME: str = config.get("FIREFLIES_WIKI_NAME", fallback="meetings")
_WIKI_STORAGE_DIR: str = config.get(
    "FIREFLIES_WIKI_STORAGE_DIR",
    fallback=str(Path.home() / ".parrot" / "wikis" / "meetings"),
)
_EXTRACT_ENTITIES: bool = _bool_env("FIREFLIES_WIKI_EXTRACT_ENTITIES", False)

#: Run bounds.
_SYNC_LIMIT: int = _int_env("FIREFLIES_WIKI_SYNC_LIMIT", 20)
_ANALYSIS_LIMIT: int = _int_env("FIREFLIES_WIKI_ANALYSIS_LIMIT", 20)
_DAILY_WINDOW_DAYS: int = _int_env("FIREFLIES_WIKI_DAILY_WINDOW_DAYS", 1)
_WEEKLY_WINDOW_DAYS: int = _int_env("FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS", 7)


@register_agent(name="fireflies_wiki", at_startup=True)
class FirefliesWikiAgent(FirefliesObsidianAgent):
    """Fireflies → Obsidian → LLM Wiki agent with scheduled email digests.

    Attributes:
        wiki_name: Target wiki identifier for ingestion.
        wiki_storage_dir: Root directory of the wiki's storage planes.
        daily_recipients: Addresses for the 08:00 digest.
        weekly_recipients: Addresses for the Monday insights email.

    Example::

        agent = FirefliesWikiAgent(vault_path="~/vaults/notes")
        await agent.configure()
        await agent.sync_meetings_to_wiki()
        await agent.email_daily_meeting_digest()
    """

    def __init__(
        self,
        name: str = "FirefliesWiki",
        wiki_name: Optional[str] = None,
        wiki_storage_dir: Optional[str | Path] = None,
        daily_recipients: Optional[List[str]] = None,
        weekly_recipients: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the agent.

        Args:
            name: Agent name.
            wiki_name: Target wiki identifier. Defaults to ``FIREFLIES_WIKI_NAME``.
            wiki_storage_dir: Wiki storage root. Defaults to
                ``FIREFLIES_WIKI_STORAGE_DIR``.
            daily_recipients: Daily digest addresses. Defaults to
                ``FIREFLIES_WIKI_DAILY_RECIPIENTS``.
            weekly_recipients: Weekly insights addresses. Defaults to
                ``FIREFLIES_WIKI_WEEKLY_RECIPIENTS``.
            **kwargs: Forwarded to :class:`FirefliesObsidianAgent`. ``llm``
                defaults to Claude Haiku 4.5 when the caller does not pin one.
        """
        kwargs.setdefault("llm", _LLM)
        super().__init__(name=name, **kwargs)

        self.wiki_name: str = wiki_name or _WIKI_NAME
        self.wiki_storage_dir: Path = Path(
            wiki_storage_dir or _WIKI_STORAGE_DIR
        ).expanduser()
        self.daily_recipients: List[str] = (
            daily_recipients
            if daily_recipients is not None
            else _list_env("FIREFLIES_WIKI_DAILY_RECIPIENTS")
        )
        self.weekly_recipients: List[str] = (
            weekly_recipients
            if weekly_recipients is not None
            else _list_env("FIREFLIES_WIKI_WEEKLY_RECIPIENTS")
        )

        #: Set in :meth:`configure`; ``None`` when the wiki plane is unavailable.
        self._wiki: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def configure(self, app=None) -> None:
        """Configure the parent agent, then build the LLM Wiki plane.

        The wiki plane is strictly best-effort: any failure leaves
        ``self._wiki`` as ``None``, logs a warning, and lets the agent boot.
        Meetings still reach the Obsidian vault in that state.

        Args:
            app: Optional aiohttp application, forwarded to the parent.
        """
        await super().configure(app)
        self._wiki = await self._build_wiki_toolkit()

    async def _build_wiki_toolkit(self) -> Optional[Any]:
        """Construct the ``LLMWikiToolkit`` backing meeting ingestion.

        Wires a PageIndex authoring plane and a persistent GraphIndex plane.
        The GraphIndex toolkit is what makes ``ingest_obsidian_vault``'s
        Phase 1b (Obsidian ``[[wikilink]]`` → graph nodes/edges) actually
        write — passing ``None`` silently skips the graph bridge.

        Returns:
            A wired ``LLMWikiToolkit``, or ``None`` when construction fails.
        """
        try:
            from parrot.knowledge.graphindex.factory import (
                build_graph_memory_toolkit,
            )
            from parrot.knowledge.wiki.models import WikiConfig
            from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

            storage = self.wiki_storage_dir
            storage.mkdir(parents=True, exist_ok=True)

            pageindex_toolkit = self._build_pageindex_toolkit(storage)
            graph_toolkit = await build_graph_memory_toolkit(
                storage / "graph",
                tenant_id=self.wiki_name,
                agent_id=self.name,
            )

            wiki_config = WikiConfig(
                wiki_name=self.wiki_name,
                storage_dir=storage,
                sync_graph=True,
            )
            toolkit = LLMWikiToolkit(
                pageindex_toolkit,
                graph_toolkit,
                None,
                wiki_config,
                agent_id=self.name,
            )
            self.logger.info(
                "LLMWikiToolkit ready (wiki=%s, storage=%s, pageindex=%s)",
                self.wiki_name,
                storage,
                "on" if pageindex_toolkit is not None else "off",
            )
            return toolkit
        except Exception as exc:  # noqa: BLE001 — wiki ingest is best-effort
            self.logger.warning(
                "LLMWikiToolkit unavailable (%s); meetings will sync to "
                "Obsidian only.",
                exc,
            )
            return None

    def _build_pageindex_toolkit(self, storage: Path) -> Optional[Any]:
        """Build the PageIndex authoring plane for the wiki.

        Uses ``WIKI_MODEL`` (the spec ``wikitoolkit ingest`` already uses),
        falling back to this agent's own LLM so a deployment that configures
        only ``FIREFLIES_WIKI_LLM`` still gets an authoring plane instead of
        degrading to retrieval-only.

        Args:
            storage: The wiki's storage root.

        Returns:
            A ``PageIndexToolkit``, or ``None`` when construction fails.
        """
        model_spec = config.get("WIKI_MODEL") or _LLM
        try:
            from parrot.clients.factory import LLMFactory
            from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
            from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

            _, model_id = LLMFactory.parse_llm_string(model_spec)
            adapter = PageIndexLLMAdapter(
                LLMFactory.create(model_spec), model=model_id
            )
            pageindex_dir = storage / "pageindex"
            pageindex_dir.mkdir(parents=True, exist_ok=True)
            return PageIndexToolkit(adapter, storage_dir=pageindex_dir)
        except Exception as exc:  # noqa: BLE001 — authoring plane is optional
            self.logger.warning(
                "PageIndexToolkit unavailable (%s); wiki pages will be written "
                "to the retrieval plane only.",
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Scheduled operation 1 — daily 07:00
    # ------------------------------------------------------------------

    @schedule(
        schedule_type=ScheduleType.CRON,
        hour=_SYNC_HOUR,
        minute=_SYNC_MINUTE,
        timezone=_TZ,
    )
    async def sync_meetings_to_wiki(
        self,
        limit: Optional[int] = None,
        analysis_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Sync the latest transcripts, summarize them, and publish to the wiki.

        Runs three steps in a load-bearing order:

        1. Fetch new Fireflies transcripts into the Obsidian vault.
        2. Summarize every note lacking an ``## Analysis`` section.
        3. Incrementally ingest the vault into the GraphIndex LLM Wiki.

        Summarizing *before* the ingest means each published wiki page carries
        the transcript **and** its summary in one pass, and guarantees the
        08:00 digest finds its input already written.

        Never raises — a scheduled job that throws produces noise and no
        diagnosis.

        Args:
            limit: Max transcripts to fetch. Defaults to
                ``FIREFLIES_WIKI_SYNC_LIMIT``.
            analysis_limit: Max notes to summarize. Defaults to
                ``FIREFLIES_WIKI_ANALYSIS_LIMIT``.

        Returns:
            Dict with ``status``, ``sync``, ``analysis``, ``wiki`` and
            ``timestamp`` keys.
        """
        report: Dict[str, Any] = {
            "status": "ok",
            "sync": None,
            "analysis": None,
            "wiki": {"ingested": False, "reason": None},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # --- Step 1: Fireflies → Obsidian -------------------------------
            report["sync"] = await self.sync_fireflies_transcripts(
                limit=limit if limit is not None else _SYNC_LIMIT,
                skip_existing=True,
            )

            # --- Step 2: per-meeting LLM analysis ---------------------------
            report["analysis"] = await self.summarize_pending_transcripts(
                granularity="standard",
                limit=(
                    analysis_limit
                    if analysis_limit is not None
                    else _ANALYSIS_LIMIT
                ),
            )

            # --- Step 3: Obsidian → GraphIndex LLM Wiki ---------------------
            report["wiki"] = await self._ingest_vault_into_wiki()

            if report["sync"].get("status") == "error":
                report["status"] = "partial"

        except Exception as exc:  # noqa: BLE001 — scheduled job must not raise
            report["status"] = "error"
            report["error"] = str(exc)
            self.logger.error("Meeting sync failed: %s", exc, exc_info=True)

        return report

    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]:
        """Incrementally ingest the Obsidian vault into the LLM Wiki.

        Returns:
            Dict with ``ingested`` (bool), ``reason`` (str or None) and, on
            success, the toolkit's phase ``report``.
        """
        if self._wiki is None:
            self.logger.warning(
                "Wiki plane unavailable — skipping ingest for this run."
            )
            return {"ingested": False, "reason": "wiki toolkit unavailable"}

        # G6 — scope the nightly ingest to the meetings subfolder only, so
        # unrelated vault notes (e.g. audio-notes/) never bleed into the
        # meetings wiki. ingest_obsidian_vault has no folder-filter
        # parameter; narrowing is done by passing the subdirectory itself.
        meetings_path = self.vault_path / self.meetings_folder

        try:
            if not meetings_path.is_dir():
                reason = f"meetings folder not found: {meetings_path}"
                self.logger.warning(reason)
                return {"ingested": False, "reason": reason}

            self.logger.info("Ingesting vault path into wiki: %s", meetings_path)
            result = await self._wiki.ingest_obsidian_vault(
                self.wiki_name,
                str(meetings_path),
                incremental=True,
                extract_entities=_EXTRACT_ENTITIES,
            )
            self.logger.info("Wiki ingest complete for %s", self.wiki_name)
            return {"ingested": True, "reason": None, "report": result}
        except Exception as exc:  # noqa: BLE001 — ingest must not fail the sync
            self.logger.warning("Wiki ingest failed: %s", exc)
            return {"ingested": False, "reason": str(exc)}

    # ------------------------------------------------------------------
    # Scheduled operation 2 — daily 08:00
    # ------------------------------------------------------------------

    @schedule(
        schedule_type=ScheduleType.CRON,
        hour=_DIGEST_HOUR,
        minute=_DIGEST_MINUTE,
        timezone=_TZ,
    )
    async def email_daily_meeting_digest(
        self,
        days: Optional[int] = None,
        recipients: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Email a consolidated bullet summary of the latest meetings.

        Reuses the ``## Analysis`` sections written by the 07:00 job rather
        than re-reading raw transcripts, so the per-meeting LLM cost is paid
        once per day.

        Never raises.

        Args:
            days: Lookback window. Defaults to
                ``FIREFLIES_WIKI_DAILY_WINDOW_DAYS``.
            recipients: Override the configured daily recipients.

        Returns:
            Dict with ``status``, ``emailed``, ``meetings`` and optionally
            ``reason`` / ``error``.
        """
        window = days if days is not None else _DAILY_WINDOW_DAYS
        return await self._run_digest(
            window_days=window,
            recipients=recipients if recipients is not None else self.daily_recipients,
            subject_prefix="Daily Meeting Digest",
            prompt_builder=self._build_daily_digest_prompt,
            job="daily digest",
        )

    # ------------------------------------------------------------------
    # Scheduled operation 3 — Monday 09:00
    # ------------------------------------------------------------------

    @schedule(
        schedule_type=ScheduleType.CRON,
        day_of_week=_WEEKLY_DAY,
        hour=_WEEKLY_HOUR,
        minute=_WEEKLY_MINUTE,
        timezone=_TZ,
    )
    async def email_weekly_insights(
        self,
        days: Optional[int] = None,
        recipients: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Email cross-meeting insights over the previous week.

        Framed as agenda input for the weekly meeting: recurring themes,
        decisions taken, unresolved issues, risks, and follow-ups.

        Never raises.

        Args:
            days: Lookback window. Defaults to
                ``FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS``.
            recipients: Override the configured weekly recipients.

        Returns:
            Dict with ``status``, ``emailed``, ``meetings`` and optionally
            ``reason`` / ``error``.
        """
        window = days if days is not None else _WEEKLY_WINDOW_DAYS
        return await self._run_digest(
            window_days=window,
            recipients=(
                recipients if recipients is not None else self.weekly_recipients
            ),
            subject_prefix="Weekly Meeting Insights",
            prompt_builder=self._build_weekly_insights_prompt,
            job="weekly insights",
        )

    # ------------------------------------------------------------------
    # Shared digest machinery
    # ------------------------------------------------------------------

    async def _run_digest(
        self,
        window_days: int,
        recipients: List[str],
        subject_prefix: str,
        prompt_builder: Any,
        job: str,
    ) -> Dict[str, Any]:
        """Collect analyses over a window, condense them, and email the result.

        Args:
            window_days: Lookback window in days.
            recipients: Email recipients.
            subject_prefix: Human-readable subject prefix.
            prompt_builder: Callable ``(analyses) -> str`` building the prompt.
            job: Short job label used in log messages.

        Returns:
            Dict with ``status``, ``emailed``, ``meetings`` and optionally
            ``reason`` / ``error``.
        """
        outcome: Dict[str, Any] = {
            "status": "ok",
            "emailed": False,
            "meetings": 0,
            "reason": None,
        }

        try:
            titles = await self._notes_in_window(window_days)
            analyses = await self._collect_analyses(titles)
            outcome["meetings"] = len(analyses)

            if not analyses:
                outcome["reason"] = "no meetings"
                self.logger.info(
                    "No analyzed meetings in the last %s day(s) — skipping %s.",
                    window_days,
                    job,
                )
                return outcome

            if not recipients:
                outcome["reason"] = "no recipients configured"
                self.logger.warning(
                    "No recipients configured for %s — nothing sent.", job
                )
                return outcome

            body = await self._ask_llm(prompt_builder(analyses))
            subject = (
                f"{subject_prefix} — "
                f"{datetime.now(_schedule_tzinfo()).strftime('%Y-%m-%d')} "
                f"({len(analyses)} meeting{'s' if len(analyses) != 1 else ''})"
            )
            outcome["emailed"] = await self._email(subject, body, recipients)
            if not outcome["emailed"]:
                outcome["status"] = "partial"
                outcome["reason"] = "email delivery failed"

        except Exception as exc:  # noqa: BLE001 — scheduled job must not raise
            outcome["status"] = "error"
            outcome["error"] = str(exc)
            self.logger.error("%s failed: %s", job, exc, exc_info=True)

        return outcome

    async def _notes_in_window(
        self, days: int, now: Optional[datetime] = None
    ) -> List[str]:
        """List meeting-note titles whose date prefix falls inside a window.

        Note titles are ``YYYY-MM-DD-slug`` (see
        :meth:`FirefliesObsidianAgent._make_note_title`), so the window filter
        is a cheap prefix comparison — the vault is listed, but no note bodies
        are read.

        The window is inclusive at both ends: a note dated exactly ``days``
        ago is included, as is one dated today.

        Args:
            days: Window size in days, counting back from ``now``.
            now: Reference time (defaults to now, UTC). Injectable for tests.

        Returns:
            Sorted note titles inside the window. Titles without a parseable
            ``YYYY-MM-DD`` prefix are ignored rather than raising.
        """
        reference = (now or datetime.now(_schedule_tzinfo())).date()
        cutoff = reference - timedelta(days=days)

        selected: List[str] = []
        for title in await self._get_existing_meeting_titles():
            try:
                note_date = datetime.strptime(title[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                self.logger.debug("Ignoring note without date prefix: %s", title)
                continue
            if cutoff <= note_date <= reference:
                selected.append(title)
        return sorted(selected)

    async def _collect_analyses(self, titles: List[str]) -> List[Dict[str, str]]:
        """Read notes and extract their generated ``## Analysis`` sections.

        Args:
            titles: Note titles (file stems) inside the meetings folder.

        Returns:
            List of ``{"note": title, "analysis": text}`` for notes that carry
            an Analysis section. Notes without one, or that cannot be read,
            are skipped with a debug/warning log.
        """
        collected: List[Dict[str, str]] = []
        for title in titles:
            try:
                note = await self.obsidian_toolkit.read_note(
                    path=f"{self.meetings_folder}/{title}",
                )
            except Exception as exc:  # noqa: BLE001 — one bad note must not stop the digest
                self.logger.warning("Could not read %s: %s", title, exc)
                continue

            content = (note or {}).get("content", "") or ""
            _, sep, analysis = content.partition(self.ANALYSIS_HEADING)
            if not sep:
                self.logger.debug("No analysis section in %s — skipping.", title)
                continue
            analysis = analysis.strip()
            if analysis:
                collected.append({"note": title, "analysis": analysis})
        return collected

    async def _ask_llm(self, prompt: str) -> str:
        """Send a single-shot prompt to the configured client.

        Args:
            prompt: Fully rendered prompt text.

        Returns:
            The model's reply as plain text.
        """
        response = await self.client.complete(prompt)
        if hasattr(response, "message"):
            return str(response.message)
        return str(response)

    async def _email(
        self, subject: str, body: str, recipients: List[str]
    ) -> bool:
        """Send one email; returns a success flag.

        ``send_notification`` swallows provider errors and reports them as
        ``{"status": "error", ...}`` instead of raising, so the returned
        status must be inspected — a bare ``await`` always "succeeds".

        Args:
            subject: Email subject line.
            body: Email body text.
            recipients: Destination addresses.

        Returns:
            ``True`` only when the provider reported success.
        """
        try:
            result = await self.send_notification(
                message=body,
                recipients=recipients,
                provider="email",
                subject=subject,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Could not send %r: %s", subject, exc)
            return False

        status = (result or {}).get("status")
        if status != "success":
            self.logger.error(
                "Could not send %r: %s", subject, (result or {}).get("error", result)
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _render_analyses(analyses: List[Dict[str, str]]) -> str:
        """Render collected analyses as a labelled block for the LLM.

        Args:
            analyses: Entries from :meth:`_collect_analyses`.

        Returns:
            One ``### <note>`` section per meeting.
        """
        return "\n\n".join(
            f"### {entry['note']}\n{entry['analysis']}" for entry in analyses
        )

    @classmethod
    def _build_daily_digest_prompt(cls, analyses: List[Dict[str, str]]) -> str:
        """Build the prompt for the daily bullet digest.

        Args:
            analyses: Entries from :meth:`_collect_analyses`.

        Returns:
            The rendered prompt.
        """
        return (
            "You are preparing a short daily briefing for a busy team.\n\n"
            "Below are the analyses of the most recent meetings. Produce a "
            "single consolidated bullet summary.\n\n"
            "Rules:\n"
            "- Use flat markdown bullets ('- '), no numbering, no headings.\n"
            "- Group related points; do not repeat the same point twice.\n"
            "- Name the meeting in parentheses at the end of a bullet when it "
            "matters, e.g. '(Quarterly Planning)'.\n"
            "- Lead with decisions and action items, then notable discussion.\n"
            "- Be concrete. Omit filler such as 'the team discussed various "
            "topics'.\n"
            "- Aim for 5-12 bullets total.\n\n"
            f"Meeting analyses:\n\n{cls._render_analyses(analyses)}"
        )

    @classmethod
    def _build_weekly_insights_prompt(cls, analyses: List[Dict[str, str]]) -> str:
        """Build the prompt for the weekly insights email.

        Args:
            analyses: Entries from :meth:`_collect_analyses`.

        Returns:
            The rendered prompt.
        """
        return (
            "You are preparing the agenda input for a weekly team meeting.\n\n"
            "Below are the analyses of every meeting from the past week. "
            "Produce a bullet list of insights worth raising.\n\n"
            "Rules:\n"
            "- Use flat markdown bullets ('- '), grouped under these exact "
            "headings, omitting any heading with no content:\n"
            "  Recurring themes / Decisions taken / Open and unresolved issues "
            "/ Risks / Follow-ups to raise\n"
            "- Prioritise items that span MORE THAN ONE meeting — that is the "
            "point of a weekly view.\n"
            "- For an unresolved issue, say what is blocking it and who raised "
            "it if the analyses make that clear.\n"
            "- Do not restate a single meeting's minutes; synthesise across "
            "them.\n"
            "- Be concrete and brief. No preamble, no closing summary.\n\n"
            f"Meeting analyses:\n\n{cls._render_analyses(analyses)}"
        )
