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
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from navconfig import config
from pydantic import BaseModel, Field

from parrot.agents.obsidian import FirefliesObsidianAgent
from parrot.interfaces.obsidian.okf import project_okf_block
from parrot.knowledge.okf.ontology import ConceptType
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule
from parrot.tools import AbstractToolkit
from parrot.tools.obsidian import ObsidianToolkit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency: ai-parrot-integrations (Telegram)
#
# FEAT-452, Module 4. ``ai-parrot-integrations`` is a separate distribution
# from the core this agent otherwise depends on — imported defensively (same
# posture as ``_build_wiki_toolkit``'s optional planes) so the agent still
# boots when the Telegram integration is not installed. ``/note`` and the
# per-chat sticky mode are simply unavailable in that case.
# ---------------------------------------------------------------------------
try:
    from parrot.integrations.telegram.context import get_current_telegram_chat_id
    from parrot.integrations.telegram.decorators import telegram_command

    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False

    def telegram_command(
        command: str, description: str = "", parse_mode: str = "keyword"
    ) -> Callable[..., Callable]:
        """No-op fallback decorator when ``parrot.integrations.telegram`` is
        not installed — preserves the decorated method unchanged."""

        def _decorator(fn: Callable) -> Callable:
            return fn

        return _decorator

    def get_current_telegram_chat_id() -> Optional[str]:
        """Fallback used when the Telegram integration is not installed."""
        return None


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

#: Audio-notes wiki plane (FEAT-452 — separate from the meetings wiki so
#: personal captures don't dilute meeting retrieval; see spec §2 "Two
#: separate wiki toolkit instances").
_AUDIO_NOTES_WIKI_NAME: str = config.get("AUDIO_NOTES_WIKI_NAME", fallback="notes")
_AUDIO_NOTES_WIKI_STORAGE_DIR: str = config.get(
    "AUDIO_NOTES_WIKI_STORAGE_DIR",
    fallback=str(Path.home() / ".parrot" / "wikis" / "notes"),
)
_AUDIO_NOTES_FOLDER: str = config.get("AUDIO_NOTES_FOLDER", fallback="audio-notes")

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

#: Run bounds.
_SYNC_LIMIT: int = _int_env("FIREFLIES_WIKI_SYNC_LIMIT", 20)
_ANALYSIS_LIMIT: int = _int_env("FIREFLIES_WIKI_ANALYSIS_LIMIT", 20)
_DAILY_WINDOW_DAYS: int = _int_env("FIREFLIES_WIKI_DAILY_WINDOW_DAYS", 1)
_WEEKLY_WINDOW_DAYS: int = _int_env("FIREFLIES_WIKI_WEEKLY_WINDOW_DAYS", 7)


# ---------------------------------------------------------------------------
# Audio-notes capture (FEAT-452, Module 3)
# ---------------------------------------------------------------------------

class AudioNoteStructure(BaseModel):
    """LLM-structured form of a raw voice/text transcript.

    ``title`` and ``tags`` are always English. ``summary``, ``key_points``
    and ``action_items`` are in the transcript's source language.
    """

    title: str = Field(..., description="English title, used for the slug")
    tags: List[str] = Field(
        default_factory=list, description="English OKF/frontmatter tags"
    )
    summary: str = Field(..., description="Summary, source language")
    key_points: List[str] = Field(
        default_factory=list, description="Key points, source language"
    )
    action_items: List[str] = Field(
        default_factory=list,
        description="Action items, source language; may be empty",
    )


class AudioNoteResult(BaseModel):
    """Return value of :meth:`AudioNoteCaptureToolkit.capture_audio_note`."""

    note_title: str = Field(..., description="'YYYY-MM-DD-slug'")
    vault_path: str = Field(..., description="'audio-notes/YYYY-MM-DD-slug.md'")
    wiki_ingested: bool
    wiki_reason: Optional[str] = Field(
        default=None, description="Populated when wiki_ingested is False"
    )
    structured: bool = Field(
        ..., description="False when the verbatim fallback path was used"
    )


def _build_note_structuring_prompt(transcript: str, language: Optional[str]) -> str:
    """Build the single structuring prompt for a captured note.

    Mirrors :meth:`FirefliesObsidianAgent._build_analysis_prompt` — a
    labelled-sections request the parser below can split on ``##``.

    Args:
        transcript: The raw note text (transcribed or typed).
        language: ISO 639-1 language code for voice input, or ``None`` for
            typed input (in which case the LLM infers the language).

    Returns:
        The rendered prompt.
    """
    language_note = (
        f"The note below is in language code '{language}'."
        if language
        else "Detect the language of the note below from its own text."
    )
    return f"""You are structuring a short personal note (spoken or typed) into a clean record.

{language_note}

RAW NOTE:
---
{transcript}
---

Produce your response in EXACTLY this format:

## Title
<a short title, 3-8 words, ALWAYS IN ENGLISH regardless of the note's language>

## Tags
<2-5 comma-separated tags, ALWAYS IN ENGLISH>

## Summary
<1-3 sentence summary, written in the SAME language as the raw note>

## Key Points
- <point, same language as the raw note>
(omit this section entirely if there are no distinct key points beyond the summary)

## Action Items
- <action, same language as the raw note>
(omit this section entirely if there are no action items)

Rules:
- Title and Tags MUST be in English, regardless of the note's language.
- Summary, Key Points and Action Items MUST be in the SAME language as the raw note.
- Be concise and do not invent information not present in the note."""


def _strip_bullet(line: str) -> str:
    """Strip a leading ``-``/``*`` list marker and surrounding whitespace.

    Args:
        line: A single line of LLM output.

    Returns:
        The line with any leading bullet marker removed.
    """
    stripped = line.strip()
    if stripped[:1] in ("-", "*"):
        stripped = stripped[1:].strip()
    return stripped


def _parse_note_structure_response(response_text: str) -> AudioNoteStructure:
    """Parse the structuring LLM response into an :class:`AudioNoteStructure`.

    Mirrors :meth:`FirefliesObsidianAgent._parse_analysis_response`'s
    split-by-``##``-header approach.

    Args:
        response_text: The LLM's plain-text reply.

    Returns:
        The parsed structure.

    Raises:
        ValueError: When the required Title or Summary sections are
            missing — the caller falls back to a verbatim note in that case.
    """
    title = ""
    tags: List[str] = []
    summary = ""
    key_points: List[str] = []
    action_items: List[str] = []

    for section in response_text.split("##"):
        stripped = section.strip()
        if not stripped:
            continue
        if stripped.startswith("Title"):
            title = stripped[len("Title"):].strip()
        elif stripped.startswith("Tags"):
            raw_tags = stripped[len("Tags"):].strip()
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif stripped.startswith("Summary"):
            summary = stripped[len("Summary"):].strip()
        elif stripped.startswith("Key Points"):
            lines = stripped[len("Key Points"):].strip().split("\n")
            key_points = [
                _strip_bullet(line)
                for line in lines
                if line.strip().startswith(("-", "*"))
            ]
        elif stripped.startswith("Action Items"):
            lines = stripped[len("Action Items"):].strip().split("\n")
            action_items = [
                _strip_bullet(line)
                for line in lines
                if line.strip().startswith(("-", "*"))
            ]

    if not title or not summary:
        raise ValueError(
            "Note structuring response is missing the required Title/Summary "
            "sections."
        )

    return AudioNoteStructure(
        title=title,
        tags=tags,
        summary=summary,
        key_points=key_points,
        action_items=action_items,
    )


def _build_note_okf_frontmatter(
    title: str, tags: List[str], date_str: str, summary: str
) -> Dict[str, Any]:
    """Build OKF frontmatter for an audio note.

    Mirrors the ``{"okf": {...}}`` shape
    :meth:`FirefliesObsidianAgent._build_okf_frontmatter` produces for
    meetings (``obsidian.py:520``), adapted for a personal note — there is
    no ``fireflies_id`` / participants / duration to fabricate, so this is
    a dedicated helper rather than a call into the meeting-shaped one.

    Args:
        title: English note title.
        tags: English tags.
        date_str: Capture date, ``YYYY-MM-DD``.
        summary: Note summary (source language), used as the OKF summary.

    Returns:
        Dict with an ``okf`` key, or ``{}`` when projection fails (mirrors
        the meeting helper's own best-effort posture).
    """
    node = {
        "concept_id": f"audio-note-{date_str}-{'-'.join(title.lower().split()[:4])}",
        "title": title,
        "node_id": f"obsidian::audio-note::{date_str}",
        "type": ConceptType.DOCUMENT_NODE.value,
        "categories": ["audio-note"] + tags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    }
    try:
        okf_yaml = project_okf_block(node, tree_name="audio-notes")
        import yaml

        return yaml.safe_load(okf_yaml)
    except Exception as exc:  # noqa: BLE001 — frontmatter is best-effort
        logger.warning("Failed to generate OKF block for audio note: %s", exc)
        return {}


class AudioNoteCaptureToolkit(AbstractToolkit):
    """Single-purpose, agent-local toolkit exposing exactly one tool.

    Holds references to the agent's collaborators because a bare ``@tool``
    function cannot close over agent state. ``AbstractToolkit`` converts
    every public async method into a tool, so this class exposes exactly
    one: :meth:`capture_audio_note`. Every helper is underscore-prefixed
    for that reason.
    """

    def __init__(
        self,
        obsidian_toolkit: ObsidianToolkit,
        notes_wiki_provider: Callable[[], Optional[Any]],
        llm_call: Callable[[str], Awaitable[str]],
        vault_path: Path,
        notes_folder: str = "audio-notes",
        wiki_name: str = "notes",
    ) -> None:
        """Initialize the capture toolkit.

        Args:
            obsidian_toolkit: The agent's ``ObsidianToolkit`` — used to
                write the note (``create`` is an allowed operation).
            notes_wiki_provider: Zero-arg callable returning the agent's
                current ``self._notes_wiki`` (``None`` when unavailable).
                A callable rather than the toolkit instance itself, so the
                tool always observes the latest value, including after a
                later ``configure()`` rebuild.
            llm_call: Single-prompt callable routed through the agent's
                configured ``AbstractClient`` — never the Anthropic SDK
                directly.
            vault_path: The agent's Obsidian vault root, used to build the
                absolute path ``ingest_source`` requires.
            notes_folder: Vault subfolder for captures.
            wiki_name: Target wiki identifier for ``ingest_source``.
        """
        super().__init__()
        self._obsidian = obsidian_toolkit
        self._notes_wiki_provider = notes_wiki_provider
        self._llm_call = llm_call
        self._vault_path = vault_path
        self._notes_folder = notes_folder
        self._wiki_name = wiki_name

    async def capture_audio_note(
        self,
        transcript: str,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save a note as a structured Obsidian note and wiki page.

        Call this when the user is recording something to REMEMBER
        (a note, idea, decision, reminder or follow-up) rather than
        asking a question.

        Transport-neutral: the text may come from a transcribed voice
        note OR from a typed message — voice is only the vehicle.
        ``language`` is the transcript's detected language for voice
        input, and ``None`` for typed input.

        Args:
            transcript: The raw note text (transcribed or typed).
            language: ISO 639-1 language code for voice input, or ``None``
                for typed input.

        Returns:
            An :class:`AudioNoteResult`, as a dict: ``note_title``,
            ``vault_path``, ``wiki_ingested``, ``wiki_reason``, ``structured``.
        """
        structure, structured = await self._structure_transcript(transcript, language)
        note_title, vault_rel_path = await self._write_note(transcript, structure)
        wiki_ingested, wiki_reason = await self._ingest_into_wiki(
            note_title, vault_rel_path
        )

        result = AudioNoteResult(
            note_title=note_title,
            vault_path=vault_rel_path,
            wiki_ingested=wiki_ingested,
            wiki_reason=wiki_reason,
            structured=structured,
        )
        return result.model_dump()

    async def _structure_transcript(
        self, transcript: str, language: Optional[str]
    ) -> tuple[AudioNoteStructure, bool]:
        """Structure the transcript via one LLM call, or fall back verbatim.

        Args:
            transcript: The raw note text.
            language: ISO 639-1 language code, or ``None``.

        Returns:
            Tuple of ``(structure, structured)`` — ``structured`` is
            ``False`` when the LLM call/parse failed and a verbatim
            fallback was used instead.
        """
        try:
            prompt = _build_note_structuring_prompt(transcript, language)
            response_text = await self._llm_call(prompt)
            return _parse_note_structure_response(response_text), True
        except Exception as exc:  # noqa: BLE001 — structuring is best-effort
            self.logger.warning(
                "Note structuring failed (%s); writing a verbatim note.", exc
            )
            fallback_title = transcript.strip().split("\n")[0][:60] or "audio-note"
            return (
                AudioNoteStructure(
                    title=fallback_title,
                    tags=[],
                    summary=transcript[:280],
                    key_points=[],
                    action_items=[],
                ),
                False,
            )

    async def _write_note(
        self, transcript: str, structure: AudioNoteStructure
    ) -> tuple[str, str]:
        """Write the structured note to the vault, retrying on slug collision.

        The vault write is the durable step: any failure OTHER than a
        same-day slug collision propagates to the caller — a write failure
        must be surfaced, never swallowed.

        Args:
            transcript: The raw note text, preserved verbatim.
            structure: The structured (or verbatim-fallback) content.

        Returns:
            Tuple of ``(note_title, vault_relative_path)``.

        Raises:
            Exception: Any non-collision failure from
                ``ObsidianToolkit.create_note``.
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base_title = FirefliesObsidianAgent._make_note_title(date_str, structure.title)
        body = self._render_note_body(structure, transcript)
        frontmatter = _build_note_okf_frontmatter(
            structure.title, structure.tags, date_str, structure.summary
        )
        frontmatter["tags"] = structure.tags

        note_title = base_title
        attempt = 1
        while True:
            vault_rel_path = f"{self._notes_folder}/{note_title}.md"
            try:
                await self._obsidian.create_note(
                    path=vault_rel_path,
                    content=body,
                    frontmatter=frontmatter,
                )
                return note_title, vault_rel_path
            except FileExistsError:
                attempt += 1
                note_title = f"{base_title}-{attempt}"

    @staticmethod
    def _render_note_body(structure: AudioNoteStructure, transcript: str) -> str:
        """Render the note body: summary, key points, action items, transcript.

        Args:
            structure: The structured (or verbatim-fallback) content.
            transcript: The raw note text, preserved verbatim.

        Returns:
            The full markdown body (frontmatter is applied separately by
            ``create_note``).
        """
        lines: List[str] = ["## Summary", "", structure.summary, ""]
        if structure.key_points:
            lines.append("## Key Points")
            lines.extend(f"- {point}" for point in structure.key_points)
            lines.append("")
        if structure.action_items:
            lines.append("## Action Items")
            lines.extend(f"- {item}" for item in structure.action_items)
            lines.append("")
        lines.append("## Transcript")
        lines.append("")
        lines.append(transcript)
        return "\n".join(lines)

    async def _ingest_into_wiki(
        self, note_title: str, vault_rel_path: str
    ) -> tuple[bool, Optional[str]]:
        """Best-effort ingest of the freshly-written note into the notes wiki.

        Uses ``ingest_source`` (never ``create_page``) so the note is
        registered in the source manifest and a later incremental vault
        ingest recognizes it rather than authoring a duplicate page.

        Args:
            note_title: The written note's title (used for log context).
            vault_rel_path: Vault-relative path, e.g.
                ``"audio-notes/2026-08-23-idea.md"``.

        Returns:
            Tuple of ``(wiki_ingested, wiki_reason)``.
        """
        notes_wiki = self._notes_wiki_provider()
        if notes_wiki is None:
            return False, "notes wiki toolkit unavailable"

        absolute_path = str(self._vault_path / vault_rel_path)
        try:
            await notes_wiki.ingest_source(self._wiki_name, absolute_path)
            return True, None
        except Exception as exc:  # noqa: BLE001 — wiki ingest must not lose the note
            self.logger.warning("Wiki ingest failed for %s: %s", note_title, exc)
            return False, str(exc)


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
        kwargs.setdefault("llm", _LLM)
        kwargs.setdefault("instructions", _AUDIO_NOTE_TOOL_GUIDANCE)
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

        # --- Audio-notes wiki plane (FEAT-452) --------------------------
        self.notes_wiki_name: str = notes_wiki_name or _AUDIO_NOTES_WIKI_NAME
        self.notes_wiki_storage_dir: Path = Path(
            notes_wiki_storage_dir or _AUDIO_NOTES_WIKI_STORAGE_DIR
        ).expanduser()
        self.notes_folder: str = notes_folder or _AUDIO_NOTES_FOLDER

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

        Args:
            app: Optional aiohttp application, forwarded to the parent.
        """
        await super().configure(app)
        self._wiki = await self._build_wiki_toolkit()
        self._notes_wiki = await self._build_notes_wiki_toolkit()

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
        self._initialize_tools([capture_toolkit])
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
        Telegram command (or when the Telegram integration is not
        installed) this replies with a clear message instead of raising or
        arming a ``None`` key.

        Args:
            _args: Unused — ``/note`` takes no arguments.

        Returns:
            A short confirmation, or an explanation when the chat cannot
            be resolved.
        """
        chat_id = get_current_telegram_chat_id()
        if chat_id is None:
            return (
                "⚠️ Could not determine the current chat — /note is "
                "unavailable here."
            )
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
            result = await self._capture_toolkit.capture_audio_note(
                transcript, language=None
            )
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
                    "create_wiki(%s) failed (%s); continuing with the "
                    "existing layout.",
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
                "Notes LLMWikiToolkit unavailable (%s); audio-note captures "
                "will be written to Obsidian only.",
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
