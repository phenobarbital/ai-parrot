"""AudioNoteCaptureToolkit — structure and persist audio/text notes.

Captures a raw transcript (voice-transcribed or typed), structures it via
a single LLM call into title / tags / summary / key-points / action-items,
writes it as a frontmattered Obsidian note, and best-effort ingests it into
a wiki plane.

Originally built as an agent-local toolkit inside ``agents/fireflies_wiki.py``
(FEAT-452, Module 3).  Extracted into ``ai-parrot-tools`` so any agent that
has an ``ObsidianToolkit`` and (optionally) a wiki plane can reuse the
capture path via ``post_configure``.

Example — wiring into an existing agent::

    from parrot_tools.audio_note_capture import AudioNoteCaptureToolkit

    class MyAgent(Agent):
        async def post_configure(self) -> None:
            await super().post_configure()
            capture = AudioNoteCaptureToolkit(
                obsidian_toolkit=self.obsidian_toolkit,
                notes_wiki_provider=lambda: self._notes_wiki,
                llm_call=self.client.complete,
                vault_path=self.vault_path,
            )
            tools = self.tool_manager.register_toolkit(capture)
            self.tools.extend(tools)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from parrot.tools import AbstractToolkit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AudioNoteStructure(BaseModel):
    """LLM-structured form of a raw voice/text transcript.

    ``title`` and ``tags`` are always English. ``summary``, ``key_points``
    and ``action_items`` are in the transcript's source language.
    """

    title: str = Field(..., description="English title, used for the slug")
    tags: List[str] = Field(default_factory=list, description="English OKF/frontmatter tags")
    summary: str = Field(..., description="Summary, source language")
    key_points: List[str] = Field(default_factory=list, description="Key points, source language")
    action_items: List[str] = Field(
        default_factory=list,
        description="Action items, source language; may be empty",
    )


class AudioNoteResult(BaseModel):
    """Return value of :meth:`AudioNoteCaptureToolkit.capture_audio_note`."""

    note_title: str = Field(..., description="'YYYY-MM-DD-slug'")
    vault_path: str = Field(..., description="'audio-notes/YYYY-MM-DD-slug.md'")
    wiki_ingested: bool
    wiki_reason: Optional[str] = Field(default=None, description="Populated when wiki_ingested is False")
    structured: bool = Field(..., description="False when the verbatim fallback path was used")


# ---------------------------------------------------------------------------
# Prompt / parsing helpers (pure functions — no agent state)
# ---------------------------------------------------------------------------


def _build_note_structuring_prompt(transcript: str, language: Optional[str]) -> str:
    """Build the single structuring prompt for a captured note.

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
            key_points = [_strip_bullet(line) for line in lines if line.strip().startswith(("-", "*"))]
        elif stripped.startswith("Action Items"):
            lines = stripped[len("Action Items"):].strip().split("\n")
            action_items = [_strip_bullet(line) for line in lines if line.strip().startswith(("-", "*"))]

    if not title or not summary:
        raise ValueError("Note structuring response is missing the required Title/Summary sections.")

    return AudioNoteStructure(
        title=title,
        tags=tags,
        summary=summary,
        key_points=key_points,
        action_items=action_items,
    )


def _build_note_okf_frontmatter(title: str, tags: List[str], date_str: str, summary: str) -> Dict[str, Any]:
    """Build OKF frontmatter for an audio note.

    Args:
        title: English note title.
        tags: English tags.
        date_str: Capture date, ``YYYY-MM-DD``.
        summary: Note summary (source language), used as the OKF summary.

    Returns:
        Dict with an ``okf`` key, or ``{}`` when projection fails (mirrors
        the meeting helper's own best-effort posture).
    """
    try:
        from parrot.interfaces.obsidian.okf import project_okf_block
        from parrot.knowledge.okf.ontology import ConceptType
    except ImportError:
        logger.debug("OKF modules not available — skipping frontmatter generation.")
        return {}

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


def _make_note_title(date_str: str, title: str) -> str:
    """Create a ``YYYY-MM-DD-kebab-case-title`` slug from a date and title.

    Equivalent to :meth:`FirefliesObsidianAgent._make_note_title` but
    decoupled — the toolkit must not import the agent hierarchy.

    Args:
        date_str: Date string, ``YYYY-MM-DD``.
        title: English note title from the structuring step.

    Returns:
        The slugified note title (e.g. ``"2026-08-23-buy-milk"``).
    """
    slug = (
        title.lower()
        .replace(" ", "-")
        .replace("_", "-")
        .replace("/", "-")
        .replace("&", "-")
        .strip("-")
    )
    # collapse consecutive hyphens and strip non-alnum/hyphen chars
    slug = re.sub(r"-{2,}", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return f"{date_str}-{slug}"


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class AudioNoteCaptureToolkit(AbstractToolkit):
    """Single-purpose toolkit exposing exactly one tool: ``capture_audio_note``.

    Holds references to collaborators (Obsidian vault, wiki, LLM) because
    a bare ``@tool`` function cannot close over agent state.
    ``AbstractToolkit`` converts every public async method into a tool, so
    this class exposes exactly one — every helper is underscore-prefixed.

    Wire it into any agent that already has an ``ObsidianToolkit`` via
    :meth:`~parrot.bots.abstract.AbstractBot.post_configure`::

        async def post_configure(self) -> None:
            await super().post_configure()
            capture = AudioNoteCaptureToolkit(
                obsidian_toolkit=self.obsidian_toolkit,
                notes_wiki_provider=lambda: self._notes_wiki,
                llm_call=self.client.complete,
                vault_path=self.vault_path,
            )
            tools = self.tool_manager.register_toolkit(capture)
            self.tools.extend(tools)

    Args:
        obsidian_toolkit: The agent's ``ObsidianToolkit`` — ``create_note``
            must be in its ``allowed_operations``.
        notes_wiki_provider: Zero-arg callable returning the agent's wiki
            toolkit (``None`` when unavailable). A callable rather than the
            instance itself, so the tool always observes the latest value.
        llm_call: Single-prompt callable routed through the agent's
            configured ``AbstractClient``.
        vault_path: The agent's Obsidian vault root.
        notes_folder: Vault subfolder for captures (default ``"audio-notes"``).
        wiki_name: Target wiki identifier for ``ingest_source``
            (default ``"notes"``).
    """

    def __init__(
        self,
        obsidian_toolkit: Any,
        notes_wiki_provider: Callable[[], Optional[Any]],
        llm_call: Callable[[str], Awaitable[str]],
        vault_path: Path,
        notes_folder: str = "audio-notes",
        wiki_name: str = "notes",
    ) -> None:
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
        wiki_ingested, wiki_reason = await self._ingest_into_wiki(note_title, vault_rel_path)

        result = AudioNoteResult(
            note_title=note_title,
            vault_path=vault_rel_path,
            wiki_ingested=wiki_ingested,
            wiki_reason=wiki_reason,
            structured=structured,
        )
        return result.model_dump()

    async def _structure_transcript(self, transcript: str, language: Optional[str]) -> tuple[AudioNoteStructure, bool]:
        """Structure the transcript via one LLM call, or fall back verbatim.

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
            self.logger.warning("Note structuring failed (%s); writing a verbatim note.", exc)
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

    async def _write_note(self, transcript: str, structure: AudioNoteStructure) -> tuple[str, str]:
        """Write the structured note to the vault, retrying on slug collision.

        Returns:
            Tuple of ``(note_title, vault_relative_path)``.

        Raises:
            Exception: Any non-collision failure from
                ``ObsidianToolkit.create_note``.
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base_title = _make_note_title(date_str, structure.title)
        body = self._render_note_body(structure, transcript)
        frontmatter = _build_note_okf_frontmatter(structure.title, structure.tags, date_str, structure.summary)
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

    async def _ingest_into_wiki(self, note_title: str, vault_rel_path: str) -> tuple[bool, Optional[str]]:
        """Best-effort ingest of the freshly-written note into the notes wiki.

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
