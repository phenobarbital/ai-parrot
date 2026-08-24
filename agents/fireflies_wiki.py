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

See ``docs/superpowers/specs/2026-08-23-fireflies-wiki-agent-design.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from parrot.agents.conf import (
    AUDIO_NOTES_FOLDER,
    AUDIO_NOTES_WIKI_NAME,
    AUDIO_NOTES_WIKI_STORAGE_DIR,
    FIREFLIES_WIKI_ANALYSIS_LIMIT,
    FIREFLIES_WIKI_DAILY_RECIPIENTS,
    FIREFLIES_WIKI_DAILY_WINDOW_DAYS,
    FIREFLIES_WIKI_DIGEST_HOUR,
    FIREFLIES_WIKI_DIGEST_MINUTE,
    FIREFLIES_WIKI_EXTRACT_ENTITIES,
    FIREFLIES_WIKI_LLM,
    FIREFLIES_WIKI_NAME,
    FIREFLIES_WIKI_STORAGE_DIR,
    FIREFLIES_WIKI_SYNC_HOUR,
    FIREFLIES_WIKI_SYNC_LIMIT,
    FIREFLIES_WIKI_SYNC_MINUTE,
    FIREFLIES_WIKI_TZ,
    FIREFLIES_WIKI_WEEKLY_DAY,
    FIREFLIES_WIKI_WEEKLY_HOUR,
    FIREFLIES_WIKI_WEEKLY_MINUTE,
    FIREFLIES_WIKI_WEEKLY_RECIPIENTS,
    FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS,
    WIKI_MODEL,
    schedule_tzinfo,
)
from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.integrations.telegram.context import get_current_telegram_chat_id
from parrot.integrations.telegram.decorators import telegram_command

# ``AudioNoteResult`` / ``AudioNoteStructure`` are re-exported unused:
# the toolkit and its models moved to ``parrot_tools.audio_note_capture``
# when they were extracted from this file, and this keeps the old import
# path (``agents.fireflies_wiki.AudioNoteResult``) working.
from parrot_tools.audio_note_capture import (  # noqa: F401
    AudioNoteCaptureToolkit,
    AudioNoteResult,
    AudioNoteStructure,
)

from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
#
# Every environment-backed setting lives in ``parrot.agents.conf`` (next to
# FirefliesObsidianAgent), resolved there at import time through navconfig's
# typed accessors. Import time is not incidental: ``@schedule`` evaluates its
# arguments at decoration time, so the trigger values must already be plain
# module-level constants.
# ---------------------------------------------------------------------------

#: FEAT-452, Module 4 — best-effort system-prompt guidance nudging the LLM
#: toward ``capture_audio_note`` on capture intent (the tool's own docstring
#: is the primary, verified guidance mechanism for tool-selection; this is
#: supplementary). Folded into ``instructions`` -> ``self.goal`` — the
#: sanctioned free-text extension point on ``BasicAgent.__init__``.
_AUDIO_NOTE_TOOL_GUIDANCE: str = (
    "When the user is recording something to REMEMBER — a note, idea, "
    "decision, reminder or follow-up ('note to self...', 'remember "
    "that...', 'idea:...') rather than asking a question, call the "
    "capture_audio_note tool instead of answering. This applies whether "
    "the message arrived as a transcribed voice note or as typed text."
)


@register_agent(name="fireflies_wiki", at_startup=True)
class FirefliesWikiAgent(FirefliesObsidianAgent):
    """Fireflies → Obsidian → LLM Wiki agent with scheduled email digests.

    Attributes:
        wiki_name: Target wiki identifier for ingestion.
        wiki_storage_dir: Root directory of the wiki's storage planes.
        daily_recipients: Addresses for the 08:00 digest.
        weekly_recipients: Addresses for the Monday insights email.
        notes_wiki_name: Identifier for the separate audio-notes wiki plane
            (FEAT-452) — distinct from ``wiki_name``.
        notes_wiki_storage_dir: Root directory of the notes wiki's storage.
        notes_folder: Vault subfolder audio-note captures are written to.

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
        notes_wiki_name: Optional[str] = None,
        notes_wiki_storage_dir: Optional[str | Path] = None,
        notes_folder: Optional[str] = None,
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
            notes_wiki_name: Audio-notes wiki identifier — a **separate**
                plane from ``wiki_name`` (FEAT-452). Defaults to
                ``AUDIO_NOTES_WIKI_NAME``.
            notes_wiki_storage_dir: Audio-notes wiki storage root. Defaults
                to ``AUDIO_NOTES_WIKI_STORAGE_DIR``.
            notes_folder: Vault subfolder for audio-note captures. Defaults
                to ``AUDIO_NOTES_FOLDER``.
            **kwargs: Forwarded to :class:`FirefliesObsidianAgent`. ``llm``
                defaults to Claude Haiku 4.5 when the caller does not pin one.
        """
        kwargs.setdefault("llm", FIREFLIES_WIKI_LLM)
        kwargs.setdefault("instructions", _AUDIO_NOTE_TOOL_GUIDANCE)
        super().__init__(name=name, **kwargs)

        self.wiki_name: str = wiki_name or FIREFLIES_WIKI_NAME
        self.wiki_storage_dir: Path = Path(wiki_storage_dir or FIREFLIES_WIKI_STORAGE_DIR).expanduser()
        # The configured defaults are module-level lists resolved once at
        # import. Copy them so a caller mutating ``agent.daily_recipients``
        # cannot write through to every other instance — the old
        # ``_list_env()`` call built a fresh list per __init__.
        self.daily_recipients: List[str] = (
            daily_recipients if daily_recipients is not None else list(FIREFLIES_WIKI_DAILY_RECIPIENTS)
        )
        self.weekly_recipients: List[str] = (
            weekly_recipients if weekly_recipients is not None else list(FIREFLIES_WIKI_WEEKLY_RECIPIENTS)
        )

        #: Set in :meth:`configure`; ``None`` when the wiki plane is unavailable.
        self._wiki: Optional[Any] = None

        # --- Audio-notes wiki plane (FEAT-452) --------------------------
        self.notes_wiki_name: str = notes_wiki_name or AUDIO_NOTES_WIKI_NAME
        self.notes_wiki_storage_dir: Path = Path(notes_wiki_storage_dir or AUDIO_NOTES_WIKI_STORAGE_DIR).expanduser()
        self.notes_folder: str = notes_folder or AUDIO_NOTES_FOLDER

        #: Set in :meth:`configure`; ``None`` when the notes plane is
        #: unavailable. A DISTINCT LLMWikiToolkit instance from ``self._wiki``
        #: — ``_config_for`` raises on a wiki_name mismatch, so one toolkit
        #: cannot serve both planes.
        self._notes_wiki: Optional[Any] = None

        #: Set in :meth:`configure`. Kept so :meth:`ask` can force a capture
        #: directly (bypassing LLM tool-selection) when ``/note`` has armed
        #: the current chat.
        self._capture_toolkit: Optional[AudioNoteCaptureToolkit] = None

        #: `/note` sticky mode (FEAT-452, Module 4) — chat id (``str``) ->
        #: armed. Consume-on-next-message: cleared after exactly one
        #: message, whether or not the forced capture succeeds.
        #: ``get_current_telegram_chat_id()`` returns a ``str`` (or
        #: ``None``) — NEVER key this by ``int``.
        self._note_mode: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def configure(self, app=None) -> None:
        """Configure the parent agent, then build the LLM Wiki plane.

        The wiki plane is strictly best-effort: any failure leaves
        ``self._wiki`` as ``None``, logs a warning, and lets the agent boot.
        Meetings still reach the Obsidian vault in that state.

        The ``AudioNoteCaptureToolkit`` is registered in
        :meth:`post_configure` — the sanctioned hook for wiring toolkits
        that depend on resources initialised by ``configure()`` (the LLM
        client, the Obsidian vault, the wiki planes).

        Args:
            app: Optional aiohttp application, forwarded to the parent.
        """
        await super().configure(app)
        self._wiki = await self._build_wiki_toolkit()
        self._notes_wiki = await self._build_notes_wiki_toolkit()

    async def post_configure(self) -> None:
        """Register the ``AudioNoteCaptureToolkit`` after base setup.

        Runs after :meth:`configure` has attached the LLM client,
        ``ObsidianToolkit``, and both wiki planes.  This is the
        ``post_configure`` pattern — the recommended way to wire
        additional toolkits that depend on agent resources that only
        become available during ``configure()``.
        """
        await super().post_configure()

        # FEAT-452, Module 3 — register the audio-note capture tool.
        capture_toolkit = AudioNoteCaptureToolkit(
            obsidian_toolkit=self.obsidian_toolkit,
            notes_wiki_provider=lambda: self._notes_wiki,
            llm_call=self.client.complete,
            vault_path=self.vault_path,
            notes_folder=self.notes_folder,
            wiki_name=self.notes_wiki_name,
        )
        self._capture_toolkit = capture_toolkit
        tools = self.tool_manager.register_toolkit(capture_toolkit)
        self.tools.extend(tools)
        self.logger.info(
            "Registered AudioNoteCaptureToolkit tools: %s",
            [t.name for t in capture_toolkit.get_tools()],
        )

    # ------------------------------------------------------------------
    # `/note` sticky mode (FEAT-452, Module 4)
    # ------------------------------------------------------------------

    @telegram_command("note", description="Capture the next message as a note")
    async def arm_note_mode(self, _args: str = "") -> str:
        """Arm capture for the next message sent in this chat.

        Deterministic override for when LLM intent detection misfires:
        the very next message in this chat — voice or typed — is captured
        with no intent guessing, and the mode clears immediately after
        (consume-on-next-message), whether or not that capture succeeds.

        Requires the invoking chat to be resolvable via
        ``get_current_telegram_chat_id()`` (wired by the ``telegram_chat_scope``
        wrapper around agent commands — FEAT-452 Module 1). Outside a scoped
        Telegram command this replies with a clear message instead of
        raising or arming a ``None`` key.

        Args:
            _args: Unused — ``/note`` takes no arguments.

        Returns:
            A short confirmation, or an explanation when the chat cannot
            be resolved.
        """
        chat_id = get_current_telegram_chat_id()
        if chat_id is None:
            return "⚠️ Could not determine the current chat — /note is " "unavailable here."
        self._note_mode[chat_id] = True
        return "📝 Noted — your next message will be saved as a note."

    async def ask(self, question: str, *args: Any, **kwargs: Any) -> Any:
        """Force a capture when ``/note`` has armed the current chat.

        Consume-on-next-message: the flag is cleared BEFORE the capture
        runs, so a failing capture can never leave the chat permanently
        armed. Otherwise falls through to the normal LLM ReAct loop with
        ``args``/``kwargs`` forwarded unchanged — ordinary Q&A and
        LLM-driven capture intent (guided by ``capture_audio_note``'s own
        docstring and the agent's ``instructions``) are byte-identical to
        before this method existed (G7).

        Deliberate trade-off (code review, FEAT-452): the armed branch
        calls :meth:`_force_capture` directly and does NOT go through
        ``BasicAgent.ask()`` — so the input guardrail pipeline
        (prompt-injection detection), tracing/OTEL spans,
        ``current_user_id``/``current_session_id`` contextvars, and
        conversation-memory recording all do NOT run for a forced capture.
        Accepted for a single-operator personal-use agent: a captured
        message is a discrete write action, not a conversational turn, and
        the raw transcript is never re-surfaced as an answer to the user.
        The non-armed path is unaffected — it is an unconditional
        passthrough to the real ``ask()``, guardrails included.

        Args:
            question: The user's message text (transcribed voice or typed).
            *args: Forwarded to the parent ``ask()`` unchanged.
            **kwargs: Forwarded to the parent ``ask()`` unchanged.

        Returns:
            A short confirmation string when a forced capture ran,
            otherwise whatever the parent ``ask()`` returns.
        """
        chat_id = get_current_telegram_chat_id()
        if chat_id is not None and self._note_mode.get(chat_id):
            self._note_mode[chat_id] = False
            return await self._force_capture(question)
        return await super().ask(question, *args, **kwargs)

    async def _force_capture(self, transcript: str) -> str:
        """Directly invoke ``capture_audio_note``, bypassing LLM tool-selection.

        Args:
            transcript: The raw note text (transcribed voice or typed).
                ``language`` is not propagated this far up the call chain,
                so it is passed as ``None`` — the structuring prompt
                already handles ``language=None`` by detecting the
                language from the text itself.

        Returns:
            A one-line confirmation, or a warning message on failure —
            never raises into :meth:`ask`.
        """
        if self._capture_toolkit is None:
            return "⚠️ Capture is unavailable right now."
        try:
            result = await self._capture_toolkit.capture_audio_note(transcript, language=None)
        except Exception as exc:  # noqa: BLE001 — armed capture must not raise into ask()
            self.logger.warning("Forced capture failed: %s", exc)
            return f"⚠️ Could not save note: {exc}"
        return f"✅ Saved: {result['note_title']}"

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
                "LLMWikiToolkit unavailable (%s); meetings will sync to " "Obsidian only.",
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
        model_spec = WIKI_MODEL
        try:
            from parrot.clients.factory import LLMFactory
            from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
            from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

            _, model_id = LLMFactory.parse_llm_string(model_spec)
            adapter = PageIndexLLMAdapter(LLMFactory.create(model_spec), model=model_id)
            pageindex_dir = storage / "pageindex"
            pageindex_dir.mkdir(parents=True, exist_ok=True)
            return PageIndexToolkit(adapter, storage_dir=pageindex_dir)
        except Exception as exc:  # noqa: BLE001 — authoring plane is optional
            self.logger.warning(
                "PageIndexToolkit unavailable (%s); wiki pages will be written " "to the retrieval plane only.",
                exc,
            )
            return None

    async def _build_notes_wiki_toolkit(self) -> Optional[Any]:
        """Construct the **separate** ``LLMWikiToolkit`` backing audio notes.

        FEAT-452, Module 2. A near-copy of :meth:`_build_wiki_toolkit`
        pointed at the notes storage root instead of the meetings one.
        A second toolkit instance is mandatory, not optional:
        ``LLMWikiToolkit._config_for`` raises ``ValueError`` when the
        requested ``wiki_name`` does not match the toolkit's own configured
        wiki, so ``self._wiki`` cannot also serve the ``notes`` plane.

        Because the two planes use different storage roots they share no
        manifest and no ``wiki.db`` — there is no cross-instance
        consistency hazard.

        Bootstraps the layout with an idempotent ``create_wiki()`` call so
        repeat ``configure()`` calls (e.g. process restarts) do not error.

        Returns:
            A wired ``LLMWikiToolkit`` for the notes plane, or ``None`` when
            construction fails.
        """
        try:
            from parrot.knowledge.graphindex.factory import (
                build_graph_memory_toolkit,
            )
            from parrot.knowledge.wiki.models import WikiConfig
            from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

            storage = self.notes_wiki_storage_dir
            storage.mkdir(parents=True, exist_ok=True)

            pageindex_toolkit = self._build_pageindex_toolkit(storage)
            graph_toolkit = await build_graph_memory_toolkit(
                storage / "graph",
                tenant_id=self.notes_wiki_name,
                agent_id=self.name,
            )

            wiki_config = WikiConfig(
                wiki_name=self.notes_wiki_name,
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

            try:
                await toolkit.create_wiki(self.notes_wiki_name)
            except Exception as exc:  # noqa: BLE001 — bootstrap must not null the toolkit
                self.logger.warning(
                    "create_wiki(%s) failed (%s); continuing with the " "existing layout.",
                    self.notes_wiki_name,
                    exc,
                )

            self.logger.info(
                "Notes LLMWikiToolkit ready (wiki=%s, storage=%s, pageindex=%s)",
                self.notes_wiki_name,
                storage,
                "on" if pageindex_toolkit is not None else "off",
            )
            return toolkit
        except Exception as exc:  # noqa: BLE001 — notes plane is best-effort
            self.logger.warning(
                "Notes LLMWikiToolkit unavailable (%s); audio-note captures " "will be written to Obsidian only.",
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Scheduled operation 1 — daily 07:00
    # ------------------------------------------------------------------

    @schedule(
        schedule_type=ScheduleType.CRON,
        hour=FIREFLIES_WIKI_SYNC_HOUR,
        minute=FIREFLIES_WIKI_SYNC_MINUTE,
        timezone=FIREFLIES_WIKI_TZ,
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
                limit=limit if limit is not None else FIREFLIES_WIKI_SYNC_LIMIT,
                skip_existing=True,
            )

            # --- Step 2: per-meeting LLM analysis ---------------------------
            report["analysis"] = await self.summarize_pending_transcripts(
                granularity="standard",
                limit=(analysis_limit if analysis_limit is not None else FIREFLIES_WIKI_ANALYSIS_LIMIT),
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
            self.logger.warning("Wiki plane unavailable — skipping ingest for this run.")
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
                extract_entities=FIREFLIES_WIKI_EXTRACT_ENTITIES,
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
        hour=FIREFLIES_WIKI_DIGEST_HOUR,
        minute=FIREFLIES_WIKI_DIGEST_MINUTE,
        timezone=FIREFLIES_WIKI_TZ,
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
        window = days if days is not None else FIREFLIES_WIKI_DAILY_WINDOW_DAYS
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
        day_of_week=FIREFLIES_WIKI_WEEKLY_DAY,
        hour=FIREFLIES_WIKI_WEEKLY_HOUR,
        minute=FIREFLIES_WIKI_WEEKLY_MINUTE,
        timezone=FIREFLIES_WIKI_TZ,
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
        window = days if days is not None else FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS
        return await self._run_digest(
            window_days=window,
            recipients=(recipients if recipients is not None else self.weekly_recipients),
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
                self.logger.warning("No recipients configured for %s — nothing sent.", job)
                return outcome

            body = await self._ask_llm(prompt_builder(analyses))
            subject = (
                f"{subject_prefix} — "
                f"{datetime.now(schedule_tzinfo()).strftime('%Y-%m-%d')} "
                f"({len(analyses)} meeting{'s' if len(analyses) != 1 else ''})"
            )
            # ``send_email`` never raises and reports provider failures in
            # its result dict, so the status must be read back — a bare
            # ``await`` always looks like it succeeded.
            result = await self.send_email(
                message=body,
                recipients=recipients,
                subject=subject,
            )
            outcome["emailed"] = self.notification_succeeded(result)
            if not outcome["emailed"]:
                outcome["status"] = "partial"
                outcome["reason"] = (result or {}).get("error") or "email delivery failed"
                self.logger.error("Could not send %r: %s", subject, outcome["reason"])

        except Exception as exc:  # noqa: BLE001 — scheduled job must not raise
            outcome["status"] = "error"
            outcome["error"] = str(exc)
            self.logger.error("%s failed: %s", job, exc, exc_info=True)

        return outcome

    async def _notes_in_window(self, days: int, now: Optional[datetime] = None) -> List[str]:
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
        reference = (now or datetime.now(schedule_tzinfo())).date()
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
        return "\n\n".join(f"### {entry['note']}\n{entry['analysis']}" for entry in analyses)

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
