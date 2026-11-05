"""GitHub Wiki page-naming rules and link rewriting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import yaml


class PageNameError(ValueError):
    """Raised for a title GitHub would rewrite (literal hyphen) or an empty title."""


# Characters ``actions/upload-artifact`` (and NTFS) refuse in a file name. A page name is also the bundle
# file name, so these never reach it: they are replaced by a space, the title keeps them.
FORBIDDEN_NAME_CHARS = '":<>|*?\r\n'

_NAME_SEPARATORS = str.maketrans(dict.fromkeys("/\\" + FORBIDDEN_NAME_CHARS, " "))


def page_name(section: str | None, title: str) -> str:
    """Return the GitHub wiki page name with spaces represented by hyphens.

    Path separators and the characters in :data:`FORBIDDEN_NAME_CHARS` (which ``actions/upload-artifact``
    rejects in a file name) are replaced by a space in the name; the title itself is not changed.

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
    # Path separators would turn the name into a nested path (or escape the output directory) and the
    # forbidden characters would make the bundle unuploadable: replace them with spaces. The name is
    # computed once and reused for every link.
    name = "-".join(title.translate(_NAME_SEPARATORS).strip().split())
    if not name:
        raise PageNameError(f"Title {title!r} has no characters usable in a page name")
    if section:
        if "-" in section:
            raise PageNameError(f"Section {section!r} contains a literal hyphen")
        prefix = "-".join(section.translate(_NAME_SEPARATORS).strip().split())
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


def page_href(name: str) -> str:
    """Return the relative, percent-encoded URL of a wiki page (``/wiki/<href>`` on GitHub).

    Args:
        name: A page name from :func:`page_name`.

    Returns:
        The name with every character outside ``-._~`` and the unreserved set percent-encoded, which is
        how GitHub itself links pages whose names carry ``—``, ``,`` or ``&``.
    """
    return quote(name, safe="-._~")


def page_link(name: str, text: str) -> str:
    """Return a standard Markdown link to a wiki page.

    The bundle never emits ``[[Page Name]]`` wiki links: GitHub resolves each one against the whole page list
    at render time, and a sidebar or index carrying hundreds of them fails to render in a wiki with
    thousands of pages. A plain ``[text](href)`` link renders at constant cost.

    Args:
        name: A page name from :func:`page_name`.
        text: Link text shown to the reader.

    Returns:
        ``[text](percent-encoded-name)``.
    """
    return f"[{text}]({page_href(name)})"


def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str:
    """Rewrite resolved relative Markdown and ``ref:`` links to links to the wiki page.

    Args:
        text: Markdown content.
        resolver: Maps a relative path or ``ref:<module>`` to a wiki page name.

    Returns:
        Markdown content with every resolved link converted to ``[original text](page-href)``; the
        author's link text and any ``#fragment`` are kept.
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
            return f"[{match.group(1)}]({page_href(page)}#{fragment})"
        return page_link(page, match.group(1))

    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(line)
        else:
            out.append(line if in_fence else pattern.sub(replace, line))
    return "\n".join(out)
