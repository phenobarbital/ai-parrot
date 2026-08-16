"""Obsidian-flavored markdown parsing into :class:`ObsidianNote` models.

Implements FEAT-392 Module 1 (relocated to the shared interface package so
the toolkit, the vault loader and the wikitoolkit vault scanner all parse
notes identically): ``python-frontmatter`` for YAML frontmatter extraction
and ``marko`` with a custom inline element for ``[[wikilinks]]`` /
``![[embeds]]``. Inline ``#tags`` are collected from raw-text nodes only
(code blocks and link targets never produce tags), callout blocks are
preserved verbatim in the note body, and dataview queries are captured as
raw text.

Parsing is pure and synchronous — no I/O happens here.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import frontmatter as fm
import yaml
from marko import Markdown
from marko.block import FencedCode
from marko.helpers import MarkoExtension
from marko.inline import CodeSpan, InlineElement

from .models import (
    ObsidianCanvas,
    ObsidianCanvasCard,
    ObsidianLink,
    ObsidianNote,
)

logger = logging.getLogger(__name__)

# Obsidian tag: at least one letter, may contain digits, '_', '-', and '/'
# for nested tags. Must be preceded by start-of-text or whitespace so URL
# fragments ("…/#anchor") and headings ("# Title") never match.
_TAG_RE = re.compile(r"(?:(?<=\s)|^)#([\w/-]*[A-Za-z][\w/-]*)")

# ``dataview`` fenced blocks are matched by info-string; inline `= …` DQL is
# out of scope (stored raw only when fenced), per the FEAT-392 non-goals.
_DATAVIEW_LANGS = frozenset({"dataview", "dataviewjs"})


class WikiLinkElement(InlineElement):
    """marko inline element for ``[[target#heading|alias]]`` / ``![[embed]]``."""

    pattern = re.compile(
        r"(!?)\[\[([^\[\]\|#\n]+)(?:#([^\[\]\|\n]+))?(?:\|([^\[\]\n]+))?\]\]"
    )
    parse_children = False
    priority = 6  # above standard links so [[...]] wins over [ ... ] parsing

    def __init__(self, match: re.Match) -> None:
        self.is_embed: bool = match.group(1) == "!"
        self.target: str = match.group(2).strip()
        self.heading: Optional[str] = (
            match.group(3).strip() if match.group(3) else None
        )
        self.alias: Optional[str] = (
            match.group(4).strip() if match.group(4) else None
        )


#: marko extension registering the wikilink inline element.
ObsidianExtension = MarkoExtension(elements=[WikiLinkElement])


def _coerce_str_list(value: Any) -> list[str]:
    """Normalize a frontmatter scalar/list into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


class ObsidianNoteParser:
    """Parse raw Obsidian markdown text into :class:`ObsidianNote` models.

    The parser is stateless and reusable; one instance can parse any number
    of notes (a single ``marko.Markdown`` instance is reused).
    """

    def __init__(self) -> None:
        self._markdown = Markdown(extensions=[ObsidianExtension])

    def parse(self, raw: str, rel_path: str | Path) -> ObsidianNote:
        """Parse one note.

        Args:
            raw: Full file text including any YAML frontmatter block.
            rel_path: Vault-relative path of the note (used for the title
                fallback and stored on the model).

        Returns:
            The parsed :class:`ObsidianNote`. Invalid YAML frontmatter is
            tolerated: the whole text becomes the body and frontmatter is
            empty (per the FEAT-392 robustness requirement).
        """
        rel_path = Path(rel_path)
        metadata: dict[str, Any] = {}
        body = raw
        try:
            post = fm.loads(raw)
            metadata = dict(post.metadata)
            body = post.content
        except (yaml.YAMLError, ValueError) as exc:
            logger.warning(
                "Invalid frontmatter in %s — treating full text as body: %s",
                rel_path, exc,
            )

        links: list[ObsidianLink] = []
        tags: set[str] = set()
        dataview_queries: list[str] = []
        try:
            document = self._markdown.parse(body)
            self._walk(document, links, tags, dataview_queries)
        except Exception as exc:  # noqa: BLE001 — parser must never fail a note
            logger.warning(
                "marko failed on %s (%s) — falling back to regex link scan",
                rel_path, exc,
            )
            links = self._fallback_links(body)
            tags = {m.group(1) for m in _TAG_RE.finditer(body)}

        # Frontmatter tags: `tags: [a, b]`, `tags: a, b` or singular `tag:`.
        for key in ("tags", "tag"):
            for tag in _coerce_str_list(metadata.get(key)):
                tags.add(tag.lstrip("#"))

        aliases = _coerce_str_list(
            metadata.get("aliases", metadata.get("alias"))
        )
        title = str(metadata.get("title") or rel_path.stem)

        return ObsidianNote(
            path=rel_path,
            title=title,
            content=body,
            frontmatter=metadata,
            links=links,
            tags=tags,
            aliases=aliases,
            dataview_queries=dataview_queries,
        )

    def _walk(
        self,
        element: Any,
        links: list[ObsidianLink],
        tags: set[str],
        dataview_queries: list[str],
    ) -> None:
        """Depth-first AST walk collecting links, tags and dataview blocks."""
        if isinstance(element, WikiLinkElement):
            links.append(
                ObsidianLink(
                    target=element.target,
                    alias=element.alias,
                    is_embed=element.is_embed,
                    heading=element.heading,
                )
            )
            return
        if isinstance(element, FencedCode):
            if (element.lang or "").lower() in _DATAVIEW_LANGS:
                query = self._raw_text(element).strip()
                if query:
                    dataview_queries.append(query)
            return  # never harvest tags/links from code
        if isinstance(element, CodeSpan):
            return
        children = getattr(element, "children", None)
        if isinstance(children, str):
            for match in _TAG_RE.finditer(children):
                tags.add(match.group(1))
            return
        if children:
            for child in children:
                self._walk(child, links, tags, dataview_queries)

    def _raw_text(self, element: Any) -> str:
        """Concatenate all raw text under an AST element."""
        children = getattr(element, "children", None)
        if isinstance(children, str):
            return children
        if not children:
            return ""
        return "".join(self._raw_text(child) for child in children)

    @staticmethod
    def _fallback_links(body: str) -> list[ObsidianLink]:
        """Regex-only link extraction used if marko raises unexpectedly."""
        found: list[ObsidianLink] = []
        for match in WikiLinkElement.pattern.finditer(body):
            found.append(
                ObsidianLink(
                    target=match.group(2).strip(),
                    alias=match.group(4).strip() if match.group(4) else None,
                    is_embed=match.group(1) == "!",
                    heading=match.group(3).strip() if match.group(3) else None,
                )
            )
        return found


def parse_canvas(raw_json: str, rel_path: str | Path) -> ObsidianCanvas:
    """Parse an Obsidian ``.canvas`` JSON file.

    Args:
        raw_json: The canvas file content (JSON Canvas format).
        rel_path: Vault-relative path of the canvas file.

    Returns:
        The parsed :class:`ObsidianCanvas` with cards and connections.

    Raises:
        ValueError: If the file is not valid JSON or not an object.
    """
    rel_path = Path(rel_path)
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid canvas JSON in {rel_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Canvas file {rel_path} is not a JSON object")

    cards = [
        ObsidianCanvasCard(
            card_id=str(node.get("id", "")),
            card_type=str(node.get("type", "text")),
            file_path=node.get("file"),
            text=node.get("text"),
            url=node.get("url"),
        )
        for node in data.get("nodes", [])
        if isinstance(node, dict)
    ]
    connections = [
        (str(edge.get("fromNode", "")), str(edge.get("toNode", "")))
        for edge in data.get("edges", [])
        if isinstance(edge, dict)
    ]
    return ObsidianCanvas(
        path=rel_path,
        title=rel_path.stem,
        cards=cards,
        connections=connections,
    )
