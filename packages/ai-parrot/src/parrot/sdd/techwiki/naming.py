"""GitHub Wiki page-naming rules and link rewriting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import yaml


class PageNameError(ValueError):
    """Raised for a title GitHub would rewrite (literal hyphen) or an empty title."""


def page_name(section: str | None, title: str) -> str:
    """Return the GitHub wiki page name with spaces represented by hyphens.

    Args:
        section: Optional wiki section name.
        title: Human-readable page title.

    Returns:
        The GitHub Wiki page name.

    Raises:
        PageNameError: If the title is empty or the title or section has a literal hyphen.
    """
    if not title or not title.strip():
        raise PageNameError("Page title must not be empty")
    if "-" in title:
        raise PageNameError(
            f"Title {title!r} contains a literal hyphen — GitHub would store it "
            "as U+2010 ('‐'), breaking [[Title]] links. Use a space instead."
        )
    # Path separators would turn the name into a nested path (or escape the output directory):
    # replace them with spaces. The name is computed once and reused for every link.
    title = title.replace("/", " ").replace("\\", " ")
    name = "-".join(title.strip().split())
    if section:
        if "-" in section:
            raise PageNameError(f"Section {section!r} contains a literal hyphen")
        prefix = "-".join(section.replace("/", " ").replace("\\", " ").strip().split())
        name = f"{prefix}-{name}"
    return name


def page_title(path: Path, text: str) -> str:
    """Extract frontmatter title, first H1, or a title-cased file stem.

    Args:
        path: Markdown path used for the fallback stem.
        text: Complete markdown text.

    Returns:
        The resolved page title.
    """
    if text.startswith("---"):
        match = re.match(r"^---\s*\n(.*?)^---\s*$", text, flags=re.DOTALL | re.MULTILINE)
        if match:
            frontmatter = yaml.safe_load(match.group(1)) or {}
            title = frontmatter.get("title") if isinstance(frontmatter, dict) else None
            if isinstance(title, str) and title.strip():
                return title.strip()

    heading = re.search(r"^#\s+(.+?)\s*#*\s*$", text, flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str:
    """Rewrite resolved relative Markdown and ``ref:`` links to wiki links.

    Args:
        text: Markdown content.
        resolver: Maps a relative path or ``ref:<module>`` to a wiki page name.

    Returns:
        Markdown content with resolved links converted to ``[[Page Name]]``.
    """
    pattern = re.compile(r"(?<!!)\[([^]]+)\]\(([^\s)]+)\)")

    def replace(match: re.Match[str]) -> str:
        target = match.group(2)
        if not target.startswith("ref:") and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            return match.group(0)  # external URL: never a wiki-page reference
        base, _, fragment = target.partition("#")
        if not (base.startswith("ref:") or base.endswith(".md")):
            return match.group(0)
        page = resolver(base)
        if page is None:
            return match.group(0)
        if fragment:
            return f"[{match.group(1)}]({page}#{fragment})"
        return f"[[{page}]]"

    return pattern.sub(replace, text)
